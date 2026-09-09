# phonelink

One front-end for Android on Omarchy/Hyprland.

## Why this exists rather than a new app

There is no single "Phone Link for Linux", and writing one would mean
reimplementing a pairing protocol, a notification bridge and a video encoder
that already exist and are better than anything worth building here. The pieces
are all good; what was missing was a single place to reach them.

| Layer | Tool | Does |
|---|---|---|
| Pairing, notifications, SMS, clipboard, media keys, file share, find-my-phone | **KDE Connect** | the actual "phone link" |
| Screen mirroring, control, virtual displays | **scrcpy** | ~30ms latency, no root, no account |
| Drop a file on any device on the LAN | **LocalSend** | AirDrop-shaped, cross-platform |
| Wireless setup, file moves | **adb** | plumbing |

`phonelink` is glue over those. It works out which device you mean, remembers
your wireless endpoint across reboots, and when something is missing it says
exactly which command fixes it instead of printing a stack trace.

## Install

```sh
git clone https://github.com/blazghost/phonelink.git
cd phonelink
./install.sh        # links phonelink onto PATH, wires up the Omarchy menu + window rules
sudo ./setup.sh     # packages, udev rules, ufw ports
```

Both are idempotent and back up every file they touch. `install.sh` needs no
root and degrades gracefully off Omarchy — you keep the command, you just lose
the menu entry and the window rules.

Then install KDE Connect on the phone and pair with `phonelink kde`.
`setup.sh` prints the full checklist.

The log-out that `setup.sh` asks for is only needed for **USB** adb, which
wants the `adbusers` group your running session does not have yet. Wireless
(`phonelink pair`) is a TCP connection with no device node, so it works
immediately without logging out.

### Requirements

Arch-based, and `setup.sh` assumes `pacman` and `ufw`. The desktop integration
assumes [Omarchy](https://omarchy.org/); the `phonelink` command itself is
plain bash and works on any Linux with the four tools installed.

## Use

`SUPER + SHIFT + L` opens the Phone section of the Omarchy menu. From a shell:

```
phonelink status            what is connected right now, and what is missing
phonelink mirror            mirror and control the phone screen
phonelink desk [package]    run one app on its own virtual display
phonelink send [files...]   share to the phone (desktop file picker if no args)
phonelink drop              LocalSend
phonelink clip              push the clipboard to the phone
phonelink ring              find my phone
phonelink wifi              switch to / reconnect wireless adb, and remember it
phonelink pair              Android 11+ wireless-debugging walkthrough
phonelink pull <remote>     copy a file off the phone
phonelink push <local>      copy a file onto the phone
phonelink kde / sms         KDE Connect windows
```

`desk` is the one worth knowing about: it gives an app its own desktop-shaped
display via scrcpy's virtual display, so the app is a normal window on your
screen while the phone stays usable in your hand.

## Tuning

```sh
PHONELINK_SCRCPY_ARGS='--stay-awake --turn-screen-off'   # defaults for `mirror`
PHONELINK_DISPLAY_SIZE='1920x1080/240'                   # geometry for `desk`
```

## Desktop integration

`install.sh` applies these, keeping a timestamped `.bak.*` of each:

- `~/.config/omarchy/extensions/omarchy-menu.jsonc` — the Phone menu section
- `~/.config/hypr/bindings.lua` — `SUPER + SHIFT + L`
- `~/.config/hypr/hyprland.lua` — scrcpy window rules: fully opaque and unblurred
  (it is video), and no idle-lock while it has focus
