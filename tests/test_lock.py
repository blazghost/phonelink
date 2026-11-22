"""lock.locked() against a stand-in omarchy-shell: what the shell says is what counts."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phonelink import lock


def shell_saying(answer):
    folder = tempfile.mkdtemp()
    stub = Path(folder) / "omarchy-shell"
    stub.write_text(f"#!/bin/sh\n[ \"$1 $2\" = 'lock isLocked' ] && echo {answer}\n")
    stub.chmod(0o755)
    return folder


class Locked(unittest.TestCase):
    def test_locked(self):
        with mock.patch.dict(os.environ, {"PATH": shell_saying("true")}):
            self.assertTrue(lock.locked())

    def test_unlocked(self):
        with mock.patch.dict(os.environ, {"PATH": shell_saying("false")}):
            self.assertFalse(lock.locked())

    def test_no_shell_reads_as_unlocked(self):
        with mock.patch.dict(os.environ, {"PATH": tempfile.mkdtemp()}):
            self.assertFalse(lock.locked())


class Away(unittest.TestCase):
    def test_locks_once_the_phone_has_been_gone_long_enough(self):
        away = lock.Away(60)
        away.update(True, 0)
        away.update(False, 10)
        self.assertFalse(away.due(69))
        self.assertTrue(away.due(70))

    def test_coming_back_in_time_cancels_it(self):
        away = lock.Away(60)
        away.update(True, 0)
        away.update(False, 10)
        away.update(True, 40)
        self.assertFalse(away.due(200))

    def test_a_phone_never_seen_never_locks(self):
        away = lock.Away(60)
        away.update(False, 0)
        self.assertFalse(away.due(1000))

    def test_once_per_departure(self):
        # Unlocking with the phone still away must not lock again straight off.
        away = lock.Away(60)
        away.update(True, 0)
        away.update(False, 1)
        self.assertTrue(away.due(61))
        away.update(False, 62)
        self.assertFalse(away.due(500))
        away.update(True, 600)
        away.update(False, 601)
        self.assertTrue(away.due(661))


if __name__ == "__main__":
    unittest.main()
