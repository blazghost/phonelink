"""Phone calls, as KDE Connect's telephony plugin reports them.

The plugin's callReceived(event, number, name) says a call is ringing, has
been picked up, or was missed. It offers no way back to the phone over D-Bus,
so the buttons go through adb (`phonelink call silence|decline`), the same key
presses as the phone's own volume and end-call keys.

What each event becomes is decided here, so it can be tested without a toast.
"""

import re


def clean_number(number):
    """Only what a phone number is made of: it goes on a command line."""
    return re.sub(r"[^0-9+*#]", "", number or "")


def caller(number, name):
    return name or number or "Unknown caller"


def call_note(device, event, number, name):
    """The toast for a call event, or None when it means the toast should go.

    `buttons` are (label, phonelink arguments) for the daemon to wire up.
    """
    key = f"call:{device}"
    number = clean_number(number)
    base = {"path": key, "app": "Phone", "package": "", "ticker": "", "thread": [],
            "icon": "", "repliable": False, "silent": False, "title": caller(number, name),
            "glyph": "" if name else "\U000f03f2"}  # a handset when there is no name to show
    if event == "ringing":
        return dict(base, sticky=True,
                    text=f"Incoming call · {number}" if name and number else "Incoming call",
                    buttons=[("Silence", ["call", "silence"]), ("Decline", ["call", "decline"])])
    if event == "missedCall":
        return dict(base, sticky=False,
                    text=f"Missed call · {number}" if name and number else "Missed call",
                    buttons=[("Text back", ["text", number])] if number else [])
    return None  # "talking", or anything else: the ringing toast is done
