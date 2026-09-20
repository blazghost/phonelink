"""Opening a notification's app, for what the notification can't carry.

KDE Connect reaches the phone's own SMS/MMS database but not Signal's,
Messenger's or WhatsApp's. So "open" means phonelink's Messages window for a
texting app, and the Android app itself on a scrcpy virtual display for the
rest.
"""

import os
import subprocess
from pathlib import Path

# The script this package sits beside: lib/phonelink/apps.py -> ./phonelink.
PHONELINK = str(Path(__file__).resolve().parent.parent.parent / "phonelink")


# The phone's own texting apps. Their photos and videos are reachable through
# KDE Connect, so "open" means phonelink's Messages window, not the app.
SMS_APPS = {"com.samsung.android.messaging", "com.google.android.apps.messaging",
            "com.android.mms", "com.android.messaging"}


def open_in_app(package, name=""):
    """Open a notification's app on the desktop, for what the notification
    can't carry: phonelink's Messages window for SMS/MMS, otherwise the Android
    app itself on a scrcpy virtual display. For Signal, Messenger or WhatsApp
    that is the only way to see the photos, videos and the rest of the thread.
    """
    if not package:
        return
    args = [PHONELINK, "messages"] if package in SMS_APPS else [PHONELINK, "desk", package]
    # The name lets a "needs setup" prompt say "Messenger", not com.facebook.orca.
    env = dict(os.environ, PHONELINK_APP_NAME=name) if name else None
    subprocess.Popen(args, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_label(package, app):
    return "Open Messages" if package in SMS_APPS else f"Open {app or 'app'}"
