"""The phone's camera roll, over KDE Connect's sftp plugin.

KDE Connect already exports the phone's storage over SFTP and mounts it with
sshfs; `mount()` here asks it to and waits. Nothing re-implements that
transport.

What shapes this module is that the result is a network filesystem on a phone,
over wifi -- about 2 MB a second here. A recent camera roll is most of a
gigabyte, so reading it to draw a grid of thumbnails would take minutes. Three
things keep that down:

  * The window only ever asks for the thumbnails it is about to show, a
    screenful at a time. Nothing here walks the roll fetching files.
  * A camera JPEG carries a thumbnail of itself in its EXIF block, near the
    start: `thumbnail_bytes` reads 128 KB and finds a 39 KB picture in it,
    instead of pulling 2 MB across.
  * A HEIC has no such block -- Samsung's have their `meta` box after the
    image data and a thumbnail coded in HEVC, reachable only by reading the
    tail and rebuilding a file around it -- so those are read whole. At about
    a third of a second each that is fine for the dozen tiles on screen, and
    it only ever happens once.

Whatever was read is decoded down to `THUMB_PX` and cached as a small PNG
under the phone's own size and mtime, so the grid is instant the second time,
the cache stays megabytes rather than gigabytes, and re-mounting at a
different path costs nothing.

Videos are never fetched for a picture: a frame would mean the whole file.
They still open, save and drag.
"""

import os
import re
import shutil
import struct
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402

from . import kdeconnect as kde  # noqa: E402

SFTP_IFACE = "org.kde.kdeconnect.device.sftp"

# Mounting asks the phone to start an SFTP server and sshfs to connect to it.
# Both involve the phone waking up, so this is far longer than a D-Bus call.
MOUNT_TIMEOUT = 30000

# Where Android keeps the camera roll. Vendors disagree -- Samsung puts
# screenshots under DCIM, stock Android under Pictures -- so look for all of
# them under every exported root and keep the ones that exist.
ROLL_DIRS = (
    "DCIM/Camera",
    "DCIM/Screenshots",
    "DCIM/Restored",
    "Pictures/Camera",
    "Pictures/Screenshots",
    "Pictures/Screenshot",
)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif", ".gif", ".bmp"}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".3gp", ".webm", ".avi", ".m4v"}

# Read this much of a file looking for its EXIF thumbnail. The block sits in
# the first APP1 marker, right after the start of the file; 128 KB is far more
# than any phone needs and still one round trip.
HEAD_BYTES = 128 * 1024

# A picture with no embedded thumbnail is read whole -- a HEIC, a screenshot.
# Phone photos run to a couple of megabytes; the cap is only here so that
# something enormous cannot hold a worker for a minute.
WHOLE_FILE_MAX = 16 * 1024 * 1024

# How big a cached thumbnail is. Comfortably over the tile size, so the grid
# stays sharp on a HiDPI screen without keeping the phone's full picture.
THUMB_PX = 480


# ------------------------------------------------------------------ the mount

def have_sshfs():
    """KDE Connect mounts with sshfs; without it the mount fails with a message
    about the helper, which is worth saying plainly before trying."""
    return shutil.which("sshfs") is not None


def _sftp(device_id):
    return f"{kde.DEVICES}/{device_id}/sftp"


def mounted(device_id):
    try:
        return bool(kde.call(_sftp(device_id), SFTP_IFACE, "isMounted").unpack()[0])
    except GLib.Error:
        return False


def mount_point(device_id):
    """Where the phone's storage is, or "" when it is not mounted."""
    try:
        return kde.call(_sftp(device_id), SFTP_IFACE, "mountPoint").unpack()[0]
    except GLib.Error:
        return ""


