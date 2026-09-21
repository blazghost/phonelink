#!/usr/bin/env python3
"""phonelink messages -- the phone's SMS/MMS conversations, Phone Link style.

A GTK 4 / libadwaita window over KDE Connect's conversations interface: the
conversation list on the left, a thread on the right with received and sent
bubbles, and MMS pictures and videos inline. A picture shows at once from the
small thumbnail the phone sends with each message and is swapped for the full
image as it arrives; a video plays in your default player. Click to open,
right-click to save to ~/Pictures/Phone, drag a picture out to another app.
Pictures and videos can be sent too: attach them, or drop files onto the
conversation.

Only SMS/MMS. KDE Connect can reach the phone's messaging database but not
Signal's, Messenger's or WhatsApp's; for those phonelink opens the app itself
on the desktop (`phonelink desk <package>`).

Names and photos come from the contacts KDE Connect syncs from the phone when
its Contacts plugin has permission; until then threads show numbers.
"""

import mimetypes
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from phonelink import kdeconnect as kde  # noqa: E402
from phonelink.sms import (FAILED, PAGE, Msg, day_label, load_contacts,  # noqa: E402
                           load_people, match_attachment, match_people, number_key,
                           pretty_number, resolve_recipient, when)
from phonelink import theme, widgets  # noqa: E402

APP_ID = "org.omarchy.phonelink.messages"
SERVICE = "org.kde.kdeconnect"
DEVICES = "/modules/kdeconnect/devices"
DEVICE_IFACE = "org.kde.kdeconnect.device"
CONV_IFACE = "org.kde.kdeconnect.device.conversations"
VERTICAL = Gtk.Orientation.VERTICAL
AUTO_FETCH = 12      # newest pictures in an open thread fetched full-size unasked
MEDIA_W = 240        # width of a picture or video in a bubble
MMS_SOFT_LIMIT = 1_500_000  # bytes; carriers commonly reject MMS much above this
HUNG = "KDE Connect isn't answering. `phonelink kde restart` brings it back."


# --------------------------------------------------------------- the message



















# ----------------------------------------------------------------- the phone

