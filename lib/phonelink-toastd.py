#!/usr/bin/env python3
"""phonelink toasts -- Phone Link-style popups for phone notifications.

A small resident GTK app. It listens for KDE Connect's notificationPosted /
notificationUpdated / notificationRemoved signals and draws each phone
notification as a toast in the corner of the screen: the app, the sender's
avatar and name, the message, and -- when the phone would let you answer from
its own notification shade -- a reply box right in the toast.

The card is sized and themed like Omarchy's own notifications (width, padding,
corner rounding, the active-border gradient, the countdown bar, Do Not
Disturb), so it belongs on the desktop; the layout is Phone Link's. KDE
Connect's plain popup for the same notification is switched off by
`phonelink toasts on`, so each message pops once. Calls, pairing requests and
the rest keep KDE Connect's normal popups.

gtk4-layer-shell has to be loaded before GTK, so run this through
`phonelink toastd`, which sets LD_PRELOAD.

    phonelink-toastd.py             resident (what the systemd user service runs)
    phonelink-toastd.py --demo      sample toasts, to check the look
    phonelink-toastd.py --show ID   draw one existing phone notification now
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

HERE = Path(__file__).resolve().parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The reply window already reads the theme, draws avatars and words errors; the
# helper already reads and parses notifications. Reuse both rather than fork.
ui = _load("phonelink_reply", "phonelink-reply-gtk.py")
kn = _load("kdeconnect_notify", "kdeconnect-notify.py")

APP_ID = "org.omarchy.phonelink.toasts"
PLUGIN_IFACE = "org.kde.kdeconnect.device.notifications"
DEVICES = "/modules/kdeconnect/devices/"
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
MAX_TOASTS = 3
VERTICAL = Gtk.Orientation.VERTICAL
# Omarchy's normal-urgency lifetime; the countdown pauses while you hover or type.
DURATION_MS = int(os.environ.get("PHONELINK_TOAST_MS", "8000"))


# ----------------------------------------------------------------- the look

def run_json(*cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
        return json.loads(out)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


def read_toml(path):
    try:
        return tomllib.loads(Path(path).read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def active_border(fallback):
    """Hyprland's active border as (css angle, [colours]) -- Omarchy's toasts use it."""
    opt = run_json("hyprctl", "getoption", "general:col.active_border", "-j")
    text = str(opt.get("gradient") or opt.get("custom") or opt.get("str") or "")
    colours = []
    for token in text.split():
        token = token.lower()
        if m := re.fullmatch(r"rgba\(([0-9a-f]{6})[0-9a-f]{2}\)", token):
            colours.append("#" + m.group(1))
        elif m := re.fullmatch(r"(?:0x)?[0-9a-f]{2}([0-9a-f]{6})", token):
            colours.append("#" + m.group(1))  # hyprctl prints AARRGGBB
    angle = next((float(t[:-3]) for t in text.split() if t.endswith("deg")), 0.0)
    # Hyprland's 0deg runs left to right; CSS's 90deg does.
    return round(90 - angle) % 360, colours or [fallback]


def bar_clearance():
    """Height of a top bar, so a top-right toast clears it the way Omarchy's do."""
    for monitor in run_json("hyprctl", "layers", "-j").values():
        for level in monitor.get("levels", {}).values():
            for layer in level:
                if (layer.get("namespace") == "omarchy-bar" and layer.get("y") == 0
                        and layer.get("w", 0) > layer.get("h", 0)):
                    return int(layer["h"])
    return 0


def hex_rgba(hexc, alpha):
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def darker(hexc, factor):
    """Roughly Qt.darker(), which Omarchy uses for toast body text."""
    r, g, b = (round(int(hexc[i:i + 2], 16) / factor) for i in (1, 3, 5))
    return f"#{r:02x}{g:02x}{b:02x}"


