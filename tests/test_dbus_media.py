"""The phone's media controls, against the fake KDE Connect.

The fake keeps what it is "playing" in a file this test writes, so each case
is set up rather than left over from the one before -- and pressing pause here
can never pause somebody's actual music.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEDIA = HERE.parent / "lib" / "phonelink-media.py"
ON_TEST_BUS = os.environ.get("PHONELINK_TEST_BUS") == "1"

IDLE = {"playerList": [], "player": "", "title": "", "artist": "", "album": "",
        "isPlaying": False, "length": 0, "position": 0, "canSeek": False}


@unittest.skipUnless(ON_TEST_BUS, "needs the private bus from tests/run.sh")
class Media(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state_file = Path(cls.tmp.name) / "mpris.json"
        env = dict(os.environ, PHONELINK_FAKE_MPRIS=str(cls.state_file))
        cls.fake = subprocess.Popen([sys.executable, str(HERE / "fake_kdeconnect.py")],
                                    stdout=subprocess.PIPE, text=True, env=env)
        line = cls.fake.stdout.readline()
        if "ready" not in line:
            cls.fake.kill()
            raise AssertionError(f"fake kdeconnect did not start: {line.strip()}")

    @classmethod
    def tearDownClass(cls):
        cls.fake.terminate()
        cls.fake.wait(timeout=5)
        cls.fake.stdout.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.playing()

    # -- the fake phone's player

    def playing(self, **changes):
        state = {"playerList": ["Spotify", "Podcasts"], "player": "Spotify",
                 "title": "Drive", "artist": "The Expanse", "album": "Season One",
                 "isPlaying": True, "position": 65000, "length": 245000,
                 "volume": 40, "canSeek": True, "localAlbumArtUrl": ""}
        state.update(changes)
        self.state_file.write_text(json.dumps(state))
        return state

    def state(self):
        return json.loads(self.state_file.read_text())

    def media(self, *args):
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "lib"))
        return subprocess.run([sys.executable, str(MEDIA), *args],
                              capture_output=True, text=True, env=env, timeout=30)

    def json(self, *args):
        run = self.media("--json", *args)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    # -- reading

    def test_the_json_is_about_the_phone_not_the_desktop(self):
        self.assertEqual(self.json()["device"], "Test Phone")

    def test_what_is_playing(self):
        data = self.json()
        self.assertEqual((data["status"], data["title"], data["artist"]),
                         ("playing", "Drive", "The Expanse"))

    def test_the_widgets_one_line_of_text(self):
        self.assertEqual(self.json()["text"], "Drive — The Expanse")

    def test_a_paused_player_is_still_loaded(self):
        self.playing(isPlaying=False)
        data = self.json()
        self.assertEqual(data["status"], "paused")
        self.assertFalse(data["playing"])

    def test_nothing_playing_is_idle_not_an_error(self):
        self.playing(**IDLE)
        data = self.json()
        self.assertEqual(data["status"], "idle")
        self.assertEqual(data["text"], "")

    def test_the_terminal_form_names_the_track(self):
        run = self.media()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Drive — The Expanse", run.stdout)
        self.assertIn("40%", run.stdout)

    def test_the_terminal_form_when_nothing_plays(self):
        self.playing(**IDLE)
        self.assertIn("Nothing is playing", self.media().stdout)

    # -- the buttons

    def test_toggle_pauses_what_is_playing(self):
        self.assertEqual(self.media("toggle").returncode, 0)
        self.assertFalse(self.state()["isPlaying"])

    def test_toggle_plays_what_is_paused(self):
        self.playing(isPlaying=False)
        self.media("toggle")
        self.assertTrue(self.state()["isPlaying"])

    def test_pause(self):
        self.media("pause")
        self.assertFalse(self.state()["isPlaying"])

    def test_next_and_previous(self):
        self.media("next")
        self.assertEqual(self.state()["title"], "Next track")
        self.media("previous")
        self.assertEqual(self.state()["title"], "Previous track")

    def test_pressing_play_with_nothing_loaded_says_so(self):
        self.playing(**IDLE)
        run = self.media("play")
        # Rather than sending an action the phone would silently drop.
        self.assertEqual(run.returncode, 1)
        self.assertIn("nothing is playing", run.stderr.lower())
        self.assertFalse(self.state()["isPlaying"])

    # -- volume and seeking

    def test_volume_is_reported_on_its_own(self):
        self.assertEqual(self.media("volume").stdout.strip(), "40%")

    def test_volume_by_steps(self):
        self.media("volume", "+15")
        self.assertEqual(self.state()["volume"], 55)
        self.media("volume", "-5")
        self.assertEqual(self.state()["volume"], 50)

    def test_volume_is_clamped_rather_than_sent_as_typed(self):
        self.media("volume", "500")
        self.assertEqual(self.state()["volume"], 100)

    def test_volume_that_is_not_a_number(self):
        run = self.media("volume", "loud")
        self.assertEqual(run.returncode, 1)
        self.assertEqual(self.state()["volume"], 40)

    def test_seeking_moves_the_position(self):
        self.media("seek", "+30")
        self.assertEqual(self.state()["position"], 95000)

    def test_seeking_backwards(self):
        self.media("seek", "-30")
        self.assertEqual(self.state()["position"], 35000)

    def test_seeking_never_goes_past_the_start(self):
        self.media("seek", "-600")
        self.assertEqual(self.state()["position"], 0)

    def test_seeking_stops_at_the_end_of_the_track(self):
        self.media("seek", "+600")
        self.assertEqual(self.state()["position"], 245000)

    def test_a_player_that_cannot_seek_is_not_asked_to(self):
        self.playing(canSeek=False)
        run = self.media("seek", "+30")
        self.assertEqual(run.returncode, 1)
        self.assertEqual(self.state()["position"], 65000)

    # -- several players

    def test_players_are_listed_with_the_current_one_marked(self):
        out = self.media("players").stdout
        self.assertIn("* Spotify", out)
        self.assertIn("  Podcasts", out)

    def test_a_named_player_is_selected_before_acting(self):
        self.media("--player", "Podcasts", "pause")
        self.assertEqual(self.state()["player"], "Podcasts")

    def test_a_player_that_is_not_running(self):
        run = self.media("--player", "Winamp", "pause")
        self.assertEqual(run.returncode, 1)
        self.assertIn("Winamp", run.stderr)
        self.assertEqual(self.state()["player"], "Spotify")

    def test_an_unknown_command_is_refused_before_the_phone_is_touched(self):
        run = self.media("explode")
        self.assertEqual(run.returncode, 2)
        self.assertTrue(self.state()["isPlaying"])


if __name__ == "__main__":
    unittest.main()
