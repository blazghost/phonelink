#!/usr/bin/env python3
"""A stand-in for kdeconnectd, for tests that must not touch the real phone.

Owns org.kde.kdeconnect on whatever bus it is started on and exposes two
devices -- a desktop listed first, then the phone, which is the arrangement
that used to send files and texts to the wrong machine -- with a handful of
notifications on the phone.

Run it only on a private bus (`dbus-run-session`): on the real session bus it
would fight the actual daemon for the name.

    dbus-run-session -- python3 tests/fake_kdeconnect.py
    dbus-run-session -- python3 tests/fake_kdeconnect.py --hang

With --hang it keeps the name and answers introspection, but never replies to a
daemon call -- which is how the real kdeconnectd has failed: still on the bus,
serving nothing.
"""

import json
import os
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

SERVICE = "org.kde.kdeconnect"
DEVICES = "/modules/kdeconnect/devices"
DEVICE_IFACE = "org.kde.kdeconnect.device"
NOTIF_IFACE = "org.kde.kdeconnect.device.notifications.notification"

DAEMON_PATH = "/modules/kdeconnect"
DAEMON_IFACE = "org.kde.kdeconnect.daemon"
SFTP_IFACE = "org.kde.kdeconnect.device.sftp"
CONV_IFACE = "org.kde.kdeconnect.device.conversations"
MPRIS_IFACE = "org.kde.kdeconnect.device.mprisremote"

# What the fake phone is playing. A test that wants something else -- nothing
# playing, a player that cannot seek -- writes the file named here before it
# asks, so each case is set up rather than left over from the test before.
MPRIS_FILE = os.environ.get("PHONELINK_FAKE_MPRIS", "")

MPRIS_DEFAULT = {
    "player": "Spotify",
    "playerList": ["Spotify", "Podcasts"],
    "title": "Drive",
    "artist": "The Expanse",
    "album": "Season One",
    "isPlaying": True,
    "position": 65000,
    "length": 245000,
    "volume": 40,
    "localAlbumArtUrl": "",
    "canSeek": True,
}

# Where the fake phone's storage is. A test points this at a directory it has
# filled with a camera roll, so the scan runs over a real filesystem and only
# the phone is pretend. PHONELINK_FAKE_MOUNT_FAILS makes the mount refuse,
# which is the other half of what the window has to handle.
FAKE_MOUNT = os.environ.get("PHONELINK_FAKE_MOUNT", "")
MOUNT_FAILS = os.environ.get("PHONELINK_FAKE_MOUNT_FAILS", "") not in ("", "0")

DESKTOP = "aaaa0000aaaa0000aaaa0000aaaa0000"
PHONE = "bbbb1111bbbb1111bbbb1111bbbb1111"

DEVICES_DATA = {
    # The desktop sorts first, exactly as the paired PC did on the real bus.
    DESKTOP: {"name": "Roci", "type": "desktop", "isReachable": True, "isPaired": True},
    PHONE: {"name": "Test Phone", "type": "phone", "isReachable": True, "isPaired": True},
}

NOTES = {
    "1": {"appName": "Reddit", "title": "Reddit", "text": "Someone replied",
          "ticker": "Reddit: Someone replied", "replyId": "", "silent": False,
          "internalId": "0|com.reddit.frontpage|1||10123", "isConversation": False,
          "hasIcon": False, "iconPath": "", "dismissable": False},
    "2": {"appName": "Messenger", "title": "Naomi Nagata",
          "text": "<b>Naomi Nagata</b><br/>Docking in ten&nbsp;minutes<br/>"
                  "<b>Alex Kamal</b><br/>Copy that",
          "ticker": "Naomi Nagata: Docking in ten minutes", "replyId": "reply-2",
          "silent": False, "internalId": "0|com.facebook.orca|2|tag|10222",
          "isConversation": True, "hasIcon": False, "iconPath": "",
          "dismissable": True},
    "3": {"appName": "Messages", "title": "(555) 010-1234", "text": "On my way",
          "ticker": "(555) 010-1234: On my way", "replyId": "reply-3", "silent": True,
          "internalId": "0|com.android.messaging|3||10333", "isConversation": True,
          "hasIcon": False, "iconPath": "", "dismissable": True},
}

DAEMON_XML = f"""
<node>
  <interface name="{DAEMON_IFACE}">
    <method name="selfId"><arg type="s" direction="out"/></method>
  </interface>
</node>
"""

DEVICE_XML = f"""
<node>
  <interface name="{DEVICE_IFACE}">
    <property name="name" type="s" access="read"/>
    <property name="type" type="s" access="read"/>
    <property name="isReachable" type="b" access="read"/>
    <property name="isPaired" type="b" access="read"/>
  </interface>
</node>
"""