def text_label(text, css, **kw):
    """A label that fills the width it is given instead of asking for more.

    A wrapping or ellipsizing label reports its unwrapped length as its natural
    width, and a toast window sizes itself to its content, so one long message
    would stretch the card past Omarchy's width. max_width_chars=1 drops the
    request to nothing; hexpand then hands it the card's width to wrap within.
    """
    return ui.label(text, css, max_width_chars=1, hexpand=True, **kw)


class Look:
    """Omarchy's notification card, measured from the live theme and Hyprland."""

    def __init__(self):
        self.pal = ui.load_palette()
        theme = STATE / "omarchy/current/theme"
        notif = read_toml(theme / "shell.notifications.toml").get("notifications", {})
        font = {**read_toml(theme / "shell.toml").get("font", {}),
                **read_toml(Path.home() / ".config/omarchy/shell.toml").get("font", {})}
        base = font.get("base-size")
        base = base if isinstance(base, (int, float)) and base > 0 else 12

        def space(px):  # Omarchy's Style.space(): pixel tokens scale with the font
            return max(1, round(px * base / 12))

        self.width = space(380)
        self.pad_h, self.pad_v = space(12), space(10)
        self.icon, self.spacing = space(40), space(8)
        self.title_px, self.body_px, self.caption_px = (round(base * k) for k in (1.167, 1.0, 0.833))

        rounding = run_json("hyprctl", "getoption", "decoration:rounding", "-j").get("int")
        self.radius = rounding if isinstance(rounding, int) and rounding >= 0 else 10
        gaps = str(run_json("hyprctl", "getoption", "general:gaps_out", "-j").get("css", "")).split()
        self.margin = round(int(gaps[0]) / 2) if gaps and gaps[0].isdigit() else 7  # Style.gapsOut

        def colour(key, default):
            return notif.get(key) if ui.is_hex(notif.get(key)) else default

        self.bg = colour("background", self.pal["dark_background"])
        self.bg_alpha = float(notif.get("background-alpha", 0.97))
        self.text = colour("text", self.pal["foreground"])
        self.countdown = colour("countdown", self.pal["accent"])
        self.border_w = int(notif.get("border-width", 2))
        border = notif.get("border", "hyprland.active-border")
        if ui.is_hex(border):
            self.border_angle, self.border_colours = 90, [border]
        else:
            self.border_angle, self.border_colours = active_border(self.pal["accent"])

        # Bottom-right by default, where Phone Link puts them -- and clear of
        # Omarchy's own toasts, which stack top-right and would overlap.
        self.top = os.environ.get("PHONELINK_TOAST_POSITION", "bottom-right") == "top-right"
        self.first_offset = (bar_clearance() + self.margin) if self.top else self.margin

    def css(self):
        p = self.pal
        on_accent = ui.ink_on(p, p["accent"])
        stops = self.border_colours * (2 if len(self.border_colours) == 1 else 1)
        inner = max(0, self.radius - self.border_w)
        return f"""
window.phonelink-toast {{ background: transparent; }}
.toast-frame {{ background-image: linear-gradient({self.border_angle}deg, {", ".join(stops)});
                border-radius: {self.radius}px; padding: {self.border_w}px; }}
.toast {{ background-color: {hex_rgba(self.bg, self.bg_alpha)}; border-radius: {inner}px;
          font-family: "Adwaita Sans", sans-serif; }}
.toast .content {{ padding: {self.pad_v}px {self.pad_h}px; }}
.toast .app-glyph {{ font-family: "JetBrainsMono Nerd Font", monospace;
                     font-size: {self.caption_px}px; color: {self.countdown}; }}
.toast .app     {{ font-size: {self.caption_px}px; color: {p['muted']}; }}
.toast .name    {{ font-size: {self.title_px}px; font-weight: 700; color: {self.text}; }}
.toast .message {{ font-size: {self.body_px}px; color: {darker(self.text, 1.15)}; }}
.toast .close   {{ min-width: 24px; min-height: 24px; padding: 0; border-radius: 999px;
                   background: transparent; color: {p['muted']}; }}
.toast .close:hover {{ background: alpha({self.text}, 0.08); color: {self.text}; }}
.toast entry {{ border-radius: 999px; min-height: 34px; padding: 0 14px; font-size: {self.body_px}px;
                background: {p['lighter_background']}; color: {self.text};
                box-shadow: none; outline: none; }}
.toast entry:focus-within {{ box-shadow: inset 0 0 0 1px alpha({p['accent']}, 0.65); }}
.toast .send {{ border-radius: 999px; min-width: 34px; min-height: 34px; padding: 0;
                background: {p['accent']}; color: {on_accent}; }}
.toast .send:disabled {{ background: {p['lighter_background']}; color: {p['muted']}; }}
.toast .sent  {{ font-size: {self.body_px}px; font-weight: 600; color: {p['accent']}; }}
.toast .error {{ font-size: {self.caption_px}px; color: {p['red']}; }}
.toast progressbar trough   {{ min-height: 2px; background: transparent; border: none; box-shadow: none; }}
.toast progressbar progress {{ min-height: 2px; background: {self.countdown}; border: none; border-radius: 0; }}
"""


