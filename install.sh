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

# Append a snippet to a config file unless its marker is already there. Each
# snippet gets its own marker so an update adds new pieces without duplicating
# the ones you already have.
append_once() {
  local target="$1" marker="$2" snippet="$3" label="$4"
  if [[ ! -f $target ]]; then skip "$target not found — skipped"; return 0; fi
  if grep -qF "$marker" "$target"; then skip "$label: already present"; return 0; fi
  cp "$target" "$target.bak.$TS"
  cat "$snippet" >> "$target"
  note "$label: added (backup: $(basename "$target").bak.$TS)"
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
append_once "$HYPR_DIR/bindings.lua" "omarchy-menu summon phone" \
  "$SRC_DIR/integration/bindings.lua.snippet" "SUPER+SHIFT+L (Phone menu)"
append_once "$HYPR_DIR/bindings.lua" "phonelink reply" \
  "$SRC_DIR/integration/bindings-reply.lua.snippet" "SUPER+SHIFT+R (Reply)"

step "Window rules"
# Markers match the rule itself, never the comment above it -- comment wording
# changes between versions, and a marker that drifts silently duplicates rules.
append_once "$HYPR_DIR/hyprland.lua" 'o.window("^([sS]crcpy)$"' \
  "$SRC_DIR/integration/hyprland.lua.snippet" "scrcpy (opaque, no idle-lock)"
# Matched literally, backslashes and all: the Lua rule escapes the dots.
append_once "$HYPR_DIR/hyprland.lua" 'org\\.kde\\.kdeconnect\\.daemon' \
  "$SRC_DIR/integration/hyprland-reply.lua.snippet" "KDE Connect reply dialog (float)"

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
