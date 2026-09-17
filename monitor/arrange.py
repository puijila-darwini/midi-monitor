"""Arrangement tracker: chain saved patterns into songs via a text string.

A song is a whitespace-separated token string like "AA BC AA BC D BC A".
Each letter is a pattern tag (set in the pattern strip). Tokens support:
  A            play pattern A once
  A*4          repeat A four times
  B+2 / B-3    transpose the slot by semitones
  C(Strings)   play slot C on the Strings voice (PC at the slot start)
  |            visual separator, ignored
Combined: D*2-3(Electric Piano 1).

Slots are laid out on a bar grid at the arrangement tempo: each slot's events
are normalized to start at 0, converted seconds->beats at the slot's recorded
tempo, then beats->seconds at the arrangement tempo, transposed, and offset by
the cumulative bar count. A slot's length in bars is ceil(beats / beats_per_bar)
unless the pattern has a stored bar override. Voice slots emit a
{"type":"program","bank","pc"} event at the slot start, which the replay
engine sends mid-stream (the board applies PC to received notes only).

Storage is JSON in ARRANGEMENTS_DIR (gitignored user data, like patterns/).
All functions here are pure / filesystem-only: keyboard-independent and unit
testable by driving them directly.
"""

import json
import os
import re
import time

ARRANGEMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "arrangements")
ARRANGEMENTS_DIR = os.path.abspath(ARRANGEMENTS_DIR)

_TOKEN = re.compile(r"^([A-Za-z])(?:\*([0-9]+))?(?:([+-])([0-9]+))?(?:\(([^)]*)\))?$")
_TOKEN_ALT = re.compile(r"^([A-Za-z])(?:\*([0-9]+))?(?:\(([^)]*)\))?(?:([+-])([0-9]+))?$")


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


def parse_arrangement(text):
    """Parse a song string into slot dicts.

    Returns (slots, error): slots = [{letter, repeat, transpose, voice}],
    expanded later (repeat is per-slot). error is None on success.
    """
    # Tokenize on whitespace, but keep parenthesised voice names (which
    # contain spaces, e.g. "Electric Piano 1") inside one token.
    toks, depth, cur = [], 0, []
    for ch in str(text or ""):
        if ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch.isspace() and depth == 0:
            if cur:
                toks.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        toks.append("".join(cur))
    toks = [t for t in toks if t and t != "|"]
    if not toks:
        return None, "empty arrangement — try something like 'AA BC AA BC D BC A'"
    slots = []
    for tok in toks:
        # Bare runs like "AA" or "BC" mean A-twice / B-then-C (the way song
        # sections are usually written). Anything with a modifier (*, +/-, or
        # parens) must be a single letter.
        if re.match(r"^[A-Za-z]{2,}$", tok):
            for ch in tok:
                slots.append({"letter": ch.upper(), "repeat": 1,
                              "transpose": 0, "voice": None})
            continue
        m = _TOKEN.match(tok)
        alt = None
        if not m:
            # Also accept voice-before-transpose: B(Strings)+2.
            alt = _TOKEN_ALT.match(tok)
            if alt:
                m = alt
        if not m:
            return None, ("bad token '%s' — use a letter like A, with optional "
                          "*N repeat, +/-N transpose, (Voice): e.g. D*2-3(Strings)" % tok)
        if alt:
            letter, rep, voice_raw, tsign, tnum = m.groups()
        else:
            letter, rep, tsign, tnum, voice_raw = m.groups()
        repeat = int(rep) if rep else 1
        if not 1 <= repeat <= 64:
            return None, "repeat out of range 1-64 in '%s'" % tok
        transpose = int(tsign + tnum) if tsign else 0
        if abs(transpose) > 60:
            return None, "transpose out of range +/-60 in '%s'" % tok
        if voice_raw is not None and not voice_raw.strip():
            return None, "empty voice in '%s' — use a voice name like (Strings)" % tok
        voice = (voice_raw or "").strip() or None
        slots.append({"letter": letter.upper(), "repeat": repeat,
                      "transpose": transpose, "voice": voice})
    return slots, None


def build_arrangement(slots, resolve_pattern, arr_tempo, arr_sig, resolve_voice):
    """Concatenate slots into one raw-event timeline.

    resolve_pattern(tag) -> {"events", "settings", "bars", "name"} (bars is
      the stored override or None). resolve_voice(name) -> (bank, pc) or None.
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
    for slot in slots:
        for _ in range(slot["repeat"]):
            try:
                pat = resolve_pattern(slot["letter"])
            except (KeyError, ValueError):
                raise ValueError("no pattern tagged '%s'" % slot["letter"])
            events = [e for e in (pat.get("events") or [])
                      if e.get("type") in ("note_on", "note_off")]
            ons = [e for e in events if e.get("type") == "note_on"]
            if not ons:
                raise ValueError("pattern '%s' has no notes" % pat.get("name", slot["letter"]))
            settings = pat.get("settings") or {}
            slot_tempo = settings.get("tempo_bpm") or 120.0
            try:
                slot_tempo = float(slot_tempo)
            except (TypeError, ValueError):
                slot_tempo = 120.0
            if slot_tempo <= 0:
                slot_tempo = 120.0
            t0 = min(float(e.get("time", 0)) for e in events)
            shift = int(slot["transpose"])
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
            if slot["voice"] and slot["voice"].lower() != "auto":
                bank_pc = resolve_voice(slot["voice"])
                if bank_pc is None:
                    raise ValueError("unknown voice '%s' (slot %s)" % (slot["voice"], slot["letter"]))
                bank, pc = bank_pc
                out.append({"type": "program", "bank": int(bank),
                            "pc": int(pc), "time": cursor, "channel": 0})
            infos.append({"tag": slot["letter"], "name": pat.get("name", ""),
                          "voice": slot["voice"], "transpose": shift,
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
    slots, err = parse_arrangement(text)
    if err:
        raise ValueError(err)
    name = (name or "").strip() or "arrangement-%s" % time.strftime("%Y%m%d-%H%M%S")
    slug = _slug(name)
    data = {"name": name, "text": " ".join(
        _slot_text(s) for s in slots), "created": time.time()}
    os.makedirs(ARRANGEMENTS_DIR, exist_ok=True)
    p = _apath(slug)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)
    return {"filename": slug, "name": name, "text": data["text"]}


def _slot_text(s):
    t = s["letter"]
    if s["repeat"] != 1:
        t += "*%d" % s["repeat"]
    if s["transpose"]:
        t += "%+d" % s["transpose"]
    if s["voice"]:
        t += "(%s)" % s["voice"]
    return t


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
