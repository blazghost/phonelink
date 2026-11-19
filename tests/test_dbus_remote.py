"""The touchpad and keys, against the fake KDE Connect.

The fake prints every call it receives, so each test reads back exactly what
the phone would have been told -- and nothing here can move a real pointer.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ON_TEST_BUS = os.environ.get("PHONELINK_TEST_BUS") == "1"
PHONE = "bbbb1111bbbb1111bbbb1111bbbb1111"


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class Remote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = subprocess.Popen([sys.executable, str(HERE / "fake_kdeconnect.py")],
                                    stdout=subprocess.PIPE, text=True)
        line = cls.fake.stdout.readline()
        if "ready" not in line:
            cls.fake.kill()
            raise AssertionError(f"fake kdeconnect did not start: {line.strip()}")
        from phonelink import remote
        cls.remote = remote

    @classmethod
    def tearDownClass(cls):
        cls.fake.terminate()
        cls.fake.wait(timeout=5)
        cls.fake.stdout.close()

    def heard(self):
        return self.fake.stdout.readline().strip()

    def test_move(self):
        self.remote.move(PHONE, 12, -3)
        self.assertEqual(self.heard(), "move 12 -3")

    def test_clicks(self):
        self.remote.click(PHONE, "left")
        self.assertEqual(self.heard(), "command singleclick=True")
        self.remote.click(PHONE, "right")
        self.assertEqual(self.heard(), "command rightclick=True")
        self.remote.click(PHONE, "middle")
        self.assertEqual(self.heard(), "command middleclick=True")

    def test_scroll(self):
        self.remote.scroll(PHONE, 0, 2)
        self.assertEqual(self.heard(), "command dx=0.0 dy=2.0 scroll=True")

    def test_keys(self):
        self.remote.key(PHONE, *self.remote.key_args("a", "a"))
        self.assertEqual(self.heard(), "key 'a' 0 000")
        self.remote.key(PHONE, *self.remote.key_args("BackSpace", "\b"))
        self.assertEqual(self.heard(), "key '' 1 000")
        self.remote.key(PHONE, *self.remote.key_args("v", "v", ctrl=True))
        self.assertEqual(self.heard(), "key 'v' 0 010")

    def test_keyboard_state(self):
        self.assertTrue(self.remote.keyboard_active(PHONE))


if __name__ == "__main__":
    unittest.main()