def mount(device_id, timeout=MOUNT_TIMEOUT):
    """Mount the phone's storage. Returns (mount point, error message).

    The phone has to wake up and start its SFTP server, so this is slow enough
    to want a spinner behind it -- never call it on the main loop's thread.
    """
    if not have_sshfs():
        return "", "sshfs isn't installed — sudo pacman -S sshfs"
    try:
        ok = kde.call(_sftp(device_id), SFTP_IFACE, "mountAndWait", None, timeout).unpack()[0]
    except GLib.Error as exc:
        return "", kde.friendly_error(exc.message)
    if not ok:
        return "", mount_error(device_id) or "the phone didn't accept the connection"
    point = mount_point(device_id)
    return point, "" if point else "KDE Connect reported no mount point"


def mount_error(device_id):
    try:
        return kde.call(_sftp(device_id), SFTP_IFACE, "getMountError").unpack()[0].strip()
    except GLib.Error:
        return ""


def unmount(device_id):
    try:
        kde.call(_sftp(device_id), SFTP_IFACE, "unmount")
        return True
    except GLib.Error:
        return False


def directories(device_id):
    """What the phone exports: {path: label}. Usually one entry, the storage root."""
    try:
        return dict(kde.call(_sftp(device_id), SFTP_IFACE, "getDirectories").unpack()[0])
    except GLib.Error:
        return {}


# ------------------------------------------------------------- the camera roll

class Shot:
    """One picture or video on the phone."""

    __slots__ = ("path", "name", "mtime", "size", "kind", "folder")

    def __init__(self, path, name, mtime, size, kind, folder):
        self.path, self.name, self.mtime = path, name, mtime
        self.size, self.kind, self.folder = size, kind, folder

    def __repr__(self):
        return f"<Shot {self.folder}/{self.name} {self.kind} {self.size}B>"


def kind_of(name):
    """"image", "video", or "" for anything the grid should not show.

    A deleted photo stays in the folder as `.trashed-<when>-<name>`, and one
    still being written is `.pending-...`; Android hides both by the leading
    dot. Showing them would put photos in the grid that the phone considers
    gone, and half-written ones that change under us.
    """
    if name.startswith("."):
        return ""
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    return ""


def roll_dirs(*roots):
    """The camera and screenshot folders that exist under these roots.

    The roots are what `directories()` reports, not the mount point: KDE
    Connect mounts the phone's whole filesystem and exports one folder inside
    it -- here `<mount>/storage/emulated/0`, labelled "Internal storage" --
    and the mount point itself lists as empty.
    """
    found = []
    for root in roots:
        if not root:
            continue
        for rel in ROLL_DIRS:
            path = os.path.join(root, rel)
            if os.path.isdir(path):
                found.append(path)
    return found


def in_view(y, height, scroll, page, ahead):
    """Is a tile at this position worth fetching yet?

    The arithmetic behind the grid's one rule -- fetch a screenful, not the
    roll -- kept here so it can be tested without a window.

    `page` or `height` of zero means GTK has not laid the grid out, and every
    tile then measures as nothing at the top. Treating that as visible is what
    made the window pull two hundred photos at once when waking the phone took
    long enough for the tiles to exist before the grid had a size.
    """
    if page <= 0 or height <= 0:
        return False
    return y + height >= scroll - ahead and y <= scroll + page + ahead


def scan(dirs, limit=200):
    """The newest `limit` pictures and videos across these folders, newest first.

    Only the directory listing is read -- never a file -- so this stays quick
    on a phone with thousands of photos in it.
    """
    shots = []
    for folder in dirs:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue  # unmounted under us, or a folder we cannot read
        label = os.path.basename(folder.rstrip("/"))
        for entry in entries:
            kind = kind_of(entry.name)
            if not kind:
                continue
            try:
                if not entry.is_file():
                    continue
                stat = entry.stat()
            except OSError:
                continue  # deleted on the phone between the listing and the stat
            shots.append(Shot(entry.path, entry.name, stat.st_mtime, stat.st_size, kind, label))
    shots.sort(key=lambda s: s.mtime, reverse=True)
    return shots[:limit]


