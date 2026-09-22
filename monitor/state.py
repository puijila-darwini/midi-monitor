"""Live musical state: held notes, recent events, melody and connectivity."""
import time
import statistics
import threading
import random

from .replay import VOICES as VOICES_BY_PROGRAM
from .replay import BEND_RANGE_ST
from . import chords


# Scale pitch-class intervals (semitones above the tonic), keyed by the SAME
# ids as the tonic·scale select in the template + the JS guide table
# (static/app.js SCALES) — the scale-snap transform stage reuses this single
# source so the guide shading and the snap op can never drift apart.
SCALE_SEMIS = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "aeolian": [0, 2, 3, 5, 7, 8, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor": [0, 2, 3, 5, 7, 9, 11],
    "harmonic_major": [0, 2, 4, 5, 7, 8, 11],
    "double_harmonic": [0, 1, 4, 5, 7, 8, 11],
    "phrygian_dominant": [0, 1, 4, 5, 7, 8, 10],
    "lydian_dominant": [0, 2, 4, 6, 7, 9, 10],
    "super_locrian": [0, 1, 3, 4, 6, 8, 10],
    "major_pent": [0, 2, 4, 7, 9],
    "minor_pent": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "hirajoshi": [0, 2, 3, 7, 8],
    "bebop_major": [0, 2, 4, 5, 7, 8, 9, 11],
    "bebop_dominant": [0, 2, 4, 5, 7, 9, 10, 11],
    "bebop_dorian": [0, 2, 3, 4, 5, 7, 9, 10],
    "whole_tone": [0, 2, 4, 6, 8, 10],
    "diminished": [0, 2, 3, 5, 6, 8, 9, 11],
    "chromatic": list(range(12)),
    "enigmatic": [0, 1, 4, 6, 8, 10, 11],
    "hungarian_minor": [0, 2, 3, 6, 7, 8, 11],
    "neapolitan_major": [0, 1, 3, 5, 7, 9, 11],
    "neapolitan_minor": [0, 1, 3, 5, 7, 8, 11],
}

# Microtonal tuning presets (Ver 96, mono): cents deviation per pitch class
# C..B, applied as a per-strike pitch pre-bend (echo + replay, one channel).
# equal = 12-TET (all zero); just = 5-limit just intonation; pythagorean =
# stacked pure fifths; meantone = quarter-comma (note the wolf C# at -24c —
# authentic, not a typo).
TUNING_PRESETS = {
    "equal": [0.0] * 12,
    "just": [0.0, 11.7, 3.9, 15.6, -13.7, -2.0, -9.8, 2.0, 13.7, -15.6,
             17.6, -11.7],
    "pythagorean": [0.0, 13.7, 3.9, -5.9, 7.8, -2.0, 11.7, 2.0, -7.8, 5.9,
                    -3.9, 9.8],
    "meantone": [0.0, -24.0, -6.8, 10.3, -13.7, 3.4, -20.5, -3.4, 13.7,
                 -10.3, 6.8, -17.1],
}


