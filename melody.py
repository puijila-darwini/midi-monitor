#!/usr/bin/env python3
"""Melody recorder: capture single-note sequences with timing."""
import subprocess, re, sys, time, threading, os
from chords import nm

PORT = sys.argv[1] if len(sys.argv) > 1 else "24:0"
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
proc = subprocess.Popen(["aseqdump", "-p", PORT],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

current = None
melody = []
start = time.time()

def finish():
    print()
    if current is not None:
        melody.append((current[0], time.time()-start-current[0], current[1]))
    if not melody:
        print("no notes captured")
        os._exit(0)
    print("\n== MELODY ==", flush=True)
    for t, d, n in melody:
        print(f"  {t:6.2f}s  {nm(n):>4}  dur={d*1000:5.0f}ms", flush=True)
    print("\n== INTERVALS (semitones) ==", flush=True)
    for i in range(1, len(melody)):
        iv = melody[i][2] - melody[i-1][2]
        d = "+" if iv>0 else ("-" if iv<0 else "=")
        print(f"  {nm(melody[i-1][2]):>4} -> {nm(melody[i][2]):>4}  {d}{abs(iv)}", flush=True)
    os._exit(0)

threading.Timer(DURATION, finish).start()
print(f"recording melody for {DURATION:.0f}s...", flush=True)
try:
    for line in proc.stdout:
        m  = re.search(r"Note on\s+(\d+),\s*note (\d+), velocity (\d+)", line)
        mo = re.search(r"Note off\s+(\d+),\s*note (\d+)", line)
        now = time.time() - start
        if mo and current and mo.group(2) == str(current[1]):
            melody.append((current[0], now-current[0], current[1]))
            current = None
        elif m:
            n = int(m.group(2))
            if current is not None and current[1] != n:
                melody.append((current[0], now-current[0], current[1]))
            current = (now, n)
except KeyboardInterrupt:
    finish()
