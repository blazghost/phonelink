"""The bar widget is QML, so the suite cannot run it -- but it can read it.

These catch the mistake that shipped in the first version: calling a helper the
Omarchy bar does not hand plugins, which only shows up as a TypeError in the
shell's log the first time somebody clicks.
"""

import re
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / "integration/omarchy-plugin/phonelink.phone"
QML = (PLUGIN / "BarWidget.qml").read_text()

# Everything Ui/PluginBarApi.qml exposes to a plugin. Anything else is a
# TypeError at click time, so the widget may only reach for these.
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
    def test_the_widget_only_touches_members_the_bar_has(self):
        used = set(re.findall(r"\bbar\.([A-Za-z_][A-Za-z0-9_]*)", QML))
        self.assertTrue(used, "the widget should use the bar API at all")
        self.assertEqual(set(), used - BAR_API)

    def test_shell_quoting_is_our_own(self):
        # It was bar.shellQuote once, which does not exist.
        self.assertNotIn("shellQuote", QML)
        self.assertIn("function quoted(value)", QML)

    def test_every_command_is_quoted(self):
        runs = re.findall(r"bar\.run\(([^\n]*)", QML)
        self.assertTrue(runs)
        for call in runs:
            self.assertIn("quoted(", call, f"unquoted command: {call.strip()}")


class Manifest(unittest.TestCase):
    def test_it_is_json_and_points_at_the_widget(self):
        import json

        data = json.loads((PLUGIN / "manifest.json").read_text())
        self.assertEqual("phonelink.phone", data["id"])
        self.assertTrue((PLUGIN / "BarWidget.qml").exists())


if __name__ == "__main__":
    unittest.main()
