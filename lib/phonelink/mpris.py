"""The phone's music, over KDE Connect's mprisremote plugin.

Android hands the desktop whatever player is in front -- Spotify, YouTube, a
podcast -- as one remote MPRIS player, and the plugin mirrors its title,
artist, album, position and volume as ordinary D-Bus properties. Reading is a
property fetch; controlling is `sendAction` with one of the names the plugin
itself accepts (Play, Pause, PlayPause, Next, Previous, Stop).

Position is milliseconds on both sides, so seeking is a write to `position`
rather than the plugin's `seek`, whose offset is microseconds on the Android
side and has no way to report that it was refused.
"""

from gi.repository import GLib

from . import kdeconnect as kde

IFACE = "org.kde.kdeconnect.device.mprisremote"

# What sendAction takes. Anything else is ignored by the phone in silence,
# which is worse than an error here.
ACTIONS = ("Play", "Pause", "PlayPause", "Next", "Previous", "Stop")

# A player with nothing loaded still answers, so "is something playing" is
# never just "does the plugin exist".
IDLE, PLAYING, PAUSED = "idle", "playing", "paused"


def path(device_id):
    return f"{kde.DEVICES}/{device_id}/mprisremote"


def state(device_id, timeout=kde.TIMEOUT):
    """What the phone is playing, or None if it has no mprisremote plugin.

    `status` is idle when no player is loaded at all -- the common case, and
    the one the bar widget hides itself for.
    """
    props = kde.properties(path(device_id), IFACE, timeout)
    if props is None:
        return None
    players = list(props.get("playerList") or [])
    title = (props.get("title") or "").strip()
    artist = (props.get("artist") or "").strip()
    playing = bool(props.get("isPlaying"))
    # No player, or one that has nothing loaded, is nothing to show.
    loaded = bool(players) and bool(title or artist)
    return {
        "status": (PLAYING if playing else PAUSED) if loaded else IDLE,
        "player": props.get("player", ""),
        "players": players,
        "title": title,
        "artist": artist,
        "album": (props.get("album") or "").strip(),
        "playing": playing and loaded,
        "position": max(0, int(props.get("position") or 0)),
        "length": max(0, int(props.get("length") or 0)),
        "volume": int(props.get("volume") or 0),
        "art": props.get("localAlbumArtUrl", ""),
        "can_seek": bool(props.get("canSeek")),
    }


def send(device_id, action):
    """Play, Pause, PlayPause, Next, Previous or Stop. Raises on anything else."""
    if action not in ACTIONS:
        raise ValueError(f"not an mpris action: {action}")
    kde.call(path(device_id), IFACE, "sendAction", GLib.Variant("(s)", (action,)))


def set_property(device_id, name, variant):
    kde.call(path(device_id), kde.PROPS, "Set",
             GLib.Variant("(ssv)", (IFACE, name, variant)))


def set_volume(device_id, percent):
    """Volume 0-100. The phone clamps too, but a typo should not reach it."""
    percent = max(0, min(100, int(percent)))
    set_property(device_id, "volume", GLib.Variant("i", percent))
    return percent


def set_player(device_id, name):
    set_property(device_id, "player", GLib.Variant("s", name))


def seek_to(device_id, position_ms):
    """Jump within the track. Milliseconds, as the phone reports them."""
    position_ms = max(0, int(position_ms))
    set_property(device_id, "position", GLib.Variant("i", position_ms))
    return position_ms


def pick_player(players, want):
    """The player a --player argument means, or None.

    An exact name first, so "YouTube" cannot pick "YouTube Music" while both
    are running; otherwise a single case-insensitive partial match.
    """
    if not want:
        return None
    if want in players:
        return want
    hits = [p for p in players if want.lower() in p.lower()]
    return hits[0] if len(hits) == 1 else None


def clock(ms):
    """Milliseconds as 3:07, or 1:02:33 once it runs past an hour."""
    seconds = max(0, int(ms)) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def now_playing(snap):
    """"Title — Artist", or the best of what the phone gave us."""
    if not snap or snap["status"] == IDLE:
        return ""
    if snap["title"] and snap["artist"]:
        return f"{snap['title']} — {snap['artist']}"
    return snap["title"] or snap["artist"] or snap["player"]


def describe(snap):
    """Several lines for a terminal: what is playing, where, and how loud."""
    if snap["status"] == IDLE:
        return "Nothing is playing" + (f" ({snap['player']})" if snap["player"] else "")
    lines = [("▶ " if snap["playing"] else "⏸ ") + now_playing(snap)]
    if snap["album"]:
        lines.append(f"   {snap['album']}")
    where = snap["player"] or "the phone"
    if snap["length"]:
        where += f" · {clock(snap['position'])} / {clock(snap['length'])}"
    lines.append(f"   {where} · volume {snap['volume']}%")
    return "\n".join(lines)
