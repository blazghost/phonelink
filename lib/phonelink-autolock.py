#!/usr/bin/env python3
"""phonelink autolock -- lock the desktop when the phone walks away.

A small resident service (phonelink-autolock.service). Every few seconds it
asks KDE Connect whether the phone is reachable; once the phone has been gone
for the configured time -- having been here first -- the screen locks. It never
unlocks anything: coming back only re-arms it.

A KDE Connect that is down or restarting says nothing about the phone, so
those checks are skipped rather than counted as the phone being away.

The delay is read from ~/.config/phonelink/autolock-after, in seconds
(`phonelink autolock on 90` writes it).
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gi.repository import GLib  # noqa: E402

from phonelink import kdeconnect as kde, lock  # noqa: E402

CHECK_S = 5
DEFAULT_AFTER = 60


def log(*parts):
    print("phonelink-autolock:", *parts, file=sys.stderr, flush=True)


def read_after():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    try:
        value = int((base / "phonelink" / "autolock-after").read_text().strip())
    except (OSError, ValueError):
        return DEFAULT_AFTER
    return max(15, value)


def main():
    away = lock.Away(read_after())
    log(f"ready: locks {away.after}s after the phone goes")

    def tick():
        if kde.health_now() != kde.OK:
            return True
        here = kde.phone() is not None
        was = away.gone_at is None
        now = time.monotonic()
        away.update(here, now)
        if was and away.gone_at is not None:
            log("the phone went away")
        if away.due(now) and not lock.locked():
            log("the phone has been gone a while: locking")
            lock.lock()
        return True

    tick()
    GLib.timeout_add_seconds(CHECK_S, tick)
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
