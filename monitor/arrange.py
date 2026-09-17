"""Arrangement tracker: chain patterns into songs via slot addresses.

There are 64 fixed SLOTS (not tags), addressed by the base64 alphabet:
A-Z, a-z, 0-9, +, /. Each slot points at one stored pattern (or is empty)
and carries its own transpose + voice. An arrangement is a string of slot
characters — each char plays that slot's pattern in sequence:

  "AABCCDAA"   play slots A A B C C D A A (repetition = repeat the char)

Whitespace and "|" are visual separators and ignored. Every other character
must be a slot address.

Slots are laid out on a bar grid at the arrangement tempo: each slot's events
are normalized to start at 0, converted seconds->beats at the slot's recorded
tempo, then beats->seconds at the arrangement tempo, transposed (the slot's
transpose), and offset by the cumulative bar count. A slot's length in bars is
ceil(beats / beats_per_bar) unless the pattern has a stored bar override;
content is clipped to the window with ringing notes cut at the edge. Slot
voices emit a {"type":"program","bank","pc"} event at the slot start, which
the replay engine sends mid-stream (the board applies PC to received notes
only).

Slot assignments persist in SLOTS_PATH (gitignored user data, like patterns/).
Arrangement strings persist in ARRANGEMENTS_DIR.
All functions here are pure / filesystem-only: keyboard-independent and unit
testable by driving them directly.
"""

import json
import os
import re
import time

ARRANGEMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "arrangements")
ARRANGEMENTS_DIR = os.path.abspath(ARRANGEMENTS_DIR)
SLOTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "slots.json")
SLOTS_PATH = os.path.abspath(SLOTS_PATH)

SLOT_ALPHABET = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                 "abcdefghijklmnopqrstuvwxyz"
                 "0123456789+/")
assert len(SLOT_ALPHABET) == 64

def slot_index(ch):
    """Base64 slot char -> 0-63, or -1."""
    try:
        return SLOT_ALPHABET.index(ch)
    except (ValueError, TypeError):
        return -1


def parse_arrangement(text):
    """Parse a song string into slot chars.

    Returns (chars, error): chars = ["A", "A", "B", ...]. error is None
    on success.
    """
    chars = [ch for ch in str(text or "") if not ch.isspace() and ch != "|"]
    if not chars:
        return None, "empty arrangement — try slot letters like 'AABC'"
    for ch in chars:
        if slot_index(ch) < 0:
            return None, ("bad slot '%s' — use a base64 slot char "
                          "A-Z a-z 0-9 + /" % ch)
    return chars, None


def blank_slots():
    """64 empty slot dicts: {"pattern": slug|None, "transpose": int, "voice": str|None}."""
    return [{"pattern": None, "transpose": 0, "voice": None} for _ in range(64)]


def _coerce_slot(raw):
    s = {"pattern": None, "transpose": 0, "voice": None}
    if not isinstance(raw, dict):
        return s
    pat = raw.get("pattern")
    s["pattern"] = str(pat) if pat else None
    try:
        t = int(raw.get("transpose", 0))
    except (TypeError, ValueError):
        t = 0
    s["transpose"] = max(-60, min(60, t))
    v = (raw.get("voice") or "")
    if isinstance(v, str):
        v = v.strip()
    s["voice"] = v or None
    return s


