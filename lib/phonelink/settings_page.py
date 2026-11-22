"""The Settings tab: mouse sharing, the phone's camera and microphone, the
walk-away lock, desktop commands for the phone, and notification history.

Both drive the phonelink command -- `phonelink mouse` runs the phonelink-mouse
user service (lib/phonelink-mouse.py), `phonelink webcam` runs scrcpy into the
"Phone camera" device -- so the window and the terminal can never disagree.
Nothing here waits on them, and each switch shows what systemd says once its
command is done.
"""

import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import commands, history, kdeconnect as kde, share  # noqa: E402

PHONELINK = str(Path(__file__).resolve().parent.parent.parent / "phonelink")
MOUSE_UNIT, WEBCAM_UNIT = "phonelink-mouse.service", "phonelink-webcam.service"
MIC_UNIT, AUTOLOCK_UNIT = "phonelink-mic.service", "phonelink-autolock.service"
FACINGS = ("front", "back")
AWAY_S = (30, 60, 120, 300)


def autolock_after():
    try:
        value = int((Path(GLib.get_user_config_dir()) / "phonelink" / "autolock-after")
                    .read_text().strip())
    except (OSError, ValueError):
        value = 60
    return min(AWAY_S, key=lambda s: abs(s - value))


def commands_on():
    """Are phonelink's desktop commands offered to the phone right now?"""
    phone = kde.phone()
    if not phone:
        return False
    try:
        text = commands.config_file(phone["id"]).read_text()
    except OSError:
        return False
    return any(k.startswith(commands.PREFIX) for k in commands.read_commands(text))


def active(unit):
    state = subprocess.run(["systemctl", "--user", "is-active", unit],
                           capture_output=True, text=True, check=False).stdout.strip()
    return state in ("active", "activating")


def webcam_facing():
    state = Path(GLib.get_user_state_dir()) / "phonelink" / "webcam-facing"
    try:
        facing = state.read_text().strip()
    except OSError:
        facing = ""
    return facing if facing in FACINGS else "front"


