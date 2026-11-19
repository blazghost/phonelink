"""Just enough of libei (as a receiver) and xkbcommon, through ctypes.

The InputCapture portal hands over captured input as an EIS connection: this
reads it. libei says which evdev key went down; xkbcommon, fed the keymap the
compositor sends along, says what that key types. Values are from libei.h and
xkbcommon.h; the libraries are part of any desktop that has the portal.
"""

import ctypes
import ctypes.util
import mmap
import os

# enum ei_event_type
CONNECT, DISCONNECT, SEAT_ADDED, SEAT_REMOVED, DEVICE_ADDED = 1, 2, 3, 4, 5
POINTER_MOTION = 300
BUTTON = 500
SCROLL_DELTA, SCROLL_DISCRETE = 600, 603
KEYBOARD_KEY = 700

# enum ei_device_capability
CAP_POINTER, CAP_KEYBOARD, CAP_SCROLL, CAP_BUTTON = 1 << 0, 1 << 2, 1 << 4, 1 << 5
KEYMAP_XKB = 1

P, INT, U, D, B = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_double, ctypes.c_bool


def _load(name, functions):
    path = ctypes.util.find_library(name)
    if not path:
        return None
    lib = ctypes.CDLL(path)
    for fname, restype, *argtypes in functions:
        fn = getattr(lib, fname)
        fn.restype = restype
        if argtypes != [...]:
            fn.argtypes = argtypes
    return lib


EI = _load("ei", [
    ("ei_new_receiver", P, P),
    ("ei_configure_name", None, P, ctypes.c_char_p),
    ("ei_setup_backend_fd", INT, P, INT),
    ("ei_get_fd", INT, P),
    ("ei_dispatch", None, P),
    ("ei_get_event", P, P),
    ("ei_unref", P, P),
    ("ei_event_unref", P, P),
    ("ei_event_get_type", INT, P),
    ("ei_event_get_seat", P, P),
    ("ei_event_get_device", P, P),
    ("ei_seat_bind_capabilities", None, ...),  # variadic, NULL-terminated
    ("ei_device_keyboard_get_keymap", P, P),
    ("ei_keymap_get_type", INT, P),
    ("ei_keymap_get_fd", INT, P),
    ("ei_keymap_get_size", ctypes.c_size_t, P),
    ("ei_event_pointer_get_dx", D, P),
    ("ei_event_pointer_get_dy", D, P),
    ("ei_event_button_get_button", U, P),
    ("ei_event_button_get_is_press", B, P),
    ("ei_event_scroll_get_dx", D, P),
    ("ei_event_scroll_get_dy", D, P),
    ("ei_event_scroll_get_discrete_dx", ctypes.c_int32, P),
    ("ei_event_scroll_get_discrete_dy", ctypes.c_int32, P),
    ("ei_event_keyboard_get_key", U, P),
    ("ei_event_keyboard_get_key_is_press", B, P),
])

XKB = _load("xkbcommon", [
    ("xkb_context_new", P, INT),
    ("xkb_keymap_new_from_string", P, P, ctypes.c_char_p, INT, INT),
    ("xkb_state_new", P, P),
    ("xkb_state_update_key", INT, P, U, INT),
    ("xkb_state_key_get_one_sym", U, P, U),
    ("xkb_keysym_get_name", INT, U, ctypes.c_char_p, ctypes.c_size_t),
    ("xkb_state_key_get_utf8", INT, P, U, ctypes.c_char_p, ctypes.c_size_t),
])


class Receiver:
    """One EIS connection: call `dispatch()` when its fd is readable, get events back.

    `on_event(kind, event)` is called for each one, with the raw event pointer
    to read with the EI functions; it is released afterwards.
    """

    def __init__(self, fd, on_event):
        if EI is None:
            raise RuntimeError("libei is not installed")
        self.on_event = on_event
        self.ctx = EI.ei_new_receiver(None)
        EI.ei_configure_name(self.ctx, b"phonelink")
        if EI.ei_setup_backend_fd(self.ctx, fd) != 0:
            raise RuntimeError("couldn't set up the libei connection")
        self.fd = EI.ei_get_fd(self.ctx)

    def dispatch(self):
        EI.ei_dispatch(self.ctx)
        while event := EI.ei_get_event(self.ctx):
            try:
                kind = EI.ei_event_get_type(event)
                if kind == SEAT_ADDED:
                    EI.ei_seat_bind_capabilities(
                        P(EI.ei_event_get_seat(event)), INT(CAP_POINTER), INT(CAP_KEYBOARD),
                        INT(CAP_SCROLL), INT(CAP_BUTTON), P(None))
                self.on_event(kind, event)
            finally:
                EI.ei_event_unref(event)

    def close(self):
        if self.ctx:
            EI.ei_unref(self.ctx)
            self.ctx = None


class Keyboard:
    """xkbcommon state for the compositor's keymap: evdev key -> (keysym name, text)."""

    def __init__(self, device):
        self.state = None
        if XKB is None:
            return
        keymap = EI.ei_device_keyboard_get_keymap(device)
        if not keymap or EI.ei_keymap_get_type(keymap) != KEYMAP_XKB:
            return
        fd, size = EI.ei_keymap_get_fd(keymap), EI.ei_keymap_get_size(keymap)
        with mmap.mmap(os.dup(fd), size, mmap.MAP_PRIVATE, mmap.PROT_READ) as m:
            text = bytes(m[:size]).rstrip(b"\0")
        ctx = XKB.xkb_context_new(0)
        km = XKB.xkb_keymap_new_from_string(ctx, text, 1, 0)  # XKB_KEYMAP_FORMAT_TEXT_V1
        self.state = XKB.xkb_state_new(km) if km else None

    def key(self, code, pressed):
        """(keysym name, text it types) for an evdev key, before the state moves on."""
        if not self.state:
            return "", ""
        xkb_code = code + 8  # evdev to X11 keycodes
        name = ctypes.create_string_buffer(64)
        XKB.xkb_keysym_get_name(XKB.xkb_state_key_get_one_sym(self.state, xkb_code), name, 64)
        text = ctypes.create_string_buffer(16)
        XKB.xkb_state_key_get_utf8(self.state, xkb_code, text, 16)
        XKB.xkb_state_update_key(self.state, xkb_code, 1 if pressed else 0)
        return name.value.decode(errors="replace"), text.value.decode(errors="replace")