# ------------------------------------------------------------- EXIF thumbnails

def _tiff_thumbnail(block):
    """(thumbnail JPEG, orientation) out of an EXIF block, or (b"", 1).

    The block is a TIFF file: a header saying which way round its numbers are,
    then IFD0 describing the picture and IFD1 describing its thumbnail. Tags
    0x0201 and 0x0202 in IFD1 are the thumbnail's offset and length, counted
    from the start of the TIFF header.

    Orientation comes from IFD0, because the thumbnail carries none of its own:
    a phone records a portrait photo as landscape pixels plus "turn this", and
    taking the thumbnail without the tag lays every portrait shot on its side.
    """
    if len(block) < 8 or block[:2] not in (b"II", b"MM"):
        return b"", 1
    endian = "<" if block[:2] == b"II" else ">"
    orient = 1
    try:
        magic, first = struct.unpack_from(endian + "HI", block, 2)
        if magic != 42:
            return b"", 1
        count = struct.unpack_from(endian + "H", block, first)[0]
        for i in range(count):
            tag, _type, _n, value = struct.unpack_from(endian + "HHII", block, first + 2 + i * 12)
            if tag == 0x0112:
                # A SHORT sits in the top half of its 4-byte slot when the
                # file is big-endian; unpack it as one rather than guessing.
                orient = struct.unpack_from(endian + "H", block, first + 2 + i * 12 + 8)[0]
        # The pointer to IFD1, where the thumbnail is described, follows IFD0.
        second = struct.unpack_from(endian + "I", block, first + 2 + count * 12)[0]
        if not second or second >= len(block):
            return b"", orient
        offset = length = 0
        count = struct.unpack_from(endian + "H", block, second)[0]
        for i in range(count):
            tag, _type, _n, value = struct.unpack_from(endian + "HHII", block, second + 2 + i * 12)
            if tag == 0x0201:
                offset = value
            elif tag == 0x0202:
                length = value
    except struct.error:
        return b"", orient
    if not offset or not length or offset + length > len(block):
        return b"", orient
    thumb = block[offset:offset + length]
    return (thumb if thumb[:2] == b"\xff\xd8" else b""), orient


def embedded_thumbnail(head):
    """(thumbnail, orientation) out of the head of a JPEG; (b"", 1) if none.

    Walks the marker chain rather than searching for bytes: a picture whose
    pixels happen to contain "Exif\\0\\0" would otherwise send us off into the
    image data.
    """
    if head[:2] != b"\xff\xd8":
        return b"", 1
    at = 2
    while at + 4 <= len(head):
        if head[at] != 0xFF:
            return b"", 1
        marker = head[at + 1]
        # Start of scan: the compressed image follows, and no more headers.
        if marker in (0xDA, 0xD9):
            return b"", 1
        size = struct.unpack_from(">H", head, at + 2)[0]
        if size < 2:
            return b"", 1
        if marker == 0xE1 and head[at + 4:at + 10] == b"Exif\x00\x00":
            return _tiff_thumbnail(head[at + 10:at + 2 + size])
        at += 2 + size
    return b"", 1


def read_head(path, count=HEAD_BYTES):
    try:
        with open(path, "rb") as handle:
            return handle.read(count)
    except OSError:
        return b""


def thumbnail_bytes(shot):
    """(image data, orientation) for a shot: as little of it as will do."""
    if shot.kind != "image":
        return b"", 1  # a video frame would mean downloading the video
    head = read_head(shot.path)
    if not head:
        return b"", 1
    thumb, orient = embedded_thumbnail(head)
    if thumb:
        return thumb, orient
    # No EXIF thumbnail: a HEIC, a screenshot, a WebP. Read it whole; the
    # decoder below will turn its own orientation tag the right way up.
    if shot.size <= len(head):
        return head, 1
    if shot.size <= WHOLE_FILE_MAX:
        return read_head(shot.path, shot.size), 1
    return b"", 1


