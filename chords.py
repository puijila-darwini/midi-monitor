"""Chord interpreter: given a held note set, return a narrative of what is played."""

NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
def nm(n): return NAMES[n % 12] + str(n // 12 - 1)

# interval templates above a root (pitch-class 0)
CHORDS = {
    # triads
    (0,3,6):"dim",    (0,3,7):"min",    (0,4,7):"maj",    (0,4,8):"aug",
    (0,5,7):"sus4",   (0,2,7):"sus2",
    # 7ths
    (0,3,6,10):"m7b5",(0,3,7,10):"m7", (0,4,7,10):"7",   (0,4,7,11):"maj7",
    (0,3,7,11):"min/maj7", (0,4,8,11):"dim7", (0,3,6,9):"dim7/bb7",
    (0,5,7,10):"7sus4", (0,4,7,9):"6",  (0,3,7,9):"m6",
    (0,1,4,8):"aug7",   (0,2,6,9):"7b5", (0,4,7,8):"maj7#5",
    # 9ths & above
    (0,2,4,7,10):"9",     (0,2,4,7,11):"maj9", (0,2,3,7,10):"m9",
    (0,2,4,7,10,5):"11",  (0,2,3,7,10,5):"m11",
    (0,2,4,7,9,10):"13",  (0,2,3,7,9,10):"m13", (0,2,4,7,9,11):"maj13",
    (0,1,3,7,10):"7b9",   (0,2,3,4,7,10):"7#9",  (0,1,4,7,10):"7b9(no3)",
    (0,2,4,7):"add9",     (0,2,3,7):"m(add9)",   (0,2,4,7,9):"6add9",
    (0,2,4):"add9(no5)",  (0,4,7,1):"maj7#11",   (0,2,5,7,9):"9sus4",
    (0,2,7,10):"7sus",    (0,1,4,7,8):"maj7b6",  (0,2,3,7,9):"m6(9)",
}

# major & minor key profiles (Krumhansl-Kessler style weights per pc)
MAJ_PROFILE = {0:6.35,1:2.23,2:3.48,3:2.33,4:4.38,5:4.09,6:2.52,7:5.19,8:2.39,9:3.66,10:2.29,11:2.88}
MIN_PROFILE = {0:6.33,1:2.68,2:3.52,3:5.38,4:2.60,5:3.53,6:2.54,7:4.75,8:3.98,9:2.69,10:3.34,11:3.17}

def _pcset(notes):
    return sorted(set(n % 12 for n in notes))

def chord_candidates(notes):
    """Return (root_note, root_pc, chord_name) for every root producing a known template."""
    pcs = _pcset(notes)
    if len(pcs) < 2: return []
    out = []
    for root in pcs:
        key = tuple(sorted((n - root) % 12 for n in pcs))
        name = CHORDS.get(key)
        if name:
            for n in notes:
                if n % 12 == root:
                    out.append((n, root, name)); break
    return out

def infer_key(notes, window):
    """Best-guess key from recent pitch classes via key-profile score."""
    pcs = _pcset(window if window else notes)
    if not pcs: return None
    best = None
    for tonic in range(12):
        rel = [(pc-tonic) % 12 for pc in pcs]
        s_maj = sum(MAJ_PROFILE[pc] for pc in rel)
        s_min = sum(MIN_PROFILE[pc] for pc in rel)
        for s,tag in ((s_maj,"maj"),(s_min,"min")):
            if best is None or s > best[1]:
                best = ((tonic, tag), s)
    t,_ = best[0]
    return f"{NAMES[t]}" + (" min" if best[0][1]=="min" else "")

def interpret(notes, window=None):
    """Return a human-readable reading of the held chord."""
    if len(notes) < 2:
        return None
    notes = sorted(notes)
    bass = notes[0]
    cands = chord_candidates(notes)
    voicing = " ".join(nm(n) for n in notes)
    if not cands:
        return f"{voicing}  (no common chord template)"
    match = [c for c in cands if c[1] == bass % 12]
    pick = match[0] if match else min(cands, key=lambda c: c[0])
    root_note, root_pc, ch = pick
    label = f"{nm(root_note)} {ch}"
    if root_pc != bass % 12:
        label += f" /{nm(bass)}"
    key = infer_key(notes, window)
    return f"{voicing}  =  {label}   [key {key}]"
def name_only(notes):
    """Fast path: just the chord name, no key inference. Returns "" if n/a."""
    if len(notes) < 2: return ""
    notes = sorted(notes)
    cands = chord_candidates(notes)
    if not cands: return "(no template)"
    bass = notes[0]
    match = [c for c in cands if c[1] == bass % 12]
    pick = match[0] if match else min(cands, key=lambda c: c[0])
    root_note, root_pc, ch = pick
    label = f"{nm(root_note)} {ch}"
    if root_pc != bass % 12:
        label += f" /{nm(bass)}"
    return label

