#!/usr/bin/env python3
import subprocess, re, sys
from chords import name_only, nm

PORT = sys.argv[1] if len(sys.argv) > 1 else "24:0"
proc = subprocess.Popen(["aseqdump", "-p", PORT],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
held = {}
_last = (0,0,0)

for line in proc.stdout:
    m  = re.search(r"Note on\s+(\d+),\s*note (\d+), velocity (\d+)", line)
    mo = re.search(r"Note off\s+(\d+),\s*note (\d+)", line)
    if m:
        held[int(m.group(2))] = True
        if len(held) >= 3:
            k = tuple(sorted(held))
            if k != _last:
                _last = k
                n = name_only(held)
                raw = " ".join(nm(x) for x in sorted(held))
                if n == "(no template)":
                    print("  ??", raw, "-> no template", flush=True)
                else:
                    print("  >>", n, " |", raw, flush=True)
    elif mo:
        held.pop(int(mo.group(2)), None)
