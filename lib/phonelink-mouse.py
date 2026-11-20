#!/usr/bin/env python3
"""phonelink mouse -- push the pointer past a screen edge and it drives the phone.

A small resident service (phonelink-mouse.service). It asks the InputCapture
portal for a pointer barrier along one edge of the screen; when the pointer
hits it the compositor stops moving the desktop's cursor and hands the input
here over libei, and this passes it on through KDE Connect's remotecontrol
and remotekeyboard -- the same calls as the window's Remote tab.

KDE Connect has a plugin of its own for this, but it sends the portal a
barrier id of the wrong D-Bus type and Hyprland's portal refuses it. Doing
the capture here sidesteps that and needs nothing changed in KDE Connect.

The pointer comes home when it is moved back past the phone's edge (see
phonelink/share.py for how that is reckoned), when the phone goes away, or
on Ctrl+Alt+Esc. Should this process die, the portal session dies with it
and the compositor gives the pointer back by itself.

The edge is read from ~/.config/phonelink/mouse-edge (left, right, top or
bottom; `phonelink mouse on right` writes it).
"""

import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

from gi.repository import Gio, GLib

try:
    from gi.repository import GLibUnix
except ImportError:  # older PyGObject: the GLib.unix_* spelling below still works
    GLibUnix = None

sys.path.insert(0, str(Path(__file__).resolve().parent))

from phonelink import ei, kdeconnect as kde, remote, share  # noqa: E402

PHONELINK = str(Path(__file__).resolve().parent.parent / "phonelink")

PORTAL, PATH = "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.InputCapture"
CAP_KEYBOARD, CAP_POINTER = 1, 2
# Scroll: a wheel notch is 120 in discrete units; a touchpad's smooth scroll
# comes in pixels. The phone takes "notches". Tune if scrolling feels off.
NOTCH = 120
PX_PER_NOTCH = 15
DEBUG = os.environ.get("PHONELINK_MOUSE_DEBUG", "") not in ("", "0")


def log(*parts):
    print("phonelink-mouse:", *parts, file=sys.stderr, flush=True)


