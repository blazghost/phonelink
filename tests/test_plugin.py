"""The bar widgets are QML, so the suite cannot run them -- but it can read them.

These catch the mistake that shipped in the first version: calling a helper the
Omarchy bar does not hand plugins, which only shows up as a TypeError in the
shell's log the first time somebody clicks.
"""

import json
import re
import unittest
from pathlib import Path

PLUGINS = Path(__file__).resolve().parent.parent / "integration/omarchy-plugin"
WIDGETS = {p.name: (p / "BarWidget.qml").read_text() for p in sorted(PLUGINS.iterdir())}

# Everything Ui/PluginBarApi.qml exposes to a plugin. Anything else is a
# TypeError at click time, so a widget may only reach for these.
BAR_API = {
    "foreground", "barForeground", "background", "urgent", "fontFamily",
    "position", "vertical", "barSize", "transparent", "shell", "activePopout",
    "clickTargets", "layoutConfig", "foregroundAnimationEnabled",
    "centerSectionRevealHeld", "centerHoverRevealSuppressed", "foreignPopoutMarker",
    "setCenterHoverRevealSuppressed", "showTooltip", "hideTooltip",
    "registerClickTarget", "unregisterClickTarget", "requestPopout",
    "releasePopout", "switchPanelFrom", "targetBelongsToWindow", "moduleWidgets",
    "run",
}


class BarApi(unittest.TestCase):
    def test_both_widgets_are_here(self):
        self.assertEqual(set(WIDGETS), {"phonelink.phone", "phonelink.media"})

    def test_the_widgets_only_touch_members_the_bar_has(self):
        for name, qml in WIDGETS.items():
            with self.subTest(plugin=name):
                used = set(re.findall(r"\bbar\.([A-Za-z_][A-Za-z0-9_]*)", qml))
                self.assertTrue(used, "the widget should use the bar API at all")
                self.assertEqual(set(), used - BAR_API)

    def test_shell_quoting_is_our_own(self):
        # It was bar.shellQuote once, which does not exist.
        for name, qml in WIDGETS.items():
            with self.subTest(plugin=name):
                self.assertNotIn("shellQuote", qml)
                self.assertIn("function quoted(value)", qml)

    def test_every_command_is_quoted(self):
        for name, qml in WIDGETS.items():
            with self.subTest(plugin=name):
                runs = re.findall(r"bar\.run\(([^\n]*)", qml)
                self.assertTrue(runs)
                for call in runs:
                    self.assertIn("quoted(", call, f"unquoted command: {call.strip()}")


class Manifest(unittest.TestCase):
    def test_each_is_json_and_points_at_its_widget(self):
        for name in WIDGETS:
            with self.subTest(plugin=name):
                data = json.loads((PLUGINS / name / "manifest.json").read_text())
                self.assertEqual(name, data["id"])
                self.assertEqual("BarWidget.qml", data["entryPoints"]["barWidget"])

    def test_every_setting_the_widget_reads_has_a_default(self):
        # A setting missing from the manifest reads as undefined in the shell,
        # and the widget falls back silently -- so keep the two in step.
        for name, qml in WIDGETS.items():
            with self.subTest(plugin=name):
                data = json.loads((PLUGINS / name / "manifest.json").read_text())
                asked = set(re.findall(r'setting\("([A-Za-z0-9_]+)"', qml))
                self.assertEqual(set(), asked - set(data["barWidget"]["defaults"]))


if __name__ == "__main__":
    unittest.main()
