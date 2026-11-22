"""Desktop actions the phone can run: KDE Connect's runcommand plugin, filled in.

The plugin lets the phone run commands this computer has listed -- and only
those. It keeps the list as JSON in a QSettings file, under one key:

    [General]
    commands="@ByteArray({\\"id\\":{\\"name\\":\\"Lock\\",\\"command\\":\\"...\\"}})"

phonelink's entries all have ids starting "phonelink-", so turning them on or
off never touches commands you added yourself in KDE Connect's settings. The
plugin reads the file when it loads, so it is switched off and on again after
a change; that also sends the new list to the phone.

    python3 -m phonelink.commands on|off|list
"""

import json
import shutil
import sys
from pathlib import Path

from gi.repository import GLib

from . import kdeconnect as kde

PLUGIN = "kdeconnect_runcommand"
PREFIX = "phonelink-"

# (id, what the phone shows, the command). Fixed: nothing the phone sends is
# ever part of a command line.
ACTIONS = [
    ("lock", "Lock the computer", ["omarchy-system-lock"]),
    ("screenshot", "Take a screenshot", ["omarchy-capture-screenshot", "fullscreen", "save"]),
    ("record", "Start screen recording", ["omarchy-capture-screenrecording", "--fullscreen"]),
    ("record-stop", "Stop screen recording",
     ["omarchy-capture-screenrecording", "--stop-recording"]),
    ("mute", "Mute or unmute the computer", ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]),
    ("suspend", "Suspend the computer", ["systemctl", "suspend"]),
]


def config_file(device_id):
    return Path(GLib.get_user_config_dir()) / "kdeconnect" / device_id / PLUGIN / "config"


# ------------------------------------------------------------ the QSettings file

def unquote(value):
    """A QSettings ini value as text: quotes off, \\" and \\\\ unescaped."""
    if not (len(value) >= 2 and value[0] == value[-1] == '"'):
        return value
    out, chars = [], iter(value[1:-1])
    for c in chars:
        out.append(next(chars, "") if c == "\\" else c)
    return "".join(out)


def quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_commands(text):
    """The commands JSON out of the file's text, {} when there is none."""
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "commands":
            raw = unquote(value.strip())
            if raw.startswith("@ByteArray(") and raw.endswith(")"):
                raw = raw[len("@ByteArray("):-1]
            try:
                found = json.loads(raw or "{}")
            except json.JSONDecodeError:
                return {}
            return found if isinstance(found, dict) else {}
    return {}


def write_commands(text, commands):
    """The file's text with `commands` set; every other line as it was."""
    line = "commands=" + quote("@ByteArray(" + json.dumps(commands, separators=(",", ":")) + ")")
    lines = text.splitlines()
    for i, old in enumerate(lines):
        if old.partition("=")[0].strip() == "commands":
            lines[i] = line
            return "\n".join(lines) + "\n"
    if "[General]" in lines:
        lines.insert(lines.index("[General]") + 1, line)
    else:
        lines = ["[General]", line, *([""] + lines if lines else [])]
    return "\n".join(lines) + "\n"


def ours():
    """phonelink's entries, by absolute path, for the actions this computer can do."""
    found = {}
    for key, name, argv in ACTIONS:
        if path := shutil.which(argv[0]):
            found[PREFIX + key] = {"name": name,
                                   "command": " ".join([path, *argv[1:]])}
    return found


def merged(existing, on):
    keep = {k: v for k, v in existing.items() if not k.startswith(PREFIX)}
    return {**keep, **ours()} if on else keep


# ----------------------------------------------------------------- the plugin

def reload(device_id):
    """Off and on again: the plugin re-reads its file and tells the phone."""
    path = f"{kde.DEVICES}/{device_id}"
    for enabled in (False, True):
        kde.call(path, kde.DEVICE_IFACE, "setPluginEnabled", GLib.Variant("(sb)", (PLUGIN, enabled)))


def main(argv):
    verb = argv[1] if len(argv) > 1 else "list"
    if verb not in ("on", "off", "list"):
        sys.exit("usage: phonelink commands on|off|list")
    if kde.BUS is None or not (phone := kde.phone()):
        sys.exit("error: the phone is not reachable over KDE Connect")
    path = config_file(phone["id"])
    text = path.read_text() if path.exists() else ""
    current = read_commands(text)
    if verb == "list":
        for key, entry in current.items():
            mark = "phonelink" if key.startswith(PREFIX) else "yours"
            print(f"  {entry.get('name', key):<30} {mark:<10} {entry.get('command', '')}")
        if not current:
            print("  none -- phonelink commands on adds lock, screenshot, recording, mute, suspend")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(write_commands(text, merged(current, verb == "on")))
    try:
        reload(phone["id"])
    except GLib.Error as exc:
        sys.exit(f"error: saved, but KDE Connect did not reload it: {exc.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
