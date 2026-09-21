"""Phone numbers, contacts, dates and the message tuple."""

import base64
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gi.repository import GLib

from phonelink import sms

# A one-pixel PNG, so a photo in a vCard is real image bytes.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def ms(when):
    return int(when.timestamp() * 1000)


class Numbers(unittest.TestCase):
    def test_last_ten_digits_match(self):
        # +1 555... from the phone and 555... in a vCard are the same person.
        self.assertEqual(sms.number_key("+1 (555) 010-1234"), sms.number_key("5550101234"))

    def test_punctuation_is_ignored(self):
        self.assertEqual(sms.number_key("555.010.1234"), "5550101234")

    def test_short_codes_keep_their_digits(self):
        self.assertEqual(sms.number_key("24255"), "24255")

    def test_no_digits(self):
        self.assertEqual(sms.number_key("unknown"), "")
        self.assertEqual(sms.number_key(None), "")

    def test_pretty_ten_digits(self):
        self.assertEqual(sms.pretty_number("5550101234"), "(555) 010-1234")

    def test_pretty_drops_the_country_code(self):
        self.assertEqual(sms.pretty_number("+1 555 010 1234"), "(555) 010-1234")

    def test_pretty_leaves_a_short_code_alone(self):
        self.assertEqual(sms.pretty_number("24255"), "24255")

    def test_pretty_empty(self):
        self.assertEqual(sms.pretty_number(""), "Unknown")


class Dates(unittest.TestCase):
    def test_today_shows_a_clock_time(self):
        noon = datetime.now().replace(hour=12, minute=5, second=0, microsecond=0)
        self.assertEqual(sms.when(ms(noon)), noon.strftime("%-I:%M %p"))

    def test_yesterday(self):
        self.assertEqual(sms.when(ms(datetime.now() - timedelta(days=1))), "Yesterday")

    def test_this_week_shows_a_weekday(self):
        then = datetime.now() - timedelta(days=3)
        self.assertEqual(sms.when(ms(then)), then.strftime("%a"))

    def test_older_shows_a_date(self):
        then = datetime.now() - timedelta(days=30)
        self.assertEqual(sms.when(ms(then)), then.strftime("%b %-d"))

    def test_another_year_carries_the_year(self):
        then = datetime.now() - timedelta(days=400)
        self.assertEqual(sms.when(ms(then)), then.strftime("%b %-d, %Y"))

    def test_day_label_today_and_yesterday(self):
        self.assertEqual(sms.day_label(ms(datetime.now())), "Today")
        self.assertEqual(sms.day_label(ms(datetime.now() - timedelta(days=1))), "Yesterday")

    def test_day_label_spells_the_day_out(self):
        then = datetime.now() - timedelta(days=5)
        self.assertEqual(sms.day_label(ms(then)), then.strftime("%A, %B %-d"))


class Contacts(unittest.TestCase):
    def cards(self, *texts):
        """A contacts folder where KDE Connect would have written its vCards."""
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "kpeoplevcard" / "kdeconnect-dev1"
        folder.mkdir(parents=True)
        for i, text in enumerate(texts):
            (folder / f"{i}.vcf").write_text(text)
        return tmp.name

    def load(self, *texts):
        data = self.cards(*texts)
        with mock.patch.object(GLib, "get_user_data_dir", return_value=data):
            return sms.load_contacts("dev1")

    def test_name_and_number(self):
        book = self.load("BEGIN:VCARD\nFN:Naomi Nagata\nTEL:+15550101234\nEND:VCARD\n")
        self.assertEqual(book["5550101234"][0], "Naomi Nagata")

    def test_several_numbers_for_one_contact(self):
        book = self.load("BEGIN:VCARD\nFN:Alex\nTEL:5550101234\nTEL:5550109999\nEND:VCARD\n")
        self.assertEqual({k: v[0] for k, v in book.items()},
                         {"5550101234": "Alex", "5550109999": "Alex"})

    def test_folded_lines_are_joined(self):
        # A long line wraps with one whitespace character that belongs to the
        # fold, so a real space in the name is written as a second one.
        book = self.load("BEGIN:VCARD\nFN:Camina\n  Drummer\nTEL:5550101234\nEND:VCARD\n")
        self.assertEqual(book["5550101234"][0], "Camina Drummer")

    def test_the_folds_own_whitespace_is_not_part_of_the_name(self):
        book = self.load("BEGIN:VCARD\nFN:Nagata\n Junior\nTEL:5550101234\nEND:VCARD\n")
        self.assertEqual(book["5550101234"][0], "NagataJunior")

    def test_photo_comes_back_as_bytes(self):
        card = ("BEGIN:VCARD\nFN:Ann\nTEL:5550101234\n"
                f"PHOTO;ENCODING=b;TYPE=PNG:{base64.b64encode(PNG).decode()}\nEND:VCARD\n")
        self.assertEqual(self.load(card)["5550101234"][1], PNG)

    def test_data_uri_photo(self):
        card = ("BEGIN:VCARD\nFN:Ann\nTEL:5550101234\n"
                f"PHOTO:data:image/png;base64,{base64.b64encode(PNG).decode()}\nEND:VCARD\n")
        self.assertEqual(self.load(card)["5550101234"][1], PNG)

    def test_no_contacts_folder(self):
        with mock.patch.object(GLib, "get_user_data_dir", return_value="/nonexistent"):
            self.assertEqual(sms.load_contacts("dev1"), {})

    def test_a_contact_without_a_number_is_skipped(self):
        self.assertEqual(self.load("BEGIN:VCARD\nFN:Nobody\nEND:VCARD\n"), {})


