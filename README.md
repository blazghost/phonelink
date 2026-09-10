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
phonelink reply             answer a phone notification from the desktop
phonelink reply "on my way" straight to the newest one, no prompt
phonelink messages          the phone's texts, with MMS photos and video
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
phonelink kde restart       unstick KDE Connect if it stops answering
```

`desk` is the one worth knowing about: it gives an app its own desktop-shaped
display via scrcpy's virtual display, so the app is a normal window on your
screen while the phone stays usable in your hand.

## Messages: texts with photos and video

`phonelink messages`, or *Messages* in the Phone menu, is Phone Link's Messages
tab for the phone's SMS and MMS. The conversation list sits on the left with a
search box; the thread is on the right, with received and sent bubbles and MMS
pictures and videos in place. A picture appears at once from the small
thumbnail the phone sends with the message and sharpens when the full image
arrives; a video plays in your default player. Click a picture or video to open
it, right-click to save it to `~/Pictures/Phone`, or drag it into another app.
To send photos or videos, use the paperclip or drop files onto the
conversation. Carriers often refuse MMS much over 1.5 MB, so it warns you.

Names and contact photos come from the contacts KDE Connect syncs from the
phone. If threads show numbers instead, enable the Contacts plugin, and allow
its permission, in the KDE Connect app on the phone.

**Signal, Messenger, WhatsApp.** KDE Connect can read the phone's texting
database, but not other apps' messages. A Signal or Messenger notification
carries its text and one small icon, never the photo or video, and Android only
lets you reply to a notification with text. Phone Link on Windows has the same
limit. So their toasts and their conversations in the reply window get an
**Open** button, which runs the app itself on your desktop:
`phonelink desk <package>`, scrcpy on its own virtual display. Every photo and
video is there, and you can send media as you would on the phone. It needs
wireless adb, set up once with `phonelink pair`.

## Replying to notifications

Android attaches a reply box to any notification you could answer from the
phone's own shade — messengers, SMS. KDE Connect carries that through, so the
message can be answered from the desktop and lands in the app as if you had
typed it on the phone. Feed and news apps offer no reply box, so they never
appear here.

There are two ways in, because they fail in different situations:

- **`SUPER + SHIFT + R`**, the menu's *Reply to a notification*, or
  `phonelink reply` from a launcher. This opens a Phone Link-style window: the
  conversation as chat bubbles, each speaker's avatar and name over their run
  of messages in a group chat, and a compose bar at the bottom. With several
  conversations waiting it becomes a two-pane window with the list on the
  left. Enter sends, Escape closes, and a single conversation closes itself a
  moment after the reply lands. Notification popups are transient; this still
  works once one has gone.
- **Click *Reply* on the notification.** That opens KDE Connect's own reply
  window, which is not phonelink's to restyle; `install.sh` only stops it
  tiling. The keybind is the nicer path.

Run from a terminal, `phonelink reply` stays in the terminal — a themed picker
and prompt, handy over SSH. `--gui` and `--tui` (or `PHONELINK_UI=gui|tui`)
force either. Given text directly — `phonelink reply "five minutes"` — it skips
both and answers the newest conversation, which is what makes it useful on a
keybind of its own.

Under the hood this is `sendReply()` on kdeconnectd's D-Bus objects; see
`lib/kdeconnect-notify.py`. Nothing reimplements KDE Connect's protocol. The
window is `lib/phonelink-reply-gtk.py`: GTK 4 and libadwaita through PyGObject,
all of which Omarchy ships.

### Group conversations

Android packs the recent thread into a single notification body as small HTML —
`<b>Sender</b><br/>what they said<br/><b>Someone else</b><br/>…`. Shown raw that
is a wall of markup and repeated names, so the helper parses it into speaker and
text, and both the window and the terminal panel lay it out as a conversation,
newest last, with a repeated speaker labelled once. The window scrolls; the
terminal panel shows the last few turns, marks the rest `… N earlier`, and
`PHONELINK_THREAD_LINES` changes how many.

Both size themselves to the conversation before opening, so a group thread is
not clipped and a one-line chat is not mostly empty.

### Avatars

KDE Connect saves each notification's large icon, which for a messenger is
usually the contact's or the group's photo; the window uses it in the header and
the conversation list. Everyone else, and anyone without a photo, gets an
initials circle.

### Theming

The window reads the active theme's full palette from
`~/.local/state/omarchy/current/theme/colors.toml`: the accent for your own
bubbles and the send button, the lighter background for incoming bubbles, the
theme's named hues for avatar circles, and whether it is a light or dark theme.
The terminal panel uses the `GUM_*` environment Omarchy exports. Either way it
follows `omarchy theme set` instead of pinning one palette, and falls back to
Adwaita or plain ANSI colours off Omarchy.

Both open floating, centred and fully opaque. Opaque on purpose: a floating
window under Omarchy's default translucency shows whatever is behind it
unblurred, and a message is not readable through another terminal.

## Notification toasts

`phonelink toasts on` (which `install.sh` runs) replaces the plain popup KDE
Connect shows for a phone notification with a Phone Link-style toast: the app,
the sender's avatar and name, the latest message — `Name: message` in a group
chat — and, when the phone would let you answer from its own notification
shade, a reply box right in the toast. Type, press Enter, and the reply goes
straight back to the app on the phone; the toast shows *Sent* and closes.

It is built to sit on Omarchy rather than on top of it:

- sized and themed like Omarchy's own notification cards — width, padding,
  Hyprland's corner rounding, the active-border gradient and the countdown bar
  — read live from the theme, so `omarchy theme set` restyles it;
- it honours Do Not Disturb, and KDE Connect's "silent" flag, so reconnecting
  the phone does not replay its whole notification shade as toasts;
- it never takes the keyboard when it appears, so you can't end up typing into
  a toast by surprise, but it does when you click its reply box;
- the countdown pauses while you hover or type; Escape or a right-click
  dismisses; a left-click opens the full reply window on that conversation;
- a new message in a chat pops again, even though the phone only updates the
  chat's existing notification rather than posting another — just as KDE
  Connect's own popup did;
- a notification read or dismissed on the phone disappears here too.

Toasts go **bottom-right**, where Phone Link puts them, which also keeps them
clear of Omarchy's own toasts in the top-right. For top-right instead, add
`Environment=PHONELINK_TOAST_POSITION=top-right` with
`systemctl --user edit phonelink-toastd`.

Only phone notifications change hands: KDE Connect's popups for calls, pairing
requests, pings and low battery are untouched. The toasts run as a systemd user
service (`phonelink-toastd`) that restarts if it crashes.
`phonelink toasts status` reports on it, `phonelink toasts demo` previews the
look with sample toasts, and `phonelink toasts off` gives KDE Connect its
popups back.

## Tuning

```sh
PHONELINK_SCRCPY_ARGS='--stay-awake --turn-screen-off'   # defaults for `mirror`
PHONELINK_DISPLAY_SIZE='1920x1080/240'                   # geometry for `desk`
```

## Desktop integration

`install.sh` applies these, keeping a timestamped `.bak.*` of each:

- `~/.config/omarchy/extensions/omarchy-menu.jsonc` — the Phone menu section
- `~/.config/hypr/bindings.lua` — `SUPER + SHIFT + L` (menu), `SUPER + SHIFT + R` (reply)
- `~/.config/hypr/hyprland.lua` — scrcpy window rules: fully opaque and unblurred
  (it is video), and no idle-lock while it has focus; plus a float rule for KDE
  Connect's reply window
- `~/.config/systemd/user/phonelink-toastd.service` — the notification toasts
- `~/.config/kdeconnect.notifyrc` — silences KDE Connect's own popup for phone
  notifications only, in a marked block that `phonelink toasts off` removes

Re-running `install.sh` after an update adds only the pieces you are missing,
matched against the rules themselves rather than comment text.
