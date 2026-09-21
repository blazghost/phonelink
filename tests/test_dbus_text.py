"""Texting somebody there is no thread with yet, against the fake KDE Connect.

Never the real bus: `phonelink text` sends for real, and a test that reached a
live daemon would text an actual person. The fake prints every message it is
handed, which is how these check what went out.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEXT = HERE.parent / "lib" / "phonelink-text.py"
ON_TEST_BUS = os.environ.get("PHONELINK_TEST_BUS") == "1"

# The fake's phone, whose contacts folder is named after its id.
PHONE = "bbbb1111bbbb1111bbbb1111bbbb1111"
CARDS = {
    "naomi": "BEGIN:VCARD\nFN:Naomi Nagata\nTEL:+15550101234\nEND:VCARD\n",
    "jim": "BEGIN:VCARD\nFN:Jim\nTEL:5550107777\nEND:VCARD\n",
    "jimmy": "BEGIN:VCARD\nFN:Jimmy Holden\nTEL:5550106666\nEND:VCARD\n",
}


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class Texting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = subprocess.Popen([sys.executable, str(HERE / "fake_kdeconnect.py")],
                                    stdout=subprocess.PIPE, text=True)
        line = cls.fake.stdout.readline()
        if "ready" not in line:
            cls.fake.kill()
            raise AssertionError(f"fake kdeconnect did not start: {line.strip()}")
        # Contacts where KDE Connect syncs them, for the phone the fake offers.
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name) / "kpeoplevcard" / f"kdeconnect-{PHONE}"
        folder.mkdir(parents=True)
        for name, card in CARDS.items():
            (folder / f"{name}.vcf").write_text(card)

    @classmethod
    def tearDownClass(cls):
        cls.fake.terminate()
        cls.fake.wait(timeout=5)
        cls.fake.stdout.close()
        cls.tmp.cleanup()

    def text(self, *args, contacts=True):
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "lib"))
        env["XDG_DATA_HOME"] = str(self.tmp.name) if contacts else str(HERE / "no-such-dir")
        return subprocess.run([sys.executable, str(TEXT), *args],
                              capture_output=True, text=True, env=env, timeout=30)

    def sent(self):
        """The one message the fake has just been handed."""
        return self.fake.stdout.readline().strip()

    # -- sending

    def test_a_number_is_texted_as_written(self):
        run = self.text("555-010-4321", "on", "my", "way")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.sent(), "new 5550104321 on my way")

    def test_it_says_who_it_went_to(self):
        run = self.text("5550104321", "hello")
        self.assertIn("(555) 010-4321", run.stdout)
        self.sent()

    def test_a_contact_name_is_looked_up(self):
        run = self.text("Naomi", "docking in ten")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.sent(), "new +15550101234 docking in ten")
        self.assertIn("Sent to Naomi Nagata", run.stdout)

    def test_a_known_number_is_named_back(self):
        run = self.text("+1 555 010 1234", "hi")
        self.assertIn("Sent to Naomi Nagata", run.stdout)
        self.sent()

    def test_the_message_may_look_like_an_option(self):
        run = self.text("5550104321", "-30", "minutes")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.sent(), "new 5550104321 -30 minutes")

    def test_an_attachment_goes_with_it(self):
        picture = Path(self.tmp.name) / "dock.jpg"
        picture.write_bytes(b"not really a jpeg")
        run = self.text("--attach", str(picture), "5550104321", "look")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.sent(), "new 5550104321 look")
        self.assertIn("1 attached", run.stdout)

    # -- refusing to guess

    def test_an_ambiguous_name_sends_nothing(self):
        run = self.text("Jim", "hello")
        # Jim is exactly one contact, so this one goes.
        self.assertEqual(run.returncode, 0, run.stderr)
        self.sent()
        run = self.text("J", "hello")
        self.assertEqual(run.returncode, 1)
        self.assertIn("Jimmy Holden", run.stderr)

    def test_an_unknown_name_sends_nothing(self):
        run = self.text("Amos", "hello")
        self.assertEqual(run.returncode, 1)
        self.assertIn("No contact matching", run.stderr)

    def test_with_no_contacts_synced_the_reason_is_given(self):
        run = self.text("Naomi", "hello", contacts=False)
        self.assertEqual(run.returncode, 1)
        self.assertIn("Contacts", run.stderr)

    def test_a_recipient_with_no_message(self):
        # `phonelink text <who>` opens the window instead; reaching the sender
        # with nothing to say is an error rather than an empty text.
        run = self.text("5550104321")
        self.assertEqual(run.returncode, 1)
        self.assertIn("nothing to send", run.stderr)

    def test_an_attachment_that_is_not_there(self):
        run = self.text("--attach", "/no/such/file.jpg", "5550104321", "look")
        self.assertEqual(run.returncode, 1)
        self.assertIn("no such file", run.stderr)

    # -- listing

    def test_the_contacts_it_can_text_by_name(self):
        run = self.text("--list")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Naomi Nagata\t(555) 010-1234", run.stdout)

    def test_listing_with_nothing_synced_explains(self):
        run = self.text("--list", contacts=False)
        self.assertEqual(run.returncode, 1)
        self.assertIn("Permissions", run.stderr)


if __name__ == "__main__":
    unittest.main()
