"""The Settings tab: mouse sharing and the phone's camera as a webcam.

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

from . import share  # noqa: E402

PHONELINK = str(Path(__file__).resolve().parent.parent.parent / "phonelink")
MOUSE_UNIT, WEBCAM_UNIT = "phonelink-mouse.service", "phonelink-webcam.service"
FACINGS = ("front", "back")


def active(unit):
    """Running, or (the webcam) waiting a moment to take the phone's camera back."""
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
            description="The phone's camera shows up as \"Phone camera\" in Meet, Zoom, OBS or a "
                        "browser. Needs the phone connected over adb (phonelink wifi) and the "
                        "virtual camera from sudo ./setup.sh.")
        self.webcam = Adw.SwitchRow(title="Use the phone as a webcam", active=active(WEBCAM_UNIT))
        self.webcam.connect("notify::active", lambda *_: self.apply_webcam())
        webcam.add(self.webcam)
        self.facing = Adw.ComboRow(title="Camera",
                                   model=Gtk.StringList.new([f.capitalize() for f in FACINGS]))
        self.facing.set_selected(FACINGS.index(webcam_facing()))
        self.facing.connect("notify::selected", lambda *_: self.apply_webcam(facing_changed=True))
        webcam.add(self.facing)

        page = Adw.PreferencesPage()
        page.add(mouse)
        page.add(webcam)
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
        self.busy = False
        return False
