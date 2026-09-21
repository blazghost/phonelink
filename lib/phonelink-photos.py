#!/usr/bin/env python3
"""phonelink photos -- the phone's camera roll, Phone Link style.

A GTK 4 / libadwaita grid of the last couple of hundred camera photos,
screenshots and videos, over the storage KDE Connect exports with its sftp
plugin. Click one to open it, right-click to save it to ~/Pictures/Phone, drag
one out to another app.

The mount is a phone over wifi -- around one and a half megabytes a second
here, whatever you do, so more workers do not help -- which decides how this
window behaves. It never reads the roll to draw it. Only tiles that are about
to be on screen are fetched, six at a time on worker threads, and every one is
shrunk and cached the first time, so a second visit is instant. See
phonelink/photos.py for how little of each file is actually read.

Nothing here downloads a video to draw it: those tiles show a play badge, and
fetch only when you open, save or drag one.
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from phonelink import kdeconnect as kde, photos, theme, widgets  # noqa: E402

APP_ID = "org.omarchy.phonelink.photos"
VERTICAL = Gtk.Orientation.VERTICAL

TILE = 168          # a tile's side, in pixels
LIMIT = 200         # how much of the roll to show; the plan's "last ~200"
WORKERS = 6         # fetching threads; the link saturates well below this
AHEAD = TILE * 3    # fetch this far beyond the viewport, so scrolling stays ahead


def extra_css(p):
    return f"""
