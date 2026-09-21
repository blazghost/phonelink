"""Talking to kdeconnectd: devices, notifications, replies.

The desktop half of KDE Connect keeps a live object per phone notification, and
each carries a `replyId` whenever the Android side attached a RemoteInput
action -- that is, whenever the app would let you reply from the phone's own
shade. Messengers and SMS have one; Reddit and news apps do not. `sendReply(s)`
on those objects is the whole mechanism; nothing here reimplements any of it.

One reader for a notification, `read_note`, so every caller sees the same
fields: the toast service, the reply window's helper, and anything added later.
"""

import html
import os
import re

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

SERVICE = "org.kde.kdeconnect"
DAEMON_PATH = "/modules/kdeconnect"
DAEMON_IFACE = "org.kde.kdeconnect.daemon"
DEVICES = "/modules/kdeconnect/devices"
DEVICE_IFACE = "org.kde.kdeconnect.device"
NOTIF_PLUGIN_IFACE = "org.kde.kdeconnect.device.notifications"
BATTERY_IFACE = "org.kde.kdeconnect.device.battery"
CONNECTIVITY_IFACE = "org.kde.kdeconnect.device.connectivity_report"
NOTIF_IFACE = "org.kde.kdeconnect.device.notifications.notification"
CONV_IFACE = "org.kde.kdeconnect.device.conversations"
PROPS = "org.freedesktop.DBus.Properties"
INTROSPECT = "org.freedesktop.DBus.Introspectable"

# A phone that has gone quiet must not hold a window for seconds: kdeconnectd
# can stop answering outright, and Hyprland marks a blocked window "not
# responding". Waiting calls are short; `phonelink kde restart` brings the
# daemon back.
TIMEOUT = 5000

try:
    BUS = Gio.bus_get_sync(Gio.BusType.SESSION, None)
except GLib.Error:
    BUS = None


def call(path, iface, method, args=None, timeout=TIMEOUT):
    return BUS.call_sync(SERVICE, path, iface, method, args, None,
                         Gio.DBusCallFlags.NONE, timeout, None)


def children(path):
    """Object-path leaf names under `path`, or [] if it is gone."""
    try:
        xml = call(path, INTROSPECT, "Introspect").unpack()[0]
    except GLib.Error:
        return []
    return re.findall(r'<node name="([^"]+)"', xml)


def properties(path, iface, timeout=TIMEOUT):
    """Every property of an interface, or None if the object has gone.

    A caller can hand us something that is not an object path at all -- a
    signal naming a bogus id. GLib refuses the call and hands back None rather
    than raising, so check the path first and the reply after.
    """
    if not GLib.Variant.is_object_path(path):
        return None
    try:
        reply = call(path, PROPS, "GetAll", GLib.Variant("(s)", (iface,)), timeout)
    except GLib.Error:
        return None
    return reply.unpack()[0] if reply is not None else None


# --------------------------------------------------------------------- health

# What a health check can find. kdeconnectd has hung outright -- still on the
# bus, still introspectable, answering nothing -- and everything phonelink does
# went quiet with it, which is worth saying out loud rather than looking broken.
OK, HUNG, GONE = "ok", "hung", "gone"


def running():
    """Is kdeconnectd on the session bus at all?"""
    if BUS is None:
        return False
    try:
        return BUS.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                             "org.freedesktop.DBus", "NameHasOwner",
                             GLib.Variant("(s)", (SERVICE,)), None,
                             Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
    except GLib.Error:
        return False


def health(callback, timeout=2500):
    """Report OK, HUNG or GONE to `callback`, without waiting for the answer.

    selfId is cheap and goes through the daemon's own event loop, so a daemon
    that has stopped serving fails it while introspection alone might not. The
    call is asynchronous on purpose: a window must never block on a phone.
    """
    if not running():
        callback(GONE)
        return

    def done(bus, result):
        try:
            bus.call_finish(result)
            callback(OK)
        except GLib.Error:
            # NoReply, a timeout, or the daemon going away mid-call.
            callback(HUNG if running() else GONE)

    BUS.call(SERVICE, DAEMON_PATH, DAEMON_IFACE, "selfId", None, None,
             Gio.DBusCallFlags.NO_AUTO_START, timeout, None, done)


# -------------------------------------------------------------------- devices

def devices():
    """[{id, name, type, reachable, paired}] for everything KDE Connect knows."""
    found = []
    for device in children(DEVICES):
        props = properties(f"{DEVICES}/{device}", DEVICE_IFACE)
        if props is None:
            continue
        found.append({
            "id": device,
            "name": props.get("name", "Phone"),
            "type": props.get("type", ""),
            "reachable": bool(props.get("isReachable")),
            "paired": bool(props.get("isPaired", True)),
        })
    return found


def pick_device(found, want=None):
    """The one device phonelink should talk to, or None.

    Not simply the first: a paired PC can be listed ahead of the phone, and
    then files, rings and texts went to the PC. `want` -- PHONELINK_DEVICE, an
    id or a name -- picks one explicitly; otherwise the first phone, then the
    first tablet. Anything else is never chosen by default, so an offline phone
    is an error rather than a quiet send to the wrong machine.
    """
    live = [d for d in found if d["reachable"] and d["paired"]]
    if want is None:
        want = os.environ.get("PHONELINK_DEVICE")
    if want:
        return next((d for d in live if want in (d["id"], d["name"])), None)
    for kind in ("phone", "tablet"):
        if chosen := next((d for d in live if d["type"] == kind), None):
            return chosen
    return None


