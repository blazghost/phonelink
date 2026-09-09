#!/usr/bin/env bash
# phonelink installer — the part that needs no root.
#
#     ./install.sh
#
# Links the script onto your PATH and wires up the Omarchy desktop integration.
# Idempotent: nothing is applied twice, and every file it touches is backed up
# first. For packages and firewall rules, run ./setup.sh with sudo afterwards.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
HYPR_DIR="${HOME}/.config/hypr"
MENU_FILE="${HOME}/.config/omarchy/extensions/omarchy-menu.jsonc"
TS="$(date +%s)"

step() { printf '\n\033[36m==>\033[0m %s\n' "$*"; }
skip() { printf '    \033[2m%s\033[0m\n' "$*"; }

step "Linking phonelink into $BIN_DIR"
mkdir -p "$BIN_DIR"
ln -sfn "$SRC_DIR/phonelink" "$BIN_DIR/phonelink"
echo "    $BIN_DIR/phonelink -> $SRC_DIR/phonelink"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '    \033[33mnote:\033[0m %s is not on your PATH\n' "$BIN_DIR" ;;
esac

# Everything below is Omarchy-specific. On plain Hyprland the script still works
# from a shell; you just do not get the menu entry or the window rules.
if [[ ! -d ${HOME}/.config/omarchy ]]; then
  step "No ~/.config/omarchy — skipping desktop integration"
  skip "phonelink itself is installed and usable from a terminal."
  exit 0
fi

# The marker is the word "phonelink" in a comment, written by the snippets. If
# it is already there, the file has been done and we leave it alone.
applied() { [[ -f $1 ]] && grep -q 'phonelink' "$1"; }

step "Omarchy menu entry (Phone section)"
if applied "$MENU_FILE"; then
  skip "already present"
elif [[ -f $MENU_FILE ]]; then
  cp "$MENU_FILE" "$MENU_FILE.bak.$TS"
  python3 - "$MENU_FILE" "$SRC_DIR/integration/omarchy-menu.jsonc.snippet" <<'PY'
import sys, pathlib, re
target, snippet = (pathlib.Path(a) for a in sys.argv[1:3])
s, add = target.read_text(), snippet.read_text().rstrip("\n")
i = s.rstrip().rfind("}")
head = s[:i].rstrip()
# A comma is needed only if a real entry already precedes us. Decide that from
# the file with // comments stripped -- the stock file's examples are commented
# out and end in "}," which would otherwise look like a live entry.
body = re.sub(r"^\s*//.*$", "", head, flags=re.M)
body = body[body.find("{") + 1:].strip()
sep = ",\n" if body else "\n"
target.write_text(head + sep + add + "\n" + s[i:].lstrip())
PY
  echo "    added (backup: $(basename "$MENU_FILE").bak.$TS)"
else
  skip "$MENU_FILE not found — skipped"
fi

step "Keybinding (SUPER + SHIFT + L)"
if applied "$HYPR_DIR/bindings.lua"; then
  skip "already present"
elif [[ -f $HYPR_DIR/bindings.lua ]]; then
  if grep -qE '^\s*o\.bind\("SUPER \+ SHIFT \+ L"' "$HYPR_DIR/bindings.lua"; then
    skip "SUPER+SHIFT+L is already bound to something else — skipped, bind it yourself"
  else
    cp "$HYPR_DIR/bindings.lua" "$HYPR_DIR/bindings.lua.bak.$TS"
    cat "$SRC_DIR/integration/bindings.lua.snippet" >> "$HYPR_DIR/bindings.lua"
    echo "    added (backup: bindings.lua.bak.$TS)"
  fi
else
  skip "$HYPR_DIR/bindings.lua not found — skipped"
fi

step "scrcpy window rules"
if applied "$HYPR_DIR/hyprland.lua"; then
  skip "already present"
elif [[ -f $HYPR_DIR/hyprland.lua ]]; then
  cp "$HYPR_DIR/hyprland.lua" "$HYPR_DIR/hyprland.lua.bak.$TS"
  cat "$SRC_DIR/integration/hyprland.lua.snippet" >> "$HYPR_DIR/hyprland.lua"
  echo "    added (backup: hyprland.lua.bak.$TS)"
else
  skip "$HYPR_DIR/hyprland.lua not found — skipped"
fi

if command -v hyprctl >/dev/null 2>&1 && [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]]; then
  step "Reloading Hyprland"
  hyprctl reload >/dev/null && echo "    reloaded"
  errs="$(hyprctl configerrors 2>/dev/null || true)"
  [[ -z ${errs//[[:space:]]/} ]] && echo "    no config errors" || printf '\033[31m%s\033[0m\n' "$errs"
fi

cat <<'EOS'

==> Installed.

Next, the part that needs root — packages, udev rules and firewall ports:

    sudo ./setup.sh

Then check everything with:

    phonelink status
EOS
