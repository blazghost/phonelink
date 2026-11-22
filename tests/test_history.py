"""Notification history: kept once, capped, private, and found by any word."""

import tempfile
import unittest
from pathlib import Path

from phonelink import history


def note(title, text, app="Signal"):
    return {"app": app, "title": title, "text": text, "ticker": "", "package": "x.y"}


class Record(unittest.TestCase):
    def setUp(self):
        self.file = Path(tempfile.mkdtemp()) / "history.jsonl"

    def test_kept_with_markup_taken_out(self):
        self.assertTrue(history.record(note("Amos", "<b>back</b> online"), self.file, now=5))
        self.assertEqual(history.load(self.file),
                         [{"time": 5, "app": "Signal", "title": "Amos", "text": "back online",
                           "package": "x.y"}])

    def test_a_resend_is_not_kept_twice(self):
        history.record(note("Amos", "hi"), self.file)
        self.assertFalse(history.record(note("Amos", "hi"), self.file))
        self.assertEqual(len(history.load(self.file)), 1)

    def test_only_you_can_read_it(self):
        history.record(note("Amos", "hi"), self.file)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_capped(self):
        for i in range(history.KEEP + 20):
            history.record(note("n", f"message {i}"), self.file)
        kept = history.load(self.file)
        self.assertEqual(len(kept), history.KEEP)
        self.assertEqual(kept[-1]["text"], f"message {history.KEEP + 19}")


class Search(unittest.TestCase):
    entries = [{"app": "Signal", "title": "Amos", "text": "reactor online"},
               {"app": "SMS", "title": "Naomi", "text": "rail fault"},
               {"app": "Signal", "title": "Alex", "text": "burn in five"}]

    def test_every_word_must_match_newest_first(self):
        self.assertEqual([e["title"] for e in history.search("signal", self.entries)],
                         ["Alex", "Amos"])
        self.assertEqual([e["title"] for e in history.search("SIGNAL reactor", self.entries)],
                         ["Amos"])

    def test_empty_query_is_everything(self):
        self.assertEqual(len(history.search("", self.entries)), 3)


if __name__ == "__main__":
    unittest.main()
