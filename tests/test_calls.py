"""What a call event becomes on the desktop."""

import unittest

from phonelink import calls


class CallNote(unittest.TestCase):
    def test_ringing_is_sticky_with_silence_and_decline(self):
        note = calls.call_note("dev", "ringing", "+15551234567", "Naomi Nagata")
        self.assertTrue(note["sticky"])
        self.assertEqual(note["title"], "Naomi Nagata")
        self.assertEqual([b[1] for b in note["buttons"]], [["call", "silence"], ["call", "decline"]])

    def test_missed_call_offers_a_text_back(self):
        note = calls.call_note("dev", "missedCall", "+1 (555) 123-4567", "")
        self.assertEqual(note["title"], "+15551234567")
        self.assertEqual(note["buttons"], [("Text back", ["text", "+15551234567"])])

    def test_a_withheld_number_has_nothing_to_text(self):
        self.assertEqual(calls.call_note("dev", "missedCall", "", "")["buttons"], [])

    def test_picking_up_closes_it(self):
        self.assertIsNone(calls.call_note("dev", "talking", "1", "x"))

    def test_the_number_cannot_carry_an_option(self):
        # It goes to `phonelink text <number>`: no letters, dashes or spaces.
        note = calls.call_note("dev", "missedCall", "--list; rm -rf ~", "")
        self.assertEqual(note["buttons"], [])


if __name__ == "__main__":
    unittest.main()
