"""The Remote tab: a touchpad and a keyboard for the phone.

Drag on the pad to move the phone's pointer, tap to click, right-click for
its right button, scroll to scroll. Keys typed into the keyboard field go to
the phone one by one; the field below sends a whole text at once. Everything
goes through KDE Connect's remotecontrol and remotekeyboard plugins (see
phonelink/remote.py), and nothing here waits on the phone.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import kdeconnect as kde, remote, widgets  # noqa: E402

VERTICAL = Gtk.Orientation.VERTICAL
# Pointer speed: phone pixels per pixel dragged here. The phone's screen is
# denser than this one, so 1:1 feels sluggish; turn it up or down to taste.
SPEED = 1.8
TAP_SLOP = 4  # a drag shorter than this, in pixels, was a tap


def extra_css(p):
    return f"""
.touchpad {{ background: alpha({p['foreground']}, 0.04); border-radius: 18px;
             border: 1px solid alpha({p['foreground']}, 0.12); min-height: 340px; }}
.touchpad image {{ color: alpha({p['foreground']}, 0.35); }}
.pad-button {{ border-radius: 999px; min-height: 40px; font-weight: 600;
               background: alpha({p['accent']}, 0.16); }}
.hint {{ font-size: 9pt; color: {p['muted']}; }}
.kbd-entry {{ border-radius: 999px; min-height: 42px; padding: 0 16px; }}
"""


class RemotePage(Adw.Bin):

    def __init__(self, device, toast):
        super().__init__()
        self.device, self.toast = device, toast
        if not device:
            self.set_child(Adw.StatusPage(icon_name="phone-symbolic", title="Phone not connected",
                                          description="Open KDE Connect on the phone."))
            return
        self.did = device["id"]
        self.last = (0.0, 0.0)
        self.travel = 0.0
        self.carry = [0.0, 0.0]

        has = remote.available(self.did)
        box = Gtk.Box(orientation=VERTICAL, spacing=16)
        box.add_css_class("hub-page")
        box.append(self.build_pad("remotecontrol" in has))
        box.append(self.build_keyboard("remotekeyboard" in has))
        self.set_child(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                          child=Adw.Clamp(maximum_size=820, child=box)))

        kde.BUS.signal_subscribe(kde.SERVICE, remote.KEYBOARD_IFACE, "remoteStateChanged",
                                 f"{kde.DEVICES}/{self.did}/remotekeyboard", None,
                                 Gio.DBusSignalFlags.NONE, lambda *_: self.show_keyboard_state())
        self.show_keyboard_state()

    # -- touchpad

    def build_pad(self, loaded):
        head = widgets.label("Touchpad", "card-head")
        hint = widgets.label(
            "Drag to move the phone's pointer, tap to click, right-click for its right "
            "button, scroll to scroll. On the phone, KDE Connect needs its Remote input "
            "permission (Android accessibility settings).", "hint", wrap=True)
        pad = Gtk.Box(hexpand=True, vexpand=True, focusable=True)
        pad.add_css_class("touchpad")
        pad.append(Gtk.Image(icon_name="input-touchpad-symbolic", pixel_size=48,
                             hexpand=True, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER))
        pad.set_cursor(Gdk.Cursor.new_from_name("crosshair"))

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        pad.add_controller(drag)
        click = Gtk.GestureClick(button=0)
        click.connect("released", self.on_tap)
        pad.add_controller(click)
        wheel = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        wheel.connect("scroll", self.on_scroll)
        pad.add_controller(wheel)

        buttons = Gtk.Box(spacing=10, homogeneous=True)
        for text, icon, which in (("Left click", "input-mouse-symbolic", "left"),
                                  ("Middle", "input-mouse-symbolic", "middle"),
                                  ("Right click", "input-mouse-symbolic", "right")):
            button = Gtk.Button(child=Adw.ButtonContent(icon_name=icon, label=text))
            button.add_css_class("pad-button")
            button.connect("clicked", lambda _b, w=which: remote.click(self.did, w))
            buttons.append(button)

        card = Gtk.Box(orientation=VERTICAL, spacing=12)
        card.add_css_class("hub-card")
        for widget in (head, hint, pad, buttons):
            card.append(widget)
        if not loaded:
            card.set_sensitive(False)
            hint.set_label("KDE Connect hasn't loaded its remote-control plugin for this phone. "
                           "Turn on Remote input in the KDE Connect app on the phone.")
        return card

    def on_drag_begin(self, _gesture, _x, _y):
        self.last, self.travel, self.carry = (0.0, 0.0), 0.0, [0.0, 0.0]

    def on_drag_update(self, _gesture, ox, oy):
        dx, dy = ox - self.last[0], oy - self.last[1]
        self.last = (ox, oy)
        self.travel += abs(dx) + abs(dy)
        # Whole pixels only go over the wire; the fractions are carried forward
        # so a slow drag still moves rather than rounding to nothing.
        self.carry[0] += dx * SPEED
        self.carry[1] += dy * SPEED
        sx, sy = int(self.carry[0]), int(self.carry[1])
        if sx or sy:
            self.carry[0] -= sx
            self.carry[1] -= sy
            remote.move(self.did, sx, sy)

    def on_tap(self, gesture, _n, _x, _y):
        if self.travel > TAP_SLOP:
            self.travel = 0.0
            return
        button = gesture.get_current_button()
        remote.click(self.did, {Gdk.BUTTON_SECONDARY: "right",
                                Gdk.BUTTON_MIDDLE: "middle"}.get(button, "left"))

    def on_scroll(self, _controller, dx, dy):
        remote.scroll(self.did, dx, dy)
        return True

    # -- keyboard

    def build_keyboard(self, loaded):
        head = Gtk.Box()
        head.append(widgets.label("Keyboard", "card-head", hexpand=True))
        self.kbd_state = Gtk.Label()
        self.kbd_state.add_css_class("chip")
        head.append(self.kbd_state)
        hint = widgets.label(
            "Click the field and type: each key goes to the phone as you press it. On the "
            "phone, pick \"KDE Connect Remote Keyboard\" as the keyboard.", "hint", wrap=True)

        live = Gtk.Entry(placeholder_text="Type here to type on the phone…")
        live.add_css_class("kbd-entry")
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        live.add_controller(keys)

        self.whole = Gtk.Entry(placeholder_text="Or send a whole text at once", hexpand=True)
        self.whole.add_css_class("kbd-entry")
        self.whole.connect("activate", lambda *_: self.send_whole())
        send = Gtk.Button(icon_name=widgets.send_icon(), tooltip_text="Send to the phone",
                          valign=Gtk.Align.CENTER)
        send.add_css_class("circular")
        send.add_css_class("suggested-action")
        send.connect("clicked", lambda *_: self.send_whole())
        row = Gtk.Box(spacing=8)
        row.append(self.whole)
        row.append(send)

        card = Gtk.Box(orientation=VERTICAL, spacing=12)
        card.add_css_class("hub-card")
        for widget in (head, hint, live, row):
            card.append(widget)
        if not loaded:
            card.set_sensitive(False)
        return card

    def on_key(self, _controller, keyval, _code, state):
        name = Gdk.keyval_name(keyval) or ""
        char = chr(Gdk.keyval_to_unicode(keyval) or 0).strip("\0")
        args = remote.key_args(name, char,
                               shift=bool(state & Gdk.ModifierType.SHIFT_MASK),
                               ctrl=bool(state & Gdk.ModifierType.CONTROL_MASK),
                               alt=bool(state & Gdk.ModifierType.ALT_MASK))
        if args is None:
            return False  # a modifier on its own: let it be
        remote.key(self.did, *args)
        return True  # typed on the phone, not into the field

    def send_whole(self):
        text = self.whole.get_text()
        if text:
            remote.key(self.did, text)
            self.whole.set_text("")

    def show_keyboard_state(self):
        active = remote.keyboard_active(self.did)
        self.kbd_state.set_label({True: "Keyboard active on the phone",
                                  False: "Keyboard not active on the phone",
                                  None: "Keyboard unavailable"}[active])
        for css in ("lead", "bad"):
            self.kbd_state.remove_css_class(css)
        self.kbd_state.add_css_class("lead" if active else "bad")
