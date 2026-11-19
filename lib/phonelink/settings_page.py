"""The Settings tab: sharing this mouse and keyboard with the phone.

The switch and the edge drive `phonelink mouse`, which runs the
phonelink-mouse user service (lib/phonelink-mouse.py); nothing here waits on
it, and the switch shows what systemd says once the command is done.
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
UNIT = "phonelink-mouse.service"


def sharing_on():
    run = subprocess.run(["systemctl", "--user", "is-active", "-q", UNIT], check=False)
    return run.returncode == 0


class SettingsPage(Adw.Bin):

    def __init__(self, toast):
        super().__init__()
        self.toast = toast
        self.busy = False

        group = Adw.PreferencesGroup(
            title="Share mouse and keyboard",
            description="Push the pointer past the chosen edge of the screen and it carries on "
                        "onto the phone, keyboard included. Move it back past the phone's edge "
                        "to bring it home, or press Ctrl+Alt+Esc. The phone needs KDE Connect's "
                        "Remote input permission.")
        self.switch = Adw.SwitchRow(title="Share mouse and keyboard", active=sharing_on())
        self.switch.connect("notify::active", lambda *_: self.apply())
        group.add(self.switch)

        self.edge = Adw.ComboRow(title="Leave the screen at",
                                 model=Gtk.StringList.new([e.capitalize() for e in share.EDGES]))
        self.edge.set_selected(share.EDGES.index(share.read_edge()))
        self.edge.connect("notify::selected", lambda *_: self.apply(edge_changed=True))
        group.add(self.edge)

        page = Adw.PreferencesPage()
        page.add(group)
        self.set_child(page)

    def apply(self, edge_changed=False):
        if self.busy:
            return
        on = self.switch.get_active()
        edge = share.EDGES[self.edge.get_selected()]
        if edge_changed and not on:
            share.edge_file().parent.mkdir(parents=True, exist_ok=True)
            share.edge_file().write_text(edge + "\n")
            return
        argv = [PHONELINK, "mouse", "on", edge] if on else [PHONELINK, "mouse", "off"]
        self.busy = True

        def work():
            run = subprocess.run(argv, capture_output=True, text=True, check=False)
            GLib.idle_add(self.done, run)
        threading.Thread(target=work, daemon=True).start()

    def done(self, run):
        if run.returncode != 0:
            self.toast((run.stderr.strip().splitlines() or ["Couldn't change mouse sharing"])[-1]
                       .removeprefix("error: "))
        self.switch.set_active(sharing_on())  # whatever actually happened
        self.busy = False
        return False
