#!/usr/bin/env python3
"""Start a text to anyone, from the terminal.

    phonelink text 5550134 "on my way"
    phonelink text "Naomi Nagata" "docking in ten"
    phonelink text --attach ~/Pictures/dock.jpg 5550134 "look at this"
    phonelink text --list               the contacts it can text by name

A name has to come out to exactly one contact, from the vCards KDE Connect
syncs; a number is taken as written, since the contact may simply not be
synced. Nothing is asked twice: the message goes as soon as the recipient is
unambiguous, so this can sit on a keybind.

There is no thread to send into, so this is KDE Connect's
`sendWithoutConversation` -- the phone decides which conversation the message
lands in, and the Messages window shows it there a moment later.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gi.repository import GLib  # noqa: E402

from phonelink import kdeconnect as kde  # noqa: E402
from phonelink import sms  # noqa: E402

USAGE = 'usage: phonelink text [--attach FILE] <name or number> <message...>'


def fail(message, code=1):
    print(message, file=sys.stderr)
    return code


def main(argv):
    args, attachments = [], []
    rest = list(argv[1:])
    listing = False
    while rest:
        arg = rest.pop(0)
        if arg == "--attach":
            if not rest:
                return fail(USAGE, 2)
            path = Path(rest.pop(0)).expanduser()
            if not path.is_file():
                return fail(f"no such file: {path}")
            attachments.append(path.resolve())
        elif arg == "--list":
            listing = True
        elif arg in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        elif arg.startswith("--"):
            return fail(f"unknown option: {arg}\n{USAGE}", 2)
        else:
            args.append(arg)

    if kde.BUS is None:
        return fail("no session bus")
    health = kde.health_now()
    if health == kde.GONE:
        return fail("KDE Connect isn't running")
    if health == kde.HUNG:
        return fail("KDE Connect isn't answering -- `phonelink kde restart`")
    device = kde.phone()
    if not device:
        return fail("no phone is reachable")

    people = sms.load_people(device["id"])

    if listing:
        if not people:
            return fail("No contacts are synced. Allow Contacts for KDE Connect on the "
                        "phone (Settings → Apps → KDE Connect → Permissions), then "
                        "reconnect. Numbers work without it.")
        for person in people:
            print(f"{person['name']}\t{sms.pretty_number(person['number'])}")
        return 0

    if not args:
        return fail(USAGE, 2)

    address, who, problem = sms.resolve_recipient(args[0], people)
    if problem:
        return fail(problem)
    text = " ".join(args[1:]).strip()
    if not text and not attachments:
        return fail(f"nothing to send to {who}")

    try:
        kde.send_new_message(device["id"], [address], text, attachments)
    except GLib.Error as exc:
        return fail(kde.friendly_error(exc.message))
    where = who if who != sms.pretty_number(address) else sms.pretty_number(address)
    extra = f" (+{len(attachments)} attached)" if attachments else ""
    print(f"Sent to {where}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