class Mouse:

    def __init__(self, edge):
        self.edge = edge
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.session = None
        self.line = None
        self.active = False
        self.activation = 0
        self.entry = 0.0
        self.device = None
        self.handoff = None
        self.carry = [0.0, 0.0]
        self.keys = share.Keys()
        self.keyboard = None
        self.receiver = None
        span = os.environ.get("PHONELINK_SHARE_SPAN", "")
        self.span = int(span) if span.isdigit() else None  # set by hand: always wins
        self.screen = None  # the phone's (width, height) as held, once adb has said
        for name in ("Activated", "Deactivated", "Disabled", "ZonesChanged"):
            self.bus.signal_subscribe(PORTAL, IFACE, name, PATH, None,
                                      Gio.DBusSignalFlags.NONE, self.on_signal)

    # -- the portal

    def request(self, method, build):
        """Call a portal method that answers through a Request object, and wait for it."""
        token = "phonelink" + secrets.token_hex(4)
        handle = f"{PATH}/request/{self.sender}/{token}"
        reply = {}

        def on_response(_c, _s, _p, _i, _m, params):
            reply["code"], reply["data"] = params.unpack()
        sub = self.bus.signal_subscribe(PORTAL, "org.freedesktop.portal.Request", "Response",
                                        handle, None, Gio.DBusSignalFlags.NONE, on_response)
        try:
            self.bus.call_sync(PORTAL, PATH, IFACE, method, build(token), None,
                               Gio.DBusCallFlags.NONE, 10000, None)
            context = GLib.MainContext.default()
            deadline = GLib.get_monotonic_time() + 10_000_000
            while "code" not in reply and GLib.get_monotonic_time() < deadline:
                context.iteration(True)
        finally:
            self.bus.signal_unsubscribe(sub)
        if reply.get("code") != 0:
            raise RuntimeError(f"{method} was refused by the portal ({reply.get('code', 'no answer')})")
        return reply["data"]

    def start(self):
        made = self.request("CreateSession", lambda t: GLib.Variant("(sa{sv})", ("", {
            "handle_token": GLib.Variant("s", t),
            "session_handle_token": GLib.Variant("s", t),
            "capabilities": GLib.Variant("u", CAP_KEYBOARD | CAP_POINTER)})))
        self.session = made["session_handle"]

        result, fds = self.bus.call_with_unix_fd_list_sync(
            PORTAL, PATH, IFACE, "ConnectToEIS", GLib.Variant("(oa{sv})", (self.session, {})),
            GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, 10000, None, None)
        self.receiver = ei.Receiver(fds.get(result.unpack()[0]), self.on_ei)
        add_fd = getattr(GLibUnix, "fd_add_full", None) or GLib.unix_fd_add_full
        add_fd(GLib.PRIORITY_DEFAULT, self.receiver.fd, GLib.IOCondition.IN,
               lambda *_: self.receiver.dispatch() or True)
        self.arm()
        self.measure()

    def measure(self):
        """Ask the phone, over adb, how big its screen is and which way up.

        On a worker thread, so a crossing never waits on adb; until it answers
        (or with no adb at all) the guess in share.SPAN stands in.
        """
        def work():
            try:
                serial = subprocess.run([PHONELINK, "adb-serial"], capture_output=True,
                                        text=True, timeout=20).stdout.strip()
                if not serial:
                    return
                adb = ["adb", "-s", serial, "shell"]
                size = subprocess.run(adb + ["wm", "size"], capture_output=True,
                                      text=True, timeout=10).stdout
                turn = subprocess.run(adb + ["dumpsys window displays | grep -m1 mRotation"],
                                      capture_output=True, text=True, timeout=10).stdout
            except (OSError, subprocess.TimeoutExpired):
                return
            if screen := share.parse_screen(size, turn):
                if screen != self.screen:
                    log(f"phone screen {screen[0]}x{screen[1]} as held")
                self.screen = screen
        threading.Thread(target=work, daemon=True).start()

    def arm(self):
        """Fetch the screen layout, put the barrier on its edge, and enable capture."""
        zones = self.request("GetZones", lambda t: GLib.Variant("(oa{sv})", (
            self.session, {"handle_token": GLib.Variant("s", t)})))
        self.line = share.barrier(self.edge, zones["zones"])
        barrier = {"barrier_id": GLib.Variant("u", 1),  # 'u': what KDE Connect gets wrong
                   "position": GLib.Variant("(iiii)", self.line)}
        result = self.request("SetPointerBarriers", lambda t: GLib.Variant("(oa{sv}aa{sv}u)", (
            self.session, {"handle_token": GLib.Variant("s", t)}, [barrier], zones["zone_set"])))
        if result.get("failed_barriers"):
            raise RuntimeError(f"the compositor refused the barrier at {self.line}")
        self.bus.call_sync(PORTAL, PATH, IFACE, "Enable",
                           GLib.Variant("(oa{sv})", (self.session, {})), None,
                           Gio.DBusCallFlags.NONE, 10000, None)
        log(f"ready: push the pointer past the {self.edge} edge {self.line}")

    def on_signal(self, _c, _s, _p, _i, name, params):
        session, options = params.unpack()
        if session != self.session:
            return
        if name == "Activated":
            self.activation = options.get("activation_id", 0)
            x, y = options.get("cursor_position", (0.0, 0.0))
            self.entry = y if self.edge in ("left", "right") else x
            log(f"captured at ({x:.0f}, {y:.0f})")
            self.begin()
        elif name == "Deactivated":
            log("deactivated by the compositor")
            self.active = False
        elif name == "ZonesChanged":
            GLib.idle_add(lambda: self.arm() and False)  # a monitor came or went
        elif name == "Disabled":
            log("the portal disabled capture; exiting so the service starts afresh")
            GLib.idle_add(lambda: sys.exit(1))

    def begin(self):
        self.device = kde.phone()
        if not self.device:
            log("no phone reachable: giving the pointer straight back")
            self.release()
            return
        did = self.device["id"]
        self.active = True
        self.handoff = share.Handoff(self.edge, self.span or share.span_for(self.edge, self.screen))
        self.measure()  # for next time: the phone may be turned by then
        self.carry = [0.0, 0.0]
        remote.move(did, *share.pin_move(self.edge))
        GLib.timeout_add_seconds(2, self.watch)

    def watch(self):
        """While the phone has the pointer: if the phone goes, the pointer comes back."""
        if not self.active:
            return False
        if not kde.pick_device(kde.devices(), self.device["id"]):
            log("the phone went away: giving the pointer back")
            self.release()
            return False
        return True

    def release(self):
        self.active = False
        x, y = share.home_point(self.edge, self.line, self.entry)
        log(f"released at ({x:.0f}, {y:.0f})")
        self.bus.call(PORTAL, PATH, IFACE, "Release", GLib.Variant("(oa{sv})", (self.session, {
            "activation_id": GLib.Variant("u", self.activation),
            "cursor_position": GLib.Variant("(dd)", (x, y))})),
            None, Gio.DBusCallFlags.NONE, 10000, None, None)

    # -- what the compositor sends while the pointer is ours

    def on_ei(self, kind, event):
        E = ei.EI
        if DEBUG:
            log(f"ei event {kind}")
        if kind == ei.DEVICE_ADDED:
            # The compositor re-creates its keyboard when the keymap changes
            # (another keyboard used, a layout switched): take the new one.
            keyboard = ei.Keyboard(E.ei_event_get_device(event))
            if keyboard.state:
                self.keyboard = keyboard
            return
        if kind == ei.KEYBOARD_KEY:
            code = E.ei_event_keyboard_get_key(event)
            pressed = E.ei_event_keyboard_get_key_is_press(event)
            if DEBUG:
                log(f"key {code} {'down' if pressed else 'up'}")
            self.on_key(code, pressed)
            return
        if not self.active:
            return
        did = self.device["id"]
        if kind == ei.POINTER_MOTION:
            dx, dy = E.ei_event_pointer_get_dx(event), E.ei_event_pointer_get_dy(event)
            if self.handoff.motion(dx, dy):
                log("moved back past the phone's edge")
                self.release()
                return
            self.carry[0] += dx
            self.carry[1] += dy
            sx, sy = int(self.carry[0]), int(self.carry[1])
            if sx or sy:
                self.carry[0] -= sx
                self.carry[1] -= sy
                remote.move(did, sx, sy)
        elif kind == ei.BUTTON:
            body = share.button_body(E.ei_event_button_get_button(event),
                                     E.ei_event_button_get_is_press(event))
            if body:
                remote.command(did, body)
        elif kind == ei.SCROLL_DISCRETE:
            remote.scroll(did, E.ei_event_scroll_get_discrete_dx(event) / NOTCH,
                          E.ei_event_scroll_get_discrete_dy(event) / NOTCH)
        elif kind == ei.SCROLL_DELTA:
            remote.scroll(did, E.ei_event_scroll_get_dx(event) / PX_PER_NOTCH,
                          E.ei_event_scroll_get_dy(event) / PX_PER_NOTCH)

    def on_key(self, code, pressed):
        if self.keys.press(code, pressed):
            log("Ctrl+Alt+Esc: giving the pointer back")
            self.release()
            return
        # Always through xkb, so its idea of what is held stays right.
        name, text = self.keyboard.key(code, pressed) if self.keyboard else ("", "")
        if not (pressed and self.active):
            return
        args = remote.key_args(name, text, *self.keys.modifiers())
        if DEBUG:
            log(f"typed {name!r} {text!r} -> {args}")
        if args:
            remote.key(self.device["id"], *args)


def main():
    if ei.EI is None:
        log("libei is not installed (pacman -S libei)")
        return 1
    mouse = Mouse(share.read_edge())
    try:
        mouse.start()
    except (GLib.Error, RuntimeError) as exc:
        log(f"couldn't start: {getattr(exc, 'message', exc)}")
        return 1
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
