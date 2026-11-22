"""Phone notifications as they came, kept so they can be searched later.

The toast service writes every notification it sees here -- Do Not Disturb
included, which is when catching up matters -- and the Overview tab searches
it. One JSON object a line, the newest last, the last KEEP of them, readable
by you alone. `phonelink history off` stops it and `phonelink history clear`
empties it.

A notification is re-sent whenever the phone reconnects or a chat gets another
message, so one already in the recent past is not written twice.
"""

import json
import os
import time
from pathlib import Path

from gi.repository import GLib

from . import kdeconnect as kde

KEEP = 500
RECENT = 50   # how far back a repeat is looked for


def path():
    return Path(GLib.get_user_state_dir()) / "phonelink" / "history.jsonl"


def off_file():
    return Path(GLib.get_user_config_dir()) / "phonelink" / "history-off"


def enabled():
    return not off_file().exists()


def flat(text):
    """One line of plain text: tags out, every run of whitespace one space."""
    return " ".join(kde.plain(text).split())


def entry(note, now=None):
    return {"time": int(now if now is not None else time.time()), "app": note.get("app", ""),
            "title": flat(note.get("title")),
            "text": flat(note.get("text") or note.get("ticker")),
            "package": note.get("package", "")}


def load(where=None):
    """Everything kept, oldest first. A line that will not parse is skipped."""
    try:
        lines = (where or path()).read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def record(note, where=None, now=None):
    """Keep one notification; False when it was a repeat or history is off."""
    if where is None and not enabled():
        return False
    where = where or path()
    new = entry(note, now)
    if not (new["title"] or new["text"]):
        return False
    kept = load(where)
    same = ("app", "title", "text")
    if any(all(old.get(k) == new[k] for k in same) for old in kept[-RECENT:]):
        return False
    kept = (kept + [new])[-KEEP:]
    where.parent.mkdir(parents=True, exist_ok=True)
    tmp = where.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in kept)
    os.replace(tmp, where)
    return True


def search(query, entries, limit=50):
    """Newest first, every word of `query` somewhere in app, title or text."""
    words = query.lower().split()
    hits = []
    for e in reversed(entries):
        hay = f"{e.get('app', '')} {e.get('title', '')} {e.get('text', '')}".lower()
        if all(w in hay for w in words):
            hits.append(e)
            if len(hits) >= limit:
                break
    return hits


def clear():
    try:
        path().unlink()
    except FileNotFoundError:
        pass


def main(argv):
    """`phonelink history [words]`: what matches, newest first, one a line."""
    from datetime import datetime
    hits = search(" ".join(argv[1:]), load(), limit=40)
    for e in reversed(hits):
        when = datetime.fromtimestamp(e.get("time", 0)).strftime("%Y-%m-%d %H:%M")
        who = " · ".join(x for x in (e.get("app"), e.get("title")) if x)
        print(f"{when}  {who}: {e.get('text', '')}")
    if not hits:
        print("nothing kept matches" if argv[1:] else
              "nothing kept yet -- the toast service records notifications as they come")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
