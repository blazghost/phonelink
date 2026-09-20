"""The palette: where colours come from, and what the CSS does with them."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from phonelink import theme


class IsHex(unittest.TestCase):
    def test_accepts_a_six_digit_colour(self):
        self.assertTrue(theme.is_hex("#1d1d20"))
        self.assertTrue(theme.is_hex("#FFFFFF"))

    def test_rejects_everything_else(self):
        for value in ("#fff", "1d1d20", "", None, "#12345g", 0x1d1d20):
            with self.subTest(value=value):
                self.assertFalse(theme.is_hex(value))


class Palette(unittest.TestCase):
    def state(self, colors_toml=None):
        """An XDG state dir, with a theme in it when one is wanted."""
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if colors_toml is not None:
            folder = Path(tmp.name) / "omarchy/current/theme"
            folder.mkdir(parents=True)
            (folder / "colors.toml").write_text(colors_toml)
        return tmp.name

    def load(self, colors_toml=None, env=None):
        environ = {"XDG_STATE_HOME": self.state(colors_toml)}
        environ.update(env or {})
        with mock.patch.dict("os.environ", environ, clear=True):
            return theme.load_palette()

    def test_falls_back_to_adwaita_dark(self):
        pal = self.load()
        self.assertEqual(pal["accent"], theme.FALLBACK["accent"])
        self.assertEqual(pal["mode"], "dark")

    def test_theme_colours_win(self):
        pal = self.load('accent = "#f0a52c"\nbackground = "#0d1117"\n')
        self.assertEqual(pal["accent"], "#f0a52c")
        self.assertEqual(pal["background"], "#0d1117")

    def test_theme_beats_the_gum_environment(self):
        pal = self.load('accent = "#f0a52c"\n',
                        env={"GUM_INPUT_PROMPT_FOREGROUND": "#ff0000"})
        self.assertEqual(pal["accent"], "#f0a52c")

    def test_gum_is_used_when_there_is_no_theme(self):
        pal = self.load(env={"GUM_INPUT_PROMPT_FOREGROUND": "#ff0000"})
        self.assertEqual(pal["accent"], "#ff0000")

    def test_rubbish_in_colors_toml_is_ignored(self):
        pal = self.load('accent = "not a colour"\nmode = "sideways"\n')
        self.assertEqual(pal["accent"], theme.FALLBACK["accent"])
        self.assertEqual(pal["mode"], "dark")

    def test_a_broken_colors_toml_does_not_raise(self):
        self.assertEqual(self.load("this is not toml = = =")["accent"],
                         theme.FALLBACK["accent"])

    def test_light_mode_is_kept(self):
        self.assertEqual(self.load('mode = "light"\n')["mode"], "light")

    def test_every_fallback_key_survives(self):
        self.assertEqual(set(self.load('accent = "#f0a52c"\n')), set(theme.FALLBACK))


class Ink(unittest.TestCase):
    PAL = {"background": "#000000", "foreground": "#ffffff"}

    def test_dark_ink_on_a_light_background(self):
        self.assertEqual(theme.ink_on(self.PAL, "#ffee88"), "#000000")

    def test_light_ink_on_a_dark_background(self):
        self.assertEqual(theme.ink_on(self.PAL, "#101010"), "#ffffff")

    def test_luminance_orders_black_under_white(self):
        self.assertLess(theme.luminance("#000000"), theme.luminance("#ffffff"))


class Css(unittest.TestCase):
    def setUp(self):
        self.pal = dict(theme.FALLBACK, accent="#f0a52c")
        self.css = theme.build_css(self.pal)

    def test_the_accent_reaches_the_stylesheet(self):
        self.assertIn("#f0a52c", self.css)

    def test_libadwaita_variables_are_defined(self):
        for var in ("--window-bg-color", "--accent-bg-color", "--sidebar-bg-color"):
            with self.subTest(var=var):
                self.assertIn(var, self.css)

    def test_an_avatar_colour_per_hue(self):
        self.assertEqual(self.css.count("avatar.color"), 14)

    def test_bubbles_are_styled_both_ways(self):
        self.assertIn(".bubble.in", self.css)
        self.assertIn(".bubble.out", self.css)


if __name__ == "__main__":
    unittest.main()