# -------------------------------------------------------------- notifications

def read_note(objpath):
    """A phone notification as the toast needs it, or None if it has gone."""
    try:
        props = kn.call(objpath, kn.PROPS, "GetAll",
                        GLib.Variant("(s)", (kn.NOTIF_IFACE,))).unpack()[0]
    except GLib.Error:
        return None
    text, ticker = props.get("text", ""), props.get("ticker", "")
    return {
        "path": objpath, "app": props.get("appName", ""), "title": props.get("title", ""),
        "text": text, "ticker": ticker,
        "thread": kn.parse_thread(text) or kn.parse_thread(ticker),
        "icon": kn.icon_path(props),
        "repliable": bool(props.get("replyId")),
        "silent": bool(props.get("silent")),
    }


def find_note(nid):
    for device in kn.children(DEVICES.rstrip("/")):
        objpath = f"{DEVICES}{device}/notifications/{nid}"
        if note := read_note(objpath):
            return note
    return None


def dnd_on():
    """Omarchy's Do Not Disturb: ask the shell, fall back to its state file."""
    try:
        out = subprocess.run(["omarchy-shell", "notifications", "isDnd"],
                             capture_output=True, text=True, timeout=1).stdout.strip()
        if out in ("on", "off"):
            return out == "on"
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        return bool(json.loads((STATE / "omarchy/notifications.json").read_text()).get("dnd"))
    except (OSError, ValueError):
        return False


# Fictional on purpose: this ships in a public repository.
DEMO_THREAD = ("<b>Amos Burton</b><br/>Reactor's back online<br/>"
               "<b>Alex Kamal</b><br/>Burn in five. Everyone strapped in?<br/>"
               "<b>Naomi Nagata</b><br/>Still seeing a fault on the rail, checking every range")


def demo_notes():
    def note(i, app, title, text, repliable):
        return {"path": f"demo:{i}", "app": app, "title": title, "text": text, "ticker": "",
                "thread": kn.parse_thread(text), "icon": "", "repliable": repliable,
                "silent": False}
    return [note(1, "Signal", "Rocinante crew", DEMO_THREAD, True),
            note(2, "Instagram", "bobbie.draper", "liked your reel", False),
            note(3, "Messenger", "Chrisjen Avasarala", "Call me when you land. We need to talk.", True)]


# ---------------------------------------------------------------------- toast

