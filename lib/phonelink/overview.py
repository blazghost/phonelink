"""What the window's Overview shows, read off KDE Connect without any GTK.

`snapshot()` is the whole of it in one dict, and it waits on D-Bus, so the
window calls it on a worker thread and draws the result on the main loop.
"""

from . import kdeconnect as kde, mpris

PAGES = ("overview", "messages", "photos", "remote", "settings")
BARS = "▂▄▆█"


def snapshot():
    """{state, name, battery, signal, media, notes}; state is ok, away, hung or gone."""
    health = kde.health_now()
    if health != kde.OK:
        return {"state": health}
    device = kde.phone()
    if not device:
        return {"state": "away"}
    did = device["id"]
    notes = [n for n in kde.notifications() if n["device"] == did]
    return {
        "state": "ok",
        "id": did,
        "name": device["name"],
        "battery": kde.battery(did),
        "signal": kde.signal_strength(did),
        "media": mpris.state(did),
        "notes": notes,
    }


def chips(snap):
    """The short status pills beside the phone's name."""
    if snap["state"] != "ok":
        return [{"away": "Not connected", "hung": "KDE Connect isn't answering",
                 "gone": "KDE Connect isn't running"}[snap["state"]]]
    out = ["Connected"]
    battery = snap.get("battery")
    if battery and battery["charge"] >= 0:
        out.append(f"{battery['charge']}%" + (" ⚡" if battery["charging"] else ""))
    if signal := snap.get("signal"):
        out.append(f"{signal['network']} {BARS[:max(0, min(4, signal['bars']))]}".strip())
    return out


def parse_args(argv):
    """(page, new_to) from `--page NAME` or `--new [who]`; new_to None means no composer."""
    if "--new" in argv:
        rest = [a for a in argv[argv.index("--new") + 1:] if not a.startswith("-")]
        return "messages", " ".join(rest).strip()
    if "--page" in argv and argv.index("--page") + 1 < len(argv):
        page = argv[argv.index("--page") + 1]
        return (page if page in PAGES else "overview"), None
    return "overview", None
