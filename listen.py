#!/usr/bin/env python3
"""Clean real-time MIDI note listener.

Filters out Clock & Active Sensing chatter. Reads aseqdump output and
prints only real note events with note names. Optionally names chords.
"""
import subprocess, re, sys, time
from chords import interpret, nm

PORT = sys.argv[1] if len(sys.argv) > 1 else "24:0"

proc = subprocess.Popen(["aseqdump", "-p", PORT],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
held = {}
history = []          # rolling list of pitch classes seen (for key inference)
KEY_WINDOW = 24
_last_chord = None

def report_chord():
    global _last_chord
    if len(held) < 2: return
    raw = sorted(held)
    key = (tuple(raw),)
    if key == _last_chord: return
    _last_chord = key
    print("     >> " + interpret(raw, history), flush=True)

try:
    for line in proc.stdout:
        m  = re.search(r"Note on\s+(\d+),\s*note (\d+), velocity (\d+)", line)
        mo = re.search(r"Note off\s+(\d+),\s*note (\d+)", line)
        if m:
            note = int(m.group(2)); vel = int(m.group(3))
            held[note] = True
            history.append(note % 12)
            if len(history) > KEY_WINDOW: history.pop(0)
            print(f"{nm(note):>4}  on   v{vel}", flush=True)
        elif mo:
            note = int(mo.group(2))
            held.pop(note, None)
            print(f"{nm(note):>4}  off", flush=True)
        report_chord()
except KeyboardInterrupt:
    pass