.roll {{ padding: 12px; }}
.tile {{ border-radius: 10px; background: {p['lighter_background']}; }}
.tile:hover {{ outline: 2px solid {p['accent']}; outline-offset: -2px; }}
.tile-badge {{ background: alpha(#000, 0.55); color: #fff; border-radius: 999px;
               padding: 4px; margin: 6px; }}
.tile-when {{ background: alpha(#000, 0.55); color: #fff; font-size: 0.75rem;
              border-radius: 6px; padding: 1px 6px; margin: 6px; }}
.status-dim {{ color: {p['muted']}; }}
"""


def day(stamp):
    when = datetime.fromtimestamp(stamp)
    today = datetime.now().date()
    if when.date() == today:
        return when.strftime("%H:%M")
    if when.year == today.year:
        return when.strftime("%-d %b")
    return when.strftime("%b %Y")


class Roll:
    """The camera roll, and the thumbnail workers behind it.

    Everything slow happens on a worker: mounting wakes the phone, scanning
    lists folders over the network, and each thumbnail is a read from it. The
    window only ever hears back through GLib.idle_add.
    """

    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="thumb")
        self.wanted = set()      # shots queued or in flight, so none is fetched twice
        self.lock = threading.Lock()

    def open(self, on_done):
        """Mount the phone and scan its roll. Calls back with (shots, error)."""
        def work():
            device = kde.pick_device(kde.devices())
            if not device:
                return GLib.idle_add(on_done, [], "", "no-phone")
            if not photos.have_sshfs():
                return GLib.idle_add(on_done, [], device["name"], "no-sshfs")
            point, err = photos.mount(device["id"])
            if not point:
                return GLib.idle_add(on_done, [], device["name"], err or "no-mount")
            roots = photos.directories(device["id"]) or {point: ""}
            shots = photos.scan(photos.roll_dirs(*roots), limit=LIMIT)
            return GLib.idle_add(on_done, shots, device["name"], "")
        threading.Thread(target=work, daemon=True).start()

    def thumbnail(self, shot, on_ready):
        """Ask for a shot's thumbnail. Cheap and synchronous if it is cached."""
        if hit := photos.cached(shot):
            on_ready(hit)
            return
        with self.lock:
            if shot.path in self.wanted:
                return
            self.wanted.add(shot.path)

        def work():
            made = photos.thumbnail(shot)
            with self.lock:
                self.wanted.discard(shot.path)
            if made:
                GLib.idle_add(on_ready, made)
        self.pool.submit(work)

    def fetch(self, shot, on_ready, on_fail):
        """Pull a whole file off the phone -- for opening, saving or dragging."""
        def work():
            try:
                with open(shot.path, "rb"):
                    pass  # touch it so a gone file fails here, not in the viewer
            except OSError as exc:
                return GLib.idle_add(on_fail, str(exc))
            return GLib.idle_add(on_ready)
        self.pool.submit(work)


class Tile(Gtk.FlowBoxChild):
    """One picture in the grid. Draws empty and fills in when its turn comes."""

    def __init__(self, win, shot):
        super().__init__()
        self.win, self.shot, self.asked, self.ready = win, shot, False, False

        # A Gtk.Picture asks for the size of the picture in it, so a tile built
        # around one grows to whatever the phone shot. The tile is sized by an
        # empty box instead, and everything else -- the photo included -- is an
        # overlay on top of it, which the overlay does not measure.
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        frame = Gtk.Overlay(child=Gtk.Box(width_request=TILE, height_request=TILE),
                            overflow=Gtk.Overflow.HIDDEN)
        frame.add_css_class("tile")
        frame.add_overlay(self.picture)

        stamp = Gtk.Label(label=day(shot.mtime), halign=Gtk.Align.START,
                          valign=Gtk.Align.END)
        stamp.add_css_class("tile-when")
        frame.add_overlay(stamp)

        if shot.kind == "video":
            badge = Gtk.Image(icon_name="media-playback-start-symbolic", pixel_size=20,
                              halign=Gtk.Align.END, valign=Gtk.Align.START)
            badge.add_css_class("tile-badge")
            frame.add_overlay(badge)

        square = frame
        self.set_child(square)
        self.set_tooltip_text(f"{shot.name} · {shot.folder}\n"
                              "Click to open · right-click to save · drag to copy")

        click = Gtk.GestureClick(button=0)
        click.connect("released", self.on_click)
        square.add_controller(click)

        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY)
        drag.connect("prepare", self.on_drag)
        square.add_controller(drag)

    def want(self):
        """Called when the tile comes near the viewport."""
        if self.asked:
            return
        self.asked = True
        self.win.roll.thumbnail(self.shot, self.show)

    def show(self, path):
        texture, _w, _h = widgets.texture_from_file(path)
        if texture:
            self.picture.set_paintable(texture)
            self.ready = True

    def on_click(self, gesture, *_):
        if gesture.get_current_button() == Gdk.BUTTON_SECONDARY:
            self.win.save(self.shot)
        elif gesture.get_current_button() == Gdk.BUTTON_PRIMARY:
            self.win.open(self.shot)

    def on_drag(self, *_):
        # The file is on the mount, so handing over its path is enough: the
        # app on the other end reads it straight off the phone.
        files = Gdk.FileList.new_from_array([Gio.File.new_for_path(self.shot.path)])
        return Gdk.ContentProvider.new_for_value(files)


class PhotosWindow(Adw.ApplicationWindow):

    def __init__(self, app):
        super().__init__(application=app, title="Photos",
                         default_width=980, default_height=720)
        self.roll = Roll()
        self.tiles = []

        self.toasts = Adw.ToastOverlay()
        self.head = Adw.HeaderBar()
        self.subtitle = Adw.WindowTitle(title="Photos", subtitle="Looking for the phone…")
        self.head.set_title_widget(self.subtitle)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Look again")
        refresh.connect("clicked", lambda *_: self.load())
        self.head.pack_end(refresh)

        self.grid = Gtk.FlowBox(valign=Gtk.Align.START, halign=Gtk.Align.CENTER,
                                selection_mode=Gtk.SelectionMode.NONE,
                                homogeneous=True, column_spacing=8, row_spacing=8,
                                min_children_per_line=1, max_children_per_line=16)
        self.grid.add_css_class("roll")
        self.scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True, child=self.grid)
        adjustment = self.scroller.get_vadjustment()
        adjustment.connect("value-changed", lambda *_: self.reveal())
        # "changed" is the one that fires when the grid finally has a size, so
        # it is what brings us back after a load that finished first.
        adjustment.connect("changed", lambda *_: self.reveal())

        self.status = Adw.StatusPage(icon_name="image-x-generic-symbolic",
                                     title="Looking for the phone…")
        self.stack = Gtk.Stack()
        self.stack.add_named(self.status, "status")
        self.stack.add_named(self.scroller, "grid")

        body = Gtk.Box(orientation=VERTICAL)
        body.append(self.head)
        body.append(self.stack)
        self.toasts.set_child(body)
        self.set_content(self.toasts)

        self.load()

    # ------------------------------------------------------------- loading

    def load(self):
        self.stack.set_visible_child_name("status")
        self.status.set_title("Reaching the phone…")
        self.status.set_description("Waking it up and opening its storage.")
        self.subtitle.set_subtitle("connecting…")
        self.roll.open(self.on_loaded)

    def on_loaded(self, shots, device, problem):
        if problem:
            self.show_problem(problem, device)
            return False
        if not shots:
            self.status.set_title("Nothing in the camera roll")
            self.status.set_description(
                "No photos, screenshots or videos where Android usually keeps them.")
            self.stack.set_visible_child_name("status")
            self.subtitle.set_subtitle(device)
            return False
        self.fill(shots, device)
        return False

    def show_problem(self, problem, device):
        title, body = {
            "no-phone": ("Phone not connected",
                         "Open KDE Connect on the phone, or check it is on the same "
                         "network. `phonelink status` will say more."),
            "no-sshfs": ("sshfs isn't installed",
                         "The phone's storage is mounted with it:\n\n"
                         "    sudo pacman -S sshfs"),
            "no-mount": ("Couldn't open the phone's storage",
                         "KDE Connect didn't mount it. Unlock the phone and try again; "
                         "`phonelink kde restart` if it stays stuck."),
        }.get(problem, ("Couldn't open the phone's storage", problem))
        self.status.set_title(title)
        self.status.set_description(body)
        self.stack.set_visible_child_name("status")
        self.subtitle.set_subtitle(device or "not connected")
        return False

    def fill(self, shots, device):
        widgets.clear(self.grid)
        self.tiles = [Tile(self, shot) for shot in shots]
        for tile in self.tiles:
            self.grid.append(tile)
        pictures = sum(1 for s in shots if s.kind == "image")
        videos = len(shots) - pictures
        counted = f"{pictures} photo{'s' if pictures != 1 else ''}"
        if videos:
            counted += f" · {videos} video{'s' if videos != 1 else ''}"
        self.subtitle.set_subtitle(f"{device} · {counted}")
        self.stack.set_visible_child_name("grid")
        # The tiles have no size until GTK has laid them out once.
        GLib.idle_add(self.reveal)

    def reveal(self):
        """Ask for the thumbnails of every tile at or near the viewport.

        This is the whole reason the window opens quickly on a roll of two
        hundred: the rest are still empty frames costing nothing.
        """
        adjustment = self.scroller.get_vadjustment()
        scroll, page = adjustment.get_value(), adjustment.get_page_size()
        # Until GTK has laid the grid out every tile measures as nothing at the
        # top, and photos.in_view calls that invisible. Waking the phone can
        # take half a minute -- long enough for the tiles to exist before the
        # grid has a size -- and the adjustment's "changed" brings us back.
        if self.grid.get_height() <= 0:
            return False
        for tile in self.tiles:
            if tile.asked:
                continue
            ok, rect = tile.compute_bounds(self.grid)
            if ok and photos.in_view(rect.origin.y, rect.size.height, scroll, page, AHEAD):
                tile.want()
        return False

    # -------------------------------------------------------------- actions

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def open(self, shot):
        self.toast("Opening it from the phone…")

        def ready():
            try:
                photos.open_shot(shot)
            except GLib.Error as exc:
                self.toast(f"Couldn't open it: {exc.message}")
            return False
        self.roll.fetch(shot, ready, lambda why: self.toast(f"It's gone from the phone ({why})"))

    def save(self, shot):
        def work():
            try:
                dest = photos.save(shot)
            except OSError as exc:
                return GLib.idle_add(self.toast, f"Couldn't save it: {exc}")
            return GLib.idle_add(self.toast, f"Saved to {dest.parent.name}/{dest.name}")
        self.toast("Saving it from the phone…")
        self.roll.pool.submit(work)


class App(Adw.Application):

    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        pal = theme.load_palette()
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if pal.get("mode") == "light"
            else Adw.ColorScheme.FORCE_DARK)
        css = Gtk.CssProvider()
        css.load_from_string(theme.build_css(pal) + extra_css(pal))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if self.win:  # opened again while open: bring it forward
            self.win.present()
            return
        self.win = PhotosWindow(self)
        self.win.present()


if __name__ == "__main__":
    sys.exit(App().run([sys.argv[0]]))
