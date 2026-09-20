"""The notification helper, run as a subprocess.

The windows do not talk to KDE Connect directly for notifications: they run
lib/kdeconnect-notify.py, or whatever PHONELINK_NOTIFY_HELPER points at. That
boundary is what lets a test drive a window with a stub -- fixed conversations,
no phone, no risk of messaging a real contact -- and keeps a wedged daemon from
blocking the GTK main loop.
"""

import json
import os
import subprocess
from pathlib import Path

HELPER = os.environ.get("PHONELINK_NOTIFY_HELPER") or str(
    Path(__file__).resolve().parent.parent / "kdeconnect-notify.py")


def fetch_conversations():
    """(conversations, error) from the helper's `list`."""
    try:
        run = subprocess.run([HELPER, "list"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"Could not run the notification helper: {exc}"
    if run.returncode != 0:
        return None, run.stderr.strip() or "The notification helper failed."
    try:
        return json.loads(run.stdout or "[]"), None
    except json.JSONDecodeError:
        return None, "The notification helper did not return JSON."


def send_argv(path, text):
    """The command that sends a reply, for a caller that wants to run it itself."""
    return [HELPER, "send", path, text]
