"""The small GTK 4 / libadwaita pieces every phonelink window draws.

An avatar that falls back to initials, a themed label, emptying a box, the
send icon whichever icon theme is installed, and turning a phone's picture --
a thumbnail out of a message, or a file on disk -- into something drawable.
"""

import base64
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402


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


def texture_from_b64(data):
    try:
        loader = GdkPixbuf.PixbufLoader()
        loader.write(base64.b64decode(data))
        loader.close()
        return Gdk.Texture.new_for_pixbuf(loader.get_pixbuf())
    except (GLib.Error, ValueError, TypeError):
        return None


def texture_from_file(path, max_px=720):
    """(texture, width, height), upright and scaled down; HEIC/AVIF/WebP included."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, max_px, max_px, True)
    except GLib.Error:
        return None, 0, 0
    # Phone cameras record rotation in EXIF rather than rotating the pixels.
    pixbuf = pixbuf.apply_embedded_orientation() or pixbuf
    return Gdk.Texture.new_for_pixbuf(pixbuf), pixbuf.get_width(), pixbuf.get_height()
