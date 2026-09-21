"""Reading what the phone is playing: clocks, labels and picking a player."""

import unittest

from phonelink import mpris


def snap(**changes):
    state = {"status": mpris.PLAYING, "player": "Spotify", "players": ["Spotify"],
             "title": "Drive", "artist": "The Expanse", "album": "Season One",
             "playing": True, "position": 65000, "length": 245000, "volume": 40,
             "art": "", "can_seek": True}
    state.update(changes)
    return state


class Clock(unittest.TestCase):
    def test_minutes_and_seconds(self):
        self.assertEqual(mpris.clock(65000), "1:05")

    def test_seconds_are_padded(self):
        self.assertEqual(mpris.clock(9000), "0:09")

    def test_an_hour_long_track(self):
        self.assertEqual(mpris.clock(3753000), "1:02:33")

    def test_nothing(self):
        self.assertEqual(mpris.clock(0), "0:00")

    def test_a_negative_position_is_the_start(self):
        self.assertEqual(mpris.clock(-500), "0:00")


class NowPlaying(unittest.TestCase):
    def test_title_and_artist(self):
        self.assertEqual(mpris.now_playing(snap()), "Drive — The Expanse")

    def test_title_alone(self):
        self.assertEqual(mpris.now_playing(snap(artist="")), "Drive")

    def test_artist_alone(self):
        self.assertEqual(mpris.now_playing(snap(title="")), "The Expanse")

    def test_neither_falls_back_to_the_player(self):
        self.assertEqual(mpris.now_playing(snap(title="", artist="")), "Spotify")

    def test_nothing_playing_says_nothing(self):
        self.assertEqual(mpris.now_playing(snap(status=mpris.IDLE)), "")

    def test_no_snapshot_at_all(self):
        self.assertEqual(mpris.now_playing(None), "")


class Describe(unittest.TestCase):
    def test_a_playing_track(self):
        text = mpris.describe(snap())
        self.assertIn("Drive — The Expanse", text)
        self.assertIn("1:05 / 4:05", text)
        self.assertIn("volume 40%", text)

    def test_a_paused_track_is_marked_as_such(self):
        self.assertTrue(mpris.describe(snap(playing=False, status=mpris.PAUSED))
                        .startswith("⏸"))

    def test_idle(self):
        self.assertEqual(mpris.describe(snap(status=mpris.IDLE, player="")),
                         "Nothing is playing")

    def test_a_stream_with_no_length(self):
        text = mpris.describe(snap(length=0))
        self.assertNotIn("/", text)


class PickPlayer(unittest.TestCase):
    PLAYERS = ["Spotify", "YouTube", "YouTube Music"]

    def test_an_exact_name_wins_over_a_longer_one(self):
        self.assertEqual(mpris.pick_player(self.PLAYERS, "YouTube"), "YouTube")

    def test_part_of_a_name(self):
        self.assertEqual(mpris.pick_player(self.PLAYERS, "spot"), "Spotify")

    def test_case_does_not_matter(self):
        self.assertEqual(mpris.pick_player(self.PLAYERS, "SPOTIFY"), "Spotify")

    def test_an_ambiguous_fragment_picks_nothing(self):
        self.assertIsNone(mpris.pick_player(self.PLAYERS, "you"))

    def test_a_player_that_is_not_running(self):
        self.assertIsNone(mpris.pick_player(self.PLAYERS, "Winamp"))

    def test_nothing_asked_for(self):
        self.assertIsNone(mpris.pick_player(self.PLAYERS, ""))


class Actions(unittest.TestCase):
    def test_only_the_actions_the_plugin_takes(self):
        # Anything else is dropped by the phone in silence.
        self.assertEqual(set(mpris.ACTIONS),
                         {"Play", "Pause", "PlayPause", "Next", "Previous", "Stop"})


if __name__ == "__main__":
    unittest.main()
