"""Which window an Open button reaches for a notification's app."""

import unittest
from unittest import mock

from phonelink import apps

SIGNAL = "org.thoughtcrime.securesms"


def which(*present):
    return lambda name: f"/usr/bin/{name}" if name in present else None


class DesktopCommand(unittest.TestCase):
    def test_signal_raises_signal_desktop(self):
        with mock.patch("shutil.which", which("signal-desktop", "omarchy-launch-or-focus")):
            self.assertEqual(apps.desktop_command(SIGNAL),
                             ["omarchy-launch-or-focus", "^signal$", "uwsm-app -- signal-desktop"])

    def test_signal_without_omarchy_runs_it_directly(self):
        with mock.patch("shutil.which", which("signal-desktop")):
            self.assertEqual(apps.desktop_command(SIGNAL), ["signal-desktop"])

    def test_signal_not_installed_falls_back_to_the_phone(self):
        with mock.patch("shutil.which", which("omarchy-launch-or-focus")):
            self.assertIsNone(apps.desktop_command(SIGNAL))

    def test_apps_without_a_client_have_none(self):
        with mock.patch("shutil.which", which("signal-desktop", "omarchy-launch-or-focus")):
            self.assertIsNone(apps.desktop_command("com.whatsapp"))


if __name__ == "__main__":
    unittest.main()
