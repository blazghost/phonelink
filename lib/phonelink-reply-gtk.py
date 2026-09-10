#!/usr/bin/env python3
"""phonelink reply window -- a Phone Link-style quick reply for Omarchy.

Lists the conversations waiting on the phone through lib/kdeconnect-notify.py
(or whatever PHONELINK_NOTIFY_HELPER points at -- a test stub, say), shows each
as a chat thread, and sends the reply back through the same helper. Nothing
here talks to KDE Connect itself; this is only the window.

Colours come from the active Omarchy theme's colors.toml, then the GUM_*
palette Omarchy exports, then plain Adwaita dark -- so the window follows
`omarchy theme set` like the rest of the desktop.
"""

import html
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
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

# Shared with the terminal panel on purpose: one Hyprland rule floats, centres
# and un-dims both.
APP_ID = "org.omarchy.phonelink"
HELPER = os.environ.get("PHONELINK_NOTIFY_HELPER") or str(
    Path(__file__).resolve().parent / "kdeconnect-notify.py")
VERTICAL = Gtk.Orientation.VERTICAL

# Plain Adwaita dark, for when there is no Omarchy theme to read.
FALLBACK = {
    "mode": "dark",
    "background": "#1d1d20", "dark_background": "#18181b",
    "lighter_background": "#2e2e32", "foreground": "#ffffff",
    "muted": "#9a9a9e", "accent": "#3584e4", "selection": "#3a3a3f",
    "red": "#e62d42", "orange": "#e66100", "yellow": "#c88800",
    "green": "#3a944a", "cyan": "#2190a4", "blue": "#3584e4",
    "magenta": "#9141ac",
}

# The GUM_* variables Omarchy exports, mapped onto colors.toml names.
GUM_KEYS = {
    "accent": "GUM_INPUT_PROMPT_FOREGROUND",
    "foreground": "GUM_INPUT_HEADER_FOREGROUND",
    "muted": "GUM_INPUT_PLACEHOLDER_FOREGROUND",
    "selection": "GUM_FILTER_SELECTED_BACKGROUND",
    "background": "GUM_INPUT_PROMPT_BACKGROUND",
}

# Initials avatars cycle through the theme's own hues rather than Adwaita's,
# so a group chat reads as part of the palette.
AVATAR_HUES = ("blue", "green", "magenta", "orange", "cyan", "red", "yellow")


# --------------------------------------------------------------------- palette

def is_hex(value):
    return (isinstance(value, str) and len(value) == 7 and value.startswith("#")
            and all(c in "0123456789abcdefABCDEF" for c in value[1:]))


