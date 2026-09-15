"""Data-driven registry of launchable MIDI destinations (the out box).

Each entry describes one external app that can receive MIDI over the ALSA
sequencer (VCV Rack, a DAW, anything), plus how to spawn it and how to tell
whether it is already running. The UI buttons, launch endpoint and boot-time
auto-routing are all derived from this table, so adding a new destination is
a one-line-ish edit here — no HTML/JS/app changes.
"""

import os
import subprocess
import threading

from .midiout import list_outs

# The keyboard's internal voices always go out over this raw device.
RAW_DEVICE = "hw:2,0,0"

# One entry per launchable app. Fields:
#   key        unique slug, used in /api/sinks/<key>/launch
#   name       display name (button label, "… is up")
#   cmd        executable to spawn when launching
#   cwd        optional working directory (default: dirname of cmd)
#   detect     seq-out client names marking the app as "running" when its
#              sink appears in aconnect -o (case-insensitive substring).
#   auto_route if True, its present sinks are ticked in the default routing.
LAUNCHABLE = [
    {
        "key": "vcv",
        "name": "VCV Rack",
        "cmd": "/home/pthag/Musica/Rack/Rack",
        "detect": ["VCV Rack"],
        "auto_route": True,
    },
]


def entries():
    """Return the LAUNCHABLE list (callers may extend it)."""
    return LAUNCHABLE


def _entries_by_key():
    return {e["key"]: e for e in LAUNCHABLE}


def _cwd(entry):
    return entry.get("cwd") or os.path.dirname(entry["cmd"]) or os.getcwd()


def _matches(entry, outs):
    det = [d.lower() for d in entry.get("detect", [])]
    if not det:
        return []
    hit = []
    for o in outs:
        name = (o.get("name") or "").lower()
        if any(d in name for d in det):
            hit.append(o["target"])
    return hit


def is_running(key, outs=None):
    """True if the sink(s) that mark this app as up are present."""
    entry = _entries_by_key().get(key)
    if entry is None:
        return False
    return bool(_matches(entry, outs if outs is not None else list_outs()))


# Per-key guard so two clicks can't double-spawn an app while it boots.
_locks = {e["key"]: threading.Lock() for e in LAUNCHABLE}
_launching = {e["key"]: False for e in LAUNCHABLE}


def launch(key):
    """Spawn the app for `key` detached if its binary exists and it isn't up.

    Returns (ok, message, running, launching)."""
    entry = _entries_by_key().get(key)
    if entry is None:
        return False, "unknown app: %s" % key, False, False
    outs = list_outs()
    if _matches(entry, outs):
        return True, "%s already running" % entry["name"], True, False
    cmd = entry.get("cmd")
    if not cmd or not os.path.isfile(cmd):
        return False, "%s binary missing: %s" % (entry["name"], cmd), False, False
    lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if _launching.get(key):
            return False, "already launching", False, True
        _launching[key] = True
    try:
        subprocess.Popen(
            [cmd] + list(entry.get("args", [])),
            cwd=_cwd(entry),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, "launching %s" % entry["name"], False, False
    except Exception as exc:
        return False, "%s launch failed: %s: %s" % (
            entry["name"], type(exc).__name__, exc), False, False
    finally:
        _launching[key] = False


def status():
    """Registry snapshot for the UI: entries with live running/launching state."""
    outs = list_outs()
    out = []
    for e in LAUNCHABLE:
        out.append({
            "key": e["key"],
            "name": e["name"],
            "cmd": e.get("cmd"),
            "cwd": _cwd(e),
            "auto_route": bool(e.get("auto_route")),
            "running": bool(_matches(e, outs)),
            "launching": bool(_launching.get(e["key"])),
        })
    return {"ok": True, "sinks": out}


def default_routing(outs=None):
    """Boot-time routing: auto-tick every present auto_route sink; the keyboard
    raw device is always on. Returns (seq_outs, raw_outs)."""
    outs = outs if outs is not None else list_outs()
    seq = []
    for e in LAUNCHABLE:
        if e.get("auto_route"):
            seq.extend(_matches(e, outs))
    return seq, [RAW_DEVICE]