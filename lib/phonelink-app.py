#!/usr/bin/env python3
"""phonelink app -- the one window: Overview, Messages and Photos as tabs.

    phonelink app                 Overview
    phonelink app --page NAME     overview, messages or photos
    phonelink app --new [who]     Messages, on a new text

Overview is the phone at a glance: its name, battery and signal, a row of
tiles for the things phonelink does, what it is playing, and its
notifications. Messages and Photos are built the first time their tab is
opened, so opening the window never mounts the phone's storage or asks it for
its texts unasked.

A second launch hands its arguments to the open window (GApplication does
the forwarding), which is how `phonelink text 555` lands in a window that is
already up.
"""

import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from phonelink import history, kdeconnect as kde, mpris, overview, sms, theme, widgets  # noqa: E402
from phonelink import messages_page, photos_page, remote_page, settings_page  # noqa: E402

APP_ID = "org.omarchy.phonelink.app"
PHONELINK = str(HERE.parent / "phonelink")
VERTICAL = Gtk.Orientation.VERTICAL
POLL_S = 2

# (command, label, icon): each runs `phonelink <command>`, which already knows
# how to fail usefully.
TILES = (
    ("ring", "Ring", "find-location-symbolic"),
    ("send", "Send files", "document-send-symbolic"),
    ("clip", "Clipboard", "edit-paste-symbolic"),
    ("mirror", "Mirror", "video-display-symbolic"),
    ("desk", "App window", "view-app-grid-symbolic"),
    ("drop", "LocalSend", "network-wireless-symbolic"),
    ("webcam toggle", "Webcam", "camera-web-symbolic"),
)


def extra_css(p):
    on_accent = theme.ink_on(p, p["accent"])
    return f"""
.hub-switcher button {{ border-radius: 999px; padding: 4px 14px; font-weight: 600; }}
.hub-switcher button:checked {{ background: alpha({p['accent']}, 0.22); color: {p['foreground']}; }}
.hub-page {{ padding: 18px 20px 24px; }}
.hub-card {{ background: {p['lighter_background']}; border-radius: 24px; padding: 20px; }}
.device-icon {{ background: alpha({p['accent']}, 0.22); color: {p['accent']};
                border-radius: 999px; min-width: 96px; min-height: 96px; }}
.device-name {{ font-size: 22pt; font-weight: 700; }}
.chip {{ background: alpha({p['foreground']}, 0.07); border-radius: 999px;
         padding: 3px 14px; font-size: 9pt; }}
.chip.lead {{ background: alpha({p['accent']}, 0.85); color: {on_accent}; font-weight: 600; }}
.chip.bad {{ background: alpha({p['red']}, 0.85); color: {theme.ink_on(p, p['red'])}; }}
.action-tile {{ background: {p['lighter_background']}; border-radius: 18px;
         min-width: 84px; min-height: 84px; padding: 10px 6px; }}
.action-tile:hover {{ background: alpha({p['accent']}, 0.16); }}
.action-tile label {{ font-size: 9pt; font-weight: 600; }}
.action-tile image {{ color: {p['accent']}; }}
.media-art {{ border-radius: 20px; background: alpha({p['accent']}, 0.12); color: {p['accent']}; }}
.media-title {{ font-size: 17pt; font-weight: 600; }}
.media-artist {{ font-size: 11pt; color: {p['muted']}; }}
.media-album {{ font-size: 10pt; }}
.media-time {{ font-size: 8.5pt; color: {p['muted']}; }}
.media-btn {{ border-radius: 999px; min-width: 46px; min-height: 46px; padding: 0;
              background: alpha({p['foreground']}, 0.07); }}
.media-play {{ border-radius: 999px; min-height: 52px; padding: 0 40px;
               background: {p['accent']}; color: {on_accent}; }}
.card-head {{ font-size: 9pt; font-weight: 600; color: {p['accent']}; }}
.note-app {{ font-size: 8.5pt; color: {p['accent']}; }}
.note-title {{ font-weight: 600; }}
.note-text {{ color: {p['muted']}; }}
"""


