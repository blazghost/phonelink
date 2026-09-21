#!/usr/bin/env bash
# phonelink installer — the part that needs no root.
#
#     ./install.sh
#
# Links the script onto your PATH and wires up the Omarchy desktop integration.
# Idempotent, and incremental: run it again after an update and it adds only the
# pieces you do not have yet. Every file it changes is backed up first.
# For packages and firewall rules, run ./setup.sh with sudo afterwards.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
HYPR_DIR="${HOME}/.config/hypr"
MENU_FILE="${HOME}/.config/omarchy/extensions/omarchy-menu.jsonc"
TS="$(date +%s)"

have() { command -v "$1" >/dev/null 2>&1; }
step() { printf '\n\033[36m==>\033[0m %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
skip() { printf '    \033[2m%s\033[0m\n' "$*"; }

step "Linking phonelink into $BIN_DIR"
mkdir -p "$BIN_DIR"
ln -sfn "$SRC_DIR/phonelink" "$BIN_DIR/phonelink"
note "$BIN_DIR/phonelink -> $SRC_DIR/phonelink"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '    \033[33mnote:\033[0m %s is not on your PATH\n' "$BIN_DIR" ;;
esac

# One mechanism for every snippet: each carries phonelink:<name>:begin vN and
# :end markers, and integration/install-block.py adds it, replaces it in place
# when its version has moved on, or leaves it alone when it is already current.
# Anything of yours outside those markers is never touched. Text given after the
# label identifies an older, unmarked version of the same rule, so an install
# from before the markers is upgraded rather than duplicated -- which is what
# used to need a hand-written migration in here for each release.
block() {
  local target="$1" snippet="$2" label="$3"; shift 3
  if [[ ! -f $target ]]; then skip "$target not found — skipped"; return 0; fi
  cp "$target" "$target.bak.$TS"
  local backup result
  backup="$(basename "$target").bak.$TS"
  if ! result=$(python3 "$SRC_DIR/integration/install-block.py" "$target" "$snippet" "$@"); then
    mv "$target.bak.$TS" "$target"
    skip "$label: could not be applied — left as it was"
    return 0
  fi
  case "$result" in
    current)  rm -f "$target.bak.$TS"; skip "$label: already current" ;;
    added)    note "$label: added (backup: $backup)" ;;
    updated)  note "$label: updated to this version (backup: $backup)" ;;
    migrated) note "$label: replaced the older rule (backup: $backup)" ;;
    *)        rm -f "$target.bak.$TS"; skip "$label: $result" ;;
  esac
}

if [[ ! -d ${HOME}/.config/omarchy ]]; then
  step "No ~/.config/omarchy — skipping desktop integration"
  skip "phonelink itself is installed and usable from a terminal."
  exit 0
fi

step "Omarchy menu entries"
if [[ -f $MENU_FILE ]]; then
  cp "$MENU_FILE" "$MENU_FILE.bak.$TS"
  added=$(python3 - "$MENU_FILE" "$SRC_DIR/integration/omarchy-menu.jsonc.snippet" <<'PY'
import re, sys, pathlib

target, snippet = (pathlib.Path(a) for a in sys.argv[1:3])
s = target.read_text()

# Decide what already exists from the file with // comments stripped: the stock
# file ships commented-out examples that would otherwise look like live entries.
live = re.sub(r"^\s*//.*$", "", s, flags=re.M)
existing = set(re.findall(r'^\s*"([^"]+)"\s*:', live, flags=re.M))

entries = []
for line in snippet.read_text().splitlines():
    m = re.match(r'\s*"([^"]+)"\s*:', line)
    if m and m.group(1) not in existing:
        entries.append(line.rstrip().rstrip(","))

if not entries:
    print(0)
    raise SystemExit(0)

i = s.rstrip().rfind("}")
head = s[:i].rstrip()
body = re.sub(r"^\s*//.*$", "", head, flags=re.M)
body = body[body.find("{") + 1:].strip()

block = ",\n".join(entries)
if "// phonelink" not in s:
    block = "  // phonelink — Android integration\n" + block

target.write_text(head + (",\n" if body else "\n") + block + "\n" + s[i:].lstrip())
print(len(entries))
PY
)
  if [[ $added == 0 ]]; then
    rm -f "$MENU_FILE.bak.$TS"
    skip "all entries already present"
  else
    note "added $added entr$([[ $added == 1 ]] && echo y || echo ies) (backup: $(basename "$MENU_FILE").bak.$TS)"
  fi
else
  skip "$MENU_FILE not found — skipped"
fi

step "Keybindings"
block "$HYPR_DIR/bindings.lua" "$SRC_DIR/integration/bindings.lua.snippet" \
  "SUPER+SHIFT+L (Phone menu)" "omarchy-menu summon phone"
