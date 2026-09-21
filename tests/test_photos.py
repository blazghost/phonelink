"""The camera roll: what counts as a picture, which folders to look in, the
newest-first scan, the EXIF thumbnail reader and the thumbnail cache.

The JPEGs here are built byte by byte rather than with an image library, so the
marker walk and the TIFF parse are tested against real structure and the suite
needs nothing installed.
"""

import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

from phonelink import photos  # noqa: E402

THUMB = b"\xff\xd8\xff\xdbTHUMBNAIL-DATA\xff\xd9"


def png(width, height):
    """A real, decodable PNG -- drawn by the same library that reads it, so the
    suite needs no image files and no image package."""
    buf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    buf.fill(0x3366FFFF)
    ok, data = buf.save_to_bufferv("png", [], [])
    assert ok
    return bytes(data)


def size_of(data):
    """(width, height) of encoded image data."""
    loader = GdkPixbuf.PixbufLoader()
    loader.write(data)
    loader.close()
    buf = loader.get_pixbuf()
    return buf.get_width(), buf.get_height()


def exif_jpeg(thumb=THUMB, endian="<", orientation=1,
              tail=b"\xff\xda" + b"pixels" * 40):
    """A JPEG whose APP1 block carries `thumb` as its EXIF thumbnail."""
    mark = b"II" if endian == "<" else b"MM"
    # IFD0: the orientation tag, then the offset of IFD1.
    ifd0 = struct.pack(endian + "H", 1)
    # A SHORT sits in the first two bytes of its four-byte value slot.
    slot = struct.pack(endian + "H", orientation) + b"\x00\x00"
    ifd0 += struct.pack(endian + "HHI", 0x0112, 3, 1) + slot
    ifd1_at = 8 + len(ifd0) + 4
    ifd0 += struct.pack(endian + "I", ifd1_at)
    # IFD1: where the thumbnail is and how long it is.
    entries = 2
    thumb_at = ifd1_at + 2 + entries * 12 + 4
    ifd1 = (struct.pack(endian + "H", entries)
            + struct.pack(endian + "HHII", 0x0201, 4, 1, thumb_at)
            + struct.pack(endian + "HHII", 0x0202, 4, 1, len(thumb))
            + struct.pack(endian + "I", 0))
    tiff = mark + struct.pack(endian + "HI", 42, 8) + ifd0 + ifd1 + thumb
    app1 = b"Exif\x00\x00" + tiff
    return (b"\xff\xd8"
            + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
            + tail)


class Kinds(unittest.TestCase):
    def test_pictures_and_videos_are_told_apart(self):
        self.assertEqual("image", photos.kind_of("IMG_2001.JPG"))
        self.assertEqual("image", photos.kind_of("shot.heic"))
        self.assertEqual("video", photos.kind_of("VID_0007.mp4"))

    def test_everything_else_is_not_a_shot(self):
        for name in ("notes.txt", ".thumbnails", "IMG_2001", "song.mp3"):
            self.assertEqual("", photos.kind_of(name))

    def test_deleted_and_half_written_photos_are_hidden(self):
        # Android keeps a deleted photo in the folder under a dotted name, and
        # a photo still being saved under another. Neither belongs in the grid.
        self.assertEqual("", photos.kind_of(".trashed-1758000000-IMG_1.jpg"))
        self.assertEqual("", photos.kind_of(".pending-1758000000-IMG_2.jpg"))


