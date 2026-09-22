"""Phone numbers, contacts, dates and the SMS/MMS message itself.

All of it plain data work over what KDE Connect's conversations interface
hands back, so it can be tested without a phone or a window.
"""

import base64
import quopri
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


def params_of(head):
    """The parameters on a vCard property, as {NAME: value}.

    `FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE` -> {"CHARSET": "UTF-8",
    "ENCODING": "QUOTED-PRINTABLE"}. A bare parameter like TEL;CELL keeps its
    name with an empty value, which is all any caller here needs.
    """
    found = {}
    for part in head.split(";")[1:]:
        key, _, value = part.partition("=")
        found[key.strip().upper()] = value.strip()
    return found


def decode_value(value, params):
    """A property value as text, decoded if the card says it is encoded.

    Android writes vCard 2.1, which encodes any value that is not plain ASCII
    as quoted-printable: a name with an emoji or an accent arrives as
    "=4A=6F=65=73". Passed through raw, that is what shows up as the contact's
    name everywhere phonelink draws one.
    """
    if params.get("ENCODING", "").upper() not in ("QUOTED-PRINTABLE", "Q"):
        return value
    try:
        # Only the escapes are non-ASCII-safe; the line itself is ASCII by
        # definition of the encoding, and a card that breaks that rule should
        # lose a character rather than the whole contact.
        return quopri.decodestring(value.encode("utf-8", "replace")).decode(
            params.get("CHARSET") or "utf-8", "replace")
    except (LookupError, ValueError):
        return value


def cards(device_id):
    """(name, [numbers], photo bytes) per vCard KDE Connect has synced."""
    folder = Path(GLib.get_user_data_dir()) / "kpeoplevcard" / f"kdeconnect-{device_id}"
    for card in sorted(folder.glob("*.vcf")) if folder.is_dir() else []:
        try:
            raw = card.read_text(errors="replace")
        except OSError:
            continue
        name, tels, photo = "", [], None
        lines = re.sub(r"\r?\n[ \t]", "", raw).splitlines()  # unfold
        index = 0
        while index < len(lines):
            head, sep, value = lines[index].partition(":")
            index += 1
            if not sep:
                continue
            params = params_of(head)
            encoded = params.get("ENCODING", "").upper() in ("QUOTED-PRINTABLE", "Q")
            # A quoted-printable value continues on the next line whenever this
            # one ends in "=" -- a soft line break, which is not the same thing
            # as the leading-whitespace folding unwound above. The phone here
            # writes one whose continuation is an empty line.
            while encoded and value.endswith("=") and index < len(lines):
                value = value[:-1] + lines[index]
                index += 1
            key = head.split(";")[0].upper()
            if key == "FN":
                # A decoded name can carry a newline of its own (=0A), and a
                # name is drawn on one line.
                name = " ".join(decode_value(value, params).split())
            elif key == "TEL":
                tels.append(decode_value(value, params))
            elif key == "PHOTO" and value:
                data = value.split(",", 1)[1] if value.startswith("data:") else value
                try:
                    photo = base64.b64decode(data)
                except ValueError:
                    photo = None
        yield name, tels, photo


def load_contacts(device_id):
    """{number key: (name, photo bytes)} from the vCards KDE Connect syncs."""
    book = {}
    for name, tels, photo in cards(device_id):
        for tel in tels:
            if k := number_key(tel):
                book.setdefault(k, (name, photo))
    return book


def load_people(device_id):
    """[{name, number, key, photo}], one per number, for starting a new text.

    The book read by number answers "who is this?"; starting a text asks the
    other way round, and a contact with a mobile and a landline is two entries
    there, because you have to pick one to send to.
    """
    people, seen = [], set()
    for name, tels, photo in cards(device_id):
        for tel in tels:
            key = number_key(tel)
            if not key or (name, key) in seen:
                continue
            seen.add((name, key))
            people.append({"name": name or pretty_number(tel), "number": tel.strip(),
                           "key": key, "photo": photo})
    people.sort(key=lambda p: (p["name"].lower(), p["key"]))
    return people


def looks_like_number(text):
    """Is this a number to text, rather than somebody's name?

    Written as people write them: +1 (555) 010-1234, 555-0134, 5550134. Short
    codes are four digits and up, which is where the lower bound comes from.
    """
    stripped = re.sub(r"[\s().\-]", "", text or "")
    return bool(re.fullmatch(r"\+?\d{4,15}", stripped))


def clean_number(text):
    """What to hand the phone: digits, and a leading + if it was written."""
    digits = re.sub(r"\D", "", text or "")
    return ("+" if (text or "").strip().startswith("+") else "") + digits


def match_people(people, query):
    """Contacts worth offering for what has been typed, best first.

    A name typed in full wins outright, so "Jim" cannot be beaten by "Jimmy"
    while both exist; otherwise the ones starting with it, then the ones
    containing it, then numbers that contain the digits typed.
    """
    q = (query or "").strip().lower()
    if not q:
        return list(people)
    digits = re.sub(r"\D", "", q)
    exact, starts, holds, numbers = [], [], [], []
    for person in people:
        name = person["name"].lower()
        if name == q:
            exact.append(person)
        elif name.startswith(q):
            starts.append(person)
        elif q in name:
            holds.append(person)
        elif digits and digits in re.sub(r"\D", "", person["number"]):
            numbers.append(person)
    return exact + starts + holds + numbers


def resolve_recipient(text, people):
    """(address, who it is, error) for what was typed in a To field.

    A number is taken as written -- a contact may simply not be synced -- and
    named when the book knows it. A name has to come out to exactly one
    person, because sending a text to the wrong Chris is not recoverable.
    """
    text = (text or "").strip()
    if not text:
        return None, "", "Who should this go to?"
    if looks_like_number(text):
        number = clean_number(text)
        known = next((p for p in people if p["key"] == number_key(number)), None)
        return number, (known["name"] if known else pretty_number(number)), None
    hits = match_people(people, text)
    if not hits:
        if not people:
            return None, "", ("No contacts are synced, so names can't be looked up — "
                              "type a number, or allow Contacts for KDE Connect on the phone")
        return None, "", f"No contact matching “{text}”"
    names = list(dict.fromkeys(p["name"] for p in hits))
    if len(names) > 1 and names[0].lower() != text.lower():
        return None, "", "Did you mean " + ", ".join(names[:4]) + "?"
    first = hits[0]
    same = [p for p in hits if p["name"] == first["name"]]
    if len(same) > 1:
        numbers = ", ".join(pretty_number(p["number"]) for p in same[:4])
        return None, "", f"{first['name']} has several numbers: {numbers}"
    return first["number"], first["name"], None


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