class Phone:
    """KDE Connect's conversations interface for the reachable phone (see _find)."""

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.id, self.name = self._find()
        self.path = f"{DEVICES}/{self.id}" if self.id else None

    # Short timeouts on the few calls that must be waited for. kdeconnectd can
    # stop answering outright -- requests piling onto its conversations
    # interface have hung it -- and a window blocked on it for seconds is one
    # Hyprland marks "not responding".
    def _call(self, path, iface, method, args=None, timeout=3000):
        return self.bus.call_sync(SERVICE, path, iface, method, args, None,
                                  Gio.DBusCallFlags.NONE, timeout, None)

    def fire(self, method, args=None, on_error=None):
        """Call without waiting. These only ask the phone for something, which
        arrives later as a signal, so there is nothing to block the window on."""
        def done(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error as exc:
                if on_error:
                    on_error(exc.message)
        self.bus.call(SERVICE, self.path, CONV_IFACE, method, args, None,
                      Gio.DBusCallFlags.NONE, 20000, None, done)

    def _find(self):
        """The phone to open, by the rule the whole of phonelink uses.

        Never simply the first device: a paired PC can be listed ahead of the
        phone, and it has no texts at all.
        """
        chosen = kde.pick_device(kde.devices())
        return (chosen["id"], chosen["name"]) if chosen else (None, None)

    def subscribe(self, member, callback):
        self.bus.signal_subscribe(SERVICE, CONV_IFACE, member, self.path, None,
                                  Gio.DBusSignalFlags.NONE, callback)

    def active(self):
        lst = self._call(self.path, CONV_IFACE, "activeConversations").get_child_value(0)
        return [Msg(lst.get_child_value(i).get_variant()) for i in range(lst.n_children())]

    def request_all(self):
        self.fire("requestAllConversationThreads")

    def request_thread(self, tid, start, end):
        self.fire("requestConversation", GLib.Variant("(xii)", (tid, start, end)))

    def request_file(self, att):
        self.fire("requestAttachmentFile", GLib.Variant("(xs)", (att.part, att.uid)))

    def reply(self, tid, text, paths, on_error=None):
        # KDE Connect reads each attachment with QFile, so plain paths, not URLs.
        self.fire("replyToConversation",
                  GLib.Variant("(xsav)", (tid, text, [GLib.Variant("s", p) for p in paths])),
                  on_error)

    def send_new(self, address, text, paths, on_error=None):
        """Text a number there is no conversation with yet.

        The phone files it into a thread of its own choosing and reports that
        back as a conversation, which is the only way to learn its id.
        """
        self.fire("sendWithoutConversation",
                  GLib.Variant("(avsav)", ([GLib.Variant("(s)", (address,))], text,
                                           [GLib.Variant("s", p) for p in paths])),
                  on_error)

    def cache_dir(self):
        return Path(GLib.get_user_cache_dir()) / "kdeconnect.daemon" / (self.name or "")


class Files:
    """Full-size attachments: from kdeconnectd's cache if already there, else
    asked of the phone, arriving later on attachmentReceived.

    At most two transfers are in flight -- a thread full of photos would
    otherwise ask for a dozen at once -- and anything you click jumps the queue.
    """

    IN_FLIGHT = 2

    def __init__(self, phone):
        self.phone, self.ready, self.waiting = phone, {}, {}
        self.queue, self.busy, self.index = [], set(), {}
        folder = phone.cache_dir()
        if folder.is_dir():
            for f in folder.iterdir():
                self.index[f.stem] = str(f)
        phone.subscribe("attachmentReceived", self.on_received)

    def cached(self, att):
        if path := self.ready.get(att.uid):
            return path
        # The phone names the file after the attachment; allow for an extension.
        for key in (att.uid, Path(att.uid).stem):
            if key in self.index and Path(self.index[key]).is_file():
                return self.index[key]
        return None

    def get(self, att, callback, urgent=False):
        if path := self.cached(att):
            self.ready[att.uid] = path
            callback(path)
            return
        first = att.uid not in self.waiting
        self.waiting.setdefault(att.uid, []).append(callback)
        if first:
            self.queue.insert(0, att) if urgent else self.queue.append(att)
        elif urgent and att in self.queue:
            self.queue.remove(att)
            self.queue.insert(0, att)
        self.pump()

    def pump(self):
        while self.queue and len(self.busy) < self.IN_FLIGHT:
            att = self.queue.pop(0)
            self.busy.add(att.uid)
            self.phone.request_file(att)
            # A transfer that never arrives must not hold its slot for ever.
            GLib.timeout_add_seconds(30, self.expire, att.uid)

    def expire(self, uid):
        if uid in self.busy:
            self.busy.discard(uid)
            # Forget what was waiting on it too, or `get` would take the file as
            # still on its way and never ask again when you click the picture.
            self.waiting.pop(uid, None)
            self.pump()
        return False

    def on_received(self, _c, _s, _p, _i, _m, params):
        path, name = params.unpack()
        self.index[Path(name).stem] = path
        match = match_attachment(name, self.waiting)
        if match is not None:
            self.busy.discard(match)
            self.ready[match] = path
            for callback in self.waiting.pop(match, []):
                callback(path)
        self.pump()


# ------------------------------------------------------------------- styling

def extra_css(p):
    return f"""
.day {{ font-size: 8.5pt; color: {p['muted']}; margin: 12px 0 4px; }}
.media {{ border-radius: 14px; background: {p['lighter_background']}; }}
.media-badge {{ background: rgba(0, 0, 0, 0.55); color: #ffffff; border-radius: 999px;
                min-width: 44px; min-height: 44px; }}
.file-chip {{ background: {p['lighter_background']}; border-radius: 12px; padding: 8px 12px; }}
.sending {{ opacity: 0.6; }}
.failed {{ font-size: 8pt; color: {p['red']}; margin: 2px 4px 0; }}
.convo-time {{ font-size: 8pt; color: {p['muted']}; }}
.unread {{ background: {p['accent']}; border-radius: 999px; min-width: 9px; min-height: 9px; }}
.pending {{ padding: 8px 12px 0; background: {p['dark_background']}; }}
.pending-tile {{ border-radius: 10px; background: {p['lighter_background']}; }}
.compose .attach {{ border-radius: 999px; min-width: 40px; min-height: 40px; padding: 0;
                    background: transparent; color: {p['muted']}; }}
.compose .attach:hover {{ color: {p['foreground']}; background: alpha({p['foreground']}, 0.06); }}
.load-earlier {{ margin: 6px 0; }}
.to-entry {{ border-radius: 999px; }}
.person-row {{ padding: 6px 10px; border-radius: 12px; }}
.compose-hint {{ color: {p['foreground']}; margin: 10px 4px 2px; }}
.compose-hint-dim {{ font-size: 9pt; color: {p['muted']}; margin: 2px 4px 8px; }}
"""


# --------------------------------------------------------------- the thread

class ThreadView(Adw.Bin):

    def __init__(self, win):
        super().__init__()
        self.win, self.tid = win, None
        self.pending, self.sending = [], []
        self._render_id = 0
        # True while writing to somebody there is no thread with yet: there is
        # no conversation id to send to, so the recipient comes out of the To
        # field instead.
        self.composing = False

        self.header = Adw.HeaderBar(show_title=False)
        self.who = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER, margin_start=4)
        self.header.pack_start(self.who)

        self.to_entry = Gtk.Entry(hexpand=True, width_chars=24,
                                  placeholder_text="Name or phone number")
        self.to_entry.add_css_class("to-entry")
        self.to_entry.connect("changed", lambda *_: self.on_to_changed())
        self.to_entry.connect("activate", lambda *_: self.entry.grab_focus())

        self.thread = Gtk.Box(orientation=VERTICAL, spacing=3, valign=Gtk.Align.END)
        self.thread.add_css_class("thread")
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.scroller.set_child(self.thread)
        self.toasts = Adw.ToastOverlay(child=self.scroller)

        self.pending_box = Gtk.Box(spacing=8, visible=False)
        self.pending_box.add_css_class("pending")

        attach = Gtk.Button(icon_name="mail-attachment-symbolic", tooltip_text="Attach photos or videos",
                            valign=Gtk.Align.CENTER, focus_on_click=False)
        attach.add_css_class("attach")
        attach.connect("clicked", self.choose_files)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Text message")
        self.entry.connect("activate", self.send)
        self.entry.connect("changed", lambda *_: self.sync_send())
        self.send_btn = Gtk.Button(icon_name=widgets.send_icon(), valign=Gtk.Align.CENTER,
                                   tooltip_text="Send", sensitive=False, focus_on_click=False)
        self.send_btn.add_css_class("send")
        self.send_btn.connect("clicked", self.send)
        compose = Gtk.Box(spacing=8)
        compose.add_css_class("compose")
        compose.append(attach)
        compose.append(self.entry)
        compose.append(self.send_btn)
        bottom = Gtk.Box(orientation=VERTICAL)
        bottom.append(self.pending_box)
        bottom.append(compose)

        view = Adw.ToolbarView(top_bar_style=Adw.ToolbarStyle.RAISED_BORDER,
                               bottom_bar_style=Adw.ToolbarStyle.FLAT)
        view.add_top_bar(self.header)
        view.set_content(self.toasts)
        view.add_bottom_bar(bottom)
        self.set_child(view)

        # Drop photos or videos anywhere on the conversation to attach them.
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.add_controller(drop)

    # -- which thread

    def show_thread(self, tid):
        self.tid = tid
        self.composing = False
        self.pending.clear()
        self.sync_pending()
        title, subtitle, photo = self.win.people(tid)
        widgets.clear(self.who)
        self.who.append(self.win.avatar_for(title, 34, photo))
        names = Gtk.Box(orientation=VERTICAL, valign=Gtk.Align.CENTER)
        names.append(widgets.label(title, "title-name", ellipsize=Pango.EllipsizeMode.END))
        if subtitle:
            names.append(widgets.label(subtitle, "title-app"))
        self.who.append(names)
        self.entry.set_placeholder_text("Text message" if not subtitle or "," in title
                                        else f"Text {title}")
        self.render(stick=True)
        self.win.phone.request_thread(tid, 0, PAGE)
        self.entry.grab_focus_without_selecting()

    # -- a text to somebody new

    def start_new(self, prefill=""):
        """Swap the thread for a To field and whoever can be texted.

        `tid` stays None throughout, which is also what keeps the live
        conversation updates from drawing over the pane: render() draws a
        thread only when there is one.
        """
        self.tid = None
        self.composing = True
        self.pending.clear()
        self.sync_pending()
        widgets.clear(self.who)
        title = Gtk.Box(orientation=VERTICAL, valign=Gtk.Align.CENTER)
        title.append(widgets.label("New message", "title-name"))
        self.who.append(title)
        self.who.append(self.to_entry)
        self.entry.set_placeholder_text("Text message")
        self.to_entry.set_text(prefill)
        self.render_compose()
        self.to_entry.grab_focus()

    def on_to_changed(self):
        if self.composing:
            self.render_compose()
            self.sync_send()

    def render_compose(self):
        """Who you could be writing to, for what has been typed so far."""
        widgets.clear(self.thread)
        typed = self.to_entry.get_text().strip()
        people = self.win.people_list

        if not people:
            # The phone has not granted KDE Connect its Contacts permission,
            # so there are no names to offer -- numbers still work.
            self.thread.append(widgets.label(
                "Type a phone number to text it.", "compose-hint", wrap=True))
            self.thread.append(widgets.label(
                "To text by name, allow Contacts for KDE Connect on the phone "
                "(Settings → Apps → KDE Connect → Permissions), then reconnect it.",
                "compose-hint-dim", wrap=True, max_width_chars=48))
            return

        hits = match_people(people, typed)[:8]
        if not hits:
            self.thread.append(widgets.label(f"No contact matching “{typed}”", "compose-hint"))
            return
        self.thread.append(widgets.label("Suggested" if not typed else "Contacts",
                                         "compose-hint-dim"))
        for person in hits:
            self.thread.append(self.person_row(person))

    def person_row(self, person):
        row = Gtk.Button(css_classes=["flat", "person-row"])
        box = Gtk.Box(spacing=10)
        box.append(self.win.avatar_for(person["name"], 34, person["photo"]))
        names = Gtk.Box(orientation=VERTICAL, valign=Gtk.Align.CENTER)
        names.append(widgets.label(person["name"], "title-name",
                                   ellipsize=Pango.EllipsizeMode.END))
        names.append(widgets.label(pretty_number(person["number"]), "title-app"))
        box.append(names)
        row.set_child(box)
        row.connect("clicked", lambda *_, p=person: self.choose_person(p))
        return row

    def choose_person(self, person):
        # The number, not the name: a contact with two numbers would otherwise
        # be ambiguous again by the time Send is pressed.
        self.to_entry.set_text(pretty_number(person["number"]))
        self.entry.grab_focus()

    def recipient(self):
        """(address, who it is, error) for what the To field says right now."""
        return resolve_recipient(self.to_entry.get_text(), self.win.people_list)

    def send_new(self, text, paths):
        address, who, problem = self.recipient()
        if problem:
            self.toast(problem)
            return
        self.win.phone.send_new(address, text, paths,
                                on_error=lambda message: self.toast(kde.friendly_error(message)))
        self.entry.set_text("")
        self.pending.clear()
        self.sync_pending()
        self.toast(f"Sent to {who}")
        # The phone answers with the conversation it filed the message under;
        # the window opens it when it arrives, so the reply lands somewhere.
        self.win.follow(address)

    def schedule(self):
        """Many messages arrive in a burst; draw once they have settled."""
        if self._render_id:
            GLib.source_remove(self._render_id)
        self._render_id = GLib.timeout_add(120, self._render_later)

    def _render_later(self):
        self._render_id = 0
        self.render()
        return False

    # -- drawing

    def at_bottom(self):
        adj = self.scroller.get_vadjustment()
        return adj.get_value() >= adj.get_upper() - adj.get_page_size() - 60

    def render(self, stick=False):
        if self.tid is None:
            return
        stick = stick or self.at_bottom()
        widgets.clear(self.thread)
        msgs = sorted(self.win.threads.get(self.tid, {}).values(), key=lambda m: m.date)
        if len(msgs) >= 20 and self.win.more.get(self.tid, True):
            more = Gtk.Button(label="Load earlier messages", halign=Gtk.Align.CENTER)
            more.add_css_class("flat")
            more.add_css_class("load-earlier")
            more.connect("clicked", lambda *_: self.load_earlier(len(msgs)))
            self.thread.append(more)

        group = len({a for m in msgs for a in m.addresses}) > 1
        pictures = [a for m in msgs for a in m.attachments if a.kind == "image"]
        auto = {a.uid for a in pictures[-AUTO_FETCH:]}
        last_day, prev_sender = None, None
        for m in msgs:
            day = datetime.fromtimestamp(m.date / 1000).date()
            if day != last_day:
                self.thread.append(Gtk.Label(label=day_label(m.date), halign=Gtk.Align.CENTER,
                                             css_classes=["day"]))
                last_day, prev_sender = day, None
            sender = None if m.outgoing else (m.addresses[0] if m.addresses else "")
            self.thread.append(self.bubble(m, group and sender != prev_sender and sender, auto))
            prev_sender = sender
        self.clear_delivered(msgs)
        for item in self.sending:
            self.thread.append(self.sending_bubble(item))
        if stick:
            self.scroll_to_end()

    def bubble(self, m, sender, auto):
        col = Gtk.Box(orientation=VERTICAL, spacing=4,
                      halign=Gtk.Align.END if m.outgoing else Gtk.Align.START)
        if sender:
            col.append(widgets.label(self.win.name_for(sender), "sender"))
        for att in m.attachments:
            col.append(self.media(att, m, fetch=att.uid in auto))
        if m.body.strip():
            text = Gtk.Label(label=m.body, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                             xalign=0, max_width_chars=40, selectable=True,
                             halign=Gtk.Align.END if m.outgoing else Gtk.Align.START)
            text.add_css_class("bubble")
            text.add_css_class("out" if m.outgoing else "in")
            col.append(text)
        if m.type == FAILED:
            col.append(Gtk.Label(label="Not sent", halign=Gtk.Align.END, css_classes=["failed"]))
        return col

    def media(self, att, m, fetch):
        if att.kind not in ("image", "video"):
            # Contact cards, audio and the like: a chip that opens the file.
            chip = Gtk.Box(spacing=8)
            chip.add_css_class("file-chip")
            chip.append(Gtk.Image(icon_name="text-x-generic-symbolic"))
            chip.append(Gtk.Label(label=att.mime))
            self.clickable(chip, att, m)
            return chip

        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        pic.set_size_request(MEDIA_W, MEDIA_W)
        if tex := widgets.texture_from_b64(att.thumb):
            pic.set_paintable(tex)
        frame = Gtk.Overlay(child=pic, overflow=Gtk.Overflow.HIDDEN,
                            halign=Gtk.Align.END if m.outgoing else Gtk.Align.START)
        frame.add_css_class("media")
        if att.kind == "video":
            badge = Gtk.Image(icon_name="media-playback-start-symbolic", pixel_size=22,
                              halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            badge.add_css_class("media-badge")
            frame.add_overlay(badge)
            frame.set_tooltip_text("Video — click to play")
        else:
            frame.set_tooltip_text("Click to open · right-click to save · drag to copy")
        self.clickable(frame, att, m)

        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY)
        drag.connect("prepare", lambda *_: self.drag_content(att))
        frame.add_controller(drag)

        if att.kind == "image" and (fetch or self.win.files.cached(att)):
            self.win.files.get(att, lambda path, p=pic: self.sharpen(p, path))
        return frame

    def sharpen(self, pic, path):
        """Swap the 100px thumbnail for the real picture, at its real shape."""
        tex, w, h = widgets.texture_from_file(path)
        if tex:
            pic.set_paintable(tex)
            pic.set_size_request(MEDIA_W, max(120, min(360, round(MEDIA_W * h / max(w, 1)))))

    def clickable(self, widget, att, m):
        click = Gtk.GestureClick(button=0)
        click.connect("released", lambda g, *_: self.on_media_click(g, att, m))
        widget.add_controller(click)

    def drag_content(self, att):
        if path := self.win.files.cached(att):
            files = Gdk.FileList.new_from_array([Gio.File.new_for_path(path)])
            return Gdk.ContentProvider.new_for_value(files)
        # Not downloaded yet: start now so the next drag has something to hand over.
        self.win.files.get(att, lambda _p: None, urgent=True)
        return None

    def on_media_click(self, gesture, att, m):
        if gesture.get_current_button() == Gdk.BUTTON_SECONDARY:
            self.save(att, m)
        elif gesture.get_current_button() == Gdk.BUTTON_PRIMARY:
            if not self.win.files.cached(att):
                self.toast("Getting it from the phone…")
            self.win.files.get(att, self.open_path, urgent=True)

    def open_path(self, path):
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        except GLib.Error as exc:
            self.toast(f"Couldn't open it: {exc.message}")

    def save(self, att, m):
        def copy(path):
            folder = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
                          or Path.home() / "Pictures") / "Phone"
            folder.mkdir(parents=True, exist_ok=True)
            ext = Path(path).suffix or mimetypes.guess_extension(att.mime) or ""
            stamp = datetime.fromtimestamp(m.date / 1000).strftime("%Y-%m-%d %H.%M.%S")
            dest, n = folder / f"{stamp}{ext}", 1
            while dest.exists():
                n += 1
                dest = folder / f"{stamp} ({n}){ext}"
            shutil.copy2(path, dest)
            self.toast(f"Saved to {dest.parent.name}/{dest.name}")
        self.win.files.get(att, copy, urgent=True)

    def load_earlier(self, have):
        self.win.more[self.tid] = False  # shown again if the page brings anything
        self.win.expect_more[self.tid] = have
        self.win.phone.request_thread(self.tid, have, have + PAGE)
        self.render()

    def scroll_to_end(self):
        def go():
            adj = self.scroller.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False
        GLib.idle_add(go)
        GLib.timeout_add(120, go)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    # -- attaching

    def choose_files(self, *_):
        media = Gtk.FileFilter(name="Photos and videos")
        media.add_mime_type("image/*")
        media.add_mime_type("video/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(media)
        dialog = Gtk.FileDialog(title="Attach photos or videos", modal=True, filters=filters)
        dialog.open_multiple(self.win, None, self.on_chosen)

    def on_chosen(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # cancelled
        self.add_pending([files.get_item(i).get_path() for i in range(files.get_n_items())])

    def on_drop(self, _target, value, _x, _y):
        self.add_pending([f.get_path() for f in value.get_files() if f.get_path()])
        return True

    def add_pending(self, paths):
        for path in paths:
            if path not in self.pending and Path(path).is_file():
                self.pending.append(path)
        self.sync_pending()
        if sum(Path(p).stat().st_size for p in self.pending) > MMS_SOFT_LIMIT:
            self.toast("Over about 1.5 MB — carriers often reject MMS that large")

    def sync_pending(self):
        widgets.clear(self.pending_box)
        for path in self.pending:
            tile = Gtk.Overlay()
            tile.add_css_class("pending-tile")
            tile.set_overflow(Gtk.Overflow.HIDDEN)
            mime = mimetypes.guess_type(path)[0] or ""
            if mime.startswith("image/") and (tex := widgets.texture_from_file(path, 160)[0]):
                pic = Gtk.Picture(paintable=tex, content_fit=Gtk.ContentFit.COVER)
                pic.set_size_request(64, 64)
                tile.set_child(pic)
            else:
                icon = Gtk.Image(icon_name="video-x-generic-symbolic", pixel_size=28)
                icon.set_size_request(64, 64)
                tile.set_child(icon)
            remove = Gtk.Button(icon_name="window-close-symbolic", halign=Gtk.Align.END,
                                valign=Gtk.Align.START, tooltip_text="Remove")
            remove.add_css_class("circular")
            remove.add_css_class("osd")
            remove.connect("clicked", lambda *_, p=path: (self.pending.remove(p), self.sync_pending()))
            tile.add_overlay(remove)
            self.pending_box.append(tile)
        self.pending_box.set_visible(bool(self.pending))
        self.sync_send()

    # -- sending

    def sync_send(self):
        ready = self.tid is not None or (self.composing and self.to_entry.get_text().strip())
        self.send_btn.set_sensitive(bool(ready)
                                    and bool(self.entry.get_text().strip() or self.pending))

    def send(self, *_):
        text, paths = self.entry.get_text().strip(), list(self.pending)
        if not (text or paths):
            return
        if self.composing:
            self.send_new(text, paths)
            return
        if self.tid is None:
            return
        item = {"text": text, "paths": paths, "since": time.time() * 1000 - 60_000}
        self.win.phone.reply(self.tid, text, paths,
                             on_error=lambda message: self.send_failed(item, message))
        # Shown at once, dimmed, until the phone reports the sent message back.
        self.sending.append(item)
        self.entry.set_text("")
        self.pending.clear()
        self.sync_pending()
        self.render(stick=True)

    def send_failed(self, item, message):
        if item in self.sending:
            self.sending.remove(item)
            # Put what was typed back, so nothing is lost.
            if not self.entry.get_text():
                self.entry.set_text(item["text"])
            self.pending = item["paths"] + [p for p in self.pending if p not in item["paths"]]
            self.sync_pending()
            self.render()
        self.toast(kde.friendly_error(message))

    def sending_bubble(self, item):
        col = Gtk.Box(orientation=VERTICAL, spacing=4, halign=Gtk.Align.END)
        col.add_css_class("sending")
        for path in item["paths"]:
            if tex := widgets.texture_from_file(path, 480)[0]:
                pic = Gtk.Picture(paintable=tex, content_fit=Gtk.ContentFit.COVER)
                pic.set_size_request(MEDIA_W, MEDIA_W)
                frame = Gtk.Overlay(child=pic, overflow=Gtk.Overflow.HIDDEN, halign=Gtk.Align.END)
                frame.add_css_class("media")
                col.append(frame)
            else:
                chip = Gtk.Box(spacing=8, halign=Gtk.Align.END)
                chip.add_css_class("file-chip")
                chip.append(Gtk.Image(icon_name="video-x-generic-symbolic"))
                chip.append(Gtk.Label(label=Path(path).name, ellipsize=Pango.EllipsizeMode.MIDDLE,
                                      max_width_chars=24))
                col.append(chip)
        if item["text"]:
            text = Gtk.Label(label=item["text"], wrap=True, xalign=0, max_width_chars=40,
                             halign=Gtk.Align.END)
            text.add_css_class("bubble")
            text.add_css_class("out")
            col.append(text)
        col.append(Gtk.Label(label="Sending…", halign=Gtk.Align.END, css_classes=["meta"]))
        return col

    def clear_delivered(self, msgs):
        """Drop a 'Sending…' bubble once the phone reports the message as sent."""
        sent = [m for m in msgs if m.outgoing]
        still = []
        for item in self.sending:
            arrived = any(m.date >= item["since"] and
                          ((item["text"] and m.body.strip() == item["text"])
                           or (not item["text"] and m.attachments)) for m in sent)
            if not arrived:
                still.append(item)
        self.sending = still


# ------------------------------------------------------------------- window

class MessagesWindow(Adw.ApplicationWindow):

    def __init__(self, app, phone, new_to=None):
        super().__init__(application=app, title="Messages")
        self.set_default_size(1000, 700)
        self.phone = phone
        # `phonelink text [who]` opens the window straight onto a blank text.
        self.new_to = new_to
        self.threads, self.latest = {}, {}
        self.more, self.expect_more = {}, {}
        self.row_by_tid = {}
        self._list_id = 0

        if not phone.id:
            page = Adw.StatusPage(icon_name="phone-symbolic", title="Phone not connected",
                                  description="Open KDE Connect on the phone, or check it is on "
                                              "the same network. `phonelink status` will say "
                                              "more; `phonelink kde restart` if it is stuck.")
            page.add_css_class("compact")
            view = Adw.ToolbarView()
            view.add_top_bar(Adw.HeaderBar())
            view.set_content(page)
            self.set_content(view)
            return

        self.contacts = load_contacts(phone.id)
        self.people_list = load_people(phone.id)
        # The number a new text has just gone to, until its thread turns up.
        self.following = None
        self.files = Files(phone)
        self.view = ThreadView(self)

        self.search = Gtk.SearchEntry(placeholder_text="Search messages", margin_start=10,
                                      margin_end=10, margin_bottom=6)
        self.search.connect("search-changed", lambda *_: self.rows.invalidate_filter())
        self.rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.rows.add_css_class("convo-list")
        self.rows.set_filter_func(self.row_visible)
        self.rows.set_sort_func(self.row_order)
        self.rows.connect("row-selected", self.on_row_selected)
        side_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        side_scroll.set_child(self.rows)
        side_body = Gtk.Box(orientation=VERTICAL)
        side_body.append(self.search)
        side_body.append(side_scroll)
        side = Adw.ToolbarView()
        side_header = Adw.HeaderBar()
        side_header.set_title_widget(Adw.WindowTitle(title="Messages", subtitle=phone.name))
        new_btn = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="New message",
                             focus_on_click=False)
        new_btn.connect("clicked", lambda *_: self.start_new())
        side_header.pack_end(new_btn)
        side.add_top_bar(side_header)
        side.set_content(side_body)

        split = Adw.NavigationSplitView(min_sidebar_width=300, max_sidebar_width=360)
        split.set_sidebar(Adw.NavigationPage(child=side, title="Messages"))
        split.set_content(Adw.NavigationPage(child=self.view, title="Conversation"))
        self.set_content(split)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_: kv == Gdk.KEY_Escape and (self.close() or True))
        self.add_controller(keys)

        for member in ("conversationCreated", "conversationUpdated"):
            phone.subscribe(member, self.on_message)
        phone.subscribe("conversationLoaded", self.on_loaded)
        try:
            cached = phone.active()
        except GLib.Error:
            cached = []
            GLib.idle_add(lambda: self.view.toast(HUNG) or False)
        for m in cached:
            self.add(m)
        if not cached:
            # kdeconnectd keeps its copy fresh while the phone is connected -- the
            # phone pushes each new message -- so the whole list is asked for only
            # when it has none, as after a restart. Asking on every open makes the
            # phone re-send hundreds of threads, and that flood has hung it.
            phone.request_all()
        for tid in self.latest:
            self.ensure_row(tid)
        if new_to is not None:
            self.start_new(new_to)
        elif first := self.rows.get_row_at_index(0):
            self.rows.select_row(first)

    # -- people

    def name_for(self, address):
        if hit := self.contacts.get(number_key(address)):
            return hit[0] or pretty_number(address)
        return pretty_number(address)

    def photo_for(self, address):
        hit = self.contacts.get(number_key(address))
        return hit[1] if hit else None

    def people(self, tid):
        """(title, subtitle, photo) for a thread."""
        latest = self.latest.get(tid)
        addresses = list(dict.fromkeys(latest.addresses if latest else []))
        if not addresses:
            return "Unknown", "", None
        if len(addresses) > 1:
            return ", ".join(self.name_for(a).split()[0] for a in addresses), \
                f"{len(addresses)} people", None
        a = addresses[0]
        name = self.name_for(a)
        return name, (pretty_number(a) if name != pretty_number(a) else ""), self.photo_for(a)

    def avatar_for(self, title, size, photo):
        avatar = widgets.avatar(title, size)
        if not any(ch.isalpha() for ch in title):
            # A bare number or short code: its "initials" would be "(7" or "2".
            avatar.set_show_initials(False)
        if photo:
            try:
                avatar.set_custom_image(Gdk.Texture.new_from_bytes(GLib.Bytes.new(photo)))
            except GLib.Error:
                pass
        return avatar

    # -- data

    def add(self, m):
        self.threads.setdefault(m.thread, {})[m.uid] = m
        if m.thread not in self.latest or m.date >= self.latest[m.thread].date:
            self.latest[m.thread] = m

    # -- a text to somebody new

    def start_new(self, prefill=""):
        """Leave whatever thread is open and write to somebody instead."""
        self.rows.select_row(None)
        self.view.start_new(prefill)

    def follow(self, address):
        """Open the thread the phone files a just-sent text under, once it says."""
        self.following = number_key(address) or address

    def open_if_followed(self, m):
        """The answer to `follow`: the sent message coming back with its thread."""
        if not self.following:
            return
        if not any((number_key(a) or a) == self.following for a in m.addresses):
            return
        self.following = None
        self.ensure_row(m.thread)
        if row := self.row_by_tid.get(m.thread):
            self.rows.select_row(row)

    def on_message(self, _c, _s, _p, _i, _m, params):
        m = Msg(params.get_child_value(0).get_variant())
        known = m.thread in self.latest
        self.add(m)
        self.open_if_followed(m)
        if m.thread == self.view.tid:
            self.view.schedule()
        if not known or self.latest[m.thread] is m:
            self.schedule_list()

    def on_loaded(self, _c, _s, _p, _i, _m, params):
        tid, count = params.unpack()
        if tid in self.expect_more:
            # A page of older messages: offer another only if this one had any.
            self.more[tid] = count > self.expect_more.pop(tid)
            if tid == self.view.tid:
                self.view.schedule()

    # -- the list
    #
    # Hundreds of threads, and the phone streams updates for every one of them
    # when the whole list is asked for. Rebuilding the list on each update
    # starved the main loop ("not responding"), so each row is made once and
    # updated in place, and the list's sort function keeps them newest first.

    def schedule_list(self):
        if not self._list_id:  # throttle rather than postpone: updates keep coming
            self._list_id = GLib.timeout_add(150, self._flush_list)

    def _flush_list(self):
        self._list_id = 0
        for tid, m in list(self.latest.items()):
            row = self.row_by_tid.get(tid)
            if row is None or row.shown_uid != m.uid:
                self.ensure_row(tid)
        # Never while a new text is being written: the pane would be pulled
        # out from under whoever is typing in it.
        if self.view.tid is None and not self.view.composing \
                and (first := self.rows.get_row_at_index(0)):
            self.rows.select_row(first)
        return False

    def row_order(self, a, b):
        x, y = self.latest[a.tid].date, self.latest[b.tid].date
        return (x < y) - (x > y)  # newest first; dates overflow a C int if subtracted

    @staticmethod
    def preview_for(m):
        if m.body.strip():
            preview = m.body.strip().splitlines()[0]
        elif any(a.kind == "video" for a in m.attachments):
            preview = "🎬 Video"
        elif m.attachments:
            preview = "📷 Photo"
        else:
            preview = ""
        return f"You: {preview}" if m.outgoing else preview

    def ensure_row(self, tid):
        m = self.latest[tid]
        title, subtitle, photo = self.people(tid)
        preview = self.preview_for(m)
        row = self.row_by_tid.get(tid)
        if row is None:
            row = Gtk.ListBoxRow()
            row.tid, row.shown_title = tid, None
            row.avatar_slot = Gtk.Box()
            row.title = widgets.label("", "convo-name", hexpand=True, ellipsize=Pango.EllipsizeMode.END)
            row.time = widgets.label("", "convo-time")
            row.preview = widgets.label("", "convo-preview", hexpand=True,
                                   ellipsize=Pango.EllipsizeMode.END, single_line_mode=True)
            row.dot = Gtk.Box(valign=Gtk.Align.CENTER, css_classes=["unread"])
            top = Gtk.Box(spacing=6)
            top.append(row.title)
            top.append(row.time)
            bottom = Gtk.Box(spacing=6)
            bottom.append(row.preview)
            bottom.append(row.dot)
            text = Gtk.Box(orientation=VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
            text.append(top)
            text.append(bottom)
            box = Gtk.Box(spacing=10)
            box.append(row.avatar_slot)
            box.append(text)
            row.set_child(box)
            self.rows.append(row)
            self.row_by_tid[tid] = row
        if row.shown_title != title:
            widgets.clear(row.avatar_slot)
            row.avatar_slot.append(self.avatar_for(title, 40, photo))
            row.title.set_label(title)
            row.shown_title = title
        row.time.set_label(when(m.date))
        row.preview.set_label(preview)
        row.dot.set_visible(not m.read and not m.outgoing)
        row.haystack = f"{title} {subtitle} {preview}".lower()
        row.shown_uid = m.uid
        row.changed()  # re-sort and re-filter just this row

    def row_visible(self, row):
        needle = self.search.get_text().strip().lower()
        return not needle or needle in row.haystack

    def on_row_selected(self, _box, row):
        if row is not None and row.tid != self.view.tid:
            self.view.show_thread(row.tid)


class App(Adw.Application):

    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win = None
        self.new_to = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        # `phonelink text` on a window that is already open arrives here: the
        # second process cannot hand over its arguments, but it can activate
        # an action on this one, which is what raises the composer.
        action = Gio.SimpleAction.new("new-message", GLib.VariantType.new("s"))
        action.connect("activate", self.on_new_message)
        self.add_action(action)
        pal = theme.load_palette()
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if pal.get("mode") == "light"
            else Adw.ColorScheme.FORCE_DARK)
        css = Gtk.CssProvider()
        css.load_from_string(theme.build_css(pal) + extra_css(pal))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def on_new_message(self, _action, param):
        if self.win:
            self.win.present()
            if self.win.phone.id:
                self.win.start_new(param.get_string())

    def do_activate(self):
        if self.win:  # opened again while open: bring it forward
            self.win.present()
            return
        self.win = MessagesWindow(self, Phone(), self.new_to)
        self.win.present()


