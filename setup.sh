#!/usr/bin/env bash
# phonelink-setup — the root-only half of phonelink.
#
# Run this once, in a real terminal window:
#
#     sudo ~/Work/phonelink/setup.sh
#
# Everything here is idempotent; running it again is harmless.

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "This needs root. Run:  sudo $0" >&2; exit 1; }
USER_NAME="${SUDO_USER:-}"
[[ -n $USER_NAME ]] || { echo "Run via sudo, not as a root login, so I know who to add to adbusers." >&2; exit 1; }

step() { printf '\n\033[36m==>\033[0m %s\n' "$*"; }

step "Installing packages"
#   kdeconnect     notifications, SMS, clipboard, media keys, file share
#   scrcpy         screen mirroring and control
#   android-tools  adb, which scrcpy drives
#   android-udev   non-root USB access, else adb sees "no permissions"
#   python-gobject, gtk4, libadwaita   the reply window (Omarchy already ships them)
#   gtk4-layer-shell   the notification toasts
pacman -S --needed --noconfirm kdeconnect scrcpy android-tools android-udev python-gobject gtk4 libadwaita gtk4-layer-shell

step "Adding $USER_NAME to the adbusers group (USB access without root)"
if id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx adbusers; then
  echo "    already a member"
else
  usermod -aG adbusers "$USER_NAME"
  echo "    added — this takes effect at your next login"
fi

step "Reloading udev rules so a plugged-in phone is picked up now"
udevadm control --reload-rules
udevadm trigger

step "Opening the KDE Connect ports in ufw"
# KDE Connect discovers and talks over this range; with ufw active and the range
# closed, pairing just silently never finds anything. This is KDE's documented
# requirement, not a guess.
if ufw status | grep -q '1714:1764'; then
  echo "    already open"
else
  ufw allow 1714:1764/tcp comment 'KDE Connect'
  ufw allow 1714:1764/udp comment 'KDE Connect'
fi

cat <<'EOS'

==> Done on the desktop side.

Still to do, by hand:

  1. Install KDE Connect on the phone:
       F-Droid or Play Store -> "KDE Connect"

  2. Log out and back in (picks up the adbusers group and starts the
     KDE Connect daemon).

  3. Pair the two:
       phonelink kde
     Both devices must be on the same network. The phone should appear;
     accept the request on both ends.

  4. For screen mirroring, turn on USB debugging:
       Settings -> About phone -> tap "Build number" 7 times
       Settings -> System -> Developer options -> USB debugging
     Then plug in the cable and run:
       phonelink mirror

  5. Optional, to cut the cable:
       phonelink wifi

Check anything at any time with:  phonelink status
EOS
