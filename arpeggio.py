#!/usr/bin/env python3
"""Arpeggio detector: catch chords played as broken/rolled notes.

Avoids false positives from scalar runs by ignoring the ambiguous
'three adjacent scale tones' shape (add9 no5) which is the hallmark of
walking scales, not intentional arpeggiation. Everything else that forms
a recognizable chord gets reported as an arpeggio."""
import subprocess, re, sys, time
from chords import name_only, nm

PORT = sys.argv[1] if len(sys.argv) > 1 else "24:0"
BURST = 0.7      # notes within this of each other form one arpeggio

proc = subprocess.Popen(["aseqdump", "-p", PORT],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

recent = []      # [(time, note)] recent onsets
last_decl = None

for line in proc.stdout:
    m = re.search(r"Note on\s+(\d+),\s*note (\d+), velocity (\d+)", line)
    if not m: continue
    now = time.time(); n = int(m.group(2))
    recent.append((now, n))
    print(f"{nm(n):>4} on", flush=True)
    while recent and now - recent[0][0] > 2.0:
        recent.pop(0)

    # candidate = notes landing within BURST going back from newest
    burst = [n]
    for t, pn in list(reversed(recent))[1:]:
        if now - t <= BURST: burst.append(pn)
        else: break
    burst = sorted(set(burst))
    if len(burst) < 3: continue
    ch = name_only(burst)
    if not ch or ch == "(no template)": continue
    # skip the ambiguous 3-adjacent-scale-degree shape (scalar walking)
    if "add9(no5)" in ch: continue
    key = tuple(burst)
    if key != last_decl:
        last_decl = key
        print("  ~~ ARP:", " ".join(nm(x) for x in burst), "->", ch, flush=True)
