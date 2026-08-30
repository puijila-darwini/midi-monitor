"""Live musical state: held notes, recent events, melody and connectivity."""
import time
import statistics


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
        # Previous note's grid-snapped onset, used to derive each note's value
        # from inter-onset spacing (the rhythmic gap) rather than held duration.
        self._last_qon = None
    
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
        suggestion (detected_bpm). Resets the onset anchor since the grid size
        changed.
        """
        if not bpm or bpm <= 0:
            self.user_tempo_bpm = 0.0
            self.tempo_bpm = self.detected_bpm
        else:
            self.user_tempo_bpm = float(bpm)
            self.tempo_bpm = float(bpm)
        self._last_qon = None
        self.version += 1

    def _quantize_time(self, time_value, now):
        """Quantize a time value to the nearest grid position based on current tempo."""
        if self.tempo_bpm <= 0:
            return time_value  # no tempo info, return as-is
        
        # Calculate beat duration (quarter note duration in seconds)
        beat_duration = 60.0 / self.tempo_bpm
        
        # Quantization grid: divide beat into quantization_divisions
        grid_step = beat_duration / max(1, self.quantization_divisions)
        
        # Quantize relative to the start of the performance
        relative_time = time_value - self._start
        quantized_relative = round(relative_time / grid_step) * grid_step
        quantized_time = self._start + quantized_relative
        
        # Don't quantize to future (only past or present)
        if quantized_time > now:
            quantized_time = now
        
        return quantized_time

    def _add_quantized_note(self, note, on_time, off_time, velocity, now):
        """Add a quantized note to the quantized notes list.

        The note's ONSET is snapped to the rhythm grid so positions line up, and
        the note VALUE (duration) is driven by the RHYTHMIC SPACING between
        onsets (the gap since the previous note's onset), NOT by how long the
        key is held. On a piano you strike a quarter note briefly and release
        quickly, so held duration is a noisy proxy for musical value — it made
        steady melody collapse into 8ths/16ths that all got beamed together.
        Inter-onset spacing is the cleaner signal: steady quarter playing gives
        a gap ~= one beat, so every note renders as a quarter. Spacings are
        taken on the snapped grid so positions and durations stay coherent. The
        first note (no preceding onset) falls back to its snapped held duration.
        """
        quantized_on = self._quantize_time(on_time, now)

        if self.tempo_bpm > 0:
            beat_duration = 60.0 / self.tempo_bpm
            grid_step = beat_duration / max(1, self.quantization_divisions)
            prev_qon = self._last_qon
            if prev_qon is not None and quantized_on > prev_qon:
                # Musical value = gap since the previous note's onset.
                spacing = quantized_on - prev_qon
                steps = max(1, int(round(spacing / grid_step)))
                quantized_duration = steps * grid_step
            else:
                # First note (or degenerate overlap): fall back to held duration.
                raw_duration = off_time - on_time
                if raw_duration <= 0:
                    raw_duration = grid_step
                steps = max(1, int(round(raw_duration / grid_step)))
                quantized_duration = steps * grid_step
        else:
            quantized_duration = off_time - on_time
            if quantized_duration <= 0:
                quantized_duration = 0.01

        self._last_qon = quantized_on
        quantized_off = quantized_on + quantized_duration

        self.quantized_notes.append({
            "note": note,
            "on_time": quantized_on,
            "off_time": quantized_off,
            "velocity": velocity,
            "duration": quantized_off - quantized_on,
        })

        # Keep list size manageable
        if len(self.quantized_notes) > self.max_quantized_notes:
            self.quantized_notes = self.quantized_notes[-self.max_quantized_notes:]

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
                # Add quantized note
                self._add_quantized_note(event["note"], prev["on_time"], event["time"], prev["velocity"], now)
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
        self._last_qon = None
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
