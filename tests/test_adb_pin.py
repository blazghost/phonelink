"""The remembered wireless endpoint is only used when it answers as the phone.

`phonelink adb-serial` against a stand-in adb: whatever sits at the remembered
address reports a serial, and only the one saved from a trusted path is kept.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ADB = """#!/bin/bash
d=$FAKE_DIR
case $1 in
  devices) echo "List of devices attached"; [ -f $d/up ] && printf '%s\\tdevice\\n' "$(cat $d/up)" ;;
  connect) echo "connected to $2"; echo "$2" >$d/up ;;
  disconnect) rm -f $d/up; echo disconnected; touch $d/dropped ;;
  -s) [ "$3 $4 $5" = "shell getprop ro.serialno" ] && echo "$FAKE_SERIAL" ;;
esac
exit 0
"""


class RememberedEndpoint(unittest.TestCase):
    def run_pick(self, answers, saved=None):
        tmp = Path(tempfile.mkdtemp())
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "adb").write_text(ADB)
        (bin_dir / "kdeconnect-cli").write_text("#!/bin/sh\nexit 0\n")  # phone not on KDE
        for f in bin_dir.iterdir():
            f.chmod(0o755)
        state = tmp / "state" / "phonelink"
        state.mkdir(parents=True)
        (state / "adb-device").write_text("10.1.2.3:5555\n")
        if saved:
            (state / "adb-serialno").write_text(saved + "\n")
        env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", XDG_STATE_HOME=str(tmp / "state"),
                   FAKE_DIR=str(tmp), FAKE_SERIAL=answers, PHONELINK_QUIET="1")
        run = subprocess.run([str(ROOT / "phonelink"), "adb-serial"], env=env,
                             capture_output=True, text=True, stdin=subprocess.DEVNULL)
        return run, (tmp / "dropped").exists()

    def test_the_phone_it_knows_is_used(self):
        run, dropped = self.run_pick("R5CX123", saved="R5CX123")
        self.assertEqual(run.stdout.strip(), "10.1.2.3:5555")
        self.assertFalse(dropped)

    def test_a_different_device_is_let_go(self):
        run, dropped = self.run_pick("EVIL0001", saved="R5CX123")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(run.stdout.strip(), "")
        self.assertTrue(dropped)

    def test_an_unknown_one_is_not_trusted_on_first_sight(self):
        run, dropped = self.run_pick("R5CX123")
        self.assertNotEqual(run.returncode, 0)
        self.assertTrue(dropped)


if __name__ == "__main__":
    unittest.main()
