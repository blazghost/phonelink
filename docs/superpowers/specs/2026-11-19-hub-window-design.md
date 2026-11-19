# One phonelink window (Caelestia Connect's look), plus remote input and a webcam

## Why

The user saw [Caelestia Connect](https://github.com/KingSahil/caelestia-connect)
and found the features both projects share cleaner there. The difference is one
window: a device card, a grid of action tiles, a media card and the phone's
notifications on an Overview page, with Messages, Remote input and Settings as
tabs. phonelink spreads the same things over separate windows, a bar widget and
toasts. They also want three Caelestia features phonelink lacks: a remote
touchpad and keyboard, the phone camera as a webcam, and sharing the mouse with
the phone past a screen edge.

Installing Caelestia instead was considered and declined: it replaces
kdeconnectd (same UDP port), is four weeks old, and would take phonelink's
toasts, reply window, Messages, Photos and bar widget down with it.

## Goals / non-goals / anti-goals

- **Goal:** one window, Caelestia's layout, Omarchy's theme colours.
- **Goal:** the three features, built on what KDE Connect 26.08, scrcpy 5 and
  xdg-desktop-portal-hyprland 1.4 already provide.
- **Non-goal:** a device sidebar. There is one phone; the device card says which.
- **Non-goal:** replacing the toasts, the reply window or the bar widget. They
  stay; the bar's click opens the window.
- **Anti-goal:** copying Caelestia's code. It is GPL-3.0 and phonelink is MIT;
  the look is rebuilt, nothing is copied.
- **Anti-goal:** a window that blocks on the phone. Every phone call that can
  stall runs off the main loop or behind the existing short D-Bus timeouts.

## Approaches

1. **Three PRs (picked by the user).** Window first, then remote input and
   mouse sharing, then the webcam. Each is judged from screenshots before the
   next starts, and the webcam's prerequisites (sudo, adb) block only the last.
2. One PR with everything. Fewer merges, but one large review, and nothing
   lands until the webcam prerequisites are sorted.

For the mouse sharing specifically: KDE Connect 26.08 ships
`kdeconnect_shareinputdevices` (off by default), which does the edge capture
over the InputCapture portal that xdph 1.4.1 implements. phonelink turns it on
and sets its edge; Caelestia's own ~500-line libei capture is not repeated.

## PR 1 — the window

- `lib/phonelink-app.py`, app id `org.omarchy.phonelink.app`, one instance.
  Header bar with a pill-styled `Adw.ViewSwitcher`: **Overview · Messages ·
  Photos**. Arguments `--page NAME` and `--new [who]`; a second launch hands
  them to the open window over GApplication actions, as `phonelink text` does
  today.
- **Overview:** device card (name, Connected/away chip, battery, signal);
  action tiles that run the existing commands (`ring`, `send`, `clip`,
  `mirror`, `desk`, `drop`); a media card over `phonelink.mpris` (art, title,
  artist, previous / play-pause / next, seek, volume) shown only when something
  is loaded; the phone's notifications with dismiss and Clear all. Phone state
  is polled every couple of seconds off the main loop while Overview is shown.
- **Messages / Photos:** the existing windows become page widgets
  (`lib/phonelink/messages_page.py`, `lib/phonelink/photos_page.py`), built the
  first time their tab is opened, so the window never mounts the phone's
  storage unasked.
- `phonelink app` opens Overview; `phonelink messages`, `photos` and `text`
  open the window on their tab. The old per-window app ids go; the opaque
  window rule moves to the new id.

## PR 2 — Remote and mouse sharing

- **Remote tab:** a touchpad area (drag → `remotecontrol.moveCursor`, click /
  right / middle / scroll → `sendCommand`), and a keyboard field whose key
  presses go to `remotekeyboard.sendKeyPress`, with the phone's `remoteState`
  shown ("KDE Connect keyboard not active on the phone").
- **Settings tab:** "Share mouse and keyboard" switch → `setPluginEnabled
  kdeconnect_shareinputdevices` plus the edge choice the plugin reads.
- Phone side, said in the UI: KDE Connect's *Remote input* accessibility
  permission; the KDE Connect keyboard selected for typing.

**Found while building PR 2 (2026-11-19):** KDE Connect 26.08's
`kdeconnect_shareinputdevices` creates its InputCapture session through
xdg-desktop-portal-hyprland 1.4.1, but sends `barrier_id` as `i` where the
portal spec says `u`; xdph then reports the barrier failed
(`failed_barriers = [0]`), so the pointer is never captured at the edge. A
probe setting the same barrier with a `u` id is accepted (`failed = []`). The
plugin cannot work on Hyprland until KDE Connect (or xdph) changes, so PR 2
ships the Remote tab alone and mouse sharing waits on the user's call:
phonelink's own InputCapture + libei client, or an upstream fix.

**Mouse sharing, built in phonelink (2026-11-19, the user's call):** a user
service (`lib/phonelink-mouse.py`, `phonelink mouse on|off|status`, a switch
on a new Settings tab) holds its own InputCapture session with an unsigned
barrier id, reads the captured input over libei (ctypes, with xkbcommon for
keys) and drives the phone through the Remote tab's calls. The phone never
reports its pointer, so the way home is reckoned: pinned at its edge on
entry, counted from there; Ctrl+Alt+Esc always gives it back, and the portal
session dies with the process.

## PR 3 — the webcam

- `phonelink webcam [front|back|off]`: scrcpy `--video-source=camera
  --v4l2-sink=/dev/videoN --no-window` while it is on; a toggle and camera
  choice in Settings and a tile on Overview.
- `setup.sh` installs `v4l2loopback-dkms` and a `modules-load.d` /
  `modprobe.d` entry (`card_label="Phone camera" exclusive_caps=1`).
- Needs adb (`phonelink wifi`) and Android 12+.
- As built (2026-11-19): a transient `systemd-run --user` unit rather than a
  unit file; 720p30 asked of the phone itself (scrcpy refuses `--max-size`
  with `--camera-size`); the device is found by its label, not a fixed
  number, since the Surface's IPU6 already holds /dev/video0-63.

## Left to the builder

Exact spacing and radii (match Caelestia's screenshots in the Omarchy palette),
poll intervals, which tiles go first.
