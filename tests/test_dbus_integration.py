"""The D-Bus side, against a fake KDE Connect rather than the real phone.

Skipped unless it is running on the private bus tests/run.sh sets up: on the
real session bus these would read a real phone, and a reply would go to a real
contact.
"""

import os
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

ON_TEST_BUS = os.environ.get("PHONELINK_TEST_BUS") == "1"


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class FakePhone(unittest.TestCase):
    """One fake daemon for the class; each test reads it afresh."""

    @classmethod
    def setUpClass(cls):
        cls.fake = subprocess.Popen([sys.executable, str(HERE / "fake_kdeconnect.py")],
                                    stdout=subprocess.PIPE, text=True)
        line = cls.fake.stdout.readline()
        if "ready" not in line:
            cls.fake.kill()
            raise AssertionError(f"fake kdeconnect did not start: {line.strip()}")
        from phonelink import kdeconnect as kde
        cls.kde = kde
        if kde.BUS is None:
            raise AssertionError("no session bus")

    @classmethod
    def tearDownClass(cls):
        cls.fake.terminate()
        cls.fake.wait(timeout=5)
        cls.fake.stdout.close()

    # -- devices

    def test_both_devices_are_listed(self):
        names = [d["name"] for d in self.kde.devices()]
        self.assertEqual(names, ["Roci", "Test Phone"])

    def test_types_come_through(self):
        types = {d["name"]: d["type"] for d in self.kde.devices()}
        self.assertEqual(types, {"Roci": "desktop", "Test Phone": "phone"})

    def test_the_phone_is_chosen_although_the_desktop_is_first(self):
        self.assertEqual(self.kde.phone()["name"], "Test Phone")

    def test_the_desktop_can_be_asked_for_by_name(self):
        self.assertEqual(self.kde.phone("Roci")["name"], "Roci")

    # -- notifications

    def test_notifications_newest_first(self):
        self.assertEqual([n["id"] for n in self.kde.notifications()], [3, 2, 1])

    def test_only_the_repliable_ones_when_asked(self):
        apps = [n["app"] for n in self.kde.notifications(repliable_only=True)]
        self.assertEqual(apps, ["Messages", "Messenger"])

    def test_a_group_chat_is_parsed(self):
        note = next(n for n in self.kde.notifications() if n["app"] == "Messenger")
        self.assertEqual([m["sender"] for m in note["thread"]],
                         ["Naomi Nagata", "Alex Kamal"])

    def test_the_package_is_read(self):
        note = next(n for n in self.kde.notifications() if n["app"] == "Messenger")
        self.assertEqual(note["package"], "com.facebook.orca")

    def test_silent_is_carried(self):
        silent = {n["app"]: n["silent"] for n in self.kde.notifications()}
        self.assertEqual(silent, {"Messages": True, "Messenger": False, "Reddit": False})

    def test_a_notification_that_is_not_there(self):
        gone = f"{self.kde.DEVICES}/bbbb1111bbbb1111bbbb1111bbbb1111/notifications/99"
        self.assertIsNone(self.kde.read_note(gone))

    def test_a_path_that_is_not_a_path(self):
        # A signal can name anything; GLib returns None rather than raising.
        self.assertIsNone(self.kde.read_note("spoofed-0"))

    # -- replying

    def test_a_reply_reaches_the_daemon(self):
        note = next(n for n in self.kde.notifications() if n["app"] == "Messenger")
        self.kde.send_reply(note["path"], "on my way")
        # The fake prints every reply it is handed.
        self.assertIn("on my way", self.fake.stdout.readline())

    # -- the command-line helper, end to end

    def helper(self, *args):
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "lib"))
        return subprocess.run([sys.executable, str(HERE.parent / "lib" / "kdeconnect-notify.py"),
                               *args], capture_output=True, text=True, env=env, timeout=20)

    def test_list_returns_the_repliable_notifications_as_json(self):
        run = self.helper("list")
        self.assertEqual(run.returncode, 0, run.stderr)
        notes = json.loads(run.stdout)
        self.assertEqual([n["app"] for n in notes], ["Messages", "Messenger"])
        self.assertEqual(set(notes[0]), set(
            "path id device app title text ticker thread conversation icon package".split()))

    def test_send_delivers(self):
        note = next(n for n in self.kde.notifications() if n["app"] == "Messenger")
        run = self.helper("send", note["path"], "from the helper")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("from the helper", self.fake.stdout.readline())

    def test_send_refuses_an_empty_reply(self):
        run = self.helper("send", "/what/ever", "   ")
        self.assertEqual(run.returncode, 1)
        self.assertIn("refusing to send an empty reply", run.stderr)

    def test_send_to_a_gone_notification_fails_clearly(self):
        gone = f"{self.kde.DEVICES}/bbbb1111bbbb1111bbbb1111bbbb1111/notifications/99"
        run = self.helper("send", gone, "hello")
        self.assertEqual(run.returncode, 1)
        self.assertIn("reply failed", run.stderr)

    def test_no_arguments_prints_usage(self):
        run = self.helper()
        self.assertEqual(run.returncode, 1)
        self.assertIn("usage:", run.stderr)


if __name__ == "__main__":
    unittest.main()
