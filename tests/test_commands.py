"""The runcommand file: read back what was written, and never lose your own entries."""

import unittest

from phonelink import commands as cmds

# What KDE Connect's own settings page writes for one command of yours.
KDE_WRITTEN = ('[General]\n'
               'commands="@ByteArray({\\"3f2a\\":{\\"command\\":\\"echo \\\\\\"hi\\\\\\"\\",'
               '\\"name\\":\\"Say hi\\"}})"\n')


class File(unittest.TestCase):
    def test_reads_what_kde_connect_writes(self):
        self.assertEqual(cmds.read_commands(KDE_WRITTEN),
                         {"3f2a": {"command": 'echo "hi"', "name": "Say hi"}})

    def test_round_trip(self):
        data = {"a": {"name": "x, y", "command": 'say "q" \\ done'}}
        self.assertEqual(cmds.read_commands(cmds.write_commands("", data)), data)

    def test_other_lines_are_kept(self):
        text = "[General]\nother=1\ncommands=\"@ByteArray({})\"\n[Extra]\nz=2\n"
        out = cmds.write_commands(text, {"a": {"name": "n", "command": "c"}})
        self.assertIn("other=1", out)
        self.assertIn("[Extra]\nz=2", out)
        self.assertEqual(out.count("commands="), 1)

    def test_nothing_there(self):
        self.assertEqual(cmds.read_commands(""), {})


class Merge(unittest.TestCase):
    def test_on_keeps_yours_and_adds_ours(self):
        out = cmds.merged({"mine": {"name": "m", "command": "c"}}, on=True)
        self.assertIn("mine", out)
        self.assertTrue(any(k.startswith(cmds.PREFIX) for k in out))
        for entry in (v for k, v in out.items() if k.startswith(cmds.PREFIX)):
            self.assertTrue(entry["command"].startswith("/"))  # resolved, not off PATH

    def test_off_takes_only_ours_away(self):
        start = {"mine": {"name": "m", "command": "c"}, "phonelink-lock": {"name": "l", "command": "x"}}
        self.assertEqual(cmds.merged(start, on=False), {"mine": {"name": "m", "command": "c"}})


if __name__ == "__main__":
    unittest.main()
