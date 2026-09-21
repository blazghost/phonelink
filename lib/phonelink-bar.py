#!/usr/bin/env python3
"""What the phone is doing, as one line of JSON -- for the Omarchy bar widget.

    phonelink bar            {"state":"ok","device":"Pixel","battery":72,...}
    phonelink bar --pretty   the same, indented, for reading in a terminal

The widget runs this every few seconds, so it says what it knows quickly and
never waits long on a phone that has gone quiet: every call has a short
timeout, and a daemon that is wedged is reported as such rather than hung on.

    state     ok | away | hung | gone
              away means KDE Connect is fine but no phone is reachable
    battery   0-100, or null when the phone does not report one
    charging  true while it is plugged in
    bars      cellular signal 0-4, or null when Android has not granted the
              phone-state permission (it reports -1 then, which is "unknown")
    network   LTE, 5G and so on, when the phone says
    waiting   messages you could answer from here, right now
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from phonelink import kdeconnect as kde  # noqa: E402


def snapshot():
    if kde.BUS is None:
        return {"state": "gone", "reason": "no session bus"}

    health = kde.health_now()
    if health != kde.OK:
        # Wedged or not running: say which, so the widget can show the same
        # thing the toast service does rather than a stale battery reading.
        return {"state": health}

    device = kde.phone()
    if not device:
        return {"state": "away"}

    battery = kde.battery(device["id"]) or {}
    signal = kde.signal_strength(device["id"]) or {}
    # One entry per conversation, not per notification: two messages in the
    # same chat are one thing waiting for you.
    seen, waiting = set(), []
    for note in kde.notifications(repliable_only=True):
        key = (note["app"], note["title"])
        if note["conversation"] and key not in seen:
            seen.add(key)
            waiting.append(note)
    return {
        "state": "ok",
        "device": device["name"],
        "battery": battery.get("charge"),
        "charging": battery.get("charging", False),
        "bars": signal.get("bars"),
        "network": signal.get("network", ""),
        "waiting": len(waiting),
        "from": [n["title"] or n["app"] for n in waiting[:4]],
    }


def main(argv):
    data = snapshot()
    indent = 2 if "--pretty" in argv else None
    json.dump(data, sys.stdout, indent=indent)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
