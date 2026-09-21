"""What the bar widget reads, and clearing a message on the phone.

Against the fake KDE Connect rather than a real phone: a test must never
dismiss somebody's actual notifications.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ON_TEST_BUS = os.environ.get("PHONELINK_TEST_BUS") == "1"


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class Bar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = subprocess.Popen([sys.executable, str(HERE / "fake_kdeconnect.py")],
                                    stdout=subprocess.PIPE, text=True)
        if "ready" not in cls.fake.stdout.readline():
            cls.fake.kill()
            raise AssertionError("fake kdeconnect did not start")

    @classmethod
    def tearDownClass(cls):
        cls.fake.terminate()
        cls.fake.wait(timeout=5)
        cls.fake.stdout.close()

    def bar(self, *args):
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "lib"))
        run = subprocess.run([sys.executable, str(HERE.parent / "lib" / "phonelink-bar.py"), *args],
                             capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_it_prints_one_json_object(self):
        self.assertIsInstance(self.bar(), dict)

    def test_the_phone_is_the_one_reported(self):
        # Not the desktop, which the fake lists first.
        self.assertEqual(self.bar()["device"], "Test Phone")

    def test_state_is_ok_when_the_daemon_answers(self):
        self.assertEqual(self.bar()["state"], "ok")

    def test_battery(self):
        # The fake's phone has no battery plugin, so it says so rather than
        # inventing a number.
        self.assertIsNone(self.bar()["battery"])

    def test_signal_is_null_without_the_phone_state_permission(self):
        self.assertIsNone(self.bar()["bars"])

    def test_waiting_counts_conversations_not_notifications(self):
        # The fake has two repliable conversations and one Reddit notification.
        data = self.bar()
        self.assertEqual(data["waiting"], 2)
        self.assertEqual(sorted(data["from"]), ["(555) 010-1234", "Naomi Nagata"])

    def test_pretty_is_the_same_data(self):
        self.assertEqual(self.bar("--pretty"), self.bar())

    def test_it_is_quick(self):
        import time
        start = time.monotonic()
        self.bar()
        self.assertLess(time.monotonic() - start, 5)


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class Dismiss(unittest.TestCase):
    def setUp(self):
        self.fake = subprocess.Popen([sys.executable, str(HERE / "fake_kdeconnect.py")],
                                     stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.fake.stdout.close)
        self.addCleanup(self.fake.wait, 5)
        self.addCleanup(self.fake.terminate)
        if "ready" not in self.fake.stdout.readline():
            self.fake.kill()
            raise AssertionError("fake kdeconnect did not start")
        from phonelink import kdeconnect as kde
        self.kde = kde

    def note(self, app):
        return next(n for n in self.kde.notifications() if n["app"] == app)

    def test_dismiss_reaches_the_phone(self):
        self.assertTrue(self.kde.dismiss(self.note("Messenger")["path"]))
        self.assertIn("dismiss", self.fake.stdout.readline())

    def test_a_notification_that_cannot_be_dismissed_is_left_alone(self):
        # The fake's Reddit notification says dismissable = false, as an
        # ongoing call or a media player does.
        self.assertFalse(self.kde.dismiss(self.note("Reddit")["path"]))

    def test_a_notification_that_is_already_gone(self):
        gone = f"{self.kde.DEVICES}/bbbb1111bbbb1111bbbb1111bbbb1111/notifications/99"
        self.assertFalse(self.kde.dismiss(gone))

    def test_a_path_that_is_not_a_path(self):
        self.assertFalse(self.kde.dismiss("not-a-path"))

    def test_the_helper_dismisses_too(self):
        path = self.note("Messages")["path"]
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "lib"))
        run = subprocess.run([sys.executable, str(HERE.parent / "lib" / "kdeconnect-notify.py"),
                              "dismiss", path], capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip(), "dismissed")
        self.assertIn("dismiss", self.fake.stdout.readline())

    def test_the_helper_says_so_when_there_is_nothing_to_dismiss(self):
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "lib"))
        run = subprocess.run([sys.executable, str(HERE.parent / "lib" / "kdeconnect-notify.py"),
                              "dismiss", "/no/such/notification"],
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stdout.strip(), "already gone")


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class WithoutADaemon(unittest.TestCase):
    """Nothing is running on this bus: the widget must be told, not left stale."""

    def test_state_is_gone(self):
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "lib"))
        run = subprocess.run([sys.executable, str(HERE.parent / "lib" / "phonelink-bar.py")],
                             capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["state"], "gone")


if __name__ == "__main__":
    unittest.main()
