# One phonelink window (PR 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One GTK window with Overview, Messages and Photos tabs in Caelestia Connect's layout and Omarchy's colours.

**Architecture:** The Messages and Photos windows become page widgets in the `phonelink` package; a new entry `lib/phonelink-app.py` hosts them under an `Adw.ViewStack` beside a new Overview page. Phone state for Overview is read on a worker thread and applied with `GLib.idle_add`.

**Tech Stack:** Python 3, PyGObject, GTK 4, libadwaita, KDE Connect D-Bus.

**Spec:** `docs/superpowers/specs/2026-11-19-hub-window-design.md`

## Global Constraints

- MIT: no code from Caelestia Connect (GPL-3.0).
- App id `org.omarchy.phonelink.app`; one instance; `--page overview|messages|photos`, `--new [who]`.
- Never block the main loop on the phone; no new flood of SMS requests (kdeconnectd hangs).
- Photos mounts the phone's storage only once its tab is opened.
- CI has no GTK 4: anything tested lives in a GTK-free module.

## Review Focus

- Phone away or kdeconnectd hung at launch: Overview says so (chip "Not connected"), tiles still render, no hang.
- Nothing playing: the media card is hidden, not an empty card.
- A second `phonelink text 555` with the window open: composer opens on Messages in the running window.
- Notification without `dismissable`: no ✕, and Clear all skips it.
- Battery/signal missing (permission not granted): chips hidden rather than "-1%".

---

### Task 1: Pages out of the windows

**Files:**
- Move: `lib/phonelink-messages.py` → `lib/phonelink/messages_page.py`; `lib/phonelink-photos.py` → `lib/phonelink/photos_page.py`
- Modify: both, `lib/phonelink/__init__.py`

**Interfaces:**
- Produces: `messages_page.MessagesPage(Adw.Bin)(phone: Phone, new_to: str|None)`, `.start_new(prefill)`, `messages_page.Phone`, `messages_page.extra_css(pal)`; `photos_page.PhotosPage(Adw.Bin)()`, `photos_page.extra_css(pal)`.

- [ ] Window classes become `Adw.Bin`; drop `App`/`main`/window sizing; file dialogs use `self.get_root()`; relative imports.
- [ ] `tests/run.sh` passes (compileall + ruff).

### Task 2: Overview data, GTK-free

**Files:** Create `lib/phonelink/overview.py`, `tests/test_overview.py`

**Interfaces:**
- Produces: `snapshot() -> dict` with keys `state` (`ok|away|hung|gone`), `name`, `battery` (`None|{charge, charging}`), `signal` (`None|{bars, network}`), `media` (`mpris.state` or None), `notes` (list of `read_note` dicts plus `dismissable`); `chips(snap) -> list[str]`; `parse_args(argv) -> (page, new_to)`.

- [ ] Test `chips`: `{"state":"ok","battery":{"charge":82,"charging":False},"signal":{"bars":3,"network":"5G"}}` → `["Connected","82%","5G ▂▄▆"]`; charging → `"82% ⚡"`; battery None/signal None → `["Connected"]`; state away → `["Not connected"]`.
- [ ] Test `parse_args`: `["x"]`→`("overview",None)`; `["x","--page","photos"]`→`("photos",None)`; `["x","--new"]`→`("messages","")`; `["x","--new","Naomi","Nagata"]`→`("messages","Naomi Nagata")`; unknown page → `"overview"`.
- [ ] Implement; tests pass.

### Task 3: The window

**Files:** Create `lib/phonelink-app.py`; modify `lib/phonelink/theme.py` (hub CSS)

- [ ] `App(Adw.Application)` with actions `page(s)` and `new-message(s)`; second launch activates them on the running instance.
- [ ] Header: pill `Adw.ViewSwitcher`; Overview page: device card, tiles (`ring send clip mirror desk drop` → `phonelink <cmd>`), media card (art, title, artist, album, ⏮ ⏯ ⏭, seek, volume), notifications card (✕ per dismissable note, Clear all). Poll `overview.snapshot()` every 2 s on a thread while Overview is visible.
- [ ] Messages/Photos pages created on first visit.
- [ ] Screenshot against the real phone (read-only), compare to Caelestia's overview.

### Task 4: Wiring

**Files:** `phonelink`, `integration/hyprland-messages.lua.snippet` (→ app id, v2), delete `integration/hyprland-photos.lua.snippet` + its install line, `integration/omarchy-menu.jsonc.snippet`, `README.md`

- [ ] `phonelink app|window` → Overview; `messages`, `photos`, `text` (no message) → the window on that tab.
- [ ] `tests/run.sh` all green; commit; PR.
