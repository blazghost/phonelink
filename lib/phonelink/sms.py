"""Phone numbers, contacts, dates and the SMS/MMS message itself.

All of it plain data work over what KDE Connect's conversations interface
hands back, so it can be tested without a phone or a window.
"""

import base64
import re
from datetime import datetime
from pathlib import Path

from gi.repository import GLib

PAGE = 50            # messages asked for per page of a thread
OUTGOING = {2, 4, 5, 6}  # Android: sent, outbox, failed, queued
FAILED = 5


class Att:
    __slots__ = ("part", "mime", "thumb", "uid")

    def __init__(self, part, mime, thumb, uid):
        self.part, self.mime, self.thumb, self.uid = part, mime, thumb, uid

    @property
    def kind(self):
        return self.mime.split("/")[0]


class Msg:
    """One entry of KDE Connect's (isa(s)xiixixa(xsss)) ConversationMessage."""
    __slots__ = ("body", "addresses", "date", "type", "read", "thread", "uid", "attachments")

    def __init__(self, variant):
        t = variant.unpack()
        self.body, self.date, self.type, self.read = t[1], t[3], t[4], t[5]
        self.addresses = [a[0] for a in t[2]]
        self.thread, self.uid = t[6], t[7]
        self.attachments = [Att(*a) for a in t[9]]

    @property
    def outgoing(self):
        return self.type in OUTGOING


def match_attachment(name, waiting):
    """Which pending attachment a delivered file belongs to, or None.

    KDE Connect writes the file under the attachment's own unique identifier,
    give or take the extension, so that is all this matches on. Anything looser
    -- a prefix, or assuming a lone transfer in flight must be the file that
    just arrived -- can put somebody else's picture in a bubble, because KDE
    Connect's own app downloads into the same folder.
    """
    stem = Path(name).stem
    return next((uid for uid in waiting if uid == name or Path(uid).stem == stem), None)


def number_key(number):
    """Phone numbers compare by their last ten digits: +1 555..., 555... match."""
    digits = re.sub(r"\D", "", number or "")
    return digits[-10:] if len(digits) >= 10 else digits


def pretty_number(number):
    digits = re.sub(r"\D", "", number or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number or "Unknown"


def load_contacts(device_id):
    """{number key: (name, photo bytes)} from the vCards KDE Connect syncs."""
    book = {}
    folder = Path(GLib.get_user_data_dir()) / "kpeoplevcard" / f"kdeconnect-{device_id}"
    for card in sorted(folder.glob("*.vcf")) if folder.is_dir() else []:
        try:
            raw = card.read_text(errors="replace")
        except OSError:
            continue
        name, tels, photo = "", [], None
        for line in re.sub(r"\r?\n[ \t]", "", raw).splitlines():  # unfold
            head, _, value = line.partition(":")
            key = head.split(";")[0].upper()
            if key == "FN":
                name = value.strip()
            elif key == "TEL":
                tels.append(value)
            elif key == "PHOTO" and value:
                data = value.split(",", 1)[1] if value.startswith("data:") else value
                try:
                    photo = base64.b64decode(data)
                except ValueError:
                    photo = None
        for tel in tels:
            if k := number_key(tel):
                book.setdefault(k, (name, photo))
    return book


def when(ms):
    """List-row time: 4:05 PM, Yesterday, Mon, Sep 3, Sep 3, 2025."""
    dt, now = datetime.fromtimestamp(ms / 1000), datetime.now()
    days = (now.date() - dt.date()).days
    if days == 0:
        return dt.strftime("%-I:%M %p")
    if days == 1:
        return "Yesterday"
    if days < 7:
        return dt.strftime("%a")
    return dt.strftime("%b %-d" if dt.year == now.year else "%b %-d, %Y")


def day_label(ms):
    dt, now = datetime.fromtimestamp(ms / 1000), datetime.now()
    days = (now.date() - dt.date()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    return dt.strftime("%A, %B %-d" if dt.year == now.year else "%A, %B %-d, %Y")
