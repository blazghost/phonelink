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
#   sshfs          mounts the phone's storage for the Photos window
pacman -S --needed --noconfirm kdeconnect scrcpy android-tools android-udev python-gobject gtk4 libadwaita gtk4-layer-shell sshfs

step "A virtual webcam for the phone's camera (v4l2loopback)"
#   v4l2loopback-dkms  a camera device other apps can open; phonelink webcam
#                      fills it from the phone. dkms builds it for this kernel,
#                      which needs the kernel's headers package installed.
pacman -S --needed --noconfirm dkms v4l2loopback-dkms
printf 'v4l2loopback\n' >/etc/modules-load.d/phonelink-webcam.conf
# exclusive_caps: browsers only list a loopback device as a camera with it.
printf 'options v4l2loopback card_label="Phone camera" exclusive_caps=1\n' \
  >/etc/modprobe.d/phonelink-webcam.conf
if grep -qx 'Phone camera' /sys/class/video4linux/video*/name 2>/dev/null; then
  echo "    already loaded"
elif lsmod | grep -q '^v4l2loopback'; then
  echo "    v4l2loopback is loaded with other settings; it picks these up at the next boot"
else
  modprobe v4l2loopback && echo "    loaded"
fi

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

step "Opening the KDE Connect ports in ufw, to local networks only"
# KDE Connect discovers and talks over this range; with ufw active and the range
# closed, pairing just silently never finds anything. This is KDE's documented
# requirement, not a guess. Only from private and tailnet addresses, though: a
# laptop handed a public address -- or any IPv6 one -- must not be answering the
# internet on them. PHONELINK_TRUSTED_NETS narrows it further, say to the home
# LAN alone (sudo PHONELINK_TRUSTED_NETS=192.168.2.0/24 ./setup.sh), at the cost
# of the phone's own hotspot, whose subnet Android picks at random.
TRUSTED_NETS=${PHONELINK_TRUSTED_NETS:-10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10}
# What earlier versions opened, to every address: taken back out, highest
# number first so the ones below keep theirs.
mapfile -t open_rules < <(ufw status numbered \
  | awk -F'[][]' '/1714:1764/ && /ALLOW IN +Anywhere/ {print $2 + 0}' | sort -rn)
for n in "${open_rules[@]}"; do ufw --force delete "$n" >/dev/null; done
(( ${#open_rules[@]} )) && echo "    closed the old rule open to every address"
for net in $TRUSTED_NETS; do
  for proto in tcp udp; do
    ufw allow proto "$proto" from "$net" to any port 1714:1764 comment 'KDE Connect' >/dev/null
  done
done
echo "    open to: $TRUSTED_NETS"

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