def load_slots(migrate_from=()):
    """Load the 64 slot assignments. migrate_from is a pattern-metadata list
    (with filename/tag keys); on a missing slots file, legacy single-letter
    pattern tags seed the matching slots once."""
    slots = None
    if os.path.isfile(SLOTS_PATH):
        try:
            with open(SLOTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                slots = [_coerce_slot(s) for s in data[:64]]
                while len(slots) < 64:
                    slots.append({"pattern": None, "transpose": 0, "voice": None})
        except (OSError, ValueError):
            slots = None
    if slots is None:
        slots = blank_slots()
        for m in migrate_from or ():
            tag = (m.get("tag") or "").strip().upper()
            if len(tag) == 1 and tag in SLOT_ALPHABET:
                i = slot_index(tag)
                if slots[i]["pattern"] is None and m.get("filename"):
                    slots[i]["pattern"] = m["filename"]
        try:
            save_slots(slots)
        except (OSError, ValueError):
            pass
    return slots


def save_slots(slots):
    """Persist 64 slot dicts atomically. Raises ValueError on bad shape."""
    if not isinstance(slots, list) or len(slots) != 64:
        raise ValueError("slots must be a list of 64")
    slots = [_coerce_slot(s) for s in slots]
    os.makedirs(os.path.dirname(SLOTS_PATH), exist_ok=True)
    tmp = SLOTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(slots, f, indent=1)
    os.replace(tmp, SLOTS_PATH)
    return slots


def set_slot(slots, index, pattern, transpose=0, voice=None):
    """Assign one slot in a loaded slot list (index 0-63). Returns the slot."""
    if not 0 <= int(index) < 64:
        raise ValueError("slot index out of range 0-63")
    try:
        transpose = int(transpose)
    except (TypeError, ValueError):
        raise ValueError("transpose must be a whole number")
    if not -60 <= transpose <= 60:
        raise ValueError("transpose out of range +/-60")
    if pattern is not None and not str(pattern).strip():
        pattern = None
    if isinstance(voice, str):
        voice = voice.strip() or None
    if voice is not None and not isinstance(voice, str):
        raise ValueError("voice must be a name")
    slots[int(index)] = {"pattern": str(pattern) if pattern else None,
                         "transpose": transpose, "voice": voice}
    return slots[int(index)]


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return s or "arrangement"


def _apath(slug):
    if not slug or _slug(slug) != slug or ".." in slug:
        return None
    return os.path.join(ARRANGEMENTS_DIR, slug + ".json")


def beats_per_bar(sig):
    """Quarter-note beats in one bar for a "N/D" time signature ("4/4"->4.0)."""
    try:
        n, d = str(sig or "4/4").split("/")
        n, d = int(n), int(d)
        if n < 1 or d not in (2, 4, 8, 16):
            raise ValueError
        return n * 4.0 / d
    except (ValueError, AttributeError):
        return 4.0


def pattern_beats(events, tempo):
    """Total beats spanned by note events (seconds * tempo/60)."""
    tempo = float(tempo or 120.0)
    if tempo <= 0:
        tempo = 120.0
    ts = [float(e.get("time", 0)) for e in events or []
          if e.get("type") in ("note_on", "note_off")]
    if not ts:
        return 0.0
    return (max(ts) - min(ts)) * tempo / 60.0


def pattern_bars(events, tempo, sig, override=None):
    """Bar length of a pattern: stored override wins, else ceil to the grid."""
    try:
        ov = int(override)
        if ov >= 1:
            return min(ov, 64)
    except (TypeError, ValueError):
        pass
    qpb = beats_per_bar(sig)
    beats = pattern_beats(events, tempo)
    if beats <= 0:
        return 1
    import math
    return max(1, min(64, int(math.ceil(beats / qpb - 1e-9))))


def build_arrangement(chars, resolve_slot, arr_tempo, arr_sig, resolve_voice):
    """Concatenate slot chars into one raw-event timeline.

    resolve_slot(char) -> {"events", "settings", "bars", "name",
      "transpose", "voice"} (bars is the stored pattern override or None;
      transpose/voice are the slot's own). Raises ValueError if the slot is
      empty or its pattern is missing. resolve_voice(name) -> (bank, pc).
    Returns {"events", "slots", "total_bars", "duration", "notes"}.
    Raises ValueError with a human message on any problem.
    """
    arr_tempo = float(arr_tempo or 120.0)
    if arr_tempo <= 0:
        arr_tempo = 120.0
    qpb = beats_per_bar(arr_sig)
    bar_sec = qpb * 60.0 / arr_tempo
    out = []
    infos = []
    cursor = 0.0
    for ch in chars:
        try:
            got = resolve_slot(ch)
        except (KeyError, ValueError) as exc:
            raise ValueError(str(exc) or "slot '%s' cannot play" % ch)
        pat, shift, voice = got["pattern"], int(got["transpose"]), got["voice"]
        events = [e for e in (pat.get("events") or [])
                  if e.get("type") in ("note_on", "note_off")]
        ons = [e for e in events if e.get("type") == "note_on"]
        if not ons:
            raise ValueError("slot '%s' pattern '%s' has no notes" % (
                ch, pat.get("name", "?")))
        settings = pat.get("settings") or {}
        slot_tempo = settings.get("tempo_bpm") or 120.0
        try:
            slot_tempo = float(slot_tempo)
        except (TypeError, ValueError):
            slot_tempo = 120.0
        if slot_tempo <= 0:
            slot_tempo = 120.0
        t0 = min(float(e.get("time", 0)) for e in events)
        bars = pattern_bars(events, slot_tempo, arr_sig, pat.get("bars"))
        window_beats = bars * qpb
        # Clip to the slot window (tracker semantics: a 2-bar slot plays
        # the first 2 bars). Pair ons/offs in beat order; notes still
        # sounding at the boundary get a cut off there. A velocity-0
        # note_on counts as an off.
        clipped = []
        for e in sorted(events, key=lambda x: float(x.get("time", 0))):
            beat = (float(e.get("time", 0)) - t0) * slot_tempo / 60.0
            note = max(0, min(127, int(e.get("note", 60)) + shift))
            if e["type"] == "note_on":
                try:
                    v = int(e.get("velocity", 90))
                except (TypeError, ValueError):
                    v = 90
                if v == 0:
                    clipped.append(("off", beat, note))
                elif beat < window_beats - 1e-9:
                    clipped.append(("on", beat, note,
                                    max(1, min(127, v))))
            else:
                clipped.append(("off", beat, note))
        top_beat = 0.0
        opens = {}
        for item in clipped:
            if item[0] == "on":
                _, beat, note, vel = item
                sec = cursor + beat * 60.0 / arr_tempo
                out.append({"type": "note_on", "note": note,
                            "velocity": vel, "time": sec, "channel": 0})
                opens[note] = opens.get(note, 0) + 1
                top_beat = max(top_beat, beat)
            else:
                _, beat, note = item
                if opens.get(note, 0) <= 0:
                    continue  # stray off (or its on was clipped away)
                opens[note] -= 1
                if beat >= window_beats - 1e-9:
                    beat = window_beats  # cut ringing notes at the edge
                sec = cursor + beat * 60.0 / arr_tempo
                out.append({"type": "note_off", "note": note,
                            "time": sec, "channel": 0})
                top_beat = max(top_beat, beat)
        for note, n in opens.items():
            for _ in range(n):
                out.append({"type": "note_off", "note": note,
                            "time": cursor + window_beats * 60.0 / arr_tempo,
                            "channel": 0})
            top_beat = window_beats
        if voice and voice.lower() != "auto":
            bank_pc = resolve_voice(voice)
            if bank_pc is None:
                raise ValueError("unknown voice '%s' (slot %s)" % (voice, ch))
            bank, pc = bank_pc
            out.append({"type": "program", "bank": int(bank),
                        "pc": int(pc), "time": cursor, "channel": 0})
        infos.append({"slot": ch, "name": pat.get("name", ""),
                      "voice": voice, "transpose": shift,
                      "bars": bars, "start": round(cursor, 3)})
        cursor += bars * bar_sec
    duration = max([float(e.get("time", 0)) for e in out] or [0.0])
    notes = sum(1 for e in out if e.get("type") == "note_on")
    total_bars = sum(i["bars"] for i in infos)
    return {"events": out, "slots": infos, "total_bars": total_bars,
            "duration": round(duration, 3), "notes": notes}


def list_arrangements():
    if not os.path.isdir(ARRANGEMENTS_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(ARRANGEMENTS_DIR)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(ARRANGEMENTS_DIR, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        out.append({"filename": fn[:-5], "name": data.get("name", fn[:-5]),
                    "text": data.get("text", ""),
                    "created": data.get("created")})
    out.sort(key=lambda m: (m.get("created") or 0), reverse=True)
    return out


def save_arrangement(name, text):
    chars, err = parse_arrangement(text)
    if err:
        raise ValueError(err)
    name = (name or "").strip() or "arrangement-%s" % time.strftime("%Y%m%d-%H%M%S")
    slug = _slug(name)
    data = {"name": name, "text": str(text or "").strip(), "created": time.time()}
    os.makedirs(ARRANGEMENTS_DIR, exist_ok=True)
    p = _apath(slug)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)
    return {"filename": slug, "name": name, "text": data["text"]}


def load_arrangement(slug):
    p = _apath(_slug(slug))
    if not p or not os.path.isfile(p):
        raise ValueError("no such arrangement: %s" % slug)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"name": data.get("name", slug), "text": data.get("text", "")}


def delete_arrangement(slug):
    p = _apath(_slug(slug))
    if not p or not os.path.isfile(p):
        return False
    os.remove(p)
    return True
