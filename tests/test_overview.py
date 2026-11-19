"""The window's Overview: the status chips, and which tab a launch opens on."""

import unittest

from phonelink import overview


class Chips(unittest.TestCase):
    def test_battery_and_signal(self):
        snap = {"state": "ok", "battery": {"charge": 82, "charging": False},
                "signal": {"bars": 3, "network": "5G"}}
        self.assertEqual(overview.chips(snap), ["Connected", "82%", "5G ▂▄▆"])

    def test_charging(self):
        snap = {"state": "ok", "battery": {"charge": 82, "charging": True}, "signal": None}
        self.assertEqual(overview.chips(snap), ["Connected", "82% ⚡"])

    def test_no_permission_means_no_chip_not_minus_one(self):
        snap = {"state": "ok", "battery": None, "signal": None}
        self.assertEqual(overview.chips(snap), ["Connected"])
        snap["battery"] = {"charge": -1, "charging": False}
        self.assertEqual(overview.chips(snap), ["Connected"])

    def test_away_hung_gone(self):
        self.assertEqual(overview.chips({"state": "away"}), ["Not connected"])
        self.assertEqual(overview.chips({"state": "hung"}), ["KDE Connect isn't answering"])
        self.assertEqual(overview.chips({"state": "gone"}), ["KDE Connect isn't running"])


class ParseArgs(unittest.TestCase):
    def test_plain_launch_is_overview(self):
        self.assertEqual(overview.parse_args(["x"]), ("overview", None))

    def test_a_page(self):
        self.assertEqual(overview.parse_args(["x", "--page", "photos"]), ("photos", None))

    def test_remote(self):
        self.assertEqual(overview.parse_args(["x", "--page", "remote"]), ("remote", None))

    def test_an_unknown_page_is_overview(self):
        self.assertEqual(overview.parse_args(["x", "--page", "nope"]), ("overview", None))

    def test_new_text(self):
        self.assertEqual(overview.parse_args(["x", "--new"]), ("messages", ""))
        self.assertEqual(overview.parse_args(["x", "--new", "Naomi", "Nagata"]),
                         ("messages", "Naomi Nagata"))


if __name__ == "__main__":
    unittest.main()