def phone(want=None):
    """The device to talk to right now, read live off the bus."""
    return pick_device(devices(), want)


def health_now(timeout=2000):
    """OK, HUNG or GONE, waited for -- for a command that is about to exit."""
    if not running():
        return GONE
    try:
        call(DAEMON_PATH, DAEMON_IFACE, "selfId", None, timeout)
        return OK
    except GLib.Error:
        return HUNG if running() else GONE


# ------------------------------------------------------- what the phone is up to

def battery(device_id):
    """{charge, charging} for the phone, or None if it does not report one."""
    props = properties(f"{DEVICES}/{device_id}/battery", BATTERY_IFACE)
    if not props or not props.get("hasBattery", True):
        return None
    return {"charge": props.get("charge", -1), "charging": bool(props.get("isCharging"))}


def signal_strength(device_id):
    """{bars, network} for the cellular connection, or None.

    The phone reports bars 0-4 and a network name like LTE. Both need the
    Android app's phone-state permission; without it the strength comes back
    as -1, which is "unknown", not "no signal".
    """
    props = properties(f"{DEVICES}/{device_id}/connectivity_report", CONNECTIVITY_IFACE)
    if not props:
        return None
    bars = props.get("cellularNetworkStrength", -1)
    if not isinstance(bars, int) or bars < 0:
        return None
    return {"bars": bars, "network": props.get("cellularNetworkType", "")}


# ---------------------------------------------------------- notification text

def strip_markup(text):
    """Android notification text is small HTML: tags out, entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def plain(text):
    """The same, for a one-line preview: a tag becomes a space, not nothing."""
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


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


def package_of(props):
    """The Android package behind a notification.

    internalId is "0|<android package>|<id>|<tag>|<uid>", and the package says
    exactly which app to open for the photos and videos a notification can't
    carry.
    """
    return (props.get("internalId", "").split("|") + ["", ""])[1]


# ------------------------------------------------------------- notifications

def read_note(path):
    """One phone notification as every caller needs it, or None if it has gone.

    The toast service and the reply window read the same fields out of the same
    place: when the phone starts carrying something new, it is added here once.
    """
    props = properties(path, NOTIF_IFACE)
    if props is None:
        return None
    nid = path.rsplit("/", 1)[-1]
    parts = path.split("/")
    text, ticker = props.get("text", ""), props.get("ticker", "")
    return {
        "path": path,
        "id": int(nid) if nid.isdigit() else 0,
        "device": parts[-3] if len(parts) >= 3 else "",
        "app": props.get("appName", ""),
        "title": props.get("title", ""),
        "text": text,
        # Android's ticker is usually "Sender: body" and survives when text is
        # empty, so it is the better fallback for a preview.
        "ticker": ticker,
        "thread": parse_thread(text) or parse_thread(ticker),
        "conversation": bool(props.get("isConversation")),
        # KDE Connect writes the notification's large icon to a temp file; for
        # a messenger that is usually the contact's or the group's photo, which
        # the windows use as the avatar.
        "icon": icon_path(props),
        "package": package_of(props),
        "repliable": bool(props.get("replyId")),
        # A notification re-synced when the phone reconnects is silent, and
        # KDE Connect never pops one of those either.
        "silent": bool(props.get("silent")),
    }


def notifications(repliable_only=False):
    """Every notification on every device, newest first."""
    found = []
    for device in children(DEVICES):
        base = f"{DEVICES}/{device}/notifications"
        for nid in children(base):
            note = read_note(f"{base}/{nid}")  # None: dismissed as we listed it
            if note and (note["repliable"] or not repliable_only):
                found.append(note)
    # Ids ascend as notifications arrive, so this is newest-first.
    found.sort(key=lambda n: n["id"], reverse=True)
    return found


def send_reply(path, text):
    """Reply to a notification. Raises GLib.Error if it has gone from the phone."""
    call(path, NOTIF_IFACE, "sendReply", GLib.Variant("(s)", (text,)))


def dismiss(path):
    """Clear a notification on the phone, the way swiping it away does.

    Answering a message on the desktop and then finding it still unread on the
    phone is the thing Phone Link does not do. Not every notification allows
    it -- an ongoing call or a media player says so with `dismissable` -- and
    those are left alone.
    """
    props = properties(path, NOTIF_IFACE)
    if not props or not props.get("dismissable", True):
        return False
    try:
        call(path, NOTIF_IFACE, "dismiss")
        return True
    except GLib.Error:
        return False  # already gone from the phone, which is the wanted end anyway


def friendly_error(message):
    """D-Bus errors are worded for a terminal; a window wants the cause."""
    msg = (message or "").strip().removeprefix("reply failed: ")
    if "UnknownObject" in msg or "No such object" in msg:
        # Read, dismissed or answered on the phone: the reply target went with it.
        return "That notification is gone from the phone"
    if "ServiceUnknown" in msg or "not provided by any" in msg:
        return "KDE Connect isn't running"
    if "NoReply" in msg or "timed out" in msg.lower():
        return "The phone didn't answer — is it on the same network?"
    return msg.splitlines()[-1] if msg else "Couldn't send the reply"