NOTIF_XML = f"""
<node>
  <interface name="{NOTIF_IFACE}">
    <method name="sendReply"><arg name="message" type="s" direction="in"/></method>
    <method name="dismiss"/>
    <property name="appName" type="s" access="read"/>
    <property name="title" type="s" access="read"/>
    <property name="text" type="s" access="read"/>
    <property name="ticker" type="s" access="read"/>
    <property name="replyId" type="s" access="read"/>
    <property name="silent" type="b" access="read"/>
    <property name="internalId" type="s" access="read"/>
    <property name="isConversation" type="b" access="read"/>
    <property name="dismissable" type="b" access="read"/>
    <property name="hasIcon" type="b" access="read"/>
    <property name="iconPath" type="s" access="read"/>
  </interface>
</node>
"""

CONV_XML = f"""
<node>
  <interface name="{CONV_IFACE}">
    <method name="sendWithoutConversation">
      <arg name="addressList" type="av" direction="in"/>
      <arg name="message" type="s" direction="in"/>
      <arg name="attachmentUrls" type="av" direction="in"/>
    </method>
    <method name="replyToConversation">
      <arg name="conversationID" type="x" direction="in"/>
      <arg name="message" type="s" direction="in"/>
      <arg name="attachmentUrls" type="av" direction="in"/>
    </method>
    <method name="requestAllConversationThreads"/>
  </interface>
</node>
"""

MPRIS_XML = f"""
<node>
  <interface name="{MPRIS_IFACE}">
    <method name="sendAction"><arg name="action" type="s" direction="in"/></method>
    <method name="requestPlayerList"/>
    <method name="seek"><arg name="offset" type="i" direction="in"/></method>
    <property name="player" type="s" access="readwrite"/>
    <property name="playerList" type="as" access="read"/>
    <property name="title" type="s" access="read"/>
    <property name="artist" type="s" access="read"/>
    <property name="album" type="s" access="read"/>
    <property name="isPlaying" type="b" access="read"/>
    <property name="position" type="i" access="readwrite"/>
    <property name="length" type="i" access="read"/>
    <property name="volume" type="i" access="readwrite"/>
    <property name="localAlbumArtUrl" type="s" access="read"/>
    <property name="canSeek" type="b" access="read"/>
  </interface>
</node>
"""

SFTP_XML = f"""
<node>
  <interface name="{SFTP_IFACE}">
    <method name="mount"/>
    <method name="unmount"/>
    <method name="mountAndWait"><arg type="b" direction="out"/></method>
    <method name="isMounted"><arg type="b" direction="out"/></method>
    <method name="mountPoint"><arg type="s" direction="out"/></method>
    <method name="getMountError"><arg type="s" direction="out"/></method>
    <method name="getDirectories"><arg type="a{{sv}}" direction="out"/></method>
  </interface>
</node>
"""

# Replies land here, and `sent` prints them, so a test can check what was said
# without a phone anywhere.
SENT = []

# Whether the fake phone's storage is "mounted" right now.
MOUNTED = [False]


def sftp_reply(name):
    """What the sftp plugin answers, which differs per method and per state."""
    if name == "mountAndWait":
        MOUNTED[0] = not MOUNT_FAILS
        return GLib.Variant("(b)", (MOUNTED[0],))
    if name == "isMounted":
        return GLib.Variant("(b)", (MOUNTED[0],))
    if name == "mountPoint":
        return GLib.Variant("(s)", (FAKE_MOUNT if MOUNTED[0] else "",))
    if name == "getMountError":
        return GLib.Variant("(s)", ("the phone refused the connection" if MOUNT_FAILS else "",))
    if name == "getDirectories":
        # The real plugin exports a folder inside the mount, not the mount
        # itself, and phonelink has to look in the exported one.
        inside = f"{FAKE_MOUNT}/storage/emulated/0"
        return GLib.Variant("(a{sv})", ({inside: GLib.Variant("s", "Internal storage")},)
                            if MOUNTED[0] else ({},))
    if name == "unmount":
        MOUNTED[0] = False
    return None


def mpris_state():
    """What the fake is playing right now, as the test left it."""
    state = dict(MPRIS_DEFAULT)
    if MPRIS_FILE and os.path.exists(MPRIS_FILE):
        try:
            state.update(json.loads(open(MPRIS_FILE).read()))
        except (OSError, ValueError):
            pass
    return state


def mpris_save(state):
    if MPRIS_FILE:
        with open(MPRIS_FILE, "w") as handle:
            json.dump(state, handle)


def mpris_call(name, params):
    """The buttons, as the phone would act on them."""
    state = mpris_state()
    if name == "sendAction":
        action = params.unpack()[0]
        SENT.append(("mpris", action))
        print(f"mpris {action}", flush=True)
        if action in ("Play", "PlayPause"):
            state["isPlaying"] = not state["isPlaying"] if action == "PlayPause" else True
        elif action in ("Pause", "Stop"):
            state["isPlaying"] = False
        elif action in ("Next", "Previous"):
            state["title"] = "Next track" if action == "Next" else "Previous track"
            state["position"] = 0
        mpris_save(state)
    elif name == "seek":
        SENT.append(("mpris", f"seek {params.unpack()[0]}"))


