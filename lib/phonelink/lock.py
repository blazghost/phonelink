"""The desktop's screen lock: is it on, and put it on.

Omarchy's shell holds the lock (an ext-session-lock), and it tells logind
nothing, so the shell is what gets asked. `loginctl lock-session` is the
fallback for anything else.
"""

import shutil
import subprocess


def locked():
    """True while the screen is locked; False when it is not, or nobody can say."""
    try:
        out = subprocess.run(["omarchy-shell", "lock", "isLocked"], capture_output=True,
                             text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.strip() == "true"


def lock():
    """Lock the screen. True if something took the request."""
    for cmd in (["omarchy-system-lock"], ["loginctl", "lock-session"]):
        if shutil.which(cmd[0]):
            try:
                return subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0
            except subprocess.TimeoutExpired:
                return False
    return False


class Away:
    """When to lock for a phone that has walked off: seen here, then gone `after` seconds.

    Once per departure: after a lock the phone has to come back and leave again,
    so unlocking at a desk the phone never reached does not lock it once more.
    """

    def __init__(self, after):
        self.after = after
        self.seen = False      # the phone has been here since the last lock
        self.gone_at = None    # when it went, while it is gone

    def update(self, reachable, now):
        if reachable:
            self.seen, self.gone_at = True, None
        elif self.seen and self.gone_at is None:
            self.gone_at = now

    def due(self, now):
        if self.gone_at is not None and now - self.gone_at >= self.after:
            self.seen, self.gone_at = False, None
            return True
        return False
