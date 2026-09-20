"""Dynamic discovery of the PSS-A50's MIDI endpoints.

The keyboard is a USB-MIDI device (driver reports PSR-E353, ALSA names it
"Digital Keyboard"). Its ALSA card + sequencer client numbers are NOT
stable - they depend on enumeration order at boot/plug time (the 2026-09-20
reboot moved it from client 24 / card 2 to client 20 / card 1). Everything
else in the app hardcoded those ids (seq "24:0", raw "hw:2,0,0"); this
module re-resolves the endpoints by name whenever asked, with a short TTL
cache so a 40ms motion-pattern send train doesn't re-parse aconnect/amidi
on every step.

Resolution:
  - seq port  (aseqdump -p): from `aconnect -l`, the KERNEL client whose
    name mentions the keyboard, first port index.
  - raw device (amidi -p): from `amidi -l`, the hw device whose name
    matches the same keywords.
If discovery comes up empty, the legacy fixed endpoints are returned so a
previously-working setup (and any other machine) keeps working unchanged.
"""

import re
import subprocess
import time

FALLBACK_SEQ = "24:0"
FALLBACK_RAW = "hw:2,0,0"

# Case-insensitive substrings that identify the board. Specific names first
# (psr/pss/yamaha) but the ALSA label "digital keyboard" is what actually
# shows up on this box.
_KEYWORDS = ("pss", "psr", "yamaha", "digital keyboard")

# Discovery is only re-run this often (motion pattern sends happen every
# ~40ms, so the cache keeps steady-state sends to one subprocess each).
_TTL = 2.0

_cache = {"seq": (None, 0.0), "raw": (None, 0.0)}

_CLIENT_RE = re.compile(r"client (\d+): '([^']+)' \[type=kernel,card=(\d+)\]")
_PORT_RE = re.compile(r"^\s+(\d+) '([^']+)'")
_AMIDI_RE = re.compile(r"^\s*\S+\s+(hw:\d+,\d+,\d+)\s+(.+)$")


def _out(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        return r.stdout or ""
    except Exception:
        return ""


def _matches(name):
    low = name.lower()
    return any(k in low for k in _KEYWORDS)


def _cached(key, fresh):
    val, at = _cache[key]
    if val is not None and time.time() - at < _TTL:
        return val, True
    return val, False


def find_seq_port():
    """Return the keyboard's aseqdump port ("N:0") or the legacy "24:0"."""
    cached, fresh = _cached("seq", None)
    if fresh:
        return cached
    port = FALLBACK_SEQ
    client_id = None
    client_ok = False
    for line in _out(["aconnect", "-l"]).splitlines():
        m = _CLIENT_RE.search(line)
        if m:
            client_id = m.group(1)
            client_ok = _matches(m.group(2))
            continue
        if client_id is not None:
            m = _PORT_RE.match(line)
            if m:
                if client_ok:
                    port = "%s:%s" % (client_id, m.group(1))
                    client_id = None
                    break
                continue
            client_id = None  # non-port line ends the current client block
    _cache["seq"] = (port, time.time())
    return port


def find_raw_device():
    """Return the keyboard's raw amidi device ("hw:N,0,0") or legacy hw:2,0,0."""
    cached, fresh = _cached("raw", None)
    if fresh:
        return cached
    dev = FALLBACK_RAW
    for line in _out(["amidi", "-l"]).splitlines():
        m = _AMIDI_RE.match(line)
        if m and _matches(m.group(2)):
            dev = m.group(1)
            break
    _cache["raw"] = (dev, time.time())
    return dev