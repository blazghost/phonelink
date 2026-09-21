"""The health check, against a fake daemon that can be made to wedge.

kdeconnectd has failed by hanging rather than exiting -- still on the bus,
answering nothing -- so the three states are pinned here: answering, wedged,
and not there at all.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from gi.repository import GLib

HERE = Path(__file__).resolve().parent
ON_TEST_BUS = os.environ.get("PHONELINK_TEST_BUS") == "1"


def state_of(kde, timeout=1500):
    """Run the asynchronous check to completion, as a window's main loop would."""
    loop, seen = GLib.MainLoop(), []
    kde.health(lambda state: (seen.append(state), loop.quit()), timeout=timeout)
    # Never hang the suite itself if the callback somehow never comes.
    GLib.timeout_add_seconds(20, loop.quit)
    loop.run()
    return seen[0] if seen else None


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class Health(unittest.TestCase):
    def fake(self, *args):
        proc = subprocess.Popen([sys.executable, str(HERE / "fake_kdeconnect.py"), *args],
                                stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait, 5)
        self.addCleanup(proc.terminate)
        line = proc.stdout.readline()
        self.assertIn("ready", line)
        return proc

    @property
    def kde(self):
        from phonelink import kdeconnect as kde
        return kde

    def test_answering(self):
        self.fake()
        self.assertEqual(state_of(self.kde), self.kde.OK)

    def test_wedged_daemon_is_not_mistaken_for_a_healthy_one(self):
        self.fake("--hang")
        self.assertEqual(state_of(self.kde), self.kde.HUNG)

    def test_not_running_at_all(self):
        self.assertEqual(state_of(self.kde), self.kde.GONE)

    def test_running_reports_the_name(self):
        self.assertFalse(self.kde.running())
        self.fake()
        self.assertTrue(self.kde.running())

    def test_a_daemon_that_goes_away_mid_check(self):
        # Stopping between the call going out and the answer coming back is
        # "gone", not "wedged": there is nothing left to restart in place.
        proc = self.fake("--hang")
        loop, seen = GLib.MainLoop(), []
        self.kde.health(lambda state: (seen.append(state), loop.quit()), timeout=2500)
        GLib.timeout_add(300, lambda: (proc.terminate(), False)[1])
        GLib.timeout_add_seconds(20, loop.quit)
        loop.run()
        self.assertEqual(seen, [self.kde.GONE])

    def test_the_check_does_not_block_its_caller(self):
        # A wedged daemon must not freeze a window: the call returns at once and
        # the answer arrives on the main loop.
        self.fake("--hang")
        ticks = []
        loop = GLib.MainLoop()
        self.kde.health(lambda state: loop.quit(), timeout=1500)
        GLib.timeout_add(100, lambda: (ticks.append(1), True)[1])
        GLib.timeout_add_seconds(20, loop.quit)
        loop.run()
        self.assertGreater(len(ticks), 3)


if __name__ == "__main__":
    unittest.main()
