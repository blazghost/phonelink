"""Mouse sharing's arithmetic, kept apart from the portal and libei so it can be tested.

The pointer leaves this screen at one edge and carries on onto the phone. The
phone never says where its pointer is -- KDE Connect's D-Bus interface only
lets phonelink send moves, not hear back -- so the hand-back is worked out
here: the phone's pointer is pinned against the edge it came in at, and
phonelink keeps count of how far it has gone since. Moving it back past that
edge brings the pointer home. Ctrl+Alt+Esc always does.
"""

import os
from pathlib import Path

# evdev codes, as libei reports them.
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
KEY_ESC = 1
KEY_LEFTCTRL, KEY_RIGHTCTRL = 29, 97
KEY_LEFTALT, KEY_RIGHTALT = 56, 100
KEY_LEFTSHIFT, KEY_RIGHTSHIFT = 42, 54

EDGES = ("left", "right", "top", "bottom")


def edge_file():
    """Where `phonelink mouse on <edge>` keeps the edge, for the service to read."""
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "phonelink" / "mouse-edge"


def read_edge():
    try:
        edge = edge_file().read_text().strip()
    except OSError:
        edge = ""
    return edge if edge in EDGES else "left"

# A move far bigger than any phone screen: Android stops the pointer at its
# edge, which is how it gets pinned there.
PIN = 10000

# How far the phone's pointer can travel across, in its pixels. Android does
# not say, so this is a guess at a phone held upright; a pointer that comes
# home too early or too late wants this nudged (PHONELINK_SHARE_SPAN).
SPAN = {"left": 1080, "right": 1080, "top": 2340, "bottom": 2340}

# Which way is "back towards this screen" on the phone, per edge.
HOMEWARD = {"left": (1, 0), "right": (-1, 0), "top": (0, 1), "bottom": (0, -1)}


def barrier(edge, zones):
    """(x1, y1, x2, y2) along the outer `edge` of the portal's zones [(w, h, x, y)]."""
    boxes = [(x, y, w, h) for w, h, x, y in zones]
    if edge == "left":
        x, y, _w, h = min(boxes, key=lambda b: b[0])
        return (x, y, x, y + h - 1)
    if edge == "right":
        x, y, w, h = max(boxes, key=lambda b: b[0] + b[2])
        return (x + w, y, x + w, y + h - 1)
    if edge == "top":
        x, y, w, _h = min(boxes, key=lambda b: b[1])
        return (x, y, x + w - 1, y)
    x, y, w, h = max(boxes, key=lambda b: b[1] + b[3])
    return (x, y + h, x + w - 1, y + h)


def pin_move(edge):
    """The move that puts the phone's pointer at the side facing this screen."""
    hx, hy = HOMEWARD[edge]
    return (hx * PIN, hy * PIN)


class Handoff:
    """Where the phone's pointer is along the axis that leads home.

    0 is the phone's edge facing this screen, -span its far side. A move that
    would take it above 0 has crossed back.
    """

    def __init__(self, edge, span=None):
        self.hx, self.hy = HOMEWARD[edge]
        self.span = span or SPAN[edge]
        self.at = 0.0

    def motion(self, dx, dy):
        """Count a move; True once the pointer has gone back past the edge."""
        along = dx * self.hx + dy * self.hy
        if self.at + along > 0:
            return True
        self.at = max(-self.span, self.at + along)
        return False


def home_point(edge, line, along):
    """Where the pointer reappears: `along` the barrier `line`, two pixels inside it."""
    x1, y1, x2, y2 = line
    inset = {"left": (2, 0), "right": (-2, 0), "top": (0, 2), "bottom": (0, -2)}[edge]
    if x1 == x2:
        return (float(x1 + inset[0]), float(min(max(along, y1), y2)))
    return (float(min(max(along, x1), x2)), float(y1 + inset[1]))


def button_body(button, pressed):
    """The mousepad request for a button, or None.

    Only the left button has a press and a release in KDE Connect's protocol,
    which is what lets a drag work on the phone; the others click on press.
    """
    if button == BTN_LEFT:
        return {"singlehold" if pressed else "singlerelease": True}
    if pressed and button == BTN_RIGHT:
        return {"rightclick": True}
    if pressed and button == BTN_MIDDLE:
        return {"middleclick": True}
    return None


class Keys:
    """Which modifiers are down, and whether Ctrl+Alt+Esc has just been pressed."""

    def __init__(self):
        self.down = set()

    def press(self, code, pressed):
        """Record a key; True when it completes Ctrl+Alt+Esc."""
        if pressed:
            self.down.add(code)
        else:
            self.down.discard(code)
        _shift, ctrl, alt = self.modifiers()
        return pressed and code == KEY_ESC and ctrl and alt

    def modifiers(self):
        """(shift, ctrl, alt) as they stand."""
        d = self.down
        return (bool(d & {KEY_LEFTSHIFT, KEY_RIGHTSHIFT}),
                bool(d & {KEY_LEFTCTRL, KEY_RIGHTCTRL}),
                bool(d & {KEY_LEFTALT, KEY_RIGHTALT}))
