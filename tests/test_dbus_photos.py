"""Mounting the phone's storage and reading its camera roll.

Against the fake KDE Connect, whose sftp plugin hands back a directory this
test has filled: the D-Bus conversation is pretend, the filesystem underneath
is real, so the scan, the thumbnails and the cache all run for real.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
sys.path.insert(0, str(HERE))

ON_TEST_BUS = os.environ.get("PHONELINK_TEST_BUS") == "1"

from test_photos import exif_jpeg, png  # noqa: E402


def camera_roll(root):
    """A phone's storage as the sftp plugin exports it: DCIM under the folder
    inside the mount, not under the mount itself."""
    inside = Path(root) / "storage/emulated/0"
    camera = inside / "DCIM/Camera"
    shots = inside / "DCIM/Screenshots"
    other = inside / "Documents"
    for folder in (camera, shots, other):
        folder.mkdir(parents=True)

    now = time.time()
    made = []
    for i in range(3):
        path = camera / f"IMG_{i}.jpg"
        path.write_bytes(exif_jpeg() + b"\x00" * 200)
        os.utime(path, (now - i, now - i))
        made.append(path)
    shot = shots / "Screenshot_1.png"
    shot.write_bytes(png(60, 120))
    os.utime(shot, (now - 10, now - 10))
    made.append(shot)
    video = camera / "VID_1.mp4"
    video.write_bytes(b"\x00" * 64)
    os.utime(video, (now - 20, now - 20))
    made.append(video)
    # Things that are not the camera roll, and must not show up.
    (other / "notes.txt").write_text("not a photo")
    (camera / ".trashed-1758000000-IMG_9.jpg").write_bytes(png(10, 10))
    return made


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class Storage(unittest.TestCase):
    fails = False

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="phonelink-roll-")
        camera_roll(cls.tmp)
        env = dict(os.environ, PHONELINK_FAKE_MOUNT=cls.tmp)
        if cls.fails:
            env["PHONELINK_FAKE_MOUNT_FAILS"] = "1"
        cls.fake = subprocess.Popen([sys.executable, str(HERE / "fake_kdeconnect.py")],
                                    stdout=subprocess.PIPE, text=True, env=env)
        if "ready" not in cls.fake.stdout.readline():
            cls.fake.kill()
            raise AssertionError("fake kdeconnect did not start")

    @classmethod
    def tearDownClass(cls):
        cls.fake.terminate()
        cls.fake.wait(timeout=5)
        cls.fake.stdout.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from phonelink import kdeconnect as kde, photos
        self.kde, self.photos = kde, photos
        self.device = kde.pick_device(kde.devices())["id"]
        cache = Path(tempfile.mkdtemp(prefix="phonelink-thumbs-"))
        self.addCleanup(shutil.rmtree, cache, True)
        self.addCleanup(setattr, photos, "cache_dir", photos.cache_dir)
        photos.cache_dir = lambda: cache


class Mounting(Storage):
    def test_it_starts_unmounted(self):
        self.assertFalse(self.photos.mounted(self.device))

    def test_mounting_gives_the_mount_point(self):
        point, err = self.photos.mount(self.device)
        self.assertEqual("", err)
        self.assertEqual(self.tmp, point)
        self.assertTrue(self.photos.mounted(self.device))

    def test_the_exported_folder_is_inside_the_mount(self):
        self.photos.mount(self.device)
        exported = self.photos.directories(self.device)
        self.assertEqual([f"{self.tmp}/storage/emulated/0"], list(exported))

    def test_unmounting(self):
        self.photos.mount(self.device)
        self.assertTrue(self.photos.unmount(self.device))
        self.assertFalse(self.photos.mounted(self.device))

    def test_a_device_with_no_sftp_plugin_does_not_raise(self):
        # The fake's desktop has no sftp object at all.
        desktop = next(d["id"] for d in self.kde.devices() if d["type"] == "desktop")
        self.assertFalse(self.photos.mounted(desktop))
        self.assertEqual("", self.photos.mount_point(desktop))
        self.assertEqual({}, self.photos.directories(desktop))


class Scanning(Storage):
    def roll(self):
        self.photos.mount(self.device)
        roots = self.photos.directories(self.device)
        return self.photos.scan(self.photos.roll_dirs(*roots))

    def test_the_roll_folders_are_found_under_the_exported_folder(self):
        self.photos.mount(self.device)
        found = self.photos.roll_dirs(*self.photos.directories(self.device))
        self.assertEqual({"Camera", "Screenshots"},
                         {os.path.basename(p) for p in found})

    def test_every_picture_and_video_is_listed_newest_first(self):
        names = [s.name for s in self.roll()]
        self.assertEqual(["IMG_0.jpg", "IMG_1.jpg", "IMG_2.jpg",
                          "Screenshot_1.png", "VID_1.mp4"], names)

    def test_documents_are_not_part_of_the_roll(self):
        self.assertNotIn("notes.txt", [s.name for s in self.roll()])

    def test_a_photo_deleted_on_the_phone_is_not_shown(self):
        # It is still sitting in DCIM/Camera under a dotted name.
        names = [s.name for s in self.roll()]
        self.assertNotIn(".trashed-1758000000-IMG_9.jpg", names)
        self.assertTrue(any(n.startswith("IMG_") for n in names))

    def test_the_video_is_marked_as_one(self):
        kinds = {s.name: s.kind for s in self.roll()}
        self.assertEqual("video", kinds["VID_1.mp4"])
        self.assertEqual("image", kinds["IMG_0.jpg"])

    def test_which_folder_each_came_from(self):
        folders = {s.name: s.folder for s in self.roll()}
        self.assertEqual("Camera", folders["IMG_0.jpg"])
        self.assertEqual("Screenshots", folders["Screenshot_1.png"])


class Thumbnails(Storage):
    def roll(self):
        self.photos.mount(self.device)
        return self.photos.scan(self.photos.roll_dirs(*self.photos.directories(self.device)))

    def test_a_photo_gets_a_thumbnail_from_its_exif_block(self):
        shot = next(s for s in self.roll() if s.name == "IMG_0.jpg")
        # The hand-built EXIF thumbnail is not a decodable picture, so what
        # matters here is that the reader found it and read only the head.
        data, orientation = self.photos.thumbnail_bytes(shot)
        self.assertEqual(1, orientation)
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertLess(len(data), shot.size)

    def test_a_screenshot_is_thumbnailed_and_cached(self):
        shot = next(s for s in self.roll() if s.name == "Screenshot_1.png")
        made = self.photos.thumbnail(shot)
        self.assertTrue(made, "no thumbnail for the screenshot")
        self.assertEqual(made, self.photos.cached(shot))

    def test_a_video_is_never_fetched(self):
        shot = next(s for s in self.roll() if s.kind == "video")
        self.assertEqual("", self.photos.thumbnail(shot))

    def test_saving_copies_off_the_phone(self):
        shot = next(s for s in self.roll() if s.name == "Screenshot_1.png")
        out = Path(tempfile.mkdtemp(prefix="phonelink-save-"))
        self.addCleanup(shutil.rmtree, out, True)
        dest = self.photos.save(shot, out)
        self.assertEqual(Path(shot.path).read_bytes(), dest.read_bytes())


class WhenTheMountFails(Storage):
    fails = True

    def test_the_error_is_reported_not_raised(self):
        point, err = self.photos.mount(self.device)
        self.assertEqual("", point)
        self.assertIn("refused", err)

    def test_nothing_is_mounted_afterwards(self):
        self.photos.mount(self.device)
        self.assertFalse(self.photos.mounted(self.device))
        self.assertEqual([], self.photos.roll_dirs(*self.photos.directories(self.device)))


del Storage  # a base class, not a test case in its own right


if __name__ == "__main__":
    unittest.main()
