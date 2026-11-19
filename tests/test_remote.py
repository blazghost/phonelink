"""Keys and clicks, worked out before anything reaches the phone."""

import unittest

from phonelink import remote


class KeyArgs(unittest.TestCase):
    def test_a_letter(self):
        self.assertEqual(remote.key_args("a", "a"), ("a", 0, False, False, False))

    def test_shifted_and_ctrl(self):
        self.assertEqual(remote.key_args("A", "A", shift=True), ("A", 0, True, False, False))
        self.assertEqual(remote.key_args("c", "c", ctrl=True), ("c", 0, False, True, False))

    def test_special_keys(self):
        self.assertEqual(remote.key_args("BackSpace", "\b"), ("", 1, False, False, False))
        self.assertEqual(remote.key_args("Return", "\r")[1], 12)
        self.assertEqual(remote.key_args("Left", "")[1], 4)
        self.assertEqual(remote.key_args("F1", "")[1], 21)
        self.assertEqual(remote.key_args("F12", "")[1], 32)

    def test_a_modifier_alone_is_not_sent(self):
        self.assertIsNone(remote.key_args("Shift_L", ""))
        self.assertIsNone(remote.key_args("Control_R", ""))


class Variants(unittest.TestCase):
    def test_types(self):
        out = remote.to_variants({"scroll": True, "dx": 0, "dy": 3})
        self.assertEqual(out["scroll"].get_type_string(), "b")
        self.assertEqual(out["dx"].get_type_string(), "d")
        self.assertEqual(out["dy"].unpack(), 3.0)


if __name__ == "__main__":
    unittest.main()