# --------------------------------------------------------------- thumb cache

def cache_dir():
    base = GLib.get_user_cache_dir() or str(Path.home() / ".cache")
    path = Path(base) / "phonelink" / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_name(shot):
    """A name that changes when the picture does, and is safe on any filesystem.

    The phone's own name plus its size and mtime: re-mounting at a different
    path keeps the cache, editing a photo on the phone misses it.
    """
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", f"{shot.folder}_{shot.name}")[-96:]
    return f"{stem}.{shot.size}.{int(shot.mtime)}.thumb"


def cached(shot):
    path = cache_dir() / cache_name(shot)
    return str(path) if path.is_file() and path.stat().st_size else ""


def cache(shot, data):
    """Write a thumbnail, and hand back where it landed."""
    path = cache_dir() / cache_name(shot)
    tmp = path.with_suffix(".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)  # never leave a half-written thumbnail behind
        return str(path)
    except OSError:
        return ""


# EXIF's eight orientations as what to do to the pixels: turn this far
# counter-clockwise, and mirror it or not.
TURNS = {1: (0, False), 2: (0, True), 3: (180, False), 4: (180, True),
         5: (270, True), 6: (270, False), 7: (90, True), 8: (90, False)}


def upright(pixbuf, orientation):
    """Turn a picture the way its EXIF tag says it should be seen."""
    angle, mirror = TURNS.get(orientation, (0, False))
    if angle:
        pixbuf = pixbuf.rotate_simple(angle) or pixbuf
    if mirror:
        pixbuf = pixbuf.flip(True) or pixbuf
    return pixbuf


def shrink(data, orientation=1, size=THUMB_PX):
    """Decode image bytes straight down to thumbnail size, as PNG bytes.

    Scaling happens inside the decoder, so a twelve-megapixel HEIC never
    becomes a forty-megabyte pixbuf on the way to a tile.
    """
    def fit(loader, width, height):
        # Scale while decoding, and only ever down: blowing a 40-pixel icon up
        # to tile size would look worse than leaving it small.
        longest = max(width, height)
        if longest > size:
            loader.set_size(max(1, round(width * size / longest)),
                            max(1, round(height * size / longest)))

    loader = GdkPixbuf.PixbufLoader()
    loader.connect("size-prepared", fit)
    try:
        loader.write(data)
        loader.close()
        pixbuf = loader.get_pixbuf()
    except GLib.Error:
        return b""  # truncated, or a format with no loader installed
    if pixbuf is None:
        return b""
    # A whole file carries its own tag and the loader has already read it; an
    # EXIF thumbnail carries none, so its parent's tag is applied here.
    pixbuf = (pixbuf.apply_embedded_orientation() or pixbuf) if orientation == 1 \
        else upright(pixbuf, orientation)
    try:
        ok, out = pixbuf.save_to_bufferv("png", [], [])
    except GLib.Error:
        return b""
    return bytes(out) if ok else b""


def thumbnail(shot):
    """A small image file for a shot: from the cache, else made and cached.

    Slow -- it reads from the phone -- so call it on a worker, never on the
    main loop.
    """
    if hit := cached(shot):
        return hit
    data, orientation = thumbnail_bytes(shot)
    if not data:
        return ""
    small = shrink(data, orientation)
    return cache(shot, small) if small else ""


# ------------------------------------------------------------------- saving

def save_dir():
    pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    folder = Path(pictures or Path.home() / "Pictures") / "Phone"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save(shot, folder=None):
    """Copy a shot off the phone, never over something already there."""
    folder = folder or save_dir()
    stem, ext = os.path.splitext(shot.name)
    dest, count = folder / shot.name, 1
    while dest.exists():
        count += 1
        dest = folder / f"{stem} ({count}){ext}"
    shutil.copy2(shot.path, dest)
    return dest


def open_shot(shot):
    """Hand a picture or video to whatever opens it on the desktop."""
    Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(shot.path).get_uri(), None)