class Toast:

    def __init__(self, daemon, note):
        self.daemon, self.note, self.key = daemon, note, note["path"]
        self.remaining, self.hovered, self.busy, self.closed = 1.0, False, False, False
        self.entry = self.send_btn = self.error = None
        look = daemon.look

        self.win = win = Gtk.Window(application=daemon.app, decorated=False, resizable=False)
        win.add_css_class("phonelink-toast")
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "phonelink-toast")
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        self.edge = LayerShell.Edge.TOP if look.top else LayerShell.Edge.BOTTOM
        LayerShell.set_anchor(win, self.edge, True)
        LayerShell.set_anchor(win, LayerShell.Edge.RIGHT, True)
        LayerShell.set_margin(win, LayerShell.Edge.RIGHT, look.margin)
        # Never take the keyboard on arrival -- a toast must not swallow what
        # you are typing elsewhere -- but take it when you click the reply box.
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.ON_DEMAND)

        self.content = Gtk.Box(orientation=VERTICAL, spacing=look.pad_v // 2)
        self.content.add_css_class("content")
        self.bar = Gtk.ProgressBar(fraction=1.0)
        # Exactly Omarchy's card width: every label in it asks for no width of
        # its own (see text_label), so width_request is what sizes the window.
        # Clipped to its rounding so the countdown bar can't paint the corners.
        card = Gtk.Box(orientation=VERTICAL, width_request=look.width,
                       overflow=Gtk.Overflow.HIDDEN)
        card.add_css_class("toast")
        card.append(self.content)
        card.append(self.bar)
        self.frame = Gtk.Box()
        self.frame.add_css_class("toast-frame")
        self.frame.append(card)
        win.set_child(self.frame)

        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_: setattr(self, "hovered", True))
        hover.connect("leave", lambda *_: setattr(self, "hovered", False))
        self.frame.add_controller(hover)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", lambda _c, kv, *_: kv == Gdk.KEY_Escape and (self.close() or True))
        win.add_controller(keys)

        self.build()
        GLib.timeout_add(50, self.tick)

    # -- content

    def preview(self):
        thread = self.note.get("thread") or []
        if thread:
            last = thread[-1]
            who = (last.get("sender") or "").split()
            return f"{who[0]}: {last['body']}" if who else last["body"]
        return ui.plain(self.note.get("text") or self.note.get("ticker"))

    def build(self):
        typed = self.entry.get_text() if self.entry else ""
        had_focus = bool(self.entry and self.entry.has_focus())
        ui.clear(self.content)
        note, look = self.note, self.daemon.look

        header = Gtk.Box(spacing=6)
        header.append(ui.label("󰄜", "app-glyph"))
        header.append(text_label(note["app"] or "Phone", "app", ellipsize=Pango.EllipsizeMode.END))
        close = Gtk.Button(icon_name="window-close-symbolic", focus_on_click=False,
                           tooltip_text="Dismiss", valign=Gtk.Align.CENTER)
        close.add_css_class("close")
        close.connect("clicked", lambda *_: self.close())
        header.append(close)
        self.content.append(header)

        main = Gtk.Box(spacing=look.pad_h)
        av = ui.avatar(note["title"] or note["app"], look.icon, note.get("icon"))
        av.set_valign(Gtk.Align.START)
        main.append(av)
        text = Gtk.Box(orientation=VERTICAL, spacing=2, hexpand=True)
        text.append(text_label(note["title"] or note["app"] or "Phone", "name",
                               ellipsize=Pango.EllipsizeMode.END))
        if message := self.preview():
            text.append(text_label(message, "message", wrap=True,
                                   wrap_mode=Pango.WrapMode.WORD_CHAR,
                                   lines=3, ellipsize=Pango.EllipsizeMode.END))
        main.append(text)
        self.content.append(main)

        # Left-click the toast for the full conversation; right-click dismisses,
        # as on Omarchy's own toasts. Only the header and message react, so the
        # reply box and buttons keep their own clicks.
        for area in (header, main):
            click = Gtk.GestureClick(button=0)
            click.connect("released", self.on_click)
            area.add_controller(click)

        if note.get("repliable"):
            self.entry = Gtk.Entry(hexpand=True, placeholder_text="Reply", text=typed)
            self.entry.connect("activate", self.send)
            self.entry.connect("changed", lambda *_: self.sync_send())
            self.send_btn = Gtk.Button(icon_name=ui.send_icon(), valign=Gtk.Align.CENTER,
                                       tooltip_text="Send", focus_on_click=False)
            self.send_btn.add_css_class("send")
            self.send_btn.connect("clicked", self.send)
            row = Gtk.Box(spacing=8, margin_start=look.icon + look.pad_h, margin_top=4)
            row.append(self.entry)
            row.append(self.send_btn)
            self.content.append(row)
            self.error = text_label("", "error", margin_start=look.icon + look.pad_h,
                                    visible=False, wrap=True)
            self.content.append(self.error)
            self.sync_send()
            if had_focus:
                self.entry.grab_focus_without_selecting()
        else:
            self.entry = self.send_btn = self.error = None

    def update(self, note):
        self.note = note
        self.remaining = 1.0  # new text deserves a full look, as Omarchy does
        self.build()
        self.daemon.restack()

    def height(self):
        look = self.daemon.look
        return self.frame.measure(VERTICAL, look.width + 2 * look.border_w)[1]

    # -- lifetime

    def paused(self):
        typing = bool(self.entry and (self.entry.has_focus() or self.entry.get_text().strip()))
        return self.hovered or self.busy or typing

    def tick(self):
        if self.closed:
            return False
        if not self.paused():
            self.remaining -= 50 / DURATION_MS
            if self.remaining <= 0:
                self.close()
                return False
        self.bar.set_fraction(max(0.0, self.remaining))
        return True

    def on_click(self, gesture, _n, _x, _y):
        button = gesture.get_current_button()
        if button == Gdk.BUTTON_PRIMARY and self.note.get("repliable"):
            # The full conversation. A notification you can't answer has
            # nothing to open -- the phone's own app can't be launched from
            # here -- so for those a left-click just dismisses, like a right.
            self.daemon.open_full(self.note)
        if button in (Gdk.BUTTON_PRIMARY, Gdk.BUTTON_SECONDARY):
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.win.destroy()
        self.daemon.forget(self)

    # -- replying

    def sync_send(self):
        if self.send_btn:
            self.send_btn.set_sensitive(not self.busy and bool(self.entry.get_text().strip()))

    def send(self, *_):
        text = self.entry.get_text().strip()
        if not text or self.busy:
            return
        self.busy = True
        self.entry.set_editable(False)  # read-only, not insensitive: keeps focus
        self.sync_send()
        self.error.set_visible(False)
        self.daemon.send_reply(self.note, text, self.on_sent)

    def on_sent(self, ok, err):
        if self.closed:
            return
        if not ok:
            self.busy = False
            self.entry.set_editable(True)
            self.sync_send()
            self.error.set_label(ui.friendly_error(err))
            self.error.set_visible(True)
            self.entry.grab_focus_without_selecting()
            self.daemon.restack()
            return
        row = self.entry.get_parent()
        self.content.remove(row)
        self.content.remove(self.error)
        self.entry = self.send_btn = self.error = None
        self.content.append(ui.label("✓ Sent", "sent", margin_start=self.daemon.look.icon
                                     + self.daemon.look.pad_h))
        self.daemon.restack()
        GLib.timeout_add(1200, lambda: self.close() or False)


