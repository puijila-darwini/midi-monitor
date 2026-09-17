"""Pattern library: save/load the raw-midi / out-midi buffers as named files.

Both the IN buffer (state.raw_take_events) and the OUT buffer
(state.transformed_events) carry the SAME event shape — note_on/note_off
dicts with an absolute `time` — so a pattern is just an events list plus the
transform-chain settings that gave it context. Loading a pattern restores the
events into the raw buffer and re-applies the saved settings, so an OUT
snapshot replays true even if the chain was changed in the meantime.

Storage is JSON in PATTERNS_DIR (gitignored user data, one file per pattern).
"""

import json
import os
import re
import time

PATTERNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patterns")
PATTERNS_DIR = os.path.abspath(PATTERNS_DIR)


def _slug(name):
    """'My Cool Riff!' -> 'my-cool-riff'. Empty -> 'pattern'."""
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return s or "pattern"


def _path(slug):
    if not slug or _slug(slug) != slug or ".." in slug:
        return None
    return os.path.join(PATTERNS_DIR, slug + ".json")


def list_patterns():
    """Metadata for every saved pattern, newest first."""
    from . import arrange
    if not os.path.isdir(PATTERNS_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(PATTERNS_DIR)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(PATTERNS_DIR, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        settings = data.get("settings") or {}
        tempo = settings.get("tempo_bpm") or 120.0
        try:
            tempo = float(tempo)
        except (TypeError, ValueError):
            tempo = 120.0
        if tempo <= 0:
            tempo = 120.0
        bars_ov = data.get("bars")
        try:
            bars_ov = int(bars_ov) if bars_ov is not None else None
            if bars_ov is not None and not 1 <= bars_ov <= 64:
                bars_ov = None
        except (TypeError, ValueError):
            bars_ov = None
        out.append({
            "filename": fn[:-5],
            "name": data.get("name", fn[:-5]),
            "kind": data.get("kind", "raw"),
            "created": data.get("created"),
            "note_count": (data.get("meta") or {}).get("note_count", 0),
            "duration": (data.get("meta") or {}).get("duration", 0.0),
            "tempo_bpm": (data.get("settings") or {}).get("tempo_bpm"),
            "time_signature": (data.get("settings") or {}).get("time_signature"),
            # Legacy arrangement tag (pre-slots): only used to seed matching
            # slots once on first run. The tag system is otherwise retired.
            "tag": data.get("tag"),
            "bars": arrange.pattern_bars(data.get("events", []), tempo,
                                         settings.get("time_signature"), bars_ov),
            "bars_auto": bars_ov is None,
        })
    out.sort(key=lambda m: (m.get("created") or 0), reverse=True)
    return out


def save_pattern(name, kind, events, settings):
    """Write a pattern file. Returns its metadata dict (or raises)."""
    events = list(events or [])
    if not events:
        raise ValueError("buffer is empty — nothing to save")
    if kind not in ("raw", "out"):
        raise ValueError("kind must be 'raw' or 'out'")
    name = (name or "").strip() or "pattern-%s" % time.strftime("%Y%m%d-%H%M%S")
    slug = _slug(name)
    ns = [int(e["note"]) for e in events if e.get("type") == "note_on"]
    duration = 0.0
    if ns or events:
        ts = [float(e.get("time", 0)) for e in events]
        duration = max(ts) - min(ts) if ts else 0.0
    meta = {"note_count": len(ns), "duration": round(duration, 3)}
    data = {
        "name": name,
        "kind": kind,
        "created": time.time(),
        "events": events,
        "settings": dict(settings or {}),
        "meta": meta,
    }
    os.makedirs(PATTERNS_DIR, exist_ok=True)
    p = _path(slug)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)
    return {
        "filename": slug,
        "name": name,
        "kind": kind,
        "created": data["created"],
        "note_count": meta["note_count"],
        "duration": meta["duration"],
    }


def load_pattern(slug):
    """Read a pattern file. Returns {name, kind, events, settings, meta}."""
    p = _path(_slug(slug))
    if not p or not os.path.isfile(p):
        raise ValueError("no such pattern: %s" % slug)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "name": data.get("name", slug),
        "kind": data.get("kind", "raw"),
        "events": data.get("events", []),
        "settings": data.get("settings", {}),
        "meta": data.get("meta", {}),
        "bars": data.get("bars"),
    }


def _update_file(slug, mutate):
    """Read-modify-write a pattern file atomically. mutate(data)->(ok, error)."""
    p = _path(_slug(slug))
    if not p or not os.path.isfile(p):
        return False, "no such pattern: %s" % slug
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False, "pattern file is corrupt: %s" % slug
    ok, err = mutate(data)
    if not ok:
        return False, err
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)
    return True, None


def set_pattern_bars(slug, bars):
    """Override a pattern's bar length (int 1-64), or clear with None."""
    if bars is None or (isinstance(bars, str) and not bars.strip()):
        bars = None
    else:
        try:
            bars = int(bars)
        except (TypeError, ValueError):
            return None, "bars must be a whole number 1-64"
        if not 1 <= bars <= 64:
            return None, "bars must be a whole number 1-64"

    def mutate(data):
        data["bars"] = bars
        return True, None
    ok, err = _update_file(slug, mutate)
    if not ok:
        return None, err
    return bars, None


def delete_pattern(slug):
    """Remove a pattern file. Returns True, or False if it didn't exist."""
    p = _path(_slug(slug))
    if not p or not os.path.isfile(p):
        return False
    os.remove(p)
    return True