"""Who a new text goes to: names, numbers, and refusing to guess.

Sending to the wrong person cannot be taken back, so an ambiguous name has to
come back as a question rather than a best guess.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gi.repository import GLib

from phonelink import sms

NAOMI = "BEGIN:VCARD\nFN:Naomi Nagata\nTEL:+15550101234\nEND:VCARD\n"
ALEX = "BEGIN:VCARD\nFN:Alex Kamal\nTEL:5550109999\nTEL:5550108888\nEND:VCARD\n"
JIM = "BEGIN:VCARD\nFN:Jim\nTEL:5550107777\nEND:VCARD\n"
JIMMY = "BEGIN:VCARD\nFN:Jimmy Holden\nTEL:5550106666\nEND:VCARD\n"


def people(*cards):
    tmp = TemporaryDirectory()
    folder = Path(tmp.name) / "kpeoplevcard" / "kdeconnect-dev1"
    folder.mkdir(parents=True)
    for i, text in enumerate(cards):
        (folder / f"{i}.vcf").write_text(text)
    with mock.patch.object(GLib, "get_user_data_dir", return_value=tmp.name):
        loaded = sms.load_people("dev1")
    tmp.cleanup()
    return loaded


class WhatIsANumber(unittest.TestCase):
    def test_numbers_as_people_write_them(self):
        for text in ("5550134", "555-010-1234", "(555) 010 1234", "+1 555 010 1234",
                     "24255"):
            self.assertTrue(sms.looks_like_number(text), text)

    def test_names_are_not_numbers(self):
        for text in ("Naomi", "Alex Kamal", "mum", "", "  "):
            self.assertFalse(sms.looks_like_number(text), repr(text))

    def test_three_digits_is_not_a_number_to_text(self):
        # Too short to be anything but a typo, and 911 is not a text target.
        self.assertFalse(sms.looks_like_number("911"))

    def test_cleaning_keeps_the_country_code(self):
        self.assertEqual(sms.clean_number("+1 (555) 010-1234"), "+15550101234")
        self.assertEqual(sms.clean_number("555.010.1234"), "5550101234")


class Contacts(unittest.TestCase):
    def test_one_entry_per_number(self):
        # A contact with a mobile and a landline is two things you could text.
        found = people(ALEX)
        self.assertEqual([p["name"] for p in found], ["Alex Kamal", "Alex Kamal"])
        self.assertEqual({p["key"] for p in found}, {"5550109999", "5550108888"})

    def test_sorted_by_name(self):
        self.assertEqual([p["name"] for p in people(NAOMI, JIM)], ["Jim", "Naomi Nagata"])

    def test_a_nameless_card_is_listed_by_its_number(self):
        found = people("BEGIN:VCARD\nTEL:5550101234\nEND:VCARD\n")
        self.assertEqual(found[0]["name"], "(555) 010-1234")

    def test_matching_prefers_the_name_typed_in_full(self):
        found = sms.match_people(people(JIM, JIMMY), "jim")
        self.assertEqual(found[0]["name"], "Jim")

    def test_matching_on_part_of_a_name(self):
        self.assertEqual([p["name"] for p in sms.match_people(people(NAOMI, ALEX), "kamal")],
                         ["Alex Kamal", "Alex Kamal"])

    def test_matching_on_digits(self):
        found = sms.match_people(people(NAOMI, JIM), "0107777")
        self.assertEqual([p["name"] for p in found], ["Jim"])

    def test_no_query_offers_everyone(self):
        self.assertEqual(len(sms.match_people(people(NAOMI, JIM), "")), 2)


class Resolving(unittest.TestCase):
    def test_a_number_goes_as_written(self):
        address, who, problem = sms.resolve_recipient("555-010-4321", [])
        self.assertEqual((address, who, problem), ("5550104321", "(555) 010-4321", None))

    def test_a_known_number_is_named(self):
        _, who, problem = sms.resolve_recipient("555 010 1234", people(NAOMI))
        self.assertEqual((who, problem), ("Naomi Nagata", None))

    def test_a_name_resolves_to_its_number(self):
        address, who, problem = sms.resolve_recipient("naomi", people(NAOMI, JIM))
        self.assertEqual((address, who, problem), ("+15550101234", "Naomi Nagata", None))

    def test_two_people_are_a_question_not_a_guess(self):
        address, _, problem = sms.resolve_recipient("j", people(JIM, JIMMY))
        self.assertIsNone(address)
        self.assertIn("Jim", problem)
        self.assertIn("Jimmy Holden", problem)

    def test_one_person_with_two_numbers_is_also_a_question(self):
        address, _, problem = sms.resolve_recipient("Alex", people(ALEX))
        self.assertIsNone(address)
        self.assertIn("several numbers", problem)

    def test_an_exact_name_wins_over_a_longer_one(self):
        address, who, problem = sms.resolve_recipient("Jim", people(JIM, JIMMY))
        self.assertEqual((address, who, problem), ("5550107777", "Jim", None))

    def test_an_unknown_name(self):
        _, _, problem = sms.resolve_recipient("Amos", people(NAOMI))
        self.assertIn("No contact matching", problem)

    def test_with_no_contacts_synced_it_says_why(self):
        _, _, problem = sms.resolve_recipient("Amos", [])
        self.assertIn("Contacts", problem)

    def test_nothing_typed(self):
        _, _, problem = sms.resolve_recipient("  ", people(NAOMI))
        self.assertTrue(problem)


if __name__ == "__main__":
    unittest.main()