# --------------------------------------------------------------------- daemon

class Daemon:

    def __init__(self, app, mode):
        self.app, self.mode, self.toasts = app, mode, []  # newest first
        self.look = Look()
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if self.look.pal.get("mode") == "light"
            else Adw.ColorScheme.FORCE_DARK)
        css = Gtk.CssProvider()
        css.load_from_string(ui.build_css(self.look.pal) + self.look.css())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def start(self, arg):
        self.app.hold()
        if self.mode == "resident":
            # Any sender, not just org.kde.kdeconnect: the notification itself is
            # always read back from kdeconnectd, so a signal from elsewhere can at
            # most re-show a real notification -- which is how `--show` and the
            # tests drive this without waiting for a message to arrive.
            kn.BUS.signal_subscribe(None, PLUGIN_IFACE, None, None, None,
                                    Gio.DBusSignalFlags.NONE, self.on_signal)
            print("phonelink toasts: listening for phone notifications", flush=True)
        elif self.mode == "demo":
            for i, note in enumerate(demo_notes()):
                GLib.timeout_add(350 * i + 1, lambda n=note: self.show(n) or False)
        else:
            note = find_note(arg)
            if not note:
                print(f"no phone notification with id {arg!r}", file=sys.stderr)
                self.app.release()
                return
            self.show(note)

    def on_signal(self, _conn, _sender, path, _iface, member, params):
        if not (path.startswith(DEVICES) and path.endswith("/notifications")):
            return
        if member == "allNotificationsRemoved":
            for toast in list(self.toasts):
                if toast.key.startswith(path + "/"):
                    toast.close()
            return
        if member not in ("notificationPosted", "notificationUpdated", "notificationRemoved"):
            return
        objpath = f"{path}/{params.unpack()[0]}"
        shown = next((t for t in self.toasts if t.key == objpath), None)
        if member == "notificationRemoved":
            if shown:
                shown.close()  # read or dismissed on the phone: gone here too
            return
        note = read_note(objpath)
        if not note:
            return
        if shown:
            shown.update(note)
        elif member == "notificationPosted" and not note["silent"] and not dnd_on():
            # KDE Connect never pops a silent notification either; honouring the
            # flag keeps a reconnect from replaying the whole shade as toasts.
            self.show(note)

    def show(self, note):
        if shown := next((t for t in self.toasts if t.key == note["path"]), None):
            shown.update(note)
            return
        while len(self.toasts) >= MAX_TOASTS:
            self.toasts[-1].close()
        toast = Toast(self, note)
        self.toasts.insert(0, toast)
        self.restack()
        toast.win.present()

    def restack(self):
        offset = self.look.first_offset
        for toast in self.toasts:  # newest nearest the corner
            LayerShell.set_margin(toast.win, toast.edge, offset)
            offset += toast.height() + self.look.spacing

    def forget(self, toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
        self.restack()
        if self.mode != "resident" and not self.toasts:
            self.app.release()

    def send_reply(self, note, text, done):
        if self.mode == "demo":
            GLib.timeout_add(400, lambda: done("FAIL" not in text,
                                               "reply failed: No such object path") or False)
            return
        try:
            proc = Gio.Subprocess.new([ui.HELPER, "send", note["path"], text],
                                      Gio.SubprocessFlags.STDOUT_SILENCE
                                      | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as exc:
            done(False, exc.message)
            return

        def finished(p, result):
            try:
                _, _, err = p.communicate_utf8_finish(result)
            except GLib.Error as exc:
                done(False, exc.message)
                return
            done(p.get_successful(), err)
        proc.communicate_utf8_async(None, None, finished)

    def open_full(self, note):
        """The full reply window, opened on this conversation."""
        if self.mode == "demo":
            return
        env = dict(os.environ, PHONELINK_FOCUS=note["path"])
        subprocess.Popen([str(HERE.parent / "phonelink"), "reply", "--gui"], env=env,
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv):
    mode, arg = "resident", None
    if argv[1:2] == ["--demo"]:
        mode = "demo"
    elif argv[1:2] == ["--show"] and len(argv) > 2:
        mode, arg = "show", argv[2]
    elif len(argv) > 1:
        sys.exit("usage: phonelink-toastd.py [--demo | --show ID]")
    if not LayerShell.is_supported():
        sys.exit("gtk4-layer-shell is not active: run through `phonelink toastd`, which "
                 "preloads it, on a compositor with wlr-layer-shell (Hyprland has it)")

    # The resident daemon is single-instance; a preview or --show must still run
    # alongside it, so those opt out of uniqueness.
    flags = (Gio.ApplicationFlags.DEFAULT_FLAGS if mode == "resident"
             else Gio.ApplicationFlags.NON_UNIQUE)
    app = Adw.Application(application_id=APP_ID, flags=flags)
    state = {}

    def activate(application):
        if "daemon" in state:
            return  # a second start of the resident daemon: already listening
        state["daemon"] = Daemon(application, mode)
        state["daemon"].start(arg)

    app.connect("activate", activate)
    return app.run([argv[0]])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
