"""The Omarchy palette, and the CSS the windows are dressed in.

Colours come from the active theme's colors.toml, then the GUM_* palette
Omarchy exports, then plain Adwaita dark -- so every phonelink window follows
`omarchy theme set` like the rest of the desktop.

Pure string and file work: no GTK here, so it can be read and tested without a
display.
"""

import os
import tomllib
from pathlib import Path


# Plain Adwaita dark, for when there is no Omarchy theme to read.
FALLBACK = {
    "mode": "dark",
    "background": "#1d1d20", "dark_background": "#18181b",
    "lighter_background": "#2e2e32", "foreground": "#ffffff",
    "muted": "#9a9a9e", "accent": "#3584e4", "selection": "#3a3a3f",
    "red": "#e62d42", "orange": "#e66100", "yellow": "#c88800",
    "green": "#3a944a", "cyan": "#2190a4", "blue": "#3584e4",
    "magenta": "#9141ac",
}


# The GUM_* variables Omarchy exports, mapped onto colors.toml names.
GUM_KEYS = {
    "accent": "GUM_INPUT_PROMPT_FOREGROUND",
    "foreground": "GUM_INPUT_HEADER_FOREGROUND",
    "muted": "GUM_INPUT_PLACEHOLDER_FOREGROUND",
    "selection": "GUM_FILTER_SELECTED_BACKGROUND",
    "background": "GUM_INPUT_PROMPT_BACKGROUND",
}


# Initials avatars cycle through the theme's own hues rather than Adwaita's,
# so a group chat reads as part of the palette.
AVATAR_HUES = ("blue", "green", "magenta", "orange", "cyan", "red", "yellow")


def is_hex(value):
    return (isinstance(value, str) and len(value) == 7 and value.startswith("#")
            and all(c in "0123456789abcdefABCDEF" for c in value[1:]))


def load_palette():
    pal = dict(FALLBACK)
    for key, var in GUM_KEYS.items():
        if is_hex(os.environ.get(var)):
            pal[key] = os.environ[var]
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    try:
        theme = tomllib.loads((state / "omarchy/current/theme/colors.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        theme = {}
    for key, value in theme.items():
        if is_hex(value) or (key == "mode" and value in ("dark", "light")):
            pal[key] = value
    return pal


def luminance(hexc):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ink_on(pal, bg):
    """Whichever of the theme's own ink colours stays legible on `bg`."""
    dark, light = sorted((pal["background"], pal["foreground"]), key=luminance)
    return dark if luminance(bg) > 0.3 else light


def build_css(p):
    on_accent = ink_on(p, p["accent"])
    hairline = f"alpha({p['foreground']}, 0.07)"
    avatars = "\n".join(
        f"avatar.color{n} {{ background-image: none; "
        f"background-color: {p[hue]}; color: {ink_on(p, p[hue])}; }}"
        for n, hue in ((i, AVATAR_HUES[(i - 1) % len(AVATAR_HUES)]) for i in range(1, 15)))
    return f"""
:root {{
  --window-bg-color: {p['background']};
  --window-fg-color: {p['foreground']};
  --view-bg-color: {p['background']};
  --view-fg-color: {p['foreground']};
  --headerbar-bg-color: {p['dark_background']};
  --headerbar-fg-color: {p['foreground']};
  --headerbar-backdrop-color: {p['dark_background']};
  --headerbar-shade-color: {hairline};
  --sidebar-bg-color: {p['dark_background']};
  --sidebar-fg-color: {p['foreground']};
  --sidebar-backdrop-color: {p['dark_background']};
  --sidebar-shade-color: {hairline};
  --card-bg-color: {p['lighter_background']};
  --popover-bg-color: {p['lighter_background']};
  --accent-bg-color: {p['accent']};
  --accent-fg-color: {on_accent};
  --accent-color: {p['accent']};
}}
window {{ font-family: "Adwaita Sans", sans-serif; }}

.thread {{ padding: 14px 16px 12px; }}
.bubble {{ padding: 8px 13px; border-radius: 18px; font-size: 10.5pt; }}
.bubble.in  {{ background: {p['lighter_background']}; color: {p['foreground']}; }}
.bubble.out {{ background: {p['accent']}; color: {on_accent}; }}
.bubble.in.head  {{ border-top-left-radius: 6px; }}
.bubble.out.head {{ border-top-right-radius: 6px; }}
.sender {{ font-size: 8.5pt; font-weight: 600; color: {p['muted']}; margin: 0 0 3px 3px; }}
.meta   {{ font-size: 8pt; color: {p['muted']}; margin: 3px 4px 0; }}

headerbar button.flat {{ font-size: 9pt; font-weight: 600; color: {p['accent']};
                         min-height: 28px; padding: 0 10px; border-radius: 999px; }}
.title-name {{ font-weight: 700; font-size: 11pt; }}
.title-app  {{ font-size: 8.5pt; color: {p['muted']}; }}

.compose {{ background: {p['dark_background']}; padding: 10px 12px 12px;
            border-top: 1px solid {hairline}; }}
.compose entry {{ border-radius: 999px; min-height: 40px; padding: 0 16px;
                  background: {p['lighter_background']}; color: {p['foreground']};
                  box-shadow: none; outline: none; }}
.compose entry:focus-within {{ box-shadow: inset 0 0 0 1px alpha({p['accent']}, 0.65); }}
.compose .send {{ border-radius: 999px; min-width: 40px; min-height: 40px; padding: 0;
                  background: {p['accent']}; color: {on_accent}; }}
.compose .send:disabled {{ background: {p['lighter_background']}; color: {p['muted']}; }}

.convo-list {{ background: transparent; }}
.convo-list row {{ border-radius: 10px; margin: 2px 6px; padding: 8px; }}
.convo-list row:selected {{ background: {p['selection']}; }}
.convo-name    {{ font-weight: 600; font-size: 10pt; }}
.convo-preview {{ font-size: 9pt; color: {p['muted']}; }}
.convo-app     {{ font-size: 8pt; color: {p['muted']}; }}
{avatars}
"""
