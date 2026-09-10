#!/usr/bin/env python3
"""KDE Connect notification reply, over D-Bus.

The desktop half of KDE Connect keeps a live object per phone notification, and
each carries a `replyId` whenever the Android side attached a RemoteInput action
-- that is, whenever the app would let you reply from the phone's own shade.
Messengers and SMS have one; Reddit and news apps do not.

kdeconnectd exposes `sendReply(s)` on those objects, which is the whole
mechanism. Nothing here reimplements any of it; it just makes the two
operations phonelink needs reachable from a shell.

    kdeconnect-notify.py list                  -> JSON array, newest first
    kdeconnect-notify.py send <objpath> <text>
"""

import html
import json
import re
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

SERVICE = "org.kde.kdeconnect"
NOTIF_IFACE = "org.kde.kdeconnect.device.notifications.notification"
DEVICES = "/modules/kdeconnect/devices"
PROPS = "org.freedesktop.DBus.Properties"

USAGE = "usage: kdeconnect-notify.py list | kdeconnect-notify.py send <objpath> <text>"

try:
    BUS = Gio.bus_get_sync(Gio.BusType.SESSION, None)
except GLib.Error as exc:
    sys.exit(f"cannot reach the session bus: {exc.message}")


def call(path, iface, method, args=None):
    return BUS.call_sync(SERVICE, path, iface, method, args, None,
                         Gio.DBusCallFlags.NONE, 5000, None)


def children(path):
    """Object-path leaf names under `path`, or [] if it is gone."""
    try:
        xml = call(path, "org.freedesktop.DBus.Introspectable", "Introspect").unpack()[0]
    except GLib.Error:
        return []
    return re.findall(r'<node name="([^"]+)"', xml)


def strip_markup(s):
    """Android notification text is small HTML: tags out, entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_thread(text):
    """Split a notification body into [{sender, body}, ...].

    A group conversation arrives as one blob with the whole recent thread in
    it -- "<b>Sender</b><br/>what they said<br/><b>Other</b><br/>reply" -- so
    rendering the raw string shows markup and a wall of names. A one-to-one
    chat is usually just the message, which falls out of this as a single
    entry with no sender.
    """
    if not text:
        return []
    out, sender = [], ""
    for part in re.split(r"<br\s*/?>", text):
        part = part.strip()
        if not part:
            continue
        # A line that is nothing but bold text is a speaker label, not speech.
        if re.fullmatch(r"<b>.*?</b>", part, flags=re.S | re.I):
            sender = strip_markup(part)
            continue
        body = strip_markup(part)
        if body:
            out.append({"sender": sender, "body": body})
    return out


def icon_path(props):
    """The notification's icon file, if KDE Connect wrote one that still exists."""
    path = props.get("iconPath", "") if props.get("hasIcon") else ""
    return path if path and GLib.file_test(path, GLib.FileTest.IS_REGULAR) else ""


def repliable():
    found = []
    for device in children(DEVICES):
        base = f"{DEVICES}/{device}/notifications"
        for nid in children(base):
            path = f"{base}/{nid}"
            try:
                props = call(path, PROPS, "GetAll",
                             GLib.Variant("(s)", (NOTIF_IFACE,))).unpack()[0]
            except GLib.Error:
                continue  # dismissed between listing it and reading it
            if not props.get("replyId"):
                continue
            found.append({
                "path": path,
                "id": int(nid) if nid.isdigit() else 0,
                "device": device,
                "app": props.get("appName", ""),
                "title": props.get("title", ""),
                "text": props.get("text", ""),
                # Android's ticker is usually "Sender: body" and survives when
                # text is empty, so it is the better fallback for a preview.
                "ticker": props.get("ticker", ""),
                "thread": parse_thread(props.get("text", ""))
                          or parse_thread(props.get("ticker", "")),
                "conversation": bool(props.get("isConversation")),
                # KDE Connect writes the notification's large icon to a temp
                # file; for a messenger that is usually the contact's or the
                # group's photo, which the reply window uses as the avatar.
                "icon": icon_path(props),
            })
    # Ids ascend as notifications arrive, so this is newest-first.
    found.sort(key=lambda n: n["id"], reverse=True)
    return found


def main(argv):
    if len(argv) == 2 and argv[1] == "list":
        json.dump(repliable(), sys.stdout)
        sys.stdout.write("\n")
        return 0

    if len(argv) == 4 and argv[1] == "send":
        path, text = argv[2], argv[3]
        if not text.strip():
            sys.exit("refusing to send an empty reply")
        try:
            call(path, NOTIF_IFACE, "sendReply", GLib.Variant("(s)", (text,)))
        except GLib.Error as exc:
            # The usual cause is the notification being dismissed on the phone
            # while you were typing; the object disappears with it.
            sys.exit(f"reply failed: {exc.message}")
        return 0

    sys.exit(USAGE)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
