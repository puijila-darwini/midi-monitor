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

    # Quantization grid settings
    QUANTIZATION_DIVISIONS = 4  # 4 = 16th notes, 3 = 8th triplets, 6 = 32nd notes

    def __init__(self, recent_keep=120, melody_keep=400):
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
        
        # Tempo detection
        self.note_onsets = []  # list of (time, note) for tempo detection
        self.tempo_bpm = 0.0
        self.last_tempo_update = 0
        self.tempo_update_interval = 2.0  # update tempo every 2 seconds
        
        # Quantized note data
        self.quantized_notes = []  # list of quantized note events
        self.max_quantized_notes = 500
    
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
                    self.tempo_bpm = best_bpm
                    self.last_tempo_update = now

    def _quantize_time(self, time_value, now):
        """Quantize a time value to the nearest grid position based on current tempo."""
        if self.tempo_bpm <= 0:
            return time_value  # no tempo info, return as-is
        
        # Calculate beat duration (quarter note duration in seconds)
        beat_duration = 60.0 / self.tempo_bpm
        
        # Quantization grid: divide beat into QUANTIZATION_DIVISIONS
        grid_step = beat_duration / self.QUANTIZATION_DIVISIONS
        
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

        Quantize the note's *onset* to the rhythm grid, then snap the *held
        duration* to the nearest grid duration (not both endpoints
        independently). Quantizing on and off separately produces artificial
        duration jitter (e.g. quarter notes interspersed with 16ths for an
        evenly played scale), because a note straddling a beat boundary gets
        pushed to wildly different lengths. Derive off from the snapped onset
        + snapped duration instead.
        """
        quantized_on = self._quantize_time(on_time, now)

        # Raw held duration (not position-quantized)
        raw_duration = off_time - on_time
        if raw_duration <= 0:
            raw_duration = 0.01

        if self.tempo_bpm > 0:
            beat_duration = 60.0 / self.tempo_bpm
            grid_step = beat_duration / self.QUANTIZATION_DIVISIONS
            # Snap duration to nearest grid multiple (minimum one step)
            steps = max(1, int(round(raw_duration / grid_step)))
            quantized_duration = steps * grid_step
        else:
            quantized_duration = raw_duration

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
            "quantized_notes": self.quantized_notes[-100:],  # last 100 quantized notes
        }
