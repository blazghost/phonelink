"""Opening a notification's app, for what the notification can't carry.

KDE Connect reaches the phone's own SMS/MMS database but not Signal's,
Messenger's or WhatsApp's. So "open" means phonelink's Messages window for a
texting app, and the Android app itself on a scrcpy virtual display for the
rest.
"""

import os
import shutil
import subprocess
from pathlib import Path

# The script this package sits beside: lib/phonelink/apps.py -> ./phonelink.
PHONELINK = str(Path(__file__).resolve().parent.parent.parent / "phonelink")


# The phone's own texting apps. Their photos and videos are reachable through
# KDE Connect, so "open" means phonelink's Messages window, not the app.
SMS_APPS = {"com.samsung.android.messaging", "com.google.android.apps.messaging",
            "com.android.mms", "com.android.messaging"}

# Apps with a client of their own on this laptop: (window pattern, command).
# Open raises that instead of running the phone's copy on a virtual display.
DESKTOP_APPS = {"org.thoughtcrime.securesms": ("^signal$", "signal-desktop")}


def without_layer_shell(preload):
    """LD_PRELOAD minus gtk4-layer-shell, or None when nothing else is left.

    The toast daemon needs the preload and keeps it once loaded, but anything
    it starts inherits the variable. That drags GTK 4 into a GTK 3 app such as
    Signal Desktop, and GTK aborts when it finds both in one process.
    """
    kept = [p for p in (preload or "").split(":")
            if p and os.path.basename(p) != "libgtk4-layer-shell.so"]
    return ":".join(kept) or None


def desktop_command(package):
    """The argv that opens a package's desktop client, or None if it has none."""
    pattern, command = DESKTOP_APPS.get(package, (None, None))
    if not command or not shutil.which(command):
        return None
    if shutil.which("omarchy-launch-or-focus"):
        return ["omarchy-launch-or-focus", pattern, f"uwsm-app -- {command}"]
    return [command]


def open_in_app(package, name=""):
    """Open a notification's app on the desktop, for what the notification
    can't carry: the app's own desktop client when this laptop has one (Signal),
    phonelink's Messages window for SMS/MMS, otherwise the Android app itself
    on a scrcpy virtual display. For Messenger or WhatsApp that is the only
    way to see the photos, videos and the rest of the thread.
    """
    if not package:
        return
    args = (desktop_command(package)
            or ([PHONELINK, "messages"] if package in SMS_APPS else [PHONELINK, "desk", package]))
    # The name lets a "needs setup" prompt say "Messenger", not com.facebook.orca.
    env = dict(os.environ, PHONELINK_APP_NAME=name) if name else None
    subprocess.Popen(args, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_label(package, app):
    return "Open Messages" if package in SMS_APPS else f"Open {app or 'app'}"
