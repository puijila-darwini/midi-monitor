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

# Mode interval patterns (half-steps from the tonic) == the 7 church modes.
MODE_STEPS = {
    "ionian":     [2, 2, 1, 2, 2, 2, 1],
    "dorian":     [2, 1, 2, 2, 2, 1, 2],
    "phrygian":   [1, 2, 2, 2, 1, 2, 2],
    "lydian":     [2, 2, 2, 1, 2, 2, 1],
    "mixolydian": [2, 2, 1, 2, 2, 1, 2],
    "aeolian":    [2, 1, 2, 2, 1, 2, 2],
    "locrian":    [1, 2, 2, 1, 2, 2, 2],
}

def _mode_pcs(tonic, mode):
    """Set of pitch classes in a mode's scale above a tonic."""
    out = {tonic}
    d = tonic
    for st in MODE_STEPS[mode][:-1]:
        d = (d + st) % 12
        out.add(d)
    return out

# Krumhansl-Kessler weight placed on the tonic/dominant-type degrees of each
# mode, used only to break near-ties across modes sharing a tonic.


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

def infer_modes(pc_weights, top=3):
    """Ranked modal key hypotheses (ionian..locrian) for a pc-weight histogram.

    pc_weights: dict {pitch_class: count_or_weight} of recently heard notes.

    Template-matching in the spirit of Krumhansl-Schmuckler, extended to the 7
    church modes. Each (mode, tonic) is scored by how well the heard pitch
    classes fall inside its scale (strays add nothing, not fatal), with extra
    weight on the tonic and its 5th. Returns the top-`top` candidates sorted
    by score, each as {"label": "C ionian", "score": float, "certainty": float}.
    """
    if not pc_weights or len(pc_weights) < 4:
        return []
    scored = []  # (score, tonic, mode)
    for tonic, tw in pc_weights.items():
        for mode in MODE_STEPS:
            scale = _mode_pcs(tonic, mode)
            s = 0.0
            for pc, w in pc_weights.items():
                if pc in scale:
                    s += w * (3.0 if pc == tonic else 1.0)
                    if pc == (tonic + 7) % 12:      # the (mode-appropriate) 5th
                        s += w * 0.5
            scored.append((s, tonic, mode))
    scored.sort(reverse=True)
    if not scored or scored[0][0] <= 0:
        return []
    best_s = scored[0][0]
    out = []
    for s, tonic, mode in scored[:top]:
        certainty = (s - scored[-1][0]) / best_s if best_s else 0.0
        out.append({"label": f"{NAMES[tonic]} {mode}", "score": s,
                    "certainty": round(certainty, 3)})
    return out

def infer_mode(pc_weights):
    """Best single modal key guess, or None if nothing definite yet."""
    cands = infer_modes(pc_weights, top=1)
    return cands[0]["label"] if cands else None

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


# interval quality by semitone distance (up to octave). Only the tritone is
# ambiguous (dim 5th vs aug 4th); that is resolved from the letter gap.
_SIMPLE = {
    0: "unison", 1: "min 2nd", 2: "maj 2nd", 3: "min 3rd", 4: "maj 3rd",
    5: "perf 4th", 7: "perf 5th", 8: "min 6th", 9: "maj 6th",
    10: "min 7th", 11: "maj 7th",
}
_LETTERS = ["C", "D", "E", "F", "G", "A", "B"]
_PC_TO_LETTER = {0: "C", 2: "D", 4: "E", 5: "F", 7: "G", 9: "A", 11: "B"}

def interval_of(notes):
    """Name a 2-note dyad as an interval (e.g. C-G = 'perf 5th'). Returns "" if
    not exactly two distinct notes. The tritone is dim 5th (same letter name
    line, e.g. C-Gb) or aug 4th (adjacent letters, e.g. C-F#); other gaps are
    named purely by size."""
    uniq = sorted(set(notes))
    if len(uniq) != 2:
        return ""
    lo, hi = uniq[0], uniq[1]
    st = hi - lo
    if st == 0:
        return "unison"
    if st == 12:
        return "octave"
    if st % 12 in _SIMPLE and st % 12 != 6:
        return _SIMPLE[st % 12]
    if st % 12 == 6:
        # tritone: letter gap decides dim5 (3) vs aug4 (4)
        lc_lo, lc_hi = lo % 12, hi % 12
        def letter_index(pc):
            # map the pc to its letter name, then its index within the letters
            letter = _PC_TO_LETTER.get(pc)
            return _LETTERS.index(letter) if letter is not None else None
        i_lo, i_hi = letter_index(lc_lo), letter_index(lc_hi)
        if i_lo is not None and i_hi is not None:
            gap = (i_hi - i_lo) % 7
            # 3 letter steps + tritone = aug 4th (C-F#); 4 = dim 5th (B-F)
            return "aug 4th" if gap == 3 else "dim 5th"
        return "tritone"
    return _SIMPLE.get(st % 12, "")


