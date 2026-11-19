"""Driving the phone's pointer and keyboard from here.

Two KDE Connect plugins, neither reimplemented here:

    remotecontrol    a touchpad: `moveCursor` for motion, `sendCommand` for a
                     click or a scroll, both as kdeconnect.mousepad.request
    remotekeyboard   keys, to the phone's "KDE Connect Remote Keyboard" input
                     method; `remoteState` says whether that is the active one

The phone needs KDE Connect's Remote input (accessibility) permission for the
pointer, and its keyboard picked as the input method for keys.
"""

from gi.repository import Gio, GLib

from . import kdeconnect as kde

CONTROL_IFACE = "org.kde.kdeconnect.device.remotecontrol"
KEYBOARD_IFACE = "org.kde.kdeconnect.device.remotekeyboard"

# GDK key names -> KDE Connect's specialKey numbers. Anything not here is sent
# as the character it types.
SPECIAL = {
    "BackSpace": 1, "Tab": 2, "ISO_Left_Tab": 2,
    "Left": 4, "Up": 5, "Right": 6, "Down": 7,
    "Page_Up": 8, "Page_Down": 9, "Home": 10, "End": 11,
    "Return": 12, "KP_Enter": 12, "Delete": 13, "Escape": 14,
    **{f"F{n}": 20 + n for n in range(1, 13)},
}

# What sendCommand takes for a press of each button.
CLICKS = {"left": "singleclick", "middle": "middleclick", "right": "rightclick",
          "double": "doubleclick"}


def _path(device_id, plugin):
    return f"{kde.DEVICES}/{device_id}/{plugin}"


def _fire(path, iface, method, args):
    """Send without waiting: a drag sends dozens of these a second, and a phone
    that has gone quiet must never hold the window up for any of them."""
    kde.BUS.call(kde.SERVICE, path, iface, method, args, None,
                 Gio.DBusCallFlags.NONE, kde.TIMEOUT, None, None)


# ------------------------------------------------------------------ pointer

def move(device_id, dx, dy):
    """Move the phone's pointer by whole pixels."""
    _fire(_path(device_id, "remotecontrol"), CONTROL_IFACE, "moveCursor",
          GLib.Variant("((ii))", ((int(dx), int(dy)),)))


def click(device_id, button="left"):
    command(device_id, {CLICKS[button]: True})


def scroll(device_id, dx, dy):
    """Scroll the phone. Positive dy is down, as a wheel turned towards you."""
    command(device_id, {"scroll": True, "dx": float(dx), "dy": float(dy)})


def command(device_id, body):
    _fire(_path(device_id, "remotecontrol"), CONTROL_IFACE, "sendCommand",
          GLib.Variant("(a{sv})", (to_variants(body),)))


def to_variants(body):
    """A dict for a{sv}: booleans stay booleans, numbers go as doubles."""
    out = {}
    for key, value in body.items():
        if isinstance(value, bool):
            out[key] = GLib.Variant("b", value)
        elif isinstance(value, (int, float)):
            out[key] = GLib.Variant("d", float(value))
        else:
            out[key] = GLib.Variant("s", str(value))
    return out


# ----------------------------------------------------------------- keyboard

def key_args(name, char, shift=False, ctrl=False, alt=False):
    """(key, specialKey, shift, ctrl, alt) for one key press, or None to ignore it.

    `name` is the GDK key name and `char` what it types (empty for a key that
    types nothing). Modifiers held on their own are not sent.
    """
    if name in SPECIAL:
        return "", SPECIAL[name], shift, ctrl, alt
    if char and char.isprintable():
        return char, 0, shift, ctrl, alt
    return None


def key(device_id, text, special=0, shift=False, ctrl=False, alt=False):
    _fire(_path(device_id, "remotekeyboard"), KEYBOARD_IFACE, "sendKeyPress",
          GLib.Variant("(sibbbb)", (text, int(special), shift, ctrl, alt, False)))


def available(device_id):
    """Which of remotecontrol and remotekeyboard KDE Connect has loaded for the phone."""
    return {p for p in kde.children(f"{kde.DEVICES}/{device_id}")
            if p in ("remotecontrol", "remotekeyboard")}


def keyboard_active(device_id):
    """Is KDE Connect's keyboard the phone's input method right now? None if unknown."""
    props = kde.properties(_path(device_id, "remotekeyboard"), KEYBOARD_IFACE)
    return None if props is None else bool(props.get("remoteState"))
