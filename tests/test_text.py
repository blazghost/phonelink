"""Notification text: the markup Android sends and the thread hidden in it.

These are the shapes that broke in real use -- a group chat rendered as raw
HTML, and &amp; showing through -- so each is pinned here.
"""

import unittest

from phonelink import kdeconnect as kde


class StripMarkup(unittest.TestCase):
    def test_tags_go(self):
        self.assertEqual(kde.strip_markup("<b>Ann</b> said hi"), "Ann said hi")

    def test_entities_decode(self):
        self.assertEqual(kde.strip_markup("Tom &amp; Jerry &lt;3"), "Tom & Jerry <3")

    def test_empty(self):
        self.assertEqual(kde.strip_markup(""), "")
        self.assertEqual(kde.strip_markup(None), "")


class Plain(unittest.TestCase):
    def test_tag_becomes_a_space(self):
        # A preview must not run two lines together into "minutesCopy".
        self.assertEqual(kde.plain("Docking<br/>Copy that"), "Docking Copy that")

    def test_entities_decode(self):
        self.assertEqual(kde.plain("5 &gt; 3"), "5 > 3")


class ParseThread(unittest.TestCase):
    GROUP = ("<b>Naomi Nagata</b><br/>Docking in ten minutes<br/>"
             "<b>Alex Kamal</b><br/>Copy that")

    def test_group_splits_into_speakers(self):
        self.assertEqual(kde.parse_thread(self.GROUP), [
            {"sender": "Naomi Nagata", "body": "Docking in ten minutes"},
            {"sender": "Alex Kamal", "body": "Copy that"},
        ])

    def test_one_to_one_has_no_sender(self):
        self.assertEqual(kde.parse_thread("On my way"),
                         [{"sender": "", "body": "On my way"}])

    def test_same_speaker_carries_on(self):
        thread = kde.parse_thread("<b>Ann</b><br/>one<br/>two")
        self.assertEqual([m["sender"] for m in thread], ["Ann", "Ann"])

    def test_entities_inside_a_thread(self):
        thread = kde.parse_thread("<b>Ann</b><br/>tea &amp; toast")
        self.assertEqual(thread[0]["body"], "tea & toast")

    def test_self_closing_and_spaced_breaks(self):
        for tag in ("<br>", "<br/>", "<br />"):
            with self.subTest(tag=tag):
                self.assertEqual(len(kde.parse_thread(f"one{tag}two")), 2)

    def test_blank_lines_are_dropped(self):
        self.assertEqual(len(kde.parse_thread("one<br/><br/>two")), 2)

    def test_empty_text(self):
        self.assertEqual(kde.parse_thread(""), [])
        self.assertEqual(kde.parse_thread(None), [])

    def test_a_name_in_bold_mid_message_is_not_a_speaker(self):
        # Only a line that is nothing but bold text is a label.
        thread = kde.parse_thread("ask <b>Ann</b> about it")
        self.assertEqual(thread, [{"sender": "", "body": "ask Ann about it"}])


class Package(unittest.TestCase):
    def test_internal_id_carries_the_package(self):
        props = {"internalId": "0|com.facebook.orca|42|tag|10222"}
        self.assertEqual(kde.package_of(props), "com.facebook.orca")

    def test_missing_internal_id(self):
        self.assertEqual(kde.package_of({}), "")

    def test_short_internal_id(self):
        self.assertEqual(kde.package_of({"internalId": "0"}), "")


class FriendlyError(unittest.TestCase):
    def test_dismissed_notification(self):
        msg = kde.friendly_error("reply failed: GDBus.Error:...UnknownObject: no such")
        self.assertEqual(msg, "That notification is gone from the phone")

    def test_daemon_not_running(self):
        msg = kde.friendly_error("...ServiceUnknown: The name is not provided by any")
        self.assertEqual(msg, "KDE Connect isn't running")

    def test_no_answer(self):
        self.assertIn("didn't answer", kde.friendly_error("Error: NoReply, timed out"))

    def test_anything_else_keeps_its_last_line(self):
        self.assertEqual(kde.friendly_error("context\nthe actual problem"),
                         "the actual problem")

    def test_nothing_at_all(self):
        self.assertEqual(kde.friendly_error(""), "Couldn't send the reply")


if __name__ == "__main__":
    unittest.main()