def variant(value):
    if isinstance(value, bool):
        return GLib.Variant("b", value)
    if isinstance(value, int):
        return GLib.Variant("i", value)
    if isinstance(value, list):
        return GLib.Variant("as", value)
    return GLib.Variant("s", value)


def register(bus, path, xml, props, on_call=None, reply=None, hang=False, answer=None,
             live=None, on_set=None):
    """Put one object on the bus.

    `reply` is the same answer for every method; `answer` is a function of the
    method name, for an interface like sftp whose methods each say something
    different. `live` is a function returning the properties as they stand,
    for an object a test changes under the program being tested.
    """
    info = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]

    def method(_c, _sender, _path, _iface, name, params, invocation):
        if on_call:
            on_call(name, params)
        if hang:
            return  # the caller waits until its own timeout, as with a wedged daemon
        invocation.return_value(answer(name) if answer else reply)

    def get_prop(_c, _sender, _path, _iface, name):
        current = live() if live else props
        return variant(current[name]) if name in current else None

    def set_prop(_c, _sender, _path, _iface, name, value):
        if on_set:
            on_set(name, value)
            return True
        return False

    # register_object is deprecated, and the closures spelling has changed over
    # PyGObject versions, so take whichever this one has.
    register_object = (getattr(bus, "register_object_with_closures2", None)
                       or getattr(bus, "register_object_with_closures", None)
                       or bus.register_object)
    register_object(path, info, method, get_prop, set_prop)


def main(hang=False):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    # Never fight the real daemon: if the name is taken, this is not a private
    # bus and the tests would be reading a real phone.
    owned = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                          "org.freedesktop.DBus", "NameHasOwner",
                          GLib.Variant("(s)", (SERVICE,)), None,
                          Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    if owned:
        sys.exit(f"{SERVICE} is already on this bus: run under dbus-run-session")

    # The daemon object itself, which is what a health check asks.
    register(bus, DAEMON_PATH, DAEMON_XML, {},
             reply=GLib.Variant("(s)", ("fake-self-id",)), hang=hang)

    for device, props in DEVICES_DATA.items():
        register(bus, f"{DEVICES}/{device}", DEVICE_XML, props)

    # The phone's storage, as the sftp plugin offers it.
    register(bus, f"{DEVICES}/{PHONE}/sftp", SFTP_XML, {}, answer=sftp_reply, hang=hang)

    # Texts to somebody there is no thread with yet. The conversations
    # interface sits on the device itself, not on a plugin object under it.
    def conversation(name, params):
        if name == "sendWithoutConversation":
            addresses, text, attachments = params.unpack()
            # Each address is a struct of one string, as KDE Connect marshals it.
            numbers = [a[0] if isinstance(a, tuple) else a for a in addresses]
            SENT.append(("new", numbers, text, list(attachments)))
            print(f"new {' '.join(numbers)} {text}", flush=True)

    register(bus, f"{DEVICES}/{PHONE}", CONV_XML, {}, conversation, hang=hang)

    # What the phone is playing, as mprisremote reports it.
    def mpris_set(name, value):
        state = mpris_state()
        state[name] = value.unpack() if hasattr(value, "unpack") else value
        SENT.append(("mpris", f"{name}={state[name]}"))
        print(f"mpris {name}={state[name]}", flush=True)
        mpris_save(state)

    register(bus, f"{DEVICES}/{PHONE}/mprisremote", MPRIS_XML, {}, mpris_call,
             hang=hang, live=mpris_state, on_set=mpris_set)

    for nid, props in NOTES.items():
        path = f"{DEVICES}/{PHONE}/notifications/{nid}"

        def sent(name, params, path=path):
            if name == "sendReply":
                SENT.append((path, params.unpack()[0]))
                print(f"reply {path} {params.unpack()[0]}", flush=True)
            elif name == "dismiss":
                SENT.append((path, "dismiss"))
                print(f"dismiss {path}", flush=True)

        register(bus, path, NOTIF_XML, props, sent)

    loop = GLib.MainLoop()
    held = []

    def acquired(*_):
        held.append(True)
        print("fake kdeconnect: ready", flush=True)

    def lost(*_):
        # Losing it after the bus goes away is just the end of the test run.
        if not held:
            sys.exit("fake kdeconnect: could not take the name -- real daemon on this bus?")
        loop.quit()

    Gio.bus_own_name(Gio.BusType.SESSION, SERVICE, Gio.BusNameOwnerFlags.NONE, None,
                     acquired, lost)
    loop.run()


if __name__ == "__main__":
    main(hang="--hang" in sys.argv)