class Folders(unittest.TestCase):
    def test_only_the_roll_folders_that_exist_are_returned(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "DCIM/Camera").mkdir(parents=True)
            (Path(root) / "Pictures/Screenshots").mkdir(parents=True)
            (Path(root) / "Documents").mkdir(parents=True)
            found = photos.roll_dirs(root)
        self.assertEqual({"Camera", "Screenshots"}, {os.path.basename(p) for p in found})

    def test_several_roots_are_searched(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            (Path(a) / "DCIM/Camera").mkdir(parents=True)
            (Path(b) / "DCIM/Camera").mkdir(parents=True)
            self.assertEqual(2, len(photos.roll_dirs(a, b)))

    def test_a_missing_root_is_not_an_error(self):
        self.assertEqual([], photos.roll_dirs("/nowhere/at/all", "", None))


class Scan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.camera = Path(self.tmp.name) / "DCIM/Camera"
        self.camera.mkdir(parents=True)

    def shot(self, name, when, data=b"x"):
        path = self.camera / name
        path.write_bytes(data)
        os.utime(path, (when, when))
        return path

    def test_newest_first(self):
        now = time.time()
        self.shot("old.jpg", now - 900)
        self.shot("new.jpg", now)
        self.shot("middle.jpg", now - 60)
        found = photos.scan([str(self.camera)])
        self.assertEqual(["new.jpg", "middle.jpg", "old.jpg"], [s.name for s in found])

    def test_the_limit_keeps_the_newest(self):
        now = time.time()
        for i in range(10):
            self.shot(f"p{i}.jpg", now - i)
        found = photos.scan([str(self.camera)], limit=3)
        self.assertEqual(["p0.jpg", "p1.jpg", "p2.jpg"], [s.name for s in found])

    def test_other_files_are_left_out(self):
        self.shot("keep.jpg", time.time())
        self.shot("notes.txt", time.time())
        (self.camera / ".thumbnails").mkdir()
        found = photos.scan([str(self.camera)])
        self.assertEqual(["keep.jpg"], [s.name for s in found])

    def test_size_and_folder_come_through(self):
        self.shot("a.jpg", time.time(), data=b"12345")
        shot = photos.scan([str(self.camera)])[0]
        self.assertEqual(5, shot.size)
        self.assertEqual("Camera", shot.folder)
        self.assertEqual("image", shot.kind)

    def test_a_folder_that_is_gone_is_skipped(self):
        self.shot("a.jpg", time.time())
        found = photos.scan([str(self.camera), "/gone/missing"])
        self.assertEqual(1, len(found))


class InView(unittest.TestCase):
    """Which tiles the grid fetches. Getting this wrong once meant pulling the
    whole camera roll instead of a screenful."""

    PAGE, AHEAD, TILE = 800, 500, 170

    def near(self, y, scroll=0):
        return photos.in_view(y, self.TILE, scroll, self.PAGE, self.AHEAD)

    def test_a_tile_on_screen(self):
        self.assertTrue(self.near(0))
        self.assertTrue(self.near(400))

    def test_a_tile_just_below_is_fetched_ahead(self):
        self.assertTrue(self.near(self.PAGE + 100))

    def test_a_tile_far_below_is_not(self):
        self.assertFalse(self.near(self.PAGE + self.AHEAD + 1))

    def test_a_tile_scrolled_far_above_is_not(self):
        self.assertFalse(self.near(0, scroll=self.AHEAD + self.TILE + 1))

    def test_a_tile_partly_above_still_counts(self):
        self.assertTrue(self.near(0, scroll=self.AHEAD + self.TILE - 1))

    def test_before_the_grid_is_laid_out_nothing_is_visible(self):
        # Every tile measures as nothing at the top until GTK lays the grid
        # out; calling that visible fetched the entire roll at once.
        self.assertFalse(photos.in_view(0, 0, 0, 0, self.AHEAD))
        for y in (0, 1000, 12000):
            self.assertFalse(photos.in_view(y, self.TILE, 0, 0, self.AHEAD))

    def test_a_tile_with_no_height_is_not_visible(self):
        self.assertFalse(photos.in_view(0, 0, 0, self.PAGE, self.AHEAD))


class Exif(unittest.TestCase):
    def test_the_thumbnail_is_pulled_out(self):
        self.assertEqual((THUMB, 1), photos.embedded_thumbnail(exif_jpeg()))

    def test_big_endian_too(self):
        self.assertEqual((THUMB, 1), photos.embedded_thumbnail(exif_jpeg(endian=">")))

    def test_a_jpeg_without_exif_gives_nothing(self):
        plain = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"\x00\x00" + b"\xff\xda"
        self.assertEqual((b"", 1), photos.embedded_thumbnail(plain))

    def test_a_png_is_not_walked(self):
        self.assertEqual((b"", 1), photos.embedded_thumbnail(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64))

    def test_the_marker_walk_stops_at_the_image_data(self):
        # "Exif\0\0" among the pixels must not be mistaken for a header.
        decoy = b"\xff\xd8\xff\xda" + b"Exif\x00\x00II*\x00" + b"\x00" * 200
        self.assertEqual((b"", 1), photos.embedded_thumbnail(decoy))

    def test_truncated_input_is_survived(self):
        whole = exif_jpeg()
        for cut in (2, 8, 20, 40, len(whole) - 5):
            self.assertIsInstance(photos.embedded_thumbnail(whole[:cut])[0], bytes)

    def test_a_thumbnail_that_is_not_a_jpeg_is_refused(self):
        self.assertEqual(b"", photos.embedded_thumbnail(exif_jpeg(thumb=b"not a jpeg at all"))[0])


class Thumbnails(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache"
        self.addCleanup(setattr, photos, "cache_dir", photos.cache_dir)
        photos.cache_dir = lambda: (self.cache.mkdir(parents=True, exist_ok=True), self.cache)[1]

    def make(self, name, data):
        path = Path(self.tmp.name) / name
        path.write_bytes(data)
        stat = path.stat()
        return photos.Shot(str(path), name, stat.st_mtime, stat.st_size, "image", "Camera")

    def test_a_camera_photo_gives_its_embedded_thumbnail(self):
        shot = self.make("IMG.jpg", exif_jpeg() + b"\x00" * 5000)
        self.assertEqual((THUMB, 1), photos.thumbnail_bytes(shot))

    def test_the_parents_orientation_comes_with_the_thumbnail(self):
        shot = self.make("IMG.jpg", exif_jpeg(orientation=6))
        self.assertEqual((THUMB, 6), photos.thumbnail_bytes(shot))

    def test_a_small_screenshot_is_read_whole(self):
        data = b"\x89PNG\r\n\x1a\n" + b"pixels" * 100
        shot = self.make("Screenshot.png", data)
        self.assertEqual((data, 1), photos.thumbnail_bytes(shot))

    def test_a_big_file_without_a_thumbnail_is_left_alone(self):
        shot = self.make("huge.png", b"\x89PNG\r\n\x1a\n")
        shot.size = photos.WHOLE_FILE_MAX + 1  # pretend, rather than write 16 MB
        self.assertEqual((b"", 1), photos.thumbnail_bytes(shot))

    def test_a_video_is_never_downloaded_for_a_thumbnail(self):
        shot = self.make("VID.mp4", b"\x00" * 100)
        shot.kind = "video"
        self.assertEqual((b"", 1), photos.thumbnail_bytes(shot))

    def test_the_cache_is_written_once_and_reused(self):
        shot = self.make("IMG.png", png(40, 40))
        self.assertEqual("", photos.cached(shot))
        first = photos.thumbnail(shot)
        self.assertTrue(first, "no thumbnail was made")
        self.assertEqual(first, photos.cached(shot))
        # Reading it again must not go back to the phone.
        self.addCleanup(setattr, photos, "thumbnail_bytes", photos.thumbnail_bytes)
        photos.thumbnail_bytes = lambda _s: self.fail("went back to the file")
        self.assertEqual(first, photos.thumbnail(shot))

    def test_the_cached_thumbnail_is_small(self):
        shot = self.make("big.png", png(2000, 1500))
        small = Path(photos.thumbnail(shot))
        self.assertLess(small.stat().st_size, shot.size)
        width, height = size_of(small.read_bytes())
        self.assertEqual(photos.THUMB_PX, max(width, height))

    def test_a_changed_picture_misses_the_cache(self):
        shot = self.make("IMG.png", png(40, 40))
        photos.thumbnail(shot)
        shot.size += 1
        self.assertEqual("", photos.cached(shot))

    def test_the_cache_name_survives_an_awkward_filename(self):
        shot = photos.Shot("/x/a b:c/'quote'.jpg", "'quote'.jpg", 1.0, 2, "image", "a b:c")
        name = photos.cache_name(shot)
        self.assertNotIn("/", name)
        self.assertNotIn("'", name)
        self.assertTrue(name.endswith(".thumb"))

    def test_no_thumbnail_is_not_cached_as_an_empty_file(self):
        shot = self.make("VID.mp4", b"\x00" * 10)
        shot.kind = "video"
        self.assertEqual("", photos.thumbnail(shot))
        self.assertEqual([], list(self.cache.glob("*.thumb")) if self.cache.exists() else [])


class Orientation(unittest.TestCase):
    """A portrait photo is landscape pixels plus a tag saying to turn it, so
    ignoring the tag lays every portrait shot on its side."""

    def test_a_quarter_turn_swaps_the_sides(self):
        wide = png(40, 20)
        self.assertEqual((20, 40), size_of(photos.shrink(wide, orientation=6)))
        self.assertEqual((20, 40), size_of(photos.shrink(wide, orientation=8)))

    def test_a_half_turn_keeps_the_shape(self):
        self.assertEqual((40, 20), size_of(photos.shrink(png(40, 20), orientation=3)))

    def test_the_usual_tag_changes_nothing(self):
        self.assertEqual((40, 20), size_of(photos.shrink(png(40, 20), orientation=1)))

    def test_an_unknown_tag_is_left_alone(self):
        self.assertEqual((40, 20), size_of(photos.shrink(png(40, 20), orientation=99)))

    def test_shrinking_fits_the_long_side(self):
        self.assertEqual((photos.THUMB_PX, photos.THUMB_PX // 2),
                         size_of(photos.shrink(png(1000, 500))))

    def test_rubbish_does_not_raise(self):
        self.assertEqual(b"", photos.shrink(b"not an image at all"))
        self.assertEqual(b"", photos.shrink(b""))


class Saving(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_shot_is_copied_out(self):
        src = Path(self.tmp.name) / "IMG.jpg"
        src.write_bytes(b"picture")
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        shot = photos.Shot(str(src), "IMG.jpg", 1.0, 7, "image", "Camera")
        dest = photos.save(shot, out)
        self.assertEqual(b"picture", dest.read_bytes())

    def test_a_second_copy_does_not_overwrite_the_first(self):
        src = Path(self.tmp.name) / "IMG.jpg"
        src.write_bytes(b"picture")
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        shot = photos.Shot(str(src), "IMG.jpg", 1.0, 7, "image", "Camera")
        first, second = photos.save(shot, out), photos.save(shot, out)
        self.assertNotEqual(first, second)
        self.assertEqual("IMG (2).jpg", second.name)
        self.assertTrue(first.exists())


if __name__ == "__main__":
    unittest.main()
