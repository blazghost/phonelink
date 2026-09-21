#!/usr/bin/env python3
"""What the phone is playing, and the buttons for it.

    phonelink media                  what is playing, in a few lines
    phonelink media --json           one line of JSON (the bar widget reads this)
    phonelink media toggle           play or pause, whichever it isn't
    phonelink media play|pause|next|previous|stop
    phonelink media volume [0-100|+10|-10]
    phonelink media seek <+/-seconds>
    phonelink media players          which players the phone is offering
    phonelink media --player NAME ...  act on one of them by name

KDE Connect's mprisremote plugin mirrors whichever player is in front on the
phone, so this controls that -- it never plays anything on the desktop. Audio
stays on the phone; only the buttons are here.

The JSON is the same shape the bar reads elsewhere: a `state` of ok, away,
hung or gone, so a wedged daemon shows as itself rather than as silence.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gi.repository import GLib  # noqa: E402

from phonelink import kdeconnect as kde  # noqa: E402
from phonelink import mpris  # noqa: E402

USAGE = ("usage: phonelink media [--json] [--player NAME] "
         "[play|pause|toggle|next|previous|stop|volume [N]|seek ±S|players]")

# A signed number argument: -10 is a quieter phone, not an option.
SIGNED = re.compile(r"[-+]\d+(?:\.\d+)?")

# What a word on the command line means to the plugin. `toggle` is ours: the
# plugin's PlayPause does the same thing, but "toggle" is what a keybind says.
VERBS = {
    "play": "Play", "pause": "Pause", "toggle": "PlayPause", "playpause": "PlayPause",
    "next": "Next", "skip": "Next", "previous": "Previous", "prev": "Previous",
    "back": "Previous", "stop": "Stop",
}


def fail(message, code=1):
    print(message, file=sys.stderr)
    return code


def phone_or_none():
    """(device, snapshot-of-trouble): exactly one of them is None."""
    if kde.BUS is None:
        return None, {"state": "gone", "reason": "no session bus"}
    health = kde.health_now()
    if health != kde.OK:
        return None, {"state": health}
    device = kde.phone()
    if not device:
        return None, {"state": "away"}
    return device, None


def snapshot(device, want_player):
    """The JSON the widget reads: the phone's player, flattened."""
    snap = mpris.state(device["id"])
    if snap is None:
        return {"state": "ok", "status": mpris.IDLE, "device": device["name"],
                "reason": "no mprisremote plugin"}
    if want_player and (chosen := mpris.pick_player(snap["players"], want_player)):
        if chosen != snap["player"]:
            mpris.set_player(device["id"], chosen)
            snap = mpris.state(device["id"]) or snap
    return {
        "state": "ok",
        "device": device["name"],
        "status": snap["status"],
        "playing": snap["playing"],
        "title": snap["title"],
        "artist": snap["artist"],
        "album": snap["album"],
        "player": snap["player"],
        "players": snap["players"],
        "position": snap["position"],
        "length": snap["length"],
        "volume": snap["volume"],
        "canSeek": snap["can_seek"],
        "text": mpris.now_playing(snap),
    }


def act(device, verb, argument, want_player):
    """One of the buttons. Returns a process exit code."""
    snap = mpris.state(device["id"])
    if snap is None:
        return fail(f"{device['name']} has no media plugin "
                    "(enable mprisremote in KDE Connect on the phone)")

    if want_player:
        chosen = mpris.pick_player(snap["players"], want_player)
        if not chosen:
            known = ", ".join(snap["players"]) or "none"
            return fail(f"no player called {want_player} on {device['name']} (running: {known})")
        mpris.set_player(device["id"], chosen)
        snap = mpris.state(device["id"]) or snap

    if verb == "players":
        if not snap["players"]:
            print(f"{device['name']} is offering no players")
            return 0
        for name in snap["players"]:
            print(("* " if name == snap["player"] else "  ") + name)
        return 0

    if verb == "volume":
        if argument is None:
            print(f"{snap['volume']}%")
            return 0
        if argument[:1] in "+-" and argument[1:].isdigit():
            level = snap["volume"] + int(argument)
        elif argument.isdigit():
            level = int(argument)
        else:
            return fail("volume takes 0-100, or +10 / -10")
        print(f"{mpris.set_volume(device['id'], level)}%")
        return 0

    if verb == "seek":
        if argument is None:
            return fail("seek takes seconds: phonelink media seek +30")
        try:
            delta = float(argument)
        except ValueError:
            return fail("seek takes seconds: phonelink media seek +30")
        if not snap["can_seek"]:
            return fail(f"{snap['player'] or 'this player'} cannot seek")
        where = snap["position"] + int(delta * 1000)
        if snap["length"]:
            where = min(where, snap["length"])
        print(mpris.clock(mpris.seek_to(device["id"], where)))
        return 0

    action = VERBS[verb]
    # Nothing loaded: pressing play on a phone with no player does nothing at
    # all, silently, which reads as phonelink being broken.
    if snap["status"] == mpris.IDLE:
        return fail(f"nothing is playing on {device['name']}")
    mpris.send(device["id"], action)
    return 0


def main(argv):
    args, as_json, want_player = [], False, ""
    rest = list(argv[1:])
    while rest:
        arg = rest.pop(0)
        if arg == "--json":
            as_json = True
        elif arg == "--player":
            if not rest:
                return fail(USAGE, 2)
            want_player = rest.pop(0)
        elif arg in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        elif arg.startswith("-") and not SIGNED.fullmatch(arg):
            # "-5" and "-30" are how you turn the volume down and rewind, so a
            # leading minus is only an option when digits do not follow it.
            return fail(f"unknown option: {arg}\n{USAGE}", 2)
        else:
            args.append(arg)

    verb = (args[0] if args else "").lower()
    argument = args[1] if len(args) > 1 else None
    if verb and verb not in VERBS and verb not in ("volume", "seek", "players", "status"):
        return fail(f"unknown command: {verb}\n{USAGE}", 2)

    device, trouble = phone_or_none()
    if trouble:
        if as_json:
            json.dump(trouble, sys.stdout)
            sys.stdout.write("\n")
            return 0
        return fail({"gone": "KDE Connect isn't running",
                     "hung": "KDE Connect isn't answering -- `phonelink kde restart`",
                     "away": "no phone is reachable"}[trouble["state"]])

    try:
        if not verb or verb == "status":
            data = snapshot(device, want_player)
            if as_json:
                json.dump(data, sys.stdout)
                sys.stdout.write("\n")
                return 0
            snap = mpris.state(device["id"])
            if snap is None:
                return fail(f"{device['name']} has no media plugin "
                            "(enable mprisremote in KDE Connect on the phone)")
            print(mpris.describe(snap))
            return 0
        return act(device, verb, argument, want_player)
    except GLib.Error as exc:
        return fail(kde.friendly_error(exc.message))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