def load_palette():
    pal = dict(FALLBACK)
    for key, var in GUM_KEYS.items():
        if is_hex(os.environ.get(var)):
            pal[key] = os.environ[var]
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    try:
        theme = tomllib.loads((state / "omarchy/current/theme/colors.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        theme = {}
    for key, value in theme.items():
        if is_hex(value) or (key == "mode" and value in ("dark", "light")):
            pal[key] = value
    return pal


def luminance(hexc):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ink_on(pal, bg):
    """Whichever of the theme's own ink colours stays legible on `bg`."""
    dark, light = sorted((pal["background"], pal["foreground"]), key=luminance)
    return dark if luminance(bg) > 0.3 else light


def build_css(p):
    on_accent = ink_on(p, p["accent"])
    hairline = f"alpha({p['foreground']}, 0.07)"
    avatars = "\n".join(
        f"avatar.color{n} {{ background-image: none; "
        f"background-color: {p[hue]}; color: {ink_on(p, p[hue])}; }}"
        for n, hue in ((i, AVATAR_HUES[(i - 1) % len(AVATAR_HUES)]) for i in range(1, 15)))
    return f"""
:root {{
  --window-bg-color: {p['background']};
  --window-fg-color: {p['foreground']};
  --view-bg-color: {p['background']};
  --view-fg-color: {p['foreground']};
  --headerbar-bg-color: {p['dark_background']};
  --headerbar-fg-color: {p['foreground']};
  --headerbar-backdrop-color: {p['dark_background']};
  --headerbar-shade-color: {hairline};
  --sidebar-bg-color: {p['dark_background']};
  --sidebar-fg-color: {p['foreground']};
  --sidebar-backdrop-color: {p['dark_background']};
  --sidebar-shade-color: {hairline};
  --card-bg-color: {p['lighter_background']};
  --popover-bg-color: {p['lighter_background']};
  --accent-bg-color: {p['accent']};
  --accent-fg-color: {on_accent};
  --accent-color: {p['accent']};
}}
window {{ font-family: "Adwaita Sans", sans-serif; }}

.thread {{ padding: 14px 16px 12px; }}
.bubble {{ padding: 8px 13px; border-radius: 18px; font-size: 10.5pt; }}
.bubble.in  {{ background: {p['lighter_background']}; color: {p['foreground']}; }}
.bubble.out {{ background: {p['accent']}; color: {on_accent}; }}
.bubble.in.head  {{ border-top-left-radius: 6px; }}
.bubble.out.head {{ border-top-right-radius: 6px; }}
.sender {{ font-size: 8.5pt; font-weight: 600; color: {p['muted']}; margin: 0 0 3px 3px; }}
.meta   {{ font-size: 8pt; color: {p['muted']}; margin: 3px 4px 0; }}

.title-name {{ font-weight: 700; font-size: 11pt; }}
.title-app  {{ font-size: 8.5pt; color: {p['muted']}; }}

.compose {{ background: {p['dark_background']}; padding: 10px 12px 12px;
            border-top: 1px solid {hairline}; }}
.compose entry {{ border-radius: 999px; min-height: 40px; padding: 0 16px;
                  background: {p['lighter_background']}; color: {p['foreground']};
                  box-shadow: none; outline: none; }}
.compose entry:focus-within {{ box-shadow: inset 0 0 0 1px alpha({p['accent']}, 0.65); }}
.compose .send {{ border-radius: 999px; min-width: 40px; min-height: 40px; padding: 0;
                  background: {p['accent']}; color: {on_accent}; }}
.compose .send:disabled {{ background: {p['lighter_background']}; color: {p['muted']}; }}

.convo-list {{ background: transparent; }}
.convo-list row {{ border-radius: 10px; margin: 2px 6px; padding: 8px; }}
.convo-list row:selected {{ background: {p['selection']}; }}
.convo-name    {{ font-weight: 600; font-size: 10pt; }}
.convo-preview {{ font-size: 9pt; color: {p['muted']}; }}
.convo-app     {{ font-size: 8pt; color: {p['muted']}; }}
{avatars}
"""


# ---------------------------------------------------------------------- helper

def plain(text):
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def fetch_conversations():
    """(conversations, error) from the helper's `list`."""
    try:
        run = subprocess.run([HELPER, "list"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"Could not run the notification helper: {exc}"
    if run.returncode != 0:
        return None, run.stderr.strip() or "The notification helper failed."
    try:
        return json.loads(run.stdout or "[]"), None
    except json.JSONDecodeError:
        return None, "The notification helper did not return JSON."


def friendly_error(message):
    """The helper's errors are worded for a terminal; a toast wants the cause."""
    msg = (message or "").strip().removeprefix("reply failed: ")
    if "UnknownObject" in msg or "No such object" in msg:
        # Read, dismissed or answered on the phone: the reply target went with it.
        return "That notification is gone from the phone"
    if "ServiceUnknown" in msg or "not provided by any" in msg:
        return "KDE Connect isn't running"
    if "NoReply" in msg or "timed out" in msg.lower():
        return "The phone didn't answer — is it on the same network?"
    return msg.splitlines()[-1] if msg else "Couldn't send the reply"


# --------------------------------------------------------------------- widgets

def avatar(name, size, icon=None):
    widget = Adw.Avatar(size=size, text=name or "?", show_initials=True)
    if icon and os.path.isfile(icon):
        try:
            widget.set_custom_image(Gdk.Texture.new_from_filename(icon))
        except GLib.Error:
            pass  # a truncated or odd image: the initials are fine
    return widget


def label(text, css, **kw):
    widget = Gtk.Label(label=text, xalign=0, **kw)
    widget.add_css_class(css)
    return widget


def clear(box):
    while child := box.get_first_child():
        box.remove(child)


def send_icon():
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    for name in ("paper-plane-symbolic", "mail-send-symbolic", "go-next-symbolic"):
        if theme.has_icon(name):
            return name
    return "go-next-symbolic"


# The phone's own texting apps. Their photos and videos are reachable through
# KDE Connect, so "open" means phonelink's Messages window, not the app.
SMS_APPS = {"com.samsung.android.messaging", "com.google.android.apps.messaging",
            "com.android.mms", "com.android.messaging"}


def open_in_app(package):
    """Open a notification's app on the desktop, for what the notification
    can't carry: phonelink's Messages window for SMS/MMS, otherwise the Android
    app itself on a scrcpy virtual display. For Signal, Messenger or WhatsApp
    that is the only way to see the photos, videos and the rest of the thread.
    """
    if not package:
        return
    phonelink = str(Path(__file__).resolve().parent.parent / "phonelink")
    args = [phonelink, "messages"] if package in SMS_APPS else [phonelink, "desk", package]
    subprocess.Popen(args, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_label(package, app):
    return "Open Messages" if package in SMS_APPS else f"Open {app or 'app'}"


class ConversationView(Adw.Bin):
    """Header, the thread as bubbles, and the compose bar."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.conv = None
        self.busy = False

        self.header = Adw.HeaderBar(show_title=False)
        self.who = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER, margin_start=4)
        self.header.pack_start(self.who)

        self.thread = Gtk.Box(orientation=VERTICAL, spacing=3, valign=Gtk.Align.END)
        self.thread.add_css_class("thread")
        # Natural height, capped: a one-liner gets a short window and a long
        # group thread scrolls instead of growing off the screen.
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                           vexpand=True, propagate_natural_height=True,
                                           min_content_height=64, max_content_height=520)
        self.scroller.set_child(self.thread)
        # Toasts sit over the conversation, not the whole window: over the
        # window they cover the compose bar you are about to retry from.
        self.toasts = Adw.ToastOverlay(child=self.scroller)

        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Enter a message")
        self.entry.connect("activate", self.on_send)
        self.entry.connect("changed", lambda *_: self.sync_send())
        # focus_on_click off, so clicking Send leaves the caret in the entry.
        self.send_btn = Gtk.Button(icon_name=send_icon(), valign=Gtk.Align.CENTER,
                                   tooltip_text="Send", sensitive=False, focus_on_click=False)
        self.send_btn.add_css_class("send")
        self.send_btn.connect("clicked", self.on_send)
        compose = Gtk.Box(spacing=8)
        compose.add_css_class("compose")
        compose.append(self.entry)
        compose.append(self.send_btn)

        view = Adw.ToolbarView(top_bar_style=Adw.ToolbarStyle.RAISED_BORDER,
                               bottom_bar_style=Adw.ToolbarStyle.FLAT)
        view.add_top_bar(self.header)
        view.set_content(self.toasts)
        view.add_bottom_bar(compose)
        self.set_child(view)

    # -- content

    def load(self, conv):
        self.conv = conv
        title = conv.get("title") or "Unknown"

        clear(self.who)
        self.who.append(avatar(title, 34, conv.get("icon")))
        names = Gtk.Box(orientation=VERTICAL, valign=Gtk.Align.CENTER)
        names.append(label(title, "title-name", ellipsize=Pango.EllipsizeMode.END))
        names.append(label(conv.get("app", ""), "title-app"))
        self.who.append(names)
        # One Open button in the header, relabelled per conversation: the way to
        # the photos and videos this notification can't show.
        if not hasattr(self, "opener"):
            self.opener = Gtk.Button(valign=Gtk.Align.CENTER, focus_on_click=False)
            self.opener.add_css_class("flat")
            self.opener.connect("clicked", lambda *_: open_in_app(self.conv.get("package")))
            self.header.pack_end(self.opener)
        self.opener.set_label(open_label(conv.get("package"), conv.get("app")))
        self.opener.set_visible(bool(conv.get("package")))

        clear(self.thread)
        thread = conv.get("thread") or [
            {"sender": "", "body": plain(conv.get("text") or conv.get("ticker"))
                                   or "(no preview text — check the phone)"}]
        group = any(m.get("sender") for m in thread)
        prev = None
        for msg in thread:
            sender = msg.get("sender", "")
            self.add_incoming(sender, msg.get("body", ""), group, head=sender != prev)
            prev = sender
        # Replies sent from this window survive switching away and back.
        for text in self.win.sent.get(conv["path"], []):
            self.add_outgoing(text, scroll=False)

        self.entry.set_text("")
        self.entry.set_placeholder_text(f"Message {title}")
        self.set_busy(False)
        self.scroll_to_end()

    def bubble(self, text, outgoing, head):
        widget = Gtk.Label(label=text, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                           xalign=0, max_width_chars=38, selectable=True,
                           halign=Gtk.Align.END if outgoing else Gtk.Align.START)
        widget.add_css_class("bubble")
        widget.add_css_class("out" if outgoing else "in")
        if head:
            widget.add_css_class("head")
        return widget

    def add_incoming(self, sender, body, group, head):
        bubble = self.bubble(body, outgoing=False, head=head)
        if not group:
            self.thread.append(bubble)
            return
        # A group chat gets Phone Link's layout: the name over the first bubble
        # of a run, an avatar beside it, and later bubbles in that run indented
        # to match. A grid keeps the avatar level with the bubble, not the name.
        # It fills the width rather than hugging the bubble: a start-aligned
        # grid is measured at one width and allocated at another, and the
        # wrapping bubble inside then needs more height than it was given.
        grid = Gtk.Grid(column_spacing=8)
        bubble.set_hexpand(True)
        if head:
            grid.set_margin_top(8)
            if sender:
                grid.attach(label(sender, "sender"), 1, 0, 1, 1)
            grid.attach(avatar(sender, 28), 0, 1, 1, 1)
        else:
            grid.attach(Gtk.Box(width_request=28), 0, 1, 1, 1)
        grid.attach(bubble, 1, 1, 1, 1)
        self.thread.append(grid)

    def add_outgoing(self, text, scroll=True):
        bubble = self.bubble(text, outgoing=True, head=True)
        bubble.set_margin_top(10)
        self.thread.append(bubble)
        self.thread.append(Gtk.Label(label="Sent", halign=Gtk.Align.END, css_classes=["meta"]))
        if scroll:
            self.scroll_to_end()

    def scroll_to_end(self):
        def go():
            adj = self.scroller.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False
        GLib.idle_add(go)
        GLib.timeout_add(80, go)  # again once the allocation has settled

    # -- sending

    def set_busy(self, busy):
        # Read-only rather than insensitive: an insensitive entry drops keyboard
        # focus (GTK warns about the lost focus-out), so answering the next
        # conversation would take a click first.
        self.busy = busy
        self.entry.set_editable(not busy)
        self.sync_send()
        if not busy:
            # Without selecting: after a failed send, the text you typed stays
            # put for a retry rather than being highlighted to be typed over.
            self.entry.grab_focus_without_selecting()

    def sync_send(self):
        self.send_btn.set_sensitive(not self.busy and bool(self.entry.get_text().strip()))

    def on_send(self, *_):
        text = self.entry.get_text().strip()
        if not text or self.busy or not self.conv:
            return
        self.set_busy(True)
        try:
            proc = Gio.Subprocess.new(
                [HELPER, "send", self.conv["path"], text],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as exc:
            self.failed(exc.message)
            return
        proc.communicate_utf8_async(None, None, self.on_sent, text)

    def on_sent(self, proc, result, text):
        try:
            _, _, err = proc.communicate_utf8_finish(result)
        except GLib.Error as exc:
            self.failed(exc.message)
            return
        if not proc.get_successful():
            self.failed(err)
            return
        self.entry.set_text("")
        self.win.sent.setdefault(self.conv["path"], []).append(text)
        self.add_outgoing(text)
        if not self.win.on_replied(self.conv, text):
            self.set_busy(False)

    def failed(self, message):
        self.set_busy(False)
        self.toasts.add_toast(Adw.Toast(title=friendly_error(message), timeout=5))


class ReplyWindow(Adw.ApplicationWindow):

    def __init__(self, app, convs, error=None):
        super().__init__(application=app, title="Phone")
        self.convs = convs or []
        self.previews = {}
        self.sent = {}  # path -> replies sent from this window

        if error or not self.convs:
            self.set_default_size(420, 340)
            self.set_content(self.status_page(error))
        elif len(self.convs) == 1:
            self.set_default_size(460, -1)
            self.view = ConversationView(self)
            self.set_content(self.view)
            self.view.load(self.convs[0])
        else:
            self.set_default_size(820, 580)
            self.view = ConversationView(self)
            self.set_content(self.split_view())

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

    def status_page(self, error):
        page = Adw.StatusPage(
            icon_name="dialog-warning-symbolic" if error else "mail-read-symbolic",
            title="Can't reach KDE Connect" if error else "Nothing to reply to",
            description=error or "Only messages you could answer from the phone's own "
                                 "notification shade show up here.")
        page.add_css_class("compact")  # full size overflows a small window
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar(show_title=False))
        view.set_content(page)
        return view

    def split_view(self):
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        rows.add_css_class("convo-list")
        for conv in self.convs:
            rows.append(self.convo_row(conv))
        rows.connect("row-selected",
                     lambda _lb, row: row and self.view.load(self.convs[row.get_index()]))

        side_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        side_scroll.set_child(rows)
        side = Adw.ToolbarView()
        side_header = Adw.HeaderBar()
        side_header.set_title_widget(Adw.WindowTitle(title="Messages",
                                                     subtitle=f"{len(self.convs)} waiting"))
        side.add_top_bar(side_header)
        side.set_content(side_scroll)

        split = Adw.NavigationSplitView(min_sidebar_width=260, max_sidebar_width=300)
        split.set_sidebar(Adw.NavigationPage(child=side, title="Messages"))
        split.set_content(Adw.NavigationPage(child=self.view, title="Conversation"))

        # Opened from a toast: start on that toast's conversation.
        focus = os.environ.get("PHONELINK_FOCUS", "")
        start = next((i for i, c in enumerate(self.convs) if c["path"] == focus), 0)

        def select_first():
            rows.select_row(rows.get_row_at_index(start))
            return False
        GLib.idle_add(select_first)
        return split

    def convo_row(self, conv):
        thread = conv.get("thread") or []
        last = thread[-1] if thread else {}
        body = last.get("body") or plain(conv.get("text") or conv.get("ticker"))
        who = (last.get("sender") or "").split()
        preview = label(f"{who[0]}: {body}" if who else body, "convo-preview",
                        ellipsize=Pango.EllipsizeMode.END, single_line_mode=True)
        self.previews[conv["path"]] = preview

        top = Gtk.Box(spacing=6)
        top.append(label(conv.get("title") or "Unknown", "convo-name", hexpand=True,
                         ellipsize=Pango.EllipsizeMode.END))
        top.append(label(conv.get("app", ""), "convo-app"))
        text = Gtk.Box(orientation=VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        text.append(top)
        text.append(preview)

        row = Gtk.Box(spacing=10)
        row.append(avatar(conv.get("title"), 40, conv.get("icon")))
        row.append(text)
        return row

    def on_replied(self, conv, text):
        """True when the window is about to close, so input stays read-only."""
        if len(self.convs) == 1:
            # Long enough to see the bubble land, short enough to feel instant.
            GLib.timeout_add(900, lambda: self.close() or False)
            return True
        if conv["path"] in self.previews:
            self.previews[conv["path"]].set_label(f"You: {text}")
        return False

    def on_key(self, _ctl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


class App(Adw.Application):

    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        pal = load_palette()
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if pal.get("mode") == "light"
            else Adw.ColorScheme.FORCE_DARK)
        css = Gtk.CssProvider()
        css.load_from_string(build_css(pal))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        # A second press of the keybind while this is open lands here: bring the
        # existing window forward instead of stacking another.
        if self.win:
            self.win.present()
            return
        convs, error = fetch_conversations()
        self.win = ReplyWindow(self, convs, error)
        self.win.present()


if __name__ == "__main__":
    sys.exit(App().run([sys.argv[0]]))
