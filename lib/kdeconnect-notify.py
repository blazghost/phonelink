#!/usr/bin/env python3
"""KDE Connect notification reply, over D-Bus -- the command-line face of it.

The windows run this rather than calling kdeconnectd themselves, so a test can
put a stub in its place (PHONELINK_NOTIFY_HELPER) and drive a window with fixed
conversations, no phone attached.

    kdeconnect-notify.py list                  -> JSON array, newest first
    kdeconnect-notify.py send <objpath> <text>
    kdeconnect-notify.py dismiss <objpath>     clear it on the phone too

Everything it does lives in phonelink.kdeconnect; this is argument handling and
the two exit codes.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gi.repository import GLib  # noqa: E402

from phonelink import kdeconnect as kde  # noqa: E402

USAGE = ("usage: kdeconnect-notify.py list"
         " | kdeconnect-notify.py send <objpath> <text>"
         " | kdeconnect-notify.py dismiss <objpath>")

# What `list` has always printed: only the notifications you can answer, and
# without the two fields that are the toast service's business alone.
LIST_FIELDS = ("path", "id", "device", "app", "title", "text", "ticker",
               "thread", "conversation", "icon", "package")


def main(argv):
    if kde.BUS is None:
        sys.exit("cannot reach the session bus")

    if len(argv) == 2 and argv[1] == "list":
        notes = [{k: note[k] for k in LIST_FIELDS}
                 for note in kde.notifications(repliable_only=True)]
        json.dump(notes, sys.stdout)
        sys.stdout.write("\n")
        return 0

    if len(argv) == 4 and argv[1] == "send":
        path, text = argv[2], argv[3]
        if not text.strip():
            sys.exit("refusing to send an empty reply")
        try:
            kde.send_reply(path, text)
        except GLib.Error as exc:
            # The usual cause is the notification being dismissed on the phone
            # while you were typing; the object disappears with it.
            sys.exit(f"reply failed: {exc.message}")
        return 0

    if len(argv) == 3 and argv[1] == "dismiss":
        # Not an error when it fails: the notification being gone from the
        # phone already is the outcome this asks for.
        print("dismissed" if kde.dismiss(argv[2]) else "already gone")
        return 0

    sys.exit(USAGE)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
