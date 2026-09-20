"""Which device phonelink talks to.

The bug this pins: with a desktop ("Roci") paired and listed first, send, ring,
clip and the Messages window all took the first reachable device, so they
targeted the PC.
"""

import os
import unittest
from unittest import mock

from phonelink import kdeconnect as kde


def device(did, name, kind, reachable=True, paired=True):
    return {"id": did, "name": name, "type": kind,
            "reachable": reachable, "paired": paired}


DESKTOP = device("aaaa", "Roci", "desktop")
PHONE = device("bbbb", "Test Phone", "phone")
TABLET = device("cccc", "Tab", "tablet")


class PickDevice(unittest.TestCase):
    def setUp(self):
        # A real PHONELINK_DEVICE in the environment must not steer the tests.
        patch = mock.patch.dict(os.environ, {}, clear=False)
        patch.start()
        os.environ.pop("PHONELINK_DEVICE", None)
        self.addCleanup(patch.stop)

    def test_phone_wins_over_a_desktop_listed_first(self):
        self.assertEqual(kde.pick_device([DESKTOP, PHONE])["name"], "Test Phone")

    def test_tablet_when_there_is_no_phone(self):
        self.assertEqual(kde.pick_device([DESKTOP, TABLET])["name"], "Tab")

    def test_phone_beats_a_tablet(self):
        self.assertEqual(kde.pick_device([TABLET, PHONE])["name"], "Test Phone")

    def test_a_desktop_alone_is_never_chosen(self):
        self.assertIsNone(kde.pick_device([DESKTOP]))

    def test_nothing_reachable(self):
        self.assertIsNone(kde.pick_device([]))

    def test_an_unreachable_phone_is_not_chosen(self):
        self.assertIsNone(kde.pick_device([device("bbbb", "P", "phone", reachable=False)]))

    def test_an_unpaired_phone_is_not_chosen(self):
        self.assertIsNone(kde.pick_device([device("bbbb", "P", "phone", paired=False)]))

    def test_first_phone_of_several(self):
        second = device("dddd", "Spare", "phone")
        self.assertEqual(kde.pick_device([PHONE, second])["name"], "Test Phone")


class Override(unittest.TestCase):
    def test_by_name(self):
        self.assertEqual(kde.pick_device([DESKTOP, PHONE], "Roci")["name"], "Roci")

    def test_by_id(self):
        self.assertEqual(kde.pick_device([DESKTOP, PHONE], "bbbb")["name"], "Test Phone")

    def test_unknown_name_picks_nothing(self):
        # Better an error than a quiet send to the wrong machine.
        self.assertIsNone(kde.pick_device([DESKTOP, PHONE], "nope"))

    def test_unreachable_override(self):
        off = device("eeee", "Away", "phone", reachable=False)
        self.assertIsNone(kde.pick_device([off, PHONE], "Away"))

    def test_environment_is_read_when_no_argument_is_given(self):
        with mock.patch.dict(os.environ, {"PHONELINK_DEVICE": "Roci"}):
            self.assertEqual(kde.pick_device([DESKTOP, PHONE])["name"], "Roci")


if __name__ == "__main__":
    unittest.main()
