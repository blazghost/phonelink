"""Mouse sharing's arithmetic: the edge, the hand-back, the buttons, the way out."""

import os
import tempfile
import unittest
from unittest import mock

from phonelink import share

ZONES = [(1368, 912, 0, 0)]  # w, h, x, y as the portal reports them


class Barrier(unittest.TestCase):
    def test_each_edge(self):
        self.assertEqual(share.barrier("left", ZONES), (0, 0, 0, 911))
        self.assertEqual(share.barrier("right", ZONES), (1368, 0, 1368, 911))
        self.assertEqual(share.barrier("top", ZONES), (0, 0, 1367, 0))
        self.assertEqual(share.barrier("bottom", ZONES), (0, 912, 1367, 912))

    def test_two_monitors_use_the_outer_edge(self):
        zones = [(1368, 912, 0, 0), (1920, 1080, 1368, 0)]
        self.assertEqual(share.barrier("left", zones), (0, 0, 0, 911))
        self.assertEqual(share.barrier("right", zones), (3288, 0, 3288, 1079))


class Handoff(unittest.TestCase):
    def test_the_phone_pointer_is_pinned_to_the_side_it_came_in(self):
        self.assertEqual(share.pin_move("left"), (share.PIN, 0))     # phone on the left: enter at its right
        self.assertEqual(share.pin_move("right"), (-share.PIN, 0))
        self.assertEqual(share.pin_move("top"), (0, share.PIN))
        self.assertEqual(share.pin_move("bottom"), (0, -share.PIN))

    def test_moving_back_past_the_edge_returns_the_pointer(self):
        h = share.Handoff("left", span=1000)
        self.assertFalse(h.motion(-300, 0))    # deeper into the phone
        self.assertFalse(h.motion(299, 0))     # back to one pixel short of its edge
        self.assertTrue(h.motion(2, 0))        # and over it

    def test_the_phone_screen_stops_the_pointer(self):
        # Shoved far past the phone's far side, the way back is only one screen.
        h = share.Handoff("left", span=1000)
        h.motion(-5000, 0)
        self.assertFalse(h.motion(999, 0))
        self.assertTrue(h.motion(2, 0))

    def test_the_other_axis_never_returns_it(self):
        h = share.Handoff("left", span=1000)
        self.assertFalse(h.motion(0, 5000))
        self.assertFalse(h.motion(0, -5000))

    def test_right_and_bottom_edges(self):
        self.assertTrue(share.Handoff("right", span=500).motion(-1, 0))
        self.assertFalse(share.Handoff("right", span=500).motion(1, 0))
        self.assertTrue(share.Handoff("bottom", span=500).motion(0, -1))
        self.assertTrue(share.Handoff("top", span=500).motion(0, 1))

    def test_coming_home_lands_just_inside_the_edge(self):
        self.assertEqual(share.home_point("left", (0, 0, 0, 911), 400.0), (2.0, 400.0))
        self.assertEqual(share.home_point("right", (1368, 0, 1368, 911), 400.0), (1366.0, 400.0))
        self.assertEqual(share.home_point("top", (0, 0, 1367, 0), 50.0), (50.0, 2.0))
        self.assertEqual(share.home_point("left", (0, 0, 0, 911), 5000.0), (2.0, 911.0))


class Buttons(unittest.TestCase):
    def test_left_holds_and_releases(self):
        self.assertEqual(share.button_body(share.BTN_LEFT, True), {"singlehold": True})
        self.assertEqual(share.button_body(share.BTN_LEFT, False), {"singlerelease": True})

    def test_right_and_middle_click_on_press(self):
        self.assertEqual(share.button_body(share.BTN_RIGHT, True), {"rightclick": True})
        self.assertIsNone(share.button_body(share.BTN_RIGHT, False))
        self.assertEqual(share.button_body(share.BTN_MIDDLE, True), {"middleclick": True})

    def test_other_buttons_are_ignored(self):
        self.assertIsNone(share.button_body(0x113, True))


class Escape(unittest.TestCase):
    def test_ctrl_alt_esc(self):
        keys = share.Keys()
        keys.press(share.KEY_LEFTCTRL, True)
        keys.press(share.KEY_LEFTALT, True)
        self.assertTrue(keys.press(share.KEY_ESC, True))

    def test_esc_alone_goes_to_the_phone(self):
        keys = share.Keys()
        self.assertFalse(keys.press(share.KEY_ESC, True))

    def test_released_modifiers_no_longer_count(self):
        keys = share.Keys()
        keys.press(share.KEY_RIGHTCTRL, True)
        keys.press(share.KEY_RIGHTALT, True)
        keys.press(share.KEY_RIGHTALT, False)
        self.assertFalse(keys.press(share.KEY_ESC, True))

    def test_modifier_state_for_the_phone(self):
        keys = share.Keys()
        keys.press(share.KEY_LEFTSHIFT, True)
        self.assertEqual(keys.modifiers(), (True, False, False))


class EdgeFile(unittest.TestCase):
    def test_default_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            self.assertEqual(share.read_edge(), "left")
            share.edge_file().parent.mkdir(parents=True)
            share.edge_file().write_text("bottom\n")
            self.assertEqual(share.read_edge(), "bottom")
            share.edge_file().write_text("sideways\n")
            self.assertEqual(share.read_edge(), "left")


if __name__ == "__main__":
    unittest.main()