# ----------------------------------------------------------------- overview

class OverviewPage(Adw.Bin):

    def __init__(self, toast):
        super().__init__()
        self.toast = toast
        self.snap, self.busy = {"state": "away"}, False
        self.shown_notes = None
        self._seek_id = self._vol_id = 0

        box = Gtk.Box(orientation=VERTICAL, spacing=16)
        box.add_css_class("hub-page")
        box.append(self.build_device())
        box.append(self.build_tiles())
        box.append(self.build_media())
        box.append(self.build_notes())
        box.append(self.build_history())
        clamp = Adw.Clamp(maximum_size=820, child=box)
        self.set_child(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=clamp))
        # Files dropped anywhere on the page go to the phone, as `phonelink send`.
        # Only here: the Messages tab takes a drop as an attachment instead.
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.add_controller(drop)

    # -- the phone

    def build_device(self):
        icon = Gtk.Image(icon_name="phone-symbolic", pixel_size=44)
        icon.add_css_class("device-icon")
        self.name = widgets.label("Looking for the phone…", "device-name",
                                  ellipsize=Pango.EllipsizeMode.END)
        self.chips = Gtk.Box(spacing=8)
        text = Gtk.Box(orientation=VERTICAL, spacing=10, valign=Gtk.Align.CENTER)
        text.append(self.name)
        text.append(self.chips)
        card = Gtk.Box(spacing=22)
        card.add_css_class("hub-card")
        card.append(icon)
        card.append(text)
        return card

    def build_tiles(self):
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           column_spacing=12, row_spacing=12, min_children_per_line=7,
                           max_children_per_line=7)
        for command, text, icon in TILES:
            inner = Gtk.Box(orientation=VERTICAL, spacing=8, valign=Gtk.Align.CENTER)
            inner.append(Gtk.Image(icon_name=icon, pixel_size=24))
            inner.append(Gtk.Label(label=text))
            button = Gtk.Button(child=inner, tooltip_text=f"phonelink {command}")
            button.add_css_class("action-tile")
            button.connect("clicked", lambda _b, c=command: self.run(c))
            grid.append(button)
        return grid

    def on_drop(self, _target, files, _x, _y):
        paths = [f.get_path() for f in files.get_files() if f.get_path()]
        if not paths:
            return False
        try:
            subprocess.Popen([PHONELINK, "send", *paths], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            self.toast(f"Couldn't send: {exc.strerror}")
            return False
        self.toast(f"Sending {len(paths)} file{'s' if len(paths) != 1 else ''} to the phone")
        return True

    def run(self, command):
        try:
            subprocess.Popen([PHONELINK, *command.split()], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            self.toast(f"Couldn't run phonelink {command}: {exc.strerror}")

    # -- what it is playing

    def build_media(self):
        self.art = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        art_frame = Gtk.Overlay(child=Gtk.Box(width_request=180, height_request=180),
                                overflow=Gtk.Overflow.HIDDEN, valign=Gtk.Align.CENTER)
        art_frame.add_css_class("media-art")
        art_frame.add_overlay(Gtk.Image(icon_name="audio-x-generic-symbolic", pixel_size=56))
        art_frame.add_overlay(self.art)

        self.title = widgets.label("", "media-title", ellipsize=Pango.EllipsizeMode.END)
        self.artist = widgets.label("", "media-artist", ellipsize=Pango.EllipsizeMode.END)
        self.album = widgets.label("", "media-album", ellipsize=Pango.EllipsizeMode.END)

        self.pos = widgets.label("0:00", "media-time")
        self.len = widgets.label("0:00", "media-time")
        self.seek = Gtk.Scale(hexpand=True, draw_value=False,
                              adjustment=Gtk.Adjustment(upper=1, step_increment=1000))
        self.seek.connect("change-value", self.on_seek)
        bar = Gtk.Box(spacing=10)
        bar.append(self.pos)
        bar.append(self.seek)
        bar.append(self.len)

        buttons = Gtk.Box(spacing=10)
        prev = Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text="Previous")
        self.play = Gtk.Button(icon_name="media-playback-start-symbolic", hexpand=True)
        nxt = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text="Next")
        for button, action in ((prev, "Previous"), (self.play, "PlayPause"), (nxt, "Next")):
            button.add_css_class("media-play" if button is self.play else "media-btn")
            button.connect("clicked", lambda _b, a=action: self.media(a))
            buttons.append(button)

        self.volume = Gtk.Scale(hexpand=True, draw_value=False,
                                adjustment=Gtk.Adjustment(upper=100, step_increment=5))
        self.volume.connect("change-value", self.on_volume)
        vol = Gtk.Box(spacing=10)
        vol.append(Gtk.Image(icon_name="audio-volume-high-symbolic"))
        vol.append(self.volume)

        right = Gtk.Box(orientation=VERTICAL, spacing=10, hexpand=True, valign=Gtk.Align.CENTER)
        for widget in (self.title, self.artist, self.album, bar, buttons, vol):
            right.append(widget)
        self.media_card = Gtk.Box(spacing=26, visible=False)
        self.media_card.add_css_class("hub-card")
        self.media_card.append(art_frame)
        self.media_card.append(right)
        return self.media_card

    def media(self, action):
        if did := self.snap.get("id"):
            widgets.in_background(lambda: mpris.send(did, action), self.toast)

    def on_seek(self, _scale, _scroll, value):
        # A drag fires this for every pixel; only where it stops goes to the phone.
        if self._seek_id:
            GLib.source_remove(self._seek_id)
        self._seek_id = GLib.timeout_add(250, self.send_seek, value)
        return False

    def send_seek(self, value):
        self._seek_id = 0
        if did := self.snap.get("id"):
            widgets.in_background(lambda: mpris.seek_to(did, value), self.toast)
        return False

    def on_volume(self, _scale, _scroll, value):
        if self._vol_id:
            GLib.source_remove(self._vol_id)
        self._vol_id = GLib.timeout_add(150, self.send_volume, value)
        return False

    def send_volume(self, value):
        self._vol_id = 0
        if did := self.snap.get("id"):
            widgets.in_background(lambda: mpris.set_volume(did, value), self.toast)
        return False

    # -- notifications

    def build_notes(self):
        head = Gtk.Box()
        head.append(widgets.label("Notifications", "card-head", hexpand=True))
        clear = Gtk.Button(child=Adw.ButtonContent(icon_name="edit-clear-all-symbolic",
                                                   label="Clear all"))
        clear.add_css_class("flat")
        clear.connect("clicked", lambda *_: self.clear_all())
        head.append(clear)
        self.notes = Gtk.Box(orientation=VERTICAL, spacing=14)
        card = Gtk.Box(orientation=VERTICAL, spacing=12)
        card.add_css_class("hub-card")
        card.append(head)
        card.append(self.notes)
        return card

    # -- what came before

    def build_history(self):
        self.search = Gtk.SearchEntry(placeholder_text="Search past notifications", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.draw_history())
        self.past = Gtk.Box(orientation=VERTICAL, spacing=14)
        card = Gtk.Box(orientation=VERTICAL, spacing=12)
        card.add_css_class("hub-card")
        card.append(widgets.label("History", "card-head"))
        card.append(self.search)
        card.append(self.past)
        self.draw_history()
        return card

    def draw_history(self):
        query = self.search.get_text().strip()
        hits = history.search(query, history.load(), limit=30 if query else 5)
        widgets.clear(self.past)
        for e in hits:
            text = Gtk.Box(orientation=VERTICAL, hexpand=True)
            text.append(widgets.label(f"{e.get('app', '')} · {sms.when(e.get('time', 0) * 1000)}",
                                      "note-app"))
            if e.get("title"):
                text.append(widgets.label(e["title"], "note-title", ellipsize=Pango.EllipsizeMode.END))
            if e.get("text"):
                text.append(widgets.label(e["text"], "note-text", wrap=True, lines=2,
                                          ellipsize=Pango.EllipsizeMode.END, selectable=True))
            row = Gtk.Box(spacing=12)
            row.append(widgets.avatar(e.get("app", ""), 38))
            row.append(text)
            self.past.append(row)
        if not hits:
            empty = ("Nothing kept matches" if query else
                     "Notifications are kept here as they arrive, while phonelink toasts are on"
                     if history.enabled() else "History is off: phonelink history on")
            self.past.append(widgets.label(empty, "note-text"))

    def note_row(self, note):
        text = Gtk.Box(orientation=VERTICAL, hexpand=True)
        text.append(widgets.label(note["app"], "note-app"))
        if note["title"]:
            text.append(widgets.label(kde.plain(note["title"]), "note-title",
                                      ellipsize=Pango.EllipsizeMode.END))
        if body := kde.plain(note["text"] or note["ticker"]):
            text.append(widgets.label(body, "note-text", wrap=True, lines=2,
                                      ellipsize=Pango.EllipsizeMode.END))
        row = Gtk.Box(spacing=12)
        row.append(widgets.avatar(note["app"], 38, note["icon"]))
        row.append(text)
        if note["dismissable"]:
            close = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.START,
                               tooltip_text="Clear on the phone")
            close.add_css_class("flat")
            close.add_css_class("circular")
            close.connect("clicked", lambda *_: self.dismiss([note]))
            row.append(close)
        return row

    def dismiss(self, notes):
        paths = [n["path"] for n in notes if n["dismissable"]]
        widgets.in_background(lambda: [kde.dismiss(p) for p in paths])
        self.snap["notes"] = [n for n in self.snap.get("notes", []) if n["path"] not in paths]
        self.draw_notes()

    def clear_all(self):
        self.dismiss(self.snap.get("notes", []))

    def draw_notes(self):
        notes = self.snap.get("notes", [])
        key = tuple((n["path"], n["title"], n["text"]) for n in notes)
        if key == self.shown_notes:
            return
        self.shown_notes = key
        widgets.clear(self.notes)
        for note in notes:
            self.notes.append(self.note_row(note))
        if not notes:
            self.notes.append(widgets.label("Nothing new on the phone", "note-text"))
        if not self.search.get_text():
            self.draw_history()  # what just arrived is history too

    # -- keeping it current

    def poll(self):
        """Read the phone on a thread; never more than one read at a time."""
        if self.busy:
            return
        self.busy = True

        def work():
            snap = overview.snapshot()
            GLib.idle_add(self.apply, snap)
        threading.Thread(target=work, daemon=True).start()

    def apply(self, snap):
        self.busy = False
        self.snap = snap
        ok = snap["state"] == "ok"
        self.name.set_label(snap.get("name") or "No phone")
        widgets.clear(self.chips)
        for n, text in enumerate(overview.chips(snap)):
            chip = Gtk.Label(label=("● " if n == 0 and ok else "") + text)
            chip.add_css_class("chip")
            if n == 0:
                chip.add_css_class("lead" if ok else "bad")
            self.chips.append(chip)
        self.draw_media(snap.get("media"))
        self.draw_notes()
        return False

    def draw_media(self, m):
        loaded = bool(m) and m["status"] != mpris.IDLE
        self.media_card.set_visible(loaded)
        if not loaded:
            return
        self.title.set_label(m["title"] or m["player"])
        self.artist.set_label(m["artist"])
        self.album.set_label(m["album"])
        self.album.set_visible(bool(m["album"]))
        self.play.set_icon_name("media-playback-pause-symbolic" if m["playing"]
                                else "media-playback-start-symbolic")
        self.seek.set_sensitive(m["can_seek"] and m["length"] > 0)
        if not self._seek_id:
            self.seek.get_adjustment().set_upper(max(1, m["length"]))
            self.seek.set_value(m["position"])
        self.pos.set_label(mpris.clock(m["position"]))
        self.len.set_label(mpris.clock(m["length"]))
        if not self._vol_id:
            self.volume.set_value(m["volume"])
        art = m["art"]
        if art.startswith("file://"):
            art = Gio.File.new_for_uri(art).get_path()
        if art != getattr(self, "shown_art", None):
            self.shown_art = art
            texture = widgets.texture_from_file(art, 360)[0] if art else None
            self.art.set_paintable(texture)