block "$HYPR_DIR/bindings.lua" "$SRC_DIR/integration/bindings-reply.lua.snippet" \
  "SUPER+SHIFT+R (Reply)" '"phonelink reply"' 

step "Window rules"
# The text after each label is how the rule looked before it had markers --
# matched literally, backslashes and all, since the Lua escapes its dots.
block "$HYPR_DIR/hyprland.lua" "$SRC_DIR/integration/hyprland.lua.snippet" \
  "scrcpy (opaque, no idle-lock)" 'o.window("^([sS]crcpy)$"'
block "$HYPR_DIR/hyprland.lua" "$SRC_DIR/integration/hyprland-reply.lua.snippet" \
  "KDE Connect reply dialog (float)" 'org\\.kde\\.kdeconnect\\.daemon'
# The panel rule used to pin a size, which fights the height phonelink asks foot
# for; both that version and the unversioned marked one are replaced in place.
block "$HYPR_DIR/hyprland.lua" "$SRC_DIR/integration/hyprland-panel.lua.snippet" \
  "phonelink reply panel (float)" 'o.window("^(org\\.omarchy\\.phonelink)$"'
block "$HYPR_DIR/hyprland.lua" "$SRC_DIR/integration/hyprland-messages.lua.snippet" \
  "Messages window (opaque)" 'o.window("^(org\\.omarchy\\.phonelink\\.messages)$"'

step "Phone widget for the bar"
# A plugin directory of its own under ~/.config/omarchy/plugins, the way every
# third-party Omarchy widget is installed. Copied rather than symlinked: the
# shell watches the directory, and a symlink to a checkout is not what it
# expects to find there.
PLUGIN_SRC="$SRC_DIR/integration/omarchy-plugin/phonelink.phone"
PLUGIN_DIR="${HOME}/.config/omarchy/plugins/phonelink.phone"
if [[ ! -d ${HOME}/.config/omarchy/plugins ]]; then
  skip "no ~/.config/omarchy/plugins — skipped"
elif ! have omarchy-shell; then
  skip "the Omarchy shell is not installed — skipped"
else
  fresh=1
  [[ -d $PLUGIN_DIR ]] && fresh=0
  mkdir -p "$PLUGIN_DIR"
  if (( fresh )) || ! diff -rq "$PLUGIN_SRC" "$PLUGIN_DIR" >/dev/null 2>&1; then
    cp "$PLUGIN_SRC"/* "$PLUGIN_DIR/"
    note "battery, signal and waiting messages; click for Messages"
  else
    skip "already current"
  fi
  omarchy-shell -q shell rescanPlugins >/dev/null 2>&1 || true
  if (( fresh )); then
    # Put it next to the other status widgets, once. Moving or removing it
    # afterwards is `omarchy bar move` / `omarchy plugin disable`, and this
    # never second-guesses that.
    if have omarchy; then
      omarchy plugin enable phonelink.phone --section right --before omarchy.bluetooth \
        >/dev/null 2>&1 || omarchy plugin enable phonelink.phone >/dev/null 2>&1 || true
      note "added to the bar (omarchy plugin disable phonelink.phone removes it)"
    fi
    # A plugin the shell has never seen appears only after it restarts; an
    # update to one it already knows is picked up by the rescan above.
    omarchy restart shell >/dev/null 2>&1 || true
  fi
fi

step "Phone notification toasts"
# Delegated to `phonelink toasts on`, which is also how you turn them back on
# later: it installs and restarts the user service (so an update picks up new
# code) and only then silences KDE Connect's duplicate popups.
if [[ -z ${WAYLAND_DISPLAY:-} ]] || ! command -v systemctl >/dev/null 2>&1; then
  skip "needs a Wayland session with systemd user services — skipped (phonelink toasts on, later)"
elif "$SRC_DIR/phonelink" toasts on >/dev/null 2>&1; then
  note "on: Phone Link-style popups with a reply box (phonelink toasts off to undo)"
else
  skip "could not start them — run: phonelink toasts on"
fi

if command -v hyprctl >/dev/null 2>&1 && [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]]; then
  step "Reloading Hyprland"
  hyprctl reload >/dev/null && note "reloaded"
  errs="$(hyprctl configerrors 2>/dev/null || true)"
  if [[ -z ${errs//[[:space:]]/} ]]; then note "no config errors"; else printf '\033[31m%s\033[0m\n' "$errs"; fi
fi

cat <<'EOS'

==> Installed.

If this is a first install, the part that needs root comes next — packages,
udev rules and firewall ports:

    sudo ./setup.sh

Then check everything with:

    phonelink status
EOS
