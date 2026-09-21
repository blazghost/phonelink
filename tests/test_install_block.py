"""Installing a block of config: added, updated in place, or left alone.

install.sh used to grow a hand-written migration whenever a shipped rule
changed shape. These pin the one mechanism that replaced them, including the
part that matters most: nothing outside phonelink's own markers moves.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "integration" / "install-block.py"

SNIPPET_V1 = """
-- phonelink:demo:begin v1
-- what this rule is for
o.window("^(demo)$", {
  float = true,
})
-- phonelink:demo:end
"""

SNIPPET_V2 = SNIPPET_V1.replace("v1", "v2").replace("float = true,", "float = true,\n  center = true,")

# A config as it looked before the markers existed: the user's own notes above,
# the old rule below.
LEGACY = """-- my own hyprland config
o.bind("SUPER + K", "Something", "mine")

-- Add any other personal configuration below.
-- o.window("qemu", { workspace = "5" })

-- phonelink: what this rule was for, worded differently
o.window("^(demo)$", {
  float = true,
  size = "96 24",
})

o.window("^(something-else)$", { float = true })
"""


class Block(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.v1 = self.write("v1.snippet", SNIPPET_V1)
        self.v2 = self.write("v2.snippet", SNIPPET_V2)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return path

    def run_tool(self, target, snippet, *legacy):
        run = subprocess.run([sys.executable, str(TOOL), str(target), str(snippet), *legacy],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return run.stdout.strip()

    # -- adding

    def test_added_to_a_file_without_it(self):
        target = self.write("hyprland.lua", "-- mine\no.bind('X', nil, 'y')\n")
        self.assertEqual(self.run_tool(target, self.v1), "added")
        self.assertIn("phonelink:demo:begin v1", target.read_text())

    def test_what_was_there_stays(self):
        target = self.write("hyprland.lua", "-- mine\no.bind('X', nil, 'y')\n")
        self.run_tool(target, self.v1)
        self.assertTrue(target.read_text().startswith("-- mine\no.bind('X', nil, 'y')\n"))

    def test_a_missing_file_is_reported_not_created(self):
        target = self.dir / "not-there.lua"
        self.assertEqual(self.run_tool(target, self.v1), "missing")
        self.assertFalse(target.exists())

    # -- leaving alone

    def test_running_twice_changes_nothing(self):
        target = self.write("hyprland.lua", "-- mine\n")
        self.run_tool(target, self.v1)
        after_first = target.read_text()
        self.assertEqual(self.run_tool(target, self.v1), "current")
        self.assertEqual(target.read_text(), after_first)

    def test_a_rule_of_your_own_that_mentions_the_same_words(self):
        target = self.write("hyprland.lua", 'o.window("^(demo)$", { workspace = "5" })\n')
        self.run_tool(target, self.v1)  # no legacy text given: appended, not replaced
        self.assertIn('{ workspace = "5" }', target.read_text())

    # -- updating

    def test_a_new_version_replaces_the_old_block(self):
        target = self.write("hyprland.lua", "-- mine\n")
        self.run_tool(target, self.v1)
        self.assertEqual(self.run_tool(target, self.v2), "updated")
        text = target.read_text()
        self.assertIn("center = true", text)
        self.assertEqual(text.count("phonelink:demo:begin"), 1)

    def test_an_update_leaves_the_rest_of_the_file_alone(self):
        target = self.write("hyprland.lua", "-- mine\no.bind('X', nil, 'y')\n")
        self.run_tool(target, self.v1)
        target.write_text(target.read_text() + "\n-- added by me afterwards\n")
        self.run_tool(target, self.v2)
        text = target.read_text()
        self.assertIn("-- added by me afterwards", text)
        self.assertIn("o.bind('X', nil, 'y')", text)

    def test_an_older_snippet_is_put_back(self):
        # Installing an earlier phonelink over a newer one: version differs, so
        # the block is replaced either way rather than left half-new.
        target = self.write("hyprland.lua", "-- mine\n")
        self.run_tool(target, self.v2)
        self.assertEqual(self.run_tool(target, self.v1), "updated")
        self.assertNotIn("center = true", target.read_text())

    # -- migrating an install from before the markers

    def test_an_unmarked_old_rule_is_replaced(self):
        target = self.write("hyprland.lua", LEGACY)
        self.assertEqual(self.run_tool(target, self.v1, 'o.window("^(demo)$"'), "migrated")
        text = target.read_text()
        self.assertNotIn('size = "96 24"', text)
        self.assertEqual(text.count('o.window("^(demo)$"'), 1)

    def test_migration_keeps_your_own_comments(self):
        target = self.write("hyprland.lua", LEGACY)
        self.run_tool(target, self.v1, 'o.window("^(demo)$"')
        text = target.read_text()
        self.assertIn("-- Add any other personal configuration below.", text)
        self.assertIn('-- o.window("qemu", { workspace = "5" })', text)

    def test_migration_keeps_the_rules_around_it(self):
        target = self.write("hyprland.lua", LEGACY)
        self.run_tool(target, self.v1, 'o.window("^(demo)$"')
        text = target.read_text()
        self.assertIn("o.bind(\"SUPER + K\", \"Something\", \"mine\")", text)
        self.assertIn('o.window("^(something-else)$", { float = true })', text)

    def test_migrating_twice_is_not_two_blocks(self):
        target = self.write("hyprland.lua", LEGACY)
        self.run_tool(target, self.v1, 'o.window("^(demo)$"')
        self.assertEqual(self.run_tool(target, self.v1, 'o.window("^(demo)$"'), "current")
        self.assertEqual(target.read_text().count("phonelink:demo:begin"), 1)

    def test_a_block_next_to_another_block_survives(self):
        # The bug this pins: the walk backwards over comments ate the end marker
        # of the block above, leaving a begin without an end.
        other = self.write("other.snippet",
                           "\n-- phonelink:other:begin v1\n-- a note\n"
                           'o.window("^(other)$", { float = true })\n-- phonelink:other:end\n')
        target = self.write("hyprland.lua", LEGACY)
        self.run_tool(target, other, 'o.window("^(something-else)$"')
        self.run_tool(target, self.v1, 'o.window("^(demo)$"')
        text = target.read_text()
        for name in ("demo", "other"):
            self.assertEqual(text.count(f"phonelink:{name}:begin"), 1, name)
            self.assertEqual(text.count(f"phonelink:{name}:end"), 1, name)

    def test_an_unmarked_rule_on_one_line(self):
        target = self.write("hyprland.lua",
                            '-- old note\no.window("^(demo)$", { float = true })\n-- after\n')
        self.assertEqual(self.run_tool(target, self.v1, 'o.window("^(demo)$"'), "migrated")
        text = target.read_text()
        self.assertIn("-- after", text)
        self.assertEqual(text.count('o.window("^(demo)$"'), 1)


if __name__ == "__main__":
    unittest.main()