# ------------------------------------------------------------------- window

class Window(Adw.ApplicationWindow):

    def __init__(self, app):
        super().__init__(application=app, title="Phone", default_width=1100, default_height=780)
        self.toasts = Adw.ToastOverlay()
        self.stack = Adw.ViewStack()
        self.overview = OverviewPage(self.toast)
        self.stack.add_titled_with_icon(self.overview, "overview", "Overview",
                                        "view-grid-symbolic")
        # The other tabs are empty until first opened.
        for name, title, icon in (("messages", "Messages", "mail-unread-symbolic"),
                                  ("photos", "Photos", "image-x-generic-symbolic"),
                                  ("remote", "Remote", "input-touchpad-symbolic"),
                                  ("settings", "Settings", "emblem-system-symbolic")):
            self.stack.add_titled_with_icon(Adw.Bin(), name, title, icon)
        self.stack.connect("notify::visible-child-name", lambda *_: self.on_page())

        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        switcher.add_css_class("hub-switcher")
        head = Adw.HeaderBar(title_widget=switcher)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(head)
        self.toasts.set_child(self.stack)
        self.set_content(view)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_: kv == Gdk.KEY_Escape and (self.close() or True))
        self.add_controller(keys)

        self.overview.poll()
        GLib.timeout_add_seconds(POLL_S, self.tick)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))
        return False

    def tick(self):
        # Only while it can be seen: a phone is not polled for a hidden page.
        if self.stack.get_visible_child_name() == "overview" and self.is_visible():
            self.overview.poll()
        return True

    def page(self, name):
        """The page widget for a tab, built on first use."""
        holder = self.stack.get_child_by_name(name)
        if name == "overview" or holder.get_child():
            return holder if name == "overview" else holder.get_child()
        if name == "messages":
            built = messages_page.MessagesPage(messages_page.Phone())
        elif name == "photos":
            built = photos_page.PhotosPage()
        elif name == "remote":
            built = remote_page.RemotePage(kde.phone(), self.toast)
        else:
            built = settings_page.SettingsPage(self.toast)
        holder.set_child(built)
        return built

    def on_page(self):
        name = self.stack.get_visible_child_name()
        self.page(name)
        if name == "overview":
            self.overview.poll()

    def open_page(self, name, new_to=None):
        self.stack.set_visible_child_name(name)
        self.page(name)
        if new_to is not None:
            messages = self.page("messages")
            if messages.phone.id:
                messages.start_new(new_to)
        self.present()


class App(Adw.Application):

    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        pal = theme.load_palette()
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if pal.get("mode") == "light"
            else Adw.ColorScheme.FORCE_DARK)
        css = Gtk.CssProvider()
        css.load_from_string(theme.build_css(pal) + messages_page.extra_css(pal)
                             + photos_page.extra_css(pal) + remote_page.extra_css(pal)
                             + extra_css(pal))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_command_line(self, command_line):
        # Runs in the first instance for every launch, the later ones included.
        page, new_to = overview.parse_args(command_line.get_arguments())
        if self.win is None:
            self.win = Window(self)
            self.win.connect("close-request", lambda *_: setattr(self, "win", None))
        self.win.open_page(page, new_to)
        return 0


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