def message(body="hi", address="5550101234", date=1_700_000_000_000, mtype=1,
            read=True, thread=7, uid=3, attachments=()):
    """A ConversationMessage as KDE Connect sends it: (isa(s)xiixixa(xsss))."""
    return GLib.Variant(
        "(isa(s)xiixixa(xsss))",
        (0, body, [(address,)], date, mtype, int(read), thread, uid, 0,
         list(attachments)))


class Message(unittest.TestCase):
    def test_fields(self):
        m = sms.Msg(message(body="On my way"))
        self.assertEqual((m.body, m.addresses, m.thread, m.uid),
                         ("On my way", ["5550101234"], 7, 3))

    def test_incoming_and_outgoing(self):
        self.assertFalse(sms.Msg(message(mtype=1)).outgoing)   # inbox
        self.assertTrue(sms.Msg(message(mtype=2)).outgoing)    # sent
        self.assertTrue(sms.Msg(message(mtype=sms.FAILED)).outgoing)

    def test_attachments(self):
        m = sms.Msg(message(attachments=[(11, "image/jpeg", "", "unique-1")]))
        self.assertEqual(len(m.attachments), 1)
        att = m.attachments[0]
        self.assertEqual((att.part, att.mime, att.uid, att.kind),
                         (11, "image/jpeg", "unique-1", "image"))

    def test_video_attachment_kind(self):
        m = sms.Msg(message(attachments=[(12, "video/mp4", "", "unique-2")]))
        self.assertEqual(m.attachments[0].kind, "video")




class MatchAttachment(unittest.TestCase):
    """Which download belongs to which bubble.

    The old rule also accepted a prefix, and assumed a single transfer in
    flight had to be the file that arrived -- either of which could put another
    conversation's picture in a bubble, since KDE Connect's own app downloads
    into the same folder.
    """

    WAITING = ["PART_1773456851589.jpg", "PART_1786542647625_63415634.jpg"]

    def test_exact_name(self):
        self.assertEqual(sms.match_attachment("PART_1773456851589.jpg", self.WAITING),
                         "PART_1773456851589.jpg")

    def test_the_extension_may_differ(self):
        self.assertEqual(sms.match_attachment("PART_1773456851589.jpeg", self.WAITING),
                         "PART_1773456851589.jpg")

    def test_an_id_without_an_extension(self):
        self.assertEqual(sms.match_attachment("PART_1773456851589", self.WAITING),
                         "PART_1773456851589.jpg")

    def test_a_prefix_is_not_a_match(self):
        # PART_17734568515891234 starts with a waiting id, and is a different file.
        self.assertIsNone(sms.match_attachment("PART_17734568515891234.jpg", self.WAITING))

    def test_a_file_nobody_asked_for(self):
        self.assertIsNone(sms.match_attachment("IMG_0042.jpg", self.WAITING))

    def test_nothing_waiting(self):
        self.assertIsNone(sms.match_attachment("PART_1773456851589.jpg", []))

    def test_a_longer_id_is_matched_in_full(self):
        self.assertEqual(sms.match_attachment("PART_1786542647625_63415634.jpg", self.WAITING),
                         "PART_1786542647625_63415634.jpg")

    def test_a_path_rather_than_a_name(self):
        self.assertIsNone(sms.match_attachment("", self.WAITING))


if __name__ == "__main__":
    unittest.main()
