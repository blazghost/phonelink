#!/usr/bin/env python3
"""Put one marked, versioned block of config into a file -- and keep it current.

Each snippet carries its own markers and a version:

    -- phonelink:panel:begin v2
    ... the rules ...
    -- phonelink:panel:end

The block is added when it is missing, replaced in place when the snippet's
version has moved on, and left alone when it is already current. That is what
lets an update change a rule it shipped earlier without a one-off migration in
install.sh for every release -- and without touching a line outside its own
markers.

An installation from before the markers existed is migrated the same way: name
the text that identifies the old rule with --legacy, and the statement it
belongs to (comments above it, brackets balanced below it) is replaced by the
new block, wherever in the file it sits.

    install-block.py <target> <snippet> [--legacy TEXT ...]

Prints what it did: added, updated, migrated, current, or missing.
"""

import re
import sys
from pathlib import Path

MARKER = re.compile(r"phonelink:([A-Za-z0-9_-]+):(begin|end)(?:\s+v(\d+))?\s*$")
OPEN, CLOSE = "([{", ")]}"


def marker(line):
    """(name, begin|end, version) for a marker line, else None."""
    found = MARKER.search(line)
    return (found[1], found[2], int(found[3]) if found[3] else 0) if found else None


def snippet_block(path):
    lines = path.read_text().splitlines(keepends=True)
    heads = [(i, marker(line)) for i, line in enumerate(lines)]
    begin = next((i for i, m in heads if m and m[1] == "begin"), None)
    end = next((i for i, m in heads if m and m[1] == "end"), None)
    if begin is None or end is None:
        sys.exit(f"{path}: needs phonelink:<name>:begin vN and :end markers")
    name, _, version = marker(lines[begin])
    return name, version, lines[begin:end + 1]


def find_block(lines, name):
    """(start, end, version) of this block in the target, or None."""
    begin = end = version = None
    for i, line in enumerate(lines):
        if not (m := marker(line)) or m[0] != name:
            continue
        if m[1] == "begin":
            begin, version = i, m[2]
        elif begin is not None:
            end = i
            break
    if begin is not None and end is None:
        sys.exit(f"phonelink:{name}:begin has no matching :end -- fix the file by hand")
    return (begin, end, version) if begin is not None else None


def blocks(lines):
    """Every line already inside some phonelink block, of any name."""
    inside, start = set(), None
    for i, line in enumerate(lines):
        if not (m := marker(line)):
            continue
        if m[1] == "begin":
            start = i
        elif start is not None:
            inside.update(range(start, i + 1))
            start = None
    return inside


def find_legacy(lines, name, texts):
    """(start, end) of an unmarked older version of this rule, or None.

    Backwards over the comment lines directly above it, forwards until the
    brackets the statement opened are closed again -- which covers both a rule
    written on one line and one spread over several.

    Nothing already inside a phonelink block counts as a hit: on a second run
    the new block contains the same text, and taking that as an old rule would
    have it replace itself. Neither walk crosses a blank line or a marker, so a
    comment of yours above the rule, and the block before it, are left alone.
    """
    taken = blocks(lines)
    hit = next((i for i, line in enumerate(lines)
                if any(t in line for t in texts) and i not in taken), None)
    if hit is None:
        return None

    def comment(i):
        return lines[i].lstrip().startswith(("--", "//", "#")) and not marker(lines[i])

    start = hit
    while start > 0 and comment(start - 1) and (start - 1) not in taken:
        start -= 1
    end, depth = hit, 0
    for i in range(hit, len(lines)):
        if marker(lines[i]):
            break
        code = lines[i].split("--")[0]
        depth += sum(code.count(c) for c in OPEN) - sum(code.count(c) for c in CLOSE)
        end = i
        if depth <= 0:
            break
    return start, end


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__.strip().splitlines()[-3].strip())
    target, snippet = Path(argv[1]), Path(argv[2])
    legacy = [a for a in argv[3:] if a != "--legacy"]

    if not target.is_file():
        print("missing")
        return 0

    name, version, block = snippet_block(snippet)
    lines = target.read_text().splitlines(keepends=True)

    if found := find_block(lines, name):
        start, end, have = found
        if have == version:
            print("current")
            return 0
        lines[start:end + 1] = block
        target.write_text("".join(lines))
        print("updated")
        return 0

    if legacy and (old := find_legacy(lines, name, legacy)):
        start, end = old
        lines[start:end + 1] = block
        target.write_text("".join(lines))
        print("migrated")
        return 0

    text = "".join(lines)
    target.write_text(text.rstrip("\n") + "\n" + "".join(block))
    print("added")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
