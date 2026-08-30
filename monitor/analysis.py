"""Analysis: turn raw musical state into recognized musical events.

Wraps chords.py and ports the arpeggio/melody logic from the retired CLI
scripts. Produces "announcements" (dicts with a human label) so the feed
can flash chords, arpeggios, chord changes, etc.
"""
from . import chords

BURST = 0.7       # notes within this of each other form one arpeggio
SIMULTANEOUS = 0.09  # a held set this tightly clustered = one block chord
RE_COOLDOWN = 0.2  # re-announce same shape once this much time has passed
ATTACK_GAP = 0.15  # gap bigger than this = new attack -> reset onset buffer
SCALAR_SHAPE = "add9(no5)"  # 3 adjacent scale tones -> walking, not arpeggio
KEY_WINDOW = 12.0  # seconds of recent notes used for tonal-key sensing
KEY_COOLDOWN = 4.0  # don't re-announce a settled key more often than this


def chord_of(notes):
    """Chord label for a held note set; "" if not a recognized chord."""
    if len(notes) < 2:
        return ""
    label = chords.name_only(notes)
    if label == "(no template)" or not label:
        return ""
    return label


class Analyser:
    """Progressive recognizer fed by state snapshots/events.

    Tracks the previously-announced held chord so we only emit on change,
    and detects arpeggios from the recent note-onset history.
    """

    def __init__(self):
        self._last_held_key = None
        self._last_held_time = 0.0
        self._last_interval_key = None
        self._last_interval_time = 0.0
        self._last_arpeggio_key = None
        self._last_arpeggio_time = 0.0
        self._last_key = None
        self._last_key_time = 0.0
        self.recent_onsets = []  # [(time, note)]
        self.onset_of = {}       # note -> onset time (last time it was pressed)
        self.key_window = []     # [(time, pc)] longer window used for key sensing

    def on_note(self, time_now, note):
        # a clear gap since the last onset = a fresh attack: start a clean burst
        if self.recent_onsets and time_now - self.recent_onsets[-1][0] > ATTACK_GAP:
            self.recent_onsets = []
        self.recent_onsets.append((time_now, note))
        self.onset_of[note] = time_now
        while self.recent_onsets and time_now - self.recent_onsets[0][0] > 2.0:
            self.recent_onsets.pop(0)
        # maintain the (longer) rolling key-sensing window
        self.key_window.append((time_now, note % 12))
        while self.key_window and time_now - self.key_window[0][0] > KEY_WINDOW:
            self.key_window.pop(0)

    def held_chord_announce(self, held_notes, time_now):
        """Return a label if the held chord changed to something recognizable.

        A held set is announced as CHORD (3+) or INTERVAL (2) only when it was
        played as a simultaneous block. If a roll/arpeggio is in progress
        (onsets spread beyond SIMULTANEOUS), we hold off -- the arpeggio
        detector will announce it instead, and we avoid noisy intermediate
        flashes (e.g. a "maj 3rd" half-way through a C-E-G roll).
        """
        if self._roll_in_progress():
            # mid-roll: don't flash transient chord/interval confirmations
            return None
        notes = sorted(held_notes)
        if len(notes) == 2:
            # an interval -- but only announce on change from last interval
            self._last_held_key = None
            label = chords.interval_of(notes)
            if not label:
                self._last_interval_key = None
                return None
            key = tuple(notes)
            if key == self._last_interval_key and time_now - self._last_interval_time <= RE_COOLDOWN:
                return None
            self._last_interval_key = key
            self._last_interval_time = time_now
            return {"kind": "interval", "label": label, "notes": notes}
        if len(notes) < 3:
            self._last_held_key = None
            self._last_interval_key = None
            return None
        label = chord_of(notes)
        if not label:
            return None
        self._last_interval_key = None
        key = tuple(notes)
        if key == self._last_held_key and time_now - self._last_held_time <= RE_COOLDOWN:
            return None
        self._last_held_key = key
        self._last_held_time = time_now
        return {"kind": "chord", "label": label}

    def arpeggio_announce(self, time_now, suppress_notes=None):
        """Return a label if a recent burst of notes forms a real arpeggio.

        suppress_notes is typically the just-announced held chord's notes.
        The arpeggio is only suppressed when that chord was genuinely played
        as a simultaneous block (all its note onsets within SIMULTANEOUS).
        A roll -- even if notes briefly overlap and thus would have tripped a
        held-chord announce -- still shows as an arpeggio.
        """
        if len(self.recent_onsets) < 3:
            return None
        newest = self.recent_onsets[-1][0]
        burst = []
        for t, n in reversed(self.recent_onsets):
            if newest - t <= BURST:
                burst.append(n)
            else:
                break
        burst = sorted(set(burst))
        if len(burst) < 3:
            return None
        if suppress_notes is not None and self._is_block(suppress_notes):
            sup_pc = set(n % 12 for n in suppress_notes)
            bur_pc = set(n % 12 for n in burst)
            if sup_pc == bur_pc:
                return None
        label = chord_of(burst)
        if not label or SCALAR_SHAPE in label:
            return None
        key = tuple(burst)
        if key == self._last_arpeggio_key and time_now - self._last_arpeggio_time <= RE_COOLDOWN:
            return None
        self._last_arpeggio_key = key
        self._last_arpeggio_time = time_now
        return {"kind": "arpeggio", "label": label, "notes": burst}

    def key_announce(self, time_now):
        """Detect the tonal key/mode from recent notes; announce on change.

        Returns the ranked modal hypotheses (top 3) so the UI can show several
        possibilities. Re-announces only when the top hypothesis changes, or
        after a stability cooldown so a settled key isn't spammed.
        """
        if len(self.key_window) < 4:
            return None
        weights = {}
        for _t, pc in self.key_window:
            weights[pc] = weights.get(pc, 0) + 1
        if len(weights) < 4:
            return None
        cands = chords.infer_modes(weights, top=3)
        if not cands:
            return None
        primary = cands[0]["label"]
        if primary == self._last_key and time_now - self._last_key_time <= KEY_COOLDOWN:
            return None
        self._last_key = primary
        self._last_key_time = time_now
        return {"kind": "key", "label": primary, "hypotheses": cands}

    def reset_key(self):
        """Clear the rolling key-detection window and lock, starting fresh."""
        self.key_window[:] = []
        self._last_key = None
        self._last_key_time = 0.0

    def _is_block(self, notes):
        """True if the given held notes all onset nearly simultaneously."""
        onsets = [self.onset_of.get(n) for n in notes]
        onsets = [o for o in onsets if o is not None]
        if len(onsets) < 2:
            return False
        return (max(onsets) - min(onsets)) <= SIMULTANEOUS

    def _roll_in_progress(self):
        """True if notes are currently arriving one-by-one (spread > SIMULTANEOUS).

        Used to suppress transient chord/interval confirms mid-roll so an
        arpeggio (not a pile-up of intermediate flashes) is what surfaces.
        """
        if len(self.recent_onsets) < 2:
            return False
        newest = self.recent_onsets[-1][0]
        burst_times = []
        for t, n in reversed(self.recent_onsets):
            if newest - t <= BURST:
                burst_times.append(t)
            else:
                break
        if len(burst_times) < 2:
            return False
        return (max(burst_times) - min(burst_times)) > SIMULTANEOUS