class State:
    """Tracks the current picture of what is being played.

    - held: dict note -> {velocity, on_time} currently held down
    - recent: rolling list of note_on/note_off events (for feed display)
    - melody: rolling list of completed (on_time, duration, note) for melody view
    - online: whether the keyboard is currently connected
    - note_onsets: list of (time, note) for tempo detection
    - tempo_bpm: estimated tempo in BPM
    """

    # Quantization grid settings. Divisions = grid steps per beat, labelled
    # explicitly in musical values (no cute tight/loose words):
    #   16 = 64ths, 8 = 32nds, 4 = 16ths (default), 2 = 8ths, 1 = quarters,
    #   0.5 = halves, 0.25 = wholes. Finer grids catch fast passages; coarser
    #   grids complete fragments into whole values ("extend to whole notes").
    # Tunable live from the UI via State.set_quantization() (0 = bypass).
    VALID_GRIDS = (0.25, 0.5, 1, 2, 4, 8, 16)

    def _grid_step(self, beat):
        """Grid step in seconds for the current resolution. Fractional
        divisions reach coarser-than-quarter grids; non-positive falls back
        to a whole beat (never zero — no division by zero)."""
        div = self.quantization_divisions
        if not isinstance(div, (int, float)) or div <= 0:
            return beat
        return beat / div
    def __init__(self, recent_keep=120, melody_keep=400, quantization_divisions=4):
        self.quantization_divisions = quantization_divisions
        self.recent_keep = recent_keep
        self.melody_keep = melody_keep
        self.held = {}
        self.recent = []
        self.melody = []
        self.online = False
        self.program = 0  # current MIDI program (0-127)
        self.bank = 0     # current bank select MSB (0 = normal, 127 = drums)
        # Receive voice (used for playback of stored/received MIDI). This is
        # separate from the panel voice (used for keys pressed on the keyboard).
        self.receive_program = 0  # current receive MIDI program (0-127)
        self.receive_bank = 0     # current receive bank select MSB
        # Time signature (numerator/denominator beats per measure). User-set via
        # set_time_signature; drives measure (bar-line) rendering on the stave
        # and the metronome's accent grouping (accent every `numer` beats).
        self.time_signature = "4/4"
        self._start = time.time()
        self.version = 0

        # MIDI output routing for replay (the "midi spaghetti zone"). seq_outs
        # are ALSA "client:port" destinations (VCV Rack, keyboard seq port,
        # Midi Through, ...); raw_outs are amidi hardware devices (hw:2,0,0).
        self.seq_outs = []
        self.raw_outs = ["hw:2,0,0"]
        self.midi_channel = 0
        
        # Tempo. tempo_bpm is the EFFECTIVE grid tempo used for quantization.
        # detected_bpm is the live on-the-fly estimate (a suggestion/guide).
        # The user tempo defaults to a FIXED 120 BPM (not auto): the grid is
        # stable from boot, and detected_bpm remains available as a suggestion.
        # Blank the tempo input (0) to revert to the live detected estimate.
        self.note_onsets = []  # list of (time, note) for tempo detection
        self.tempo_bpm = 120.0
        self.detected_bpm = 0.0   # live estimate (suggestion)
        self.user_tempo_bpm = 120.0  # >0 = fixed by user (default 120)
        self.last_tempo_update = 0
        self.tempo_update_interval = 2.0  # update tempo every 2 seconds
        
        # Quantized note data
        self.quantized_notes = []  # list of quantized note events
        self.raw_take_events = []  # semi-raw MIDI events for replay / piano roll
        self.take_notes = []  # the frozen take = exactly what the stave shows (for replay)
        # Transform chain output (RAW -> quantizer -> OUT). quantized_take is
        # the canonical quantized intermediate: same shape as quantized_notes
        # entries (note/on_time/off_time/velocity/duration/rest?). The stave
        # groups+labels it; OUT expands it to MIDI on/off pairs
        # (transformed_events, same dict shape as raw_take_events).
        # Rebuilt on demand by requantize() — never accumulates live.
        self.quantized_take = []
        self.transformed_events = []
        # Bypass switch for the quantizer stage ("no quantization" option):
        # False = exact on/off pairs straight from the raw buffer.
        self.quantize_enabled = True
        # Transposer stage (semitones, -24..+24): pitch shift applied to the
        # quantized take, so OUT and notation hear the same transposed take.
        # Out-of-range notes clamp to 0/127.
        self.transpose_semitones = 0
        # Velocity compressor stage (RAW -> quantizer -> velocity -> OUT).
        # The compressor operates on the quantized take after transposition;
        # it does not touch timing. Standard velocity is the target center
        # (default 100, the MIDI "loud" default). Width is the half-width of
        # the allowed velocity band (default 50, so 50..150 is clamped to the
        # MIDI range and all values are scaled into that band). Mode is either
        # "threshold" (clip everything outside the band to the band edges) or
        # "compress" (linearly rescale the whole buffer into the band).
        self.velocity_enabled = True
        self.velocity_standard = 100.0
        self.velocity_width = 50.0
        self.velocity_mode = "compress"  # "threshold" or "compress"
        # Velocity stats derived from the raw buffer (like tempo detection).
        self.detected_velocity = 0.0
        self.detected_velocity_min = 0.0
        self.detected_velocity_max = 0.0
        self.detected_velocity_count = 0
        # Humanizer stage (OUT -> humanized OUT): adds subtle timing and
        # velocity variations to make the output sound more human-like.
        # Timing variation: max random shift in milliseconds (±)
        # Velocity variation: max random shift in velocity units (±)
        self.humanizer_enabled = False
        self.humanizer_timing_ms = 10.0   # ±10ms default
        self.humanizer_velocity = 5       # ±5 velocity default
        # Release articulation (percent of the slot before the next onset to
        # leave SILENT — a staccato gap). 0 = legato: each note ends exactly
        # when the next attacks (and may never outlast it).
        self.articulation_gap = 0.0
        # Ver 92 transform stages: scale-snap, melodic invert, reverse. Applied
        # AFTER transpose/velocity/articulation, in that order, so OUT + the
        # notation hear the same take (requantize rebuilds on every change).
        #   snap  - force every pitch onto the tonic·scale card selection
        #           (bias = nearest scale tone / next up / next down).
        #   invert- mirror each pitch around invert_pivot (melodic inversion:
        #           rising phrases fall, contour flips about the pivot note).
        #   reverse - play the take backwards: reversed order + each note's
        #           on/off mirrored around the take's span (durations kept).
        self.snap_enabled = False
        self.snap_bias = "nearest"        # "nearest" | "up" | "down"
        self.invert_enabled = False
        self.invert_pivot = 48            # MIDI note to reflect around (C3 =
                                          # octave 3 default; the UI selects
                                          # note + octave, key-tonic follows
                                          # until the user picks a pivot)
        self.invert_pivot_auto = False    # auto: pivot = the pattern's FIRST
                                          # note (earliest attack), so the
                                          # inverted phrase keeps its register
        self.invert_pivot_live = None     # resolved auto pivot (take -> echo)
        self.invert_mode = "chromatic"     # "chromatic" | "diatonic" (Ver 95:
                                           # diatonic reflects ON the scale
                                           # ladder so every result stays in
                                           # the key; needs tonic·scale set)
        self.reverse_enabled = False
        # Echo-stream application (Ver 92): which of the above ALSO run LIVE on
        # the echoed keybed notes (app.py note_on/note_off path). Only the
        # per-note ops qualify — quantize/velocity/humanize are buffer ops and
        # cannot (articulation/reverse have live ordering semantics too, so
        # they are excluded). transpose is opted in separately.
        self.echo_transpose = False
        self.echo_snap = False
        self.echo_invert = False
        self.echo_velocity = False     # Ver 95: velocity compressor ALSO runs
                                       # live on echoed note_ons; the band uses
                                       # the compressor's std/width, compress
                                       # mode rescales a rolling seen-window
        self.echo_tuning = False       # Ver 96: tuning pre-bend ALSO runs live
                                       # on echoed note_ons (opt-in like the
                                       # other transform ops)
        self._echo_vel_hist = []       # rolling velocities for live compress
        # Microtonal tuning (Ver 96, mono): cents deviation per pitch class,
        # applied as a pitch pre-bend at strike time (echo note_ons + replay
        # batches, one shared channel). Integer notes everywhere else stay
        # 12-TET, so this needs no requantize — it is a performance layer.
        self.tuning_enabled = False
        self.tuning_cents = [0.0] * 12
        self.tuning_preset = "equal"
        self._tuning_last_bend = {}    # channel -> last sent bend (semis)
        # Press-time echo mapping (Ver 94 de-jank): note_on freezes the mapped
        # pitch SENT to the board so note_off releases exactly that pitch even
        # when the transforms change mid-hold. echo_holders refcounts per
        # MAPPED note (snap/invert collapse different raw keys onto one tone),
        # so a release only rings off when the last holder lets go.
        self.echo_held = {}       # raw note -> {"mapped": int, "channel": int}
        self.echo_holders = {}    # mapped note -> count of raw keys on it
        # Key context from the tonic·scale card (server copy so the scale
        # stage + echo snap share it). tonic -1 = guide off; scale "" = none.
        self.key_tonic = -1
        self.key_scale = ""
        # Received-control watch (signals arriving FROM the keyboard: wheel ->
        # pitch bend + CC1, panel voice buttons -> bank/PC, aux 120/121/123).
        # {controller: last value 0-127}; pitch bend in semitones (± range).
        self.received_ctrl = {}
        self.received_pitch_bend = 0.0
        # Out control surface: last values we SENT to the keyboard, for UI
        # boot-sync. {controller: value 0-127}, pitch bend in semitones, and
        # the CC122 local-control state (None until first set).
        self.control_values = {}
        self.control_pitch_bend = 0.0
        self.local_control = None
        # Live-echo mode: when on, incoming keybed notes are routed back to
        # the keyboard as RX notes, so the controls that only bind to received
        # notes (program/voice, sustain, CC, pitch) apply to live playing.
        # Local control is independent (keys/layer/echo/midi in the UI): local
        # on layers the echo against the panel voice, local off is echo alone.
        self.echo_enabled = False
        # Voice the echo path plays ("auto" = leave the keyboard as-is).
        self.echo_voice = "auto"
        # Near-simultaneous window (seconds) for grouping chord members when
        # bypassing (no grid to snap them together). Grouping ALSO requires
        # overlap (next onset lands while the group still sounds) so fast
        # legato runs stay single notes and only true block chords/dyads
        # group — otherwise a fast passage collapses into intervals and the
        # stave (with intervals hidden) goes silently blank.
        self.bypass_group_window = 0.05
        self.max_quantized_notes = 500
        self.max_raw_take_events = 2000
        # Pending-onset based note value derivation (TIME-TO-NEXT-ONSET).
        #
        # Why: the "gap since the previous onset" model marks a metronome-guided
        # quarter note as an 8th/dotted-8th whenever the PLAYER'S OWN jitter makes
        # the gap to the previous onset short (observed: 0.45s = 3 grid steps from
        # a note that was clearly meant as a quarter). Note value should be "until
        # the NEXT onset": if you strike a quarter, the next strike comes a beat
        # later, so the note renders as a quarter regardless of when the previous
        # note happened to land. This makes human playing with normal timing jitter
        # notate as the intended values instead of punishing a slightly-short gap.
        # Cost (accepted): each note is finalized and emitted one onset late, and a
        # note with no following onset is flushed by a background timer instead.
        #
        # self._pending is the "currently open" note's group: {qon, notes:[(note,v)]}.
        # A chord member (same grid tick) joins the group; a new tick finalizes the
        # previous group with duration = gap (in grid steps) to this onset.
        self._pending = None
        self._emit_queue = []  # finalized quantized notes (or rests) waiting for app.py to emit
        self._emit_lock = threading.RLock()  # guard _emit_queue/_pending across threads
        self._flush_daemon = None
        self._flush_stop = threading.Event()

        # Recording take: when True the frontend accumulates a fresh take on the
        # stave/roll. Default False = idle noodling and background board chatter
        # never accumulate into a take; REC arms a fresh take (clearing the
        # quantized buffer), STOP freezes it. Stopping flushes the trailing
        # pending note immediately so the last played note is captured.
        self.recording = False

    def set_humanizer(self, enabled=None, timing_ms=None, velocity=None):
        """Set the humanizer stage (called by /api/humanizer)."""
        if enabled is not None:
            self.humanizer_enabled = bool(enabled)
        if timing_ms is not None:
            try:
                self.humanizer_timing_ms = float(timing_ms)
            except (TypeError, ValueError):
                pass
        if velocity is not None:
            try:
                self.humanizer_velocity = int(velocity)
            except (TypeError, ValueError):
                pass
        self.humanizer_timing_ms = max(0.0, self.humanizer_timing_ms)
        self.humanizer_velocity = max(0, self.humanizer_velocity)
        self.requantize()

    def set_articulation(self, gap=None):
        """Set the release-articulation stage: the fraction of each note's slot
        (time to the next attack) left SILENT. 0 = legato/clamped. Max 0.9 so a
        note never shrinks to nothing."""
        if gap is not None:
            try:
                gap = float(gap)
            except (TypeError, ValueError):
                return
            self.articulation_gap = max(0.0, min(0.9, gap))
        self.requantize()

    def set_scale_context(self, tonic=None, scale=None):
        """Set the key context (tonic·scale card). tonic = pitch class 0-11,
        -1 = off; scale = scale id ("" = off). Rebuilds if snap is live."""
        if tonic is not None:
            try:
                tonic = int(tonic)
            except (TypeError, ValueError):
                return
            self.key_tonic = max(-1, min(11, tonic))
        if scale is not None:
            self.key_scale = str(scale) if scale in SCALE_SEMIS else ""
        self.requantize()

    def set_snap(self, enabled=None, bias=None):
        """Set the scale-snap stage. bias: "nearest" (default) | "up" | "down"."""
        if enabled is not None:
            self.snap_enabled = bool(enabled)
        if bias in ("nearest", "up", "down"):
            self.snap_bias = bias
        self.requantize()

    def set_invert(self, enabled=None, pivot=None, auto=None, mode=None):
        """Set the melodic-inversion stage. pivot = MIDI note to reflect
        around (when auto is off); auto = pivot follows the pattern's FIRST
        note so the inverted phrase keeps its register; mode = "chromatic"
        (exact semitones, n' = 2*pivot - n) or "diatonic" (reflects on the
        scale ladder so every result stays IN the key — needs the key set)."""
        if enabled is not None:
            self.invert_enabled = bool(enabled)
        if auto is not None:
            self.invert_pivot_auto = bool(auto)
            if not self.invert_pivot_auto:
                self.invert_pivot_live = None
        if pivot is not None:
            try:
                pivot = int(pivot)
            except (TypeError, ValueError):
                return
            self.invert_pivot = max(0, min(127, pivot))
        if mode in ("chromatic", "diatonic"):
            self.invert_mode = mode
        self.requantize()

    def set_reverse(self, enabled=None):
        """Set the reverse stage (take plays backwards)."""
        if enabled is not None:
            self.reverse_enabled = bool(enabled)
        self.requantize()

    def set_echo_transform(self, which=None, enabled=None):
        """Opt a transform into the LIVE echo stream. which: "transpose" |
        "snap" | "invert" | "velocity" | "tuning". Only per-note ops qualify
        (buffer ops cannot)."""
        if which not in ("transpose", "snap", "invert", "velocity", "tuning") or enabled is None:
            return
        attr = {"transpose": "echo_transpose",
                "snap": "echo_snap",
                "invert": "echo_invert",
                "velocity": "echo_velocity",
                "tuning": "echo_tuning"}[which]
        if attr == "echo_velocity" and enabled:
            self._echo_vel_hist = []   # fresh window for the newly-live comp
        setattr(self, attr, bool(enabled))

    # -- press-time echo map (Ver 94): keyed notes map ONCE at press; note_off
    # releases the SAME pitch even if the transforms changed mid-hold.
    def echo_hold(self, raw, channel=0):
        """Remember a press: map the raw keyed note through the live
        transforms and return the pitch to send. Also records the send channel
        so the release can match it."""
        try:
            r = int(raw)
        except (TypeError, ValueError):
            r = raw
        mapped = self.echo_transform(r)
        self.echo_held[r] = {"mapped": mapped, "channel": int(channel)}
        self.echo_holders[mapped] = self.echo_holders.get(mapped, 0) + 1
        return mapped

    def echo_release(self, raw):
        """Release a press. Returns None while OTHER raw keys still hold the
        same mapped pitch (refcounted) — None also when the press was never
        echoed at all — else {"mapped", "channel"} to send the note_off."""
        try:
            r = int(raw)
        except (TypeError, ValueError):
            r = raw
        held = self.echo_held.pop(r, None)
        if not held:
            return None
        mapped = held["mapped"]
        n = self.echo_holders.get(mapped, 0) - 1
        if n > 0:
            self.echo_holders[mapped] = n
            return None
        self.echo_holders.pop(mapped, None)
        return held

    def echo_release_all(self):
        """Every held press (for ringing off when echo is disabled), clearing
        the press-time map."""
        out = list(self.echo_held.values())
        self.echo_held.clear()
        self.echo_holders.clear()
        return out

    def _snap_pitch(self, note):
        """Snap a single pitch onto the tonic·scale selection's scale, per
        snap_bias (nearest/up/down). Returns the note when no scale is set."""
        semis = SCALE_SEMIS.get(self.key_scale)
        if semis is None or self.key_tonic < 0:
            return note
        # Absolute pitch classes of the scale under this tonic = (s + tonic),
        # exactly what the JS guide shades. (Was (s - tonic), which snapped
        # non-zero tonics onto a DIFFERENT scale than the one displayed.)
        pcs = sorted((s + self.key_tonic) % 12 for s in semis)
        base = note - (note % 12)
        # Candidates around the note: same octave region +/- one octave.
        cands = [base + pc - 12 for pc in pcs] + [base + pc for pc in pcs] \
                + [base + pc + 12 for pc in pcs]
        if self.snap_bias == "up":
            best = min(c for c in cands if c >= note) if any(c >= note for c in cands) \
                else base + pcs[0] + 12
        elif self.snap_bias == "down":
            best = max(c for c in cands if c <= note) if any(c <= note for c in cands) \
                else base + pcs[-1] - 12
        else:  # nearest (ties resolve to the lower scale tone)
            best = min(cands, key=lambda c: (abs(c - note), c))
        return max(0, min(127, best))

    def _apply_scale_snap(self, notes):
        """Scale-snap stage: force every quantized pitch onto the scale set in
        the tonic·scale card (uses SCALE_SEMIS + key_tonic/key_scale)."""
        if not self.snap_enabled:
            return
        for qn in notes:
            if qn.get("rest") or qn.get("note") is None:
                continue
            try:
                qn["note"] = self._snap_pitch(int(qn["note"]))
            except (TypeError, ValueError):
                continue

    def _first_note_pitch(self, notes):
        """Pitch of the take's earliest attack — the auto-invert pivot.
        None for an empty / all-rest take."""
        best = None
        for qn in notes:
            if qn.get("rest") or qn.get("note") is None:
                continue
            try:
                t = float(qn.get("on_time", 0.0))
            except (TypeError, ValueError):
                continue
            if best is None or t < best[0]:
                try:
                    best = (t, int(qn["note"]))
                except (TypeError, ValueError):
                    continue
        return best[1] if best else None

    # -- Ver 95: inversion modes -------------------------------------------------
    def _scale_pcs(self):
        """Absolute pitch classes of the tonic·scale selection, or None when
        no key context is declared (mirrors the JS guide shading exactly)."""
        semis = SCALE_SEMIS.get(self.key_scale)
        if semis is None or self.key_tonic < 0:
            return None
        return sorted((s + self.key_tonic) % 12 for s in semis)

    def _nearest_ladder_index(self, ladder, pitch):
        """Index of the ladder tone nearest to `pitch` (ties to the lower)."""
        best = 0
        for i in range(1, len(ladder)):
            if abs(ladder[i] - pitch) < abs(ladder[best] - pitch):
                best = i
        return best

    def _diatonic_invert(self, note, pivot):
        """Mirror `note` around `pivot` ON THE DIATONIC LADDER: both pitches
        map to their scale position (nearest scale tone) and the degree index
        reflects, 2*pivotIdx - noteIdx, so the result always lands IN the
        key — a C-major E inverted around C gives B, not Gb. Returns None
        when no key context is declared."""
        pcs = self._scale_pcs()
        if pcs is None:
            return None
        ladder = sorted(x for x in range(0, 128) if x % 12 in pcs)
        src_idx = self._nearest_ladder_index(ladder, note)
        piv_idx = self._nearest_ladder_index(ladder, pivot)
        tgt_idx = 2 * piv_idx - src_idx
        tgt_idx = max(0, min(len(ladder) - 1, tgt_idx))
        return ladder[tgt_idx]

    def _invert_pitch(self, note, pivot):
        """Mirror a single pitch around `pivot` per invert_mode: chromatic
        (exact semitones, n' = 2*pivot - n) or diatonic (stays on the scale
        ladder when the tonic·scale context is declared, chromatic fallback)."""
        if self.invert_mode == "diatonic":
            d = self._diatonic_invert(note, pivot)
            if d is not None:
                return d
        return max(0, min(127, 2 * pivot - note))

    def _apply_invert(self, notes):
        """Melodic-inversion stage: mirror every pitch around the pivot. Auto
        mode pivots on the pattern's FIRST note (the inverted phrase keeps its
        register); the resolved pitch is cached for the live echo path."""
        if not self.invert_enabled:
            return
        if self.invert_pivot_auto:
            first = self._first_note_pitch(notes)
            if first is not None:
                self.invert_pivot_live = first
                pivot = first
            else:
                pivot = self.invert_pivot
        else:
            pivot = self.invert_pivot
        for qn in notes:
            if qn.get("rest") or qn.get("note") is None:
                continue
            try:
                n = int(qn["note"])
            except (TypeError, ValueError):
                continue
            qn["note"] = self._invert_pitch(n, pivot)

    def _apply_reverse(self, notes):
        """Reverse stage: play the take backwards. Order is reversed and every
        note's on/off pair is mirrored around the take's span, so durations are
        kept (the same phrase shape, played tail-first). Mirrored rests are
        notation-only; remirroring them keeps the stave's silhouette coherent.
        Returns the new list (does not mutate in place)."""
        if not self.reverse_enabled or not notes:
            return notes
        span = 0.0
        for qn in notes:
            end = qn.get("off_time", qn.get("on_time", 0.0))
            try:
                span = max(span, float(end))
            except (TypeError, ValueError):
                continue
        new = []
        for qn in reversed(notes):
            m = dict(qn)
            try:
                on = float(m["on_time"])
                off = float(m["off_time"])
            except (TypeError, ValueError, KeyError):
                new.append(m)
                continue
            m["on_time"] = max(0.0, span - off)
            m["off_time"] = max(0.0, span - on)
            new.append(m)
        return new

    def echo_transform(self, note):
        """Map a keyed note through the transforms that RUN LIVE on the echo
        stream (transpose/snap/invert — quantize, velocity, humanize and
        reverse are buffer ops). Deterministic per note, so note_off mirrors
        exactly. Applied in the same order as the take chain."""
        try:
            n = int(note)
        except (TypeError, ValueError):
            return note
        if self.echo_transpose and self.transpose_semitones:
            n = max(0, min(127, n + self.transpose_semitones))
        if self.echo_invert and self.invert_enabled:
            pivot = self.invert_pivot_live \
                if (self.invert_pivot_auto and self.invert_pivot_live is not None) \
                else self.invert_pivot
            n = self._invert_pitch(n, pivot)
        if self.echo_snap and self.snap_enabled:
            n = self._snap_pitch(n)
        return n

    def map_echo_velocity(self, velocity):
        """Velocity-compressor stage for the LIVE echo stream (Ver 95): a raw
        keyed note_on's velocity is remapped the way the take pipeline does.
        threshold clips to the standard±width/2 band; compress rescales the
        rolling window of recent note velocities into that band (early notes
        clip until the window warms). Deterministic per note_on; note_off
        carries no velocity."""
        if not self.echo_velocity or not self.velocity_enabled or self.velocity_width <= 0:
            return velocity
        try:
            v = int(velocity)
        except (TypeError, ValueError):
            return velocity
        std = self.velocity_standard
        width = self.velocity_width
        lo = max(1, int(std - width / 2.0))
        hi = min(127, int(std + width / 2.0))
        if lo >= hi:
            return velocity
        if self.velocity_mode == "threshold":
            return max(lo, min(hi, v))
        # compress: rescale the recent seen window into the band
        self._echo_vel_hist.append(v)
        if len(self._echo_vel_hist) > 48:
            del self._echo_vel_hist[0]
        if len(self._echo_vel_hist) < 3:
            return max(lo, min(hi, v))
        mn = min(self._echo_vel_hist)
        mx = max(self._echo_vel_hist)
        if mn >= mx:
            return max(lo, min(hi, v))
        scale = (hi - lo) / (mx - mn)
        nv = lo + (v - mn) * scale
        return max(1, min(127, int(round(nv))))

    # -- Ver 96: microtonal tuning (mono) --------------------------------------
    def set_tuning(self, enabled=None, cents=None, preset=None):
        """Set the microtonal tuning table: cents deviation per pitch class
        C..B, applied as a pitch pre-bend at strike time (echo note_ons +
        replay batches). A preset name loads its table; explicit cents (12
        numbers, clamped ±100) mark the table "custom". No requantize — the
        take's integer notes are untouched."""
        if enabled is not None:
            self.tuning_enabled = bool(enabled)
            if not self.tuning_enabled:
                self._tuning_last_bend = {}
        if preset in TUNING_PRESETS:
            self.tuning_preset = preset
            self.tuning_cents = list(TUNING_PRESETS[preset])
        if cents is not None:
            try:
                vals = [max(-100.0, min(100.0, float(c))) for c in cents]
            except (TypeError, ValueError):
                return
            if len(vals) == 12:
                self.tuning_cents = vals
                self.tuning_preset = "custom"

    def tuning_cents_for(self, note):
        """Cents deviation for a MIDI note's pitch class (0.0 when off)."""
        if not self.tuning_enabled:
            return 0.0
        try:
            return float(self.tuning_cents[int(note) % 12])
        except (TypeError, ValueError, IndexError):
            return 0.0

    def tuning_strike_bend(self, note, channel=0):
        """Bend (semitones) to send BEFORE striking `note`, or None when the
        channel already carries it. Skips the redundant amidi round-trip when
        the same detune repeats (fast repeated notes, unbent pcs)."""
        if not self.tuning_enabled:
            return None
        try:
            ch = int(channel) & 0x0F
        except (TypeError, ValueError):
            ch = 0
        semis = self.tuning_cents_for(note) / 100.0
        if abs(semis - self._tuning_last_bend.get(ch, 0.0)) <= 0.005:
            return None
        self._tuning_last_bend[ch] = semis
        return semis

    def _apply_articulation(self, notes):
        """Quantized-take post-pass: no monophonic line may ring into the next
        attack, and an optional "release gap" trims each note's slot for
        staccato articulation.

        Notes struck within ROLL_WINDOW of the group start and still sounding
        are treated as CHORD MEMBERS: they keep their true durations and are
        only ever trimmed/lowered against the NEXT group's attack, never
        against each other — so a real chord with natural roll keeps every
        member (no 1ms blips), while a genuine successive note still cuts the
        previous one.

        Only fires in the GRIDDED (quantize-enabled) path: in the bypass path
        the take already holds the player's real durations, chords legitimately
        overlap, and a clamp would destroy polyphony (Ver 66 regression). The
        release gap is a grid/articulation concept and simply does not apply
        off-grid.
        """
        if not notes:
            return
        if not self.quantize_enabled:
            return
        frac = min(0.9, max(0.0, self.articulation_gap))
        ROLL_WINDOW = 0.10  # seconds: natural chord roll tolerance
        ordered = sorted(notes, key=lambda q: q.get("on_time", 0.0))
        group = []
        group_start = None
        group_max_off = None

        def finalize(attack_on):
            """End the current group: cap its members against the next real
            attack (optionally leaving a staccato gap before it)."""
            if not group:
                return
            cap = attack_on
            if frac > 0 and group_start is not None:
                cap = group_start + (attack_on - group_start) * (1.0 - frac)
            for m in group:
                try:
                    mo = float(m["off_time"])
                except (TypeError, ValueError):
                    continue
                if mo > cap:
                    m["off_time"] = cap
                    try:
                        m["duration"] = max(0.0, cap - float(m["on_time"]))
                    except (TypeError, ValueError):
                        pass

        for qn in ordered:
            if qn.get("rest"):
                # Silence: the group may release into it (staccato tail).
                finalize(qn.get("on_time", float("inf")))
                group = []
                group_start = None
                group_max_off = None
                continue
            try:
                on = float(qn["on_time"])
                off = float(qn["off_time"])
            except (TypeError, ValueError):
                continue
            if group and group_start is not None and group_max_off is not None:
                if on - group_start < ROLL_WINDOW and on < group_max_off:
                    # Chord member: struck with the group, still sounding.
                    group.append(qn)
                    group_max_off = max(group_max_off, off)
                    continue
            finalize(on)
            group = [qn]
            group_start = on
            group_max_off = off
        finalize(float("inf"))

    def _apply_humanizer(self, events):
        """Apply the humanizer to the transformed MIDI events (OUT side)."""
        if not self.humanizer_enabled:
            return events
        if not events:
            return events
        rng = random.Random()
        seed = 0
        for ev in events:
            seed ^= int(float(ev.get("time", 0)) * 1000000) & 0xFFFFFFFF
        rng.seed(seed)
        out = []
        for ev in events:
            if ev.get("type") not in ("note_on", "note_off"):
                out.append(ev)
                continue
            t = float(ev.get("time", 0))
            v = int(ev.get("velocity", 0))
            if self.humanizer_timing_ms > 0:
                t += rng.uniform(-self.humanizer_timing_ms,
                                 self.humanizer_timing_ms) / 1000.0
            if ev.get("type") == "note_on" and self.humanizer_velocity > 0:
                v = max(1, min(127, v + rng.randint(-self.humanizer_velocity,
                                                     self.humanizer_velocity)))
            out.append({**ev, "time": t, "velocity": v})
        out.sort(key=lambda e: (e["time"], 0 if e["type"] == "note_off" else 1)
                 if e["type"] == "note_off"
                 else (e["time"], 1))
        return out

    def set_velocity_compressor(self, standard=None, width=None, mode=None, enabled=None):
        """Set the velocity compressor stage (called by /api/velocity-compressor)."""
        if enabled is not None:
            self.velocity_enabled = bool(enabled)
        if standard is not None:
            try:
                self.velocity_standard = float(standard)
            except (TypeError, ValueError):
                pass
        if width is not None:
            try:
                self.velocity_width = float(width)
            except (TypeError, ValueError):
                pass
        if mode is not None:
            if mode not in ("threshold", "compress"):
                raise ValueError("mode must be 'threshold' or 'compress'")
            self.velocity_mode = mode
        self.velocity_standard = max(1.0, min(127.0, self.velocity_standard))
        self.velocity_width = max(1.0, min(127.0, self.velocity_width))
        self._echo_vel_hist = []   # Ver 95: band changed — restart the live window
        self.requantize()

    def compute_velocity_stats(self):
        """Compute the standard velocity and range from the raw buffer.

        The standard velocity is the median of note-on velocities (robust to
        outliers and drift). The min/max are the raw observed range so the
        UI can show what the compressor is working with.
        """
        velocities = []
        for ev in self.raw_take_events:
            if ev.get("type") != "note_on":
                continue
            try:
                v = float(ev.get("velocity", 100))
            except (TypeError, ValueError):
                continue
            if 1 <= v <= 127:
                velocities.append(v)
        self.detected_velocity = statistics.median(velocities) if velocities else 0.0
        self.detected_velocity_min = min(velocities) if velocities else 0.0
        self.detected_velocity_max = max(velocities) if velocities else 0.0
        self.detected_velocity_count = len(velocities)
        return {
            "velocity_standard": self.detected_velocity,
            "velocity_min": self.detected_velocity_min,
            "velocity_max": self.detected_velocity_max,
            "velocity_count": self.detected_velocity_count,
        }

    def _apply_velocity_compressor(self, notes):
        """Apply the velocity compressor to a list of quantized notes."""
        if not self.velocity_enabled or self.velocity_width <= 0:
            return notes
        self.compute_velocity_stats()
        std = self.velocity_standard
        width = self.velocity_width
        lo = max(1, int(std - width / 2.0))
        hi = min(127, int(std + width / 2.0))
        if lo >= hi:
            return notes
        if self.velocity_mode == "threshold":
            for qn in notes:
                if qn.get("rest"):
                    continue
                try:
                    v = int(qn.get("velocity", 100))
                    if v < lo:
                        v = lo
                    elif v > hi:
                        v = hi
                    qn["velocity"] = max(1, min(127, v))
                except (TypeError, ValueError):
                    continue
            return notes
        # compress mode: linearly rescale the whole buffer into the band.
        min_v = self.detected_velocity_min
        max_v = self.detected_velocity_max
        if min_v >= max_v:
            return notes
        scale = (hi - lo) / (max_v - min_v)
        for qn in notes:
            if qn.get("rest"):
                continue
            try:
                v = float(qn.get("velocity", 100))
                if min_v <= max_v:
                    v = lo + (v - min_v) * scale
                v = max(1, min(127, int(round(v))))
                qn["velocity"] = v
            except (TypeError, ValueError):
                continue
        return notes

    def _start_flush_daemon(self):
        """Daemon that flushes the trailing pending note so the last note of a
        phrase is not stuck un-rendered forever (no next onset to finalize it).

        It finalizes a pending group once no new onset has arrived within a
        grace period that scales with the tempo (so slow tempos are not flushed
        prematurely). The flushed value falls back to a robust local estimate of
        the beat gap (recent quantized durations) so the trailing note still gets
        its musically-expected value, then the note_off held-duration only if
        nothing is known yet.
        """
        def _run():
            while not self._flush_stop.wait(0.4):
                try:
                    self._flush_stale_pending()
                except Exception:
                    pass
        if self._flush_daemon is None or not self._flush_daemon.is_alive():
            self._flush_stop.clear()
            self._flush_daemon = threading.Thread(
                target=_run, name="quant-flush", daemon=True)
            self._flush_daemon.start()

    def _flush_stale_pending(self):
        with self._emit_lock:
            p = self._pending
            if p is None:
                return
            if self.tempo_bpm <= 0:
                return
            beat = 60.0 / self.tempo_bpm
            grace = 2.0 * beat + 0.5
            # wall_t is stored in the SAME time base as time.time() (epoch), so
            # this age check is correct. p["qon"] is in capture-relative time.
            if time.time() - p["wall_t"] < grace:
                return
            fallback = self._robust_gap_duration()
            self._finalize_pending(fallback)

    def _robust_gap_duration(self):
        """A musically-plausible duration for flushing the trailing pending note:
        the median of recent quantized durations (the player's local beat), or the
        snapped held duration if nothing is known yet."""
        if self.tempo_bpm <= 0:
            # No grid to snap to yet (tempo not estimated / no user tempo set).
            return None
        if self.quantized_notes:
            recent = [n["duration"] for n in self.quantized_notes[-8:]
                      if not n.get("rest")]
            if recent:
                med = statistics.median(recent)
                beat = 60.0 / self.tempo_bpm
                grid = self._grid_step(beat)
                if grid > 0:
                    steps = max(1, int(round(med / grid)))
                    return steps * grid
        # No history yet (leading note of the phrase): fall back to one beat
        # at the current tempo.
        return 60.0 / self.tempo_bpm

    def _finalize_pending(self, duration):
        """Append quantized notes for the pending group with the given duration,
        push them to the emit queue, and clear the pending group.

        duration == None -> fall back to the snapped held duration of the group's
        first note (purely for the degenerate no-tempo case).

        Rests: when a gap to the next onset is LONGER than the group's own held
        time implies, the excess is emitted as a quantized REST so recording
        shows empty beats instead of stretching the note value. Held time is only
        used to decide how much of the gap is the note vs the silence.
        """
        p = self._pending
        if p is None:
            return []
        self._pending = None
        if duration is None:
            return []
        new = []

        held = self._group_held(p)
        note_dur, rest_dur = self._split_note_rest(duration, held)
        for note, vel, rel in p["notes"]:
            off = p["qon"] + note_dur
            qn = {
                "note": note,
                "on_time": p["qon"],
                "off_time": off,
                "velocity": vel,
                "duration": off - p["qon"],
            }
            self.quantized_notes.append(qn)
            if self.recording:
                self.take_notes.append(qn)
            new.append(qn)
        if rest_dur is not None and rest_dur > 0:
            rstart = p["qon"] + note_dur
            rn = {
                "note": None,
                "on_time": rstart,
                "off_time": rstart + rest_dur,
                "velocity": 0,
                "duration": rest_dur,
                "rest": True,
            }
            self.quantized_notes.append(rn)
            if self.recording:
                self.take_notes.append(rn)
            new.append(rn)
        if len(self.quantized_notes) > self.max_quantized_notes:
            self.quantized_notes = self.quantized_notes[-self.max_quantized_notes:]
        with self._emit_lock:
            self._emit_queue.extend(new)
        return new

    def _group_held(self, p):
        """Longest held duration among the pending group's members (seconds),
        or None if no release has arrived yet."""
        held = None
        for note, vel, rel in p["notes"]:
            if rel is not None:
                h = rel - p["qon"]
                if held is None or h > held:
                    held = h
        return held

    def _split_note_rest(self, gap, held):
        """Decide how a gap-to-next-onset splits into a note value and a rest.

        The gap is the time-to-next-onset (what the note would stretch to). A rest
        is introduced only for a true PAUSE — a gap well beyond the player's
        prevailing beat (>2x). Everything inside 2x is normal phrasing (dotted
        values, half notes between quarters, simple timing jitter) and keeps its
        full value as a single note.

        Signals:
          - sustained: key held through (almost) the whole gap -> the whole gap is
            one note (a genuinely long/held note), no rest.
          - even/phrased rhythm: gap <= 2x the player's prevailing beat -> note
            value = full gap (Ver 34 time-to-next), no rest, whatever the held
            time. On a keyboard nearly all strikes are released early
            (staccato-ish), so held time canNOT be the discriminator — capping at
            1.5x the beat used to demote dotted/half phrasing into tiny rests.
          - pause: gap > 2x the prevailing beat AND the key was released early ->
            the note keeps its prevailing value and the SILENCE becomes a rest.

        Returns (note_dur, rest_dur) in seconds. rest_dur is None when there is
        no silence to show (unknown held time, sustained, or normal phrasing).
        """
        # No held info yet (chord member still down) -> note covers the whole gap.
        if held is None or held <= 0:
            return gap, None
        # They held the note for most of the gap -> sustained, no rest.
        if held >= gap * 0.9:
            return gap, None
        prev = self._robust_gap_duration()
        if prev is None or prev <= 0:
            # No history yet (leading note of the phrase): fall back to one beat
            # at the current tempo.
            if self.tempo_bpm > 0:
                prev = 60.0 / self.tempo_bpm
            else:
                return gap, None
        if gap <= prev * 2.0:
            # Normal phrasing (up to ~2 beats: dotted, halves, jitter) -> the
            # whole gap is the note's value, no rest.
            return gap, None
        # True pause: the note keeps its prevailing value (snapped held time as a
        # floor — if they actually held longer than one prevailing beat, honour
        # the longer value), and the surplus is silence.
        held_snapped = held
        if self.tempo_bpm > 0:
            beat = 60.0 / self.tempo_bpm
            grid = self._grid_step(beat)
            if grid > 0:
                held_snapped = max(1, int(round(held / grid))) * grid
        note_dur = min(gap, max(prev, held_snapped))
        rest_dur = gap - note_dur
        # Avoid emitting a meaningless sliver of a rest (grid-sized or smaller).
        if rest_dur <= 0:
            return note_dur, None
        # Floor the rest at one grid step at the current grid (else sub-unit rests
        # would render as 32nd slivers on the stave).
        if self.tempo_bpm > 0:
            beat = 60.0 / self.tempo_bpm
            grid = self._grid_step(beat)
            if grid > 0 and rest_dur < grid:
                return gap, None
        return note_dur, rest_dur

    def take_quantized_events(self):
        """Drain and return the finalized quantized notes not yet emitted via SSE."""
        with self._emit_lock:
            out, self._emit_queue = self._emit_queue, []
        return out

    def requantize(self):
        """Rebuild the transform-chain output from the raw take buffer.

        THE quantizer stage (RAW -> quantizer -> OUT): replays raw_take_events
        under the CURRENT settings into the canonical quantized_take, then
        expands it to transformed_events (MIDI on/off pairs for OUT; rests
        are notation-only and dropped). Always recomputed on demand, so every
        consumer (notation, replay, counts) hears the same take. Returns the
        quantized_take list.
        """
        raw = list(self.raw_take_events)
        self.quantized_take = []
        self.transformed_events = []
        if not raw:
            return self.quantized_take
        if self.quantize_enabled:
            qns = self._requantize_gridded(raw)
        else:
            qns = self._requantize_exact(raw)
        # Transposer stage: shift every quantized pitch (both paths), so the
        # notation labels and OUT hear the same transposed take.
        st = self.transpose_semitones
        if st:
            for qn in qns:
                if not qn.get("rest") and qn.get("note") is not None:
                    try:
                        qn["note"] = max(0, min(127, int(qn["note"]) + st))
                    except (TypeError, ValueError):
                        continue
        # Apply velocity compressor (if enabled)
        if self.velocity_enabled:
            self._apply_velocity_compressor(qns)
        # Release articulation: clamp releases to their successor's attack and
        # apply the optional staccato gap (never any ring-over).
        self._apply_articulation(qns)
        # Ver 92 stages (after articulation, before expansion): melodic
        # inversion, then scale-snap (snap pulls the inverted line onto the
        # scale), then reverse (mirrored timeline — pitch ops precede it since
        # they are time-blind).
        if self.invert_enabled:
            self._apply_invert(qns)
        if self.snap_enabled:
            self._apply_scale_snap(qns)
        if self.reverse_enabled:
            qns = self._apply_reverse(qns)
        self.quantized_take = qns
        self.transformed_events = self._expand_midi(self.quantized_take)
        # Apply humanizer (if enabled) to the final output events
        if self.humanizer_enabled:
            self.transformed_events = self._apply_humanizer(self.transformed_events)
        return self.quantized_take

    def _requantize_gridded(self, raw):
        """Scratch-State rebuild: same grid anchor, same pending-group code
        path as live capture, tempo/divisions fixed at current values."""
        scratch = State(quantization_divisions=self.quantization_divisions)
        scratch._start = self._start
        scratch.tempo_bpm = self.tempo_bpm
        # Lock the scratch tempo (mirrors set_user_tempo): the rebuild must
        # not re-estimate, it renders under the current effective tempo.
        scratch.user_tempo_bpm = self.tempo_bpm if self.tempo_bpm > 0 else 0.0
        scratch.recording = False
        for ev in raw:
            if ev.get("type") not in ("note_on", "note_off"):
                continue
            try:
                scratch.handle({
                    "type": ev["type"],
                    "note": int(ev["note"]),
                    "velocity": int(ev.get("velocity", 0)),
                    "time": float(ev["time"]),
                    "channel": int(ev.get("channel", 0)),
                })
            except (TypeError, ValueError, KeyError):
                continue
        # The scratch daemon never fires for freshly-fed events (grace period),
        # but stop it so no stray thread outlives the rebuild.
        scratch._flush_stop.set()
        with scratch._emit_lock:
            # Same trailing-note semantics as stopping a take live.
            if scratch._pending is not None and scratch.tempo_bpm > 0:
                scratch._finalize_pending(scratch._robust_gap_duration())
        return list(scratch.quantized_notes)

    def _requantize_exact(self, raw):
        """Bypass path ("no quantization"): exact on/off pairs matched
        straight from the raw buffer. No rests — gaps are just gaps; hanging
        notes (no off yet) close at the buffer end. Same dict shape as the
        gridded path so downstream grouping/labelling is shared."""
        notes = []
        open_notes = {}  # note -> (on_time, velocity)
        last_t = None
        for ev in raw:
            if ev.get("type") not in ("note_on", "note_off"):
                continue
            try:
                n = int(ev["note"])
                t = float(ev["time"])
            except (TypeError, ValueError, KeyError):
                continue
            last_t = t if last_t is None else max(last_t, t)
            if ev["type"] == "note_on":
                try:
                    v = max(1, min(127, int(ev.get("velocity", 100))))
                except (TypeError, ValueError):
                    v = 100
                if n in open_notes:
                    # Re-strike without release: close the previous at now.
                    ot, ov = open_notes.pop(n)
                    if t > ot:
                        notes.append({"note": n, "on_time": ot,
                                      "off_time": t, "velocity": ov,
                                      "duration": t - ot})
                open_notes[n] = (t, v)
            else:
                if n in open_notes:
                    ot, ov = open_notes.pop(n)
                    if t >= ot:
                        notes.append({"note": n, "on_time": ot,
                                      "off_time": t, "velocity": ov,
                                      "duration": max(0.0, t - ot)})
        if last_t is not None:
            for n, (ot, ov) in sorted(open_notes.items()):
                off = max(last_t, ot + 0.1)
                notes.append({"note": n, "on_time": ot, "off_time": off,
                              "velocity": ov, "duration": off - ot})
        notes.sort(key=lambda q: q["on_time"])
        return notes

    @staticmethod
    def _expand_midi(quantized_take):
        """Expand quantized notes to MIDI on/off event dicts (OUT side of the
        chain; same shape as raw_take_events). Rests are notation-only."""
        events = []
        for qn in quantized_take:
            if qn.get("rest"):
                continue
            try:
                n = int(qn["note"])
                on = float(qn["on_time"])
                off = float(qn["off_time"])
                v = max(1, min(127, int(qn.get("velocity", 100))))
            except (TypeError, ValueError, KeyError):
                continue
            if off < on:
                continue
            events.append({"type": "note_on", "note": n, "velocity": v,
                           "time": on, "channel": 0})
            events.append({"type": "note_off", "note": n, "velocity": 0,
                           "time": off, "channel": 0})
        events.sort(key=lambda e: (e["time"], 0 if e["type"] == "off" else 1)
                    if e["type"] == "note_off"
                    else (e["time"], 1))
        return events

    def notation_from_buffer(self):
        """Re-derive the notation card's note/rest events from the stored raw
        take buffer, processed by the CURRENT quantisation settings.

        Groups simultaneous onsets (3+ -> "chord" via chords.name_only, 2 ->
        "interval" via chords.interval_of; unmatched groups carry label None)
        and preserves time order (rests stay where they fall). See requantize
        for the rebuild both notation and OUT share.
        """
        self.requantize()
        window = 0.0 if self.quantize_enabled else self.bypass_group_window
        merged = []  # list of ("notes", [qn, ...]) | ("rest", qn)
        for qn in self.quantized_take:
            if qn.get("rest"):
                merged.append(("rest", qn))
                continue
            if merged and merged[-1][0] == "notes":
                members = merged[-1][1]
                gap = qn["on_time"] - members[0]["on_time"]
                if window <= 0.0:
                    # Gridded path: same snapped tick (exact float equality).
                    same_slot = gap <= 0.0
                else:
                    # Bypass path: near-simultaneous AND overlapping — a true
                    # block chord, not a fast legato run.
                    same_slot = gap <= window and qn["on_time"] < max(
                        q["off_time"] for q in members)
                if same_slot:
                    # Dedupe: re-strikes of one pitch inside one slot are a
                    # single notation event, not a unison "interval".
                    if qn["note"] not in [q["note"] for q in members]:
                        members.append(qn)
                    continue
            merged.append(("notes", [qn]))
        out = []
        for kind, payload in merged:
            if kind == "rest":
                out.append({
                    "kind": "rest", "notes": [],
                    "on_time": payload["on_time"],
                    "off_time": payload["off_time"],
                    "velocity": 0, "duration": payload["duration"],
                    "label": None,
                })
                continue
            # Dedupe: re-strikes of one pitch inside a single grid tick are
            # one notation slot, not a unison "interval".
            notes = sorted({q["note"] for q in payload})
            first = payload[0]
            if len(notes) >= 3:
                label = chords.name_only(notes) or None
                if label == "(no template)":
                    label = None
                k = "chord"
            elif len(notes) == 2:
                label = chords.interval_of(notes) or None
                k = "interval"
            else:
                label, k = None, "note"
            out.append({
                "kind": k, "notes": notes,
                "on_time": first["on_time"], "off_time": first["off_time"],
                "velocity": first["velocity"], "duration": first["duration"],
                "label": label,
            })
        return out
    
    @property
    def up_time(self):
        return time.time() - self._start

    def _bump(self):
        self.version += 1
        if len(self.recent) > self.recent_keep:
            self.recent = self.recent[-self.recent_keep:]
        if len(self.melody) > self.melody_keep:
            self.melody = self.melody[-self.melody_keep:]
        if len(self.quantized_notes) > self.max_quantized_notes:
            self.quantized_notes = self.quantized_notes[-self.max_quantized_notes:]

    def _estimate_tempo(self, now):
        """Estimate tempo from recent note onsets using autocorrelation with perceptual weighting.
        
        Based on audiojs/beat approach: autocorrelation of inter-onset intervals
        with perceptual weighting (log-Gaussian centered at 120 BPM) to resolve
        octave ambiguity. Uses comb-filter-like resonance for cross-validation.
        """
        if len(self.note_onsets) < 8:
            return
        
        # Get intervals between consecutive onsets (last 30 seconds)
        cutoff = now - 30.0
        recent_onsets = [t for t, _ in self.note_onsets if t > cutoff]
        if len(recent_onsets) < 8:
            return
        
        recent_onsets.sort()
        intervals = []
        for i in range(1, len(recent_onsets)):
            interval = recent_onsets[i] - recent_onsets[i - 1]
            if 0.08 < interval < 2.0:  # filter outliers - exclude trills (<80ms) and long pauses (>2s)
                intervals.append(interval)
        
        if len(intervals) < 8:
            return
        
        # Filter out very short intervals that are likely trills/tremolos (< 100ms)
        # and very long intervals (> 1.5s) which are likely phrase boundaries
        filtered_intervals = [iv for iv in intervals if 0.1 <= iv <= 1.5]
        
        if len(filtered_intervals) < 6:
            # Fall back if filtering too aggressive
            filtered_intervals = [iv for iv in intervals if 0.1 <= iv <= 2.0]
            if len(filtered_intervals) < 6:
                return
        
        # Method 1: Histogram-based approach with perceptual weighting
        # Build histogram of intervals with perceptual weighting (log-Gaussian at 120 BPM)
        import math
        
        # BPM range to search
        min_bpm, max_bpm = 50, 220
        
        # Create bins for BPM values
        num_bins = 100
        bpm_bins = [0] * num_bins
        bpm_values = [min_bpm + (max_bpm - min_bpm) * i / (num_bins - 1) for i in range(num_bins)]
        
        # Perceptual weighting: log-Gaussian centered at 120 BPM
        def perceptual_weight(bpm):
            # Log-Gaussian centered at 120 BPM (Ellis 2007)
            log_bpm = math.log(bpm)
            log_center = math.log(120)
            sigma = 0.5  # controls width
            return math.exp(-0.5 * ((log_bpm - log_center) / sigma) ** 2)
        
        # For each interval, find candidate BPMs and accumulate weighted votes
        for iv in intervals:
            # Candidate BPM = 60 / interval (quarter note beat)
            # Also consider half/double tempo (eighth/half note beats)
            for mult in [0.5, 1.0, 2.0]:
                bpm = 60.0 / (iv * mult)
                if min_bpm <= bpm <= max_bpm:
                    # Find bin
                    bin_idx = int((bpm - min_bpm) / (max_bpm - min_bpm) * (num_bins - 1))
                    bin_idx = max(0, min(bin_idx, num_bins - 1))
                    weight = perceptual_weight(bpm)
                    bpm_bins[bin_idx] += weight
        
        # Find peak in histogram
        if max(bpm_bins) == 0:
            return
        
        best_bin = bpm_bins.index(max(bpm_bins))
        best_bpm = bpm_values[best_bin]
        max_weight = bpm_bins[best_bin]
        
        # Cross-validation: check if this tempo makes sense with the intervals
        # Calculate how many intervals fit this tempo (within tolerance)
        if best_bpm > 0:
            beat_duration = 60.0 / best_bpm
            # Count intervals that match this beat duration (within 15% tolerance)
            matches = 0
            for iv in intervals:
                # Check if interval matches beat, half-beat, or double-beat
                for mult in [0.5, 1.0, 1.5, 2.0, 3.0]:
                    expected = beat_duration * mult
                    if abs(iv - expected) < 0.15 * expected:  # 15% tolerance
                        matches += 1
                        break
            
            match_ratio = matches / len(intervals) if intervals else 0
            
            # Only accept if a good fraction of intervals match
            if match_ratio >= 0.5:
                # Cross-check with perceptual weighting to resolve octave ambiguity
                # Prefer BPM close to 120 (perceptual center)
                perceptual_score = perceptual_weight(best_bpm)
                
                # Only update if confident
                if max_weight > 0.1 and match_ratio >= 0.5:
                    self.detected_bpm = best_bpm
                    self.last_tempo_update = now
                    # Mirror into the effective tempo only when the user has NOT
                    # fixed a tempo. A user-defined tempo locks tempo_bpm so the
                    # grid (and the note values derived from it) stay stable.
                    if self.user_tempo_bpm <= 0:
                        self.tempo_bpm = best_bpm

    def set_user_tempo(self, bpm):
        """Fix the effective (quantization) tempo to a user value in BPM.

        Pass 0 / None / 'auto' to clear the override and revert to the live
        detected estimate. A fixed tempo stops the flapping that made note
        values change mid-recording; the detected value remains available as a
        suggestion (detected_bpm). Resets the pending-onset anchor since the
        grid size changed.
        """
        if not bpm or bpm <= 0:
            self.user_tempo_bpm = 0.0
            self.tempo_bpm = self.detected_bpm
        else:
            self.user_tempo_bpm = float(bpm)
            self.tempo_bpm = float(bpm)
        self._pending = None
        self.version += 1

    def set_time_signature(self, numer, denom):
        """Set the user time signature (beats per measure / beat unit).

        Accepts common denominators (1, 2, 4, 8, 16). Resets the pending-onset
        anchor so measure/bar boundaries shift cleanly to the new meter.
        """
        denom = int(denom) if denom is not None else 4
        try:
            numer = int(numer)
        except (TypeError, ValueError):
            return False
        if numer < 1 or numer > 16:
            return False
        if denom not in (1, 2, 4, 8, 16):
            return False
        self.time_signature = "%d/%d" % (numer, denom)
        self._pending = None
        self.version += 1
        return True

    @property
    def time_sig_numer(self):
        return int(self.time_signature.split("/")[0])

    @property
    def time_sig_denom(self):
        return int(self.time_signature.split("/")[1])

    def _onset_grid(self, on_time, now):
        """Snap a note onset to the rhythm grid, returning (quantized_on, grid_step)."""
        if self.tempo_bpm <= 0:
            return on_time, 0.0
        beat_duration = 60.0 / self.tempo_bpm
        grid_step = self._grid_step(beat_duration)
        relative_time = on_time - self._start
        quantized_relative = round(relative_time / grid_step) * grid_step
        quantized_time = self._start + quantized_relative
        if quantized_time > now:
            quantized_time = now
        return quantized_time, grid_step

    def _on_note_on(self, event, now):
        """Time-to-next-onset: a note's value is the gap until the NEXT onset.

        The pending group (self._pending) holds the currently-open onset. On a
        new onset:
          - same grid tick  -> chord member, join the group (no finalize)
          - later grid tick -> finalize the group with duration = gap (in grid
            steps) between the two snapped onsets, then open a new group.
        The pending note is only emitted one onset later (the accepted cost of
        this derivation), and the trailing note is flushed by a daemon.
        """
        qon, grid_step = self._onset_grid(event["time"], now)
        with self._emit_lock:
            finalize = None
            if self._pending is not None:
                if qon > self._pending["qon"]:
                    # A genuinely later onset: finalize the previous group with the
                    # gap. With a grid we use the snapped gap (in grid steps); with
                    # no tempo yet (grid_step==0) the raw gap is still a sensible
                    # duration (the frontend renders it as a default quarter anyway).
                    if grid_step > 0:
                        gap_steps = round((qon - self._pending["qon"]) / grid_step)
                        finalize = max(1, gap_steps) * grid_step
                    else:
                        finalize = qon - self._pending["qon"]
                else:
                    # Simultaneous onset (chord member, or a clock-skew tie): join the
                    # group. The whole group's duration is set when the NEXT distinct
                    # onset arrives.
                    self._pending["notes"].append((event["note"], event["velocity"], None))
                    return
            if finalize is not None:
                self._finalize_pending(finalize)
            self._pending = {
                "qon": qon,
                # wall_t in epoch seconds; qon in capture-relative seconds. The
                # flush daemon needs the same time base as time.time() to age the
                # note correctly (capture-relative qon would ALWAYS look ancient).
                "wall_t": time.time(),
                # members are (note, velocity, release_time) where release_time is
                # set when the key's note_off arrives (used to split long gaps
                # into note-value + rest when the player pauses between notes).
                "notes": [(event["note"], event["velocity"], None)],
            }

    def _quantize_time(self, time_value, now):
        """Quantize a time value to the nearest grid position based on current tempo."""
        qon, _ = self._onset_grid(time_value, now)
        return qon

    def handle(self, event):
        self._bump()
        etype = event["type"]
        now = event["time"]
        if etype == "note_on":
            self.held[event["note"]] = {
                "velocity": event["velocity"],
                "on_time": event["time"],
            }
            self.recent.append(
                {"type": "note_on", "note": event["note"],
                 "velocity": event["velocity"], "time": event["time"]}
            )
            # Record raw event immediately for live raw buffer display
            if self.recording:
                self.raw_take_events.append({
                    "type": "note_on",
                    "note": event["note"],
                    "velocity": event["velocity"],
                    "time": event["time"],
                    "channel": event.get("channel", 0),
                })
                if len(self.raw_take_events) > self.max_raw_take_events:
                    self.raw_take_events = self.raw_take_events[-self.max_raw_take_events:]
            # Track onset for tempo detection
            self.note_onsets.append((now, event["note"]))
            # Keep only last 60 seconds of onsets for tempo detection
            cutoff = now - 60.0
            self.note_onsets = [(t, n) for t, n in self.note_onsets if t > cutoff]
            
            # Update tempo estimate
            self._estimate_tempo(now)
            # Time-to-next-onset: finalize the previous note using the gap to
            # this onset (emitting it one onset late), open a new pending group.
            self._on_note_on(event, now)
            self._start_flush_daemon()
        elif etype == "note_off":
            prev = self.held.pop(event["note"], None)
            self.recent.append(
                {"type": "note_off", "note": event["note"], "time": event["time"]}
            )
            # Record raw event immediately for live raw buffer display
            if self.recording:
                self.raw_take_events.append({
                    "type": "note_off",
                    "note": event["note"],
                    "velocity": 0,
                    "time": event["time"],
                    "channel": event.get("channel", 0),
                })
                if len(self.raw_take_events) > self.max_raw_take_events:
                    self.raw_take_events = self.raw_take_events[-self.max_raw_take_events:]
            # Record the release on the open pending group (if the note is still
            # pending here) so held time is known when the group is finalized.
            if self._pending is not None:
                for i, m in enumerate(self._pending["notes"]):
                    if m[0] == event["note"]:
                        notes = list(self._pending["notes"])
                        notes[i] = (m[0], m[1], event["time"])
                        self._pending["notes"] = notes
                        break
            if prev is not None:
                duration = event["time"] - prev["on_time"]
                self.melody.append(
                    (prev["on_time"], duration, event["note"])
                )
        elif etype == "program_change":
            self.program = event["program"]
            self.bank = event.get("bank", 0)
            self.receive_program = event["program"]
            self.receive_bank = self.bank
            self.recent.append(
                {"type": "program_change", "program": event["program"],
                 "bank": self.bank, "channel": event.get("channel", 0), "time": event["time"]}
            )
        elif etype == "control_change":
            # Watch received CCs (wheel -> CC1, panel -> aux resets, etc.).
            self.received_ctrl[int(event["controller"])] = int(event["value"])
        elif etype == "pitch_bend":
            # aseqdump reports the full 14-bit value (0-16383, center 8192);
            # map onto the board's real bend range (BEND_RANGE_ST).
            v = int(event["value"])
            self.received_pitch_bend = round((v - 8192) / 8192.0 * BEND_RANGE_ST, 2)
        elif etype == "offline":
            self.online = False
            self.recent.append({"type": "offline", "time": event["time"]})
        elif etype == "online":
            self.online = True
            self.recent.append({"type": "online", "time": event["time"]})

    def set_quantization(self, divisions):
        """Set the quantization grid resolution (steps per beat), labelled in
        explicit note values: 16 = 64ths, 8 = 32nds, 4 = 16ths (default),
        2 = 8ths, 1 = quarters, 0.5 = halves, 0.25 = wholes.
        0 = bypass ("no quantization"): the transform chain passes exact
        timing through. Resets the pending-onset anchor so the next note
        is treated as a fresh phrase after the grid changes.
        """
        try:
            divisions = float(divisions)
        except (TypeError, ValueError):
            return False
        if divisions == 0:
            self.quantize_enabled = False
        elif divisions in self.VALID_GRIDS:
            self.quantize_enabled = True
            self.quantization_divisions = divisions
        else:
            return False
        self._pending = None
        self.version += 1
        return True

    def set_transpose(self, semitones):
        """Set the transposer stage shift in semitones (-24..+24, 0 = off).

        Pitch-only: onset detection and the grid are untouched, so the live
        pending group needs no reset.
        """
        try:
            st = int(semitones)
        except (TypeError, ValueError):
            return False
        if st < -24 or st > 24:
            return False
        self.transpose_semitones = st
        self.version += 1
        return True

    def settings_snapshot(self):
        """The transform-chain settings that give a buffer musical context."""
        return {
            "quantization_divisions": self.quantization_divisions,
            "quantize_enabled": self.quantize_enabled,
            "transpose_semitones": self.transpose_semitones,
            "velocity_enabled": self.velocity_enabled,
            "velocity_standard": self.velocity_standard,
            "velocity_width": self.velocity_width,
            "velocity_mode": self.velocity_mode,
            "humanizer_enabled": self.humanizer_enabled,
            "humanizer_timing_ms": self.humanizer_timing_ms,
            "humanizer_velocity": self.humanizer_velocity,
            "articulation_gap": self.articulation_gap,
            "snap_enabled": self.snap_enabled,
            "snap_bias": self.snap_bias,
            "invert_enabled": self.invert_enabled,
            "invert_mode": self.invert_mode,
            "invert_pivot": self.invert_pivot,
            "invert_pivot_auto": self.invert_pivot_auto,
            "reverse_enabled": self.reverse_enabled,
            "echo_transpose": self.echo_transpose,
            "echo_snap": self.echo_snap,
            "echo_invert": self.echo_invert,
            "echo_velocity": self.echo_velocity,
            "echo_tuning": self.echo_tuning,
            "tuning_enabled": self.tuning_enabled,
            "tuning_cents": list(self.tuning_cents),
            "tuning_preset": self.tuning_preset,
            "key_tonic": self.key_tonic,
            "key_scale": self.key_scale,
            "tempo_bpm": self.tempo_bpm,
            "user_tempo_bpm": self.user_tempo_bpm,
            "time_signature": self.time_signature,
            "midi_channel": self.midi_channel,
        }

    def apply_settings(self, settings):
        """Restore a settings_snapshot() dict from a saved pattern.

        Bounds-checked value by value; unknown/invalid keys are skipped so a
        corrupt pattern can never wedge the chain. Chain-dependent state gets
        rebuilt (grid reset) but the buffer is NOT re-derived here — callers
        decide when to requantize().
        """
        if not isinstance(settings, dict):
            return False

        try:
            div = float(settings.get("quantization_divisions", 4))
            if div in self.VALID_GRIDS:
                self.quantization_divisions = div
                self.quantize_enabled = bool(settings.get("quantize_enabled", True))
                self._pending = None
        except (TypeError, ValueError):
            pass

        st = settings.get("transpose_semitones", 0)
        try:
            st = int(st)
            if -24 <= st <= 24:
                self.transpose_semitones = st
        except (TypeError, ValueError):
            pass

        self.velocity_enabled = bool(settings.get("velocity_enabled", True))
        try:
            std = float(settings.get("velocity_standard", 100.0))
            if 0 <= std <= 127:
                self.velocity_standard = std
        except (TypeError, ValueError):
            pass
        try:
            w = float(settings.get("velocity_width", 50.0))
            if 0 <= w <= 127:
                self.velocity_width = w
        except (TypeError, ValueError):
            pass
        mode = settings.get("velocity_mode", "compress")
        if mode in ("threshold", "compress"):
            self.velocity_mode = mode

        self.humanizer_enabled = bool(settings.get("humanizer_enabled", False))
        try:
            tm = float(settings.get("humanizer_timing_ms", 10.0))
            if 0 <= tm <= 200:
                self.humanizer_timing_ms = tm
        except (TypeError, ValueError):
            pass
        try:
            hv = int(settings.get("humanizer_velocity", 5))
            if 0 <= hv <= 127:
                self.humanizer_velocity = hv
        except (TypeError, ValueError):
            pass

        try:
            ag = float(settings.get("articulation_gap", 0.0))
            if 0 <= ag <= 0.9:
                self.articulation_gap = ag
        except (TypeError, ValueError):
            pass

        self.snap_enabled = bool(settings.get("snap_enabled", False))
        bias = settings.get("snap_bias", "nearest")
        if bias in ("nearest", "up", "down"):
            self.snap_bias = bias
        self.invert_enabled = bool(settings.get("invert_enabled", False))
        try:
            pv = int(settings.get("invert_pivot", 48))
            if 0 <= pv <= 127:
                self.invert_pivot = pv
        except (TypeError, ValueError):
            pass
        auto = bool(settings.get("invert_pivot_auto", False))
        self.invert_pivot_auto = auto
        if not auto:
            self.invert_pivot_live = None
        imode = settings.get("invert_mode", "chromatic")
        if imode in ("chromatic", "diatonic"):
            self.invert_mode = imode
        self.reverse_enabled = bool(settings.get("reverse_enabled", False))
        self.echo_transpose = bool(settings.get("echo_transpose", False))
        self.echo_snap = bool(settings.get("echo_snap", False))
        self.echo_invert = bool(settings.get("echo_invert", False))
        self.echo_velocity = bool(settings.get("echo_velocity", False))
        if self.echo_velocity:
            self._echo_vel_hist = []
        self.echo_tuning = bool(settings.get("echo_tuning", False))
        self.tuning_enabled = bool(settings.get("tuning_enabled", False))
        tp = settings.get("tuning_preset", "equal")
        self.tuning_preset = tp if tp in TUNING_PRESETS or tp == "custom" else "equal"
        tc = settings.get("tuning_cents", None)
        try:
            vals = [max(-100.0, min(100.0, float(c))) for c in tc] if tc is not None else None
        except (TypeError, ValueError):
            vals = None
        self.tuning_cents = vals if vals is not None and len(vals) == 12 else list(
            TUNING_PRESETS.get(self.tuning_preset, TUNING_PRESETS["equal"]))
        if not self.tuning_enabled:
            self._tuning_last_bend = {}
        try:
            kt = int(settings.get("key_tonic", -1))
            self.key_tonic = max(-1, min(11, kt))
        except (TypeError, ValueError):
            pass
        ks = settings.get("key_scale", "")
        if ks in SCALE_SEMIS:
            self.key_scale = ks
        else:
            self.key_scale = ""

        try:
            u = float(settings.get("user_tempo_bpm", 0.0))
            if u >= 0 and u <= 300:
                self.user_tempo_bpm = u
        except (TypeError, ValueError):
            pass
        try:
            t = float(settings.get("tempo_bpm", 120.0))
            if t > 0:
                self.tempo_bpm = t
        except (TypeError, ValueError):
            pass
        ts = settings.get("time_signature", "4/4")
        if isinstance(ts, str) and "/" in ts:
            try:
                n, d = ts.split("/")
                self.set_time_signature(int(n), int(d))
            except (TypeError, ValueError):
                pass
        try:
            ch = int(settings.get("midi_channel", 0))
            if 0 <= ch <= 15:
                self.midi_channel = ch
        except (TypeError, ValueError):
            pass

        self.version += 1
        return True

    def set_recording(self, flag):
        """Start or stop a recording take.

        Starting a take clears pending quantized state (fresh piece) and sets
        self.recording = True. Stopping a take flushes the trailing pending note
        immediately (so the last-played note is captured rather than hanging) and
        sets self.recording = False.

        The frontend only accumulates events into its stave while recording, which
        is what gives the explicit REC/STOP behaviour: press REC to clear the stave
        and start a take, press STOP to freeze it (flushing the final note).
        """
        flag = bool(flag)
        if flag:
            with self._emit_lock:
                self._pending = None
                self.quantized_notes = []
                self.raw_take_events = []
                self.take_notes = []  # clear the take buffer
                self.quantized_take = []  # clear the transform output
                self.transformed_events = []
                self.held = {}
                self.version += 1
            self.recording = True
        else:
            with self._emit_lock:
                # Flush the trailing pending note so STOP captures the last attack.
                if self._pending is not None and self.tempo_bpm > 0:
                    self._finalize_pending(self._robust_gap_duration())
                self.version += 1
            self.recording = False

    def reset_take(self):
        """New empty buffer: stop any recording and wipe every take-derived
        buffer, discarding an open pending note WITHOUT flushing it into the
        take. The next notes start from nothing instead of appending to the
        old take. (The live note feed `recent` is left alone — it has its own
        stream-only clear.)"""
        with self._emit_lock:
            self._pending = None
            self.quantized_notes = []
            self.raw_take_events = []
            self.take_notes = []
            self.quantized_take = []
            self.transformed_events = []
            self.held = {}
            self.version += 1
        self.recording = False

    def _get_receive_voice_name(self):
        """Return the name of the current receive voice from bank/program."""
        return VOICES_BY_PROGRAM.get((self.receive_bank, self.receive_program), "Unknown")

    def snapshot(self):
        return {
            "online": self.online,
            "held": sorted(self.held.keys()),
            "held_detail": {str(k): self.held[k] for k in sorted(self.held)},
            "recent": self.recent[-40:],
            "up_time": round(self.up_time, 1),
            "version": self.version,
            "program": self.program,
            "bank": self.bank,
            "receive_program": self.receive_program,
            "receive_bank": self.receive_bank,
            "receive_voice": self._get_receive_voice_name(),
            "tempo_bpm": round(self.tempo_bpm, 1) if self.tempo_bpm > 0 else 0,
            "detected_bpm": round(self.detected_bpm, 1) if self.detected_bpm > 0 else 0,
            "user_tempo_bpm": round(self.user_tempo_bpm, 1) if self.user_tempo_bpm > 0 else 0,
            "quantization_divisions": self.quantization_divisions,
            "quantize_enabled": self.quantize_enabled,
            "transpose_semitones": self.transpose_semitones,
            "time_signature": self.time_signature,
            "recording": self.recording,
            "velocity_standard": self.velocity_standard,
            "velocity_width": self.velocity_width,
            "velocity_mode": self.velocity_mode,
            "velocity_enabled": self.velocity_enabled,
            "velocity_detected": round(self.detected_velocity, 1) if self.detected_velocity > 0 else 0,
            "velocity_min": round(self.detected_velocity_min, 1) if self.detected_velocity_min > 0 else 0,
            "velocity_max": round(self.detected_velocity_max, 1) if self.detected_velocity_max > 0 else 0,
            "velocity_count": self.detected_velocity_count,
            "humanizer_enabled": self.humanizer_enabled,
            "humanizer_timing_ms": self.humanizer_timing_ms,
            "humanizer_velocity": self.humanizer_velocity,
            "articulation_gap": self.articulation_gap,
            "transform": {
                "snap_enabled": self.snap_enabled,
                "snap_bias": self.snap_bias,
                "invert_enabled": self.invert_enabled,
                "invert_mode": self.invert_mode,
                "invert_pivot_auto": self.invert_pivot_auto,
                "invert_pivot": self.invert_pivot,
                # Ver 94: the pivot actually in force — the auto-resolved one
                # (first note of the take) when auto is on, else the manual one.
                "invert_pivot_effective": self.invert_pivot_live
                    if (self.invert_pivot_auto and self.invert_pivot_live is not None)
                    else self.invert_pivot,
                "reverse_enabled": self.reverse_enabled,
                "echo_transpose": self.echo_transpose,
                "echo_snap": self.echo_snap,
                "echo_invert": self.echo_invert,
                "echo_velocity": self.echo_velocity,
                "echo_tuning": self.echo_tuning,
            },
            "tuning": {
                "enabled": self.tuning_enabled,
                "cents": list(self.tuning_cents),
                "preset": self.tuning_preset,
            },
            "scale": {"tonic": self.key_tonic, "scale": self.key_scale},
            "received_ctrl": dict(self.received_ctrl),
            "received_pitch_bend": self.received_pitch_bend,
            "control_values": dict(self.control_values),
            "control_pitch_bend": self.control_pitch_bend,
            "local_control": self.local_control,
            "echo_enabled": self.echo_enabled,
            "echo_voice": self.echo_voice,
            "seq_outs": list(self.seq_outs),
            "raw_outs": list(self.raw_outs),
            "midi_channel": self.midi_channel,
            "quantized_notes": self.quantized_notes[-100:],  # last 100 quantized notes
            "take_notes": self.take_notes[-100:],  # the frozen take for replay
            "raw_take_events": self.raw_take_events[-500:],  # semi-raw MIDI events for replay / piano roll
        }