class SettingsPage(Adw.Bin):

    def __init__(self, toast):
        super().__init__()
        self.toast = toast
        self.busy = False

        mouse = Adw.PreferencesGroup(
            title="Share mouse and keyboard",
            description="Push the pointer past the chosen edge of the screen and it carries on "
                        "onto the phone, keyboard included. Move it back past the phone's edge "
                        "to bring it home, or press Ctrl+Alt+Esc. The phone needs KDE Connect's "
                        "Remote input permission.")
        self.mouse = Adw.SwitchRow(title="Share mouse and keyboard", active=active(MOUSE_UNIT))
        self.mouse.connect("notify::active", lambda *_: self.apply_mouse())
        mouse.add(self.mouse)
        self.edge = Adw.ComboRow(title="Leave the screen at",
                                 model=Gtk.StringList.new([e.capitalize() for e in share.EDGES]))
        self.edge.set_selected(share.EDGES.index(share.read_edge()))
        self.edge.connect("notify::selected", lambda *_: self.apply_mouse(edge_changed=True))
        mouse.add(self.edge)

        webcam = Adw.PreferencesGroup(
            title="Phone camera as webcam",
            description="Offers \"Phone camera\" to Meet, Zoom, OBS and browsers. The phone's "
                        "camera only comes on while an app is using it. Needs the phone over "
                        "adb (phonelink wifi) and the virtual camera from sudo ./setup.sh.")
        self.webcam = Adw.SwitchRow(title="Offer the phone as a webcam", active=active(WEBCAM_UNIT))
        self.webcam.connect("notify::active", lambda *_: self.apply_webcam())
        webcam.add(self.webcam)
        self.facing = Adw.ComboRow(title="Camera",
                                   model=Gtk.StringList.new([f.capitalize() for f in FACINGS]))
        self.facing.set_selected(FACINGS.index(webcam_facing()))
        self.facing.connect("notify::selected", lambda *_: self.apply_webcam(facing_changed=True))
        webcam.add(self.facing)

        self.mic = Adw.SwitchRow(title="Offer the phone as a microphone",
                                 subtitle="\"Phone microphone\", on only while an app records from it",
                                 active=active(MIC_UNIT))
        self.mic.connect("notify::active", lambda *_: self.toggle(self.mic, "mic"))
        webcam.add(self.mic)

        away = Adw.PreferencesGroup(
            title="Lock when the phone walks away",
            description="Locks the screen once the phone has been out of reach for a while. "
                        "Coming back never unlocks it.")
        self.autolock = Adw.SwitchRow(title="Walk-away lock", active=active(AUTOLOCK_UNIT))
        self.autolock.connect("notify::active", lambda *_: self.apply_autolock())
        away.add(self.autolock)
        self.after = Adw.ComboRow(title="After",
                                  model=Gtk.StringList.new([f"{s // 60} min" if s >= 60 else f"{s} s"
                                                            for s in AWAY_S]))
        self.after.set_selected(AWAY_S.index(autolock_after()))
        self.after.connect("notify::selected", lambda *_: self.apply_autolock())
        away.add(self.after)

        phone_side = Adw.PreferencesGroup(
            title="From the phone",
            description="KDE Connect's Run command on the phone gets: lock, screenshot, start and "
                        "stop screen recording, mute, suspend. Only these; nothing the phone "
                        "sends becomes part of a command.")
        self.commands = Adw.SwitchRow(title="Let the phone run desktop actions",
                                      active=commands_on())
        self.commands.connect("notify::active", lambda *_: self.toggle(self.commands, "commands"))
        phone_side.add(self.commands)
        self.history = Adw.SwitchRow(title="Keep notification history",
                                     subtitle="The last 500, on this computer only, for the "
                                              "Overview's search", active=history.enabled())
        self.history.connect("notify::active", lambda *_: self.toggle(self.history, "history"))
        phone_side.add(self.history)
        wipe = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        wipe.connect("clicked", lambda *_: (history.clear(), self.toast("Notification history cleared")))
        clear_row = Adw.ActionRow(title="Clear notification history")
        clear_row.add_suffix(wipe)
        phone_side.add(clear_row)

        page = Adw.PreferencesPage()
        page.add(mouse)
        page.add(webcam)
        page.add(away)
        page.add(phone_side)
        self.set_child(page)

    def apply_mouse(self, edge_changed=False):
        if self.busy:
            return
        edge = share.EDGES[self.edge.get_selected()]
        if not self.mouse.get_active():
            if edge_changed:  # remembered for next time; nothing is running to restart
                share.edge_file().parent.mkdir(parents=True, exist_ok=True)
                share.edge_file().write_text(edge + "\n")
                return
            self.run(["mouse", "off"])
        else:
            self.run(["mouse", "on", edge])

    def apply_webcam(self, facing_changed=False):
        if self.busy:
            return
        on = self.webcam.get_active()
        if facing_changed and not on:
            return  # used the next time it is switched on
        self.run(["webcam", FACINGS[self.facing.get_selected()]] if on else ["webcam", "off"])

    def toggle(self, row, command):
        if not self.busy:
            self.run([command, "on" if row.get_active() else "off"])

    def apply_autolock(self):
        if self.busy:
            return
        if self.autolock.get_active():
            self.run(["autolock", "on", str(AWAY_S[self.after.get_selected()])])
        else:
            self.run(["autolock", "off"])

    def run(self, args):
        """`phonelink <args>` on a thread; a failure comes back as a toast."""
        self.busy = True

        def work():
            done = subprocess.run([PHONELINK, *args], capture_output=True, text=True, check=False)
            GLib.idle_add(self.done, done)
        threading.Thread(target=work, daemon=True).start()

    def done(self, run):
        if run.returncode != 0:
            lines = [line for line in run.stderr.strip().splitlines() if line.startswith("error:")]
            self.toast((lines or ["That didn't work"])[-1].removeprefix("error: "))
        # Whatever actually happened, not what was asked for.
        self.mouse.set_active(active(MOUSE_UNIT))
        self.webcam.set_active(active(WEBCAM_UNIT))
        self.mic.set_active(active(MIC_UNIT))
        self.autolock.set_active(active(AUTOLOCK_UNIT))
        self.commands.set_active(commands_on())
        self.history.set_active(history.enabled())
        self.busy = False
        return False