def new_to(argv=None):
    """`--new [who]` from `phonelink text`, or None for the ordinary window.

    GTK's own argument handling is deliberately not used -- the application is
    run with the program name alone, so that a second `phonelink messages`
    raises the open window rather than starting another.
    """
    argv = sys.argv if argv is None else argv
    if "--new" not in argv:
        return None
    rest = [a for a in argv[argv.index("--new") + 1:] if not a.startswith("-")]
    return " ".join(rest).strip()


def tell_the_open_window(who):
    """Hand a recipient to a Messages window that is already open, or say no.

    A second process cannot pass arguments to the first -- GTK raises the open
    window and drops them -- so this asks the running one to open its composer
    over the interface every GApplication exports.
    """
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    try:
        owned = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "NameHasOwner",
                              GLib.Variant("(s)", (APP_ID,)), None,
                              Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        if not owned:
            return False
        bus.call_sync(APP_ID, "/" + APP_ID.replace(".", "/"),
                      "org.freedesktop.Application", "ActivateAction",
                      GLib.Variant("(sava{sv})",
                                   ("new-message", [GLib.Variant("s", who)], {})),
                      None, Gio.DBusCallFlags.NONE, 5000, None)
        return True
    except GLib.Error:
        return False  # not answering: open a window of our own instead


def main(argv):
    app = App()
    app.new_to = new_to(argv)
    if app.new_to is not None and tell_the_open_window(app.new_to):
        return 0
    return app.run([argv[0]])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
