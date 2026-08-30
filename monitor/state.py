"""Live musical state: held notes, recent events, melody and connectivity."""
import time
import statistics
import threading


class State:
    """Tracks the current picture of what is being played.

    - held: dict note -> {velocity, on_time} currently held down
    - recent: rolling list of note_on/note_off events (for feed display)
    - melody: rolling list of completed (on_time, duration, note) for melody view
    - online: whether the keyboard is currently connected
    - note_onsets: list of (time, note) for tempo detection
    - tempo_bpm: estimated tempo in BPM
    """

    # Quantization grid settings.
    # Divisions = how finely each beat (quarter note) is subdivided into grid
    # steps. This doubles as the "strictness"/coarseness control for the stave:
    #   - loose   (2) = 8th-note grid  -> fewer tiny beamed notes, quarters easy
    #   - normal  (4) = 16th-note grid (default)
    #   - tight   (8) = 32nd-note grid -> captures fast passages in detail
    # Tunable live from the UI via State.set_quantization().
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
        self._start = time.time()
        self.version = 0
        
        # Tempo. tempo_bpm is the EFFECTIVE grid tempo used for quantization.
        # detected_bpm is the live on-the-fly estimate (a suggestion/guide).
        # If the user fixes a tempo, tempo_bpm is locked to that value and no
        # longer tracks detected_bpm, so note values stop flapping mid-take.
        self.note_onsets = []  # list of (time, note) for tempo detection
        self.tempo_bpm = 0.0
        self.detected_bpm = 0.0   # live estimate (suggestion)
        self.user_tempo_bpm = 0.0  # 0 = auto (use detected); >0 = fixed by user
        self.last_tempo_update = 0
        self.tempo_update_interval = 2.0  # update tempo every 2 seconds
        
        # Quantized note data
        self.quantized_notes = []  # list of quantized note events
        self.max_quantized_notes = 500
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
        self._emit_queue = []  # finalized quantized notes waiting for app.py to emit
        self._emit_lock = threading.RLock()  # guard _emit_queue/_pending across threads
        self._flush_daemon = None
        self._flush_stop = threading.Event()

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
        if self.quantized_notes:
            recent = [n["duration"] for n in self.quantized_notes[-8:]]
            med = statistics.median(recent)
            beat = 60.0 / self.tempo_bpm
            grid = beat / max(1, self.quantization_divisions)
            if grid > 0:
                steps = max(1, int(round(med / grid)))
                return steps * grid
        return None

    def _finalize_pending(self, duration):
        """Append quantized notes for the pending group with the given duration,
        push them to the emit queue, and clear the pending group.
        duration == None -> fall back to the snapped held duration of the group's
        first note (purely for the degenerate no-tempo case)."""
        p = self._pending
        if p is None:
            return []
        self._pending = None
        if duration is None:
            return []
        new = []
        for note, vel in p["notes"]:
            off = p["qon"] + duration
            qn = {
                "note": note,
                "on_time": p["qon"],
                "off_time": off,
                "velocity": vel,
                "duration": off - p["qon"],
            }
            self.quantized_notes.append(qn)
            new.append(qn)
        if len(self.quantized_notes) > self.max_quantized_notes:
            self.quantized_notes = self.quantized_notes[-self.max_quantized_notes:]
        with self._emit_lock:
            self._emit_queue.extend(new)
        return new

    def take_quantized_events(self):
        """Drain and return the finalized quantized notes not yet emitted via SSE."""
        with self._emit_lock:
            out, self._emit_queue = self._emit_queue, []
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

    def _onset_grid(self, on_time, now):
        """Snap a note onset to the rhythm grid, returning (quantized_on, grid_step)."""
        if self.tempo_bpm <= 0:
            return on_time, 0.0
        beat_duration = 60.0 / self.tempo_bpm
        grid_step = beat_duration / max(1, self.quantization_divisions)
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
                    self._pending["notes"].append((event["note"], event["velocity"]))
                    return
            if finalize is not None:
                self._finalize_pending(finalize)
            self._pending = {
                "qon": qon,
                # wall_t in epoch seconds; qon in capture-relative seconds. The
                # flush daemon needs the same time base as time.time() to age the
                # note correctly (capture-relative qon would ALWAYS look ancient).
                "wall_t": time.time(),
                "notes": [(event["note"], event["velocity"])],
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
            if prev is not None:
                duration = event["time"] - prev["on_time"]
                self.melody.append(
                    (prev["on_time"], duration, event["note"])
                )
        elif etype == "program_change":
            self.program = event["program"]
            self.bank = event.get("bank", 0)
            self.recent.append(
                {"type": "program_change", "program": event["program"],
                 "bank": self.bank, "channel": event.get("channel", 0), "time": event["time"]}
            )
        elif etype == "offline":
            self.online = False
            self.recent.append({"type": "offline", "time": event["time"]})
        elif etype == "online":
            self.online = True
            self.recent.append({"type": "online", "time": event["time"]})

    def set_quantization(self, divisions):
        """Set the quantization grid's fineness (divisions per beat).

        Loose (2) = 8th-note grid, Normal (4) = 16th grid, Tight (8) = 32nd grid.
        Resets the pending-onset anchor so the next note is treated as a fresh
        phrase after the grid changes.
        """
        old = self.quantization_divisions
        self.quantization_divisions = max(1, int(divisions))
        self._pending = None
        if old != self.quantization_divisions:
            self.version += 1

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
            "tempo_bpm": round(self.tempo_bpm, 1) if self.tempo_bpm > 0 else 0,
            "detected_bpm": round(self.detected_bpm, 1) if self.detected_bpm > 0 else 0,
            "user_tempo_bpm": round(self.user_tempo_bpm, 1) if self.user_tempo_bpm > 0 else 0,
            "quantization_divisions": self.quantization_divisions,
            "quantized_notes": self.quantized_notes[-100:],  # last 100 quantized notes
        }
