"""Play a recorded take back through the keyboard's internal voices.

The PSS-A50 has no ALSA seq output port, so playback goes out over the raw MIDI
device (hw:2,0,0) via amidi. This module schedules the quantized-note buffer
(captured from live playing) back out preserving its relative timing: the same
onset times, the same held durations, the same chords.

Timeline construction is a pure function (plan) so it can be unit-tested
without the keyboard; Replay only handles the real-time serialization.
"""
import subprocess
import threading
import time

DEVICE = "hw:2,0,0"

# PSS-A50 voice list, keyed by (bank select MSB, program) -> name.
# The PSS-A50 is NOT full GM: it has exactly 42 presets (40 normal voices +
# 2 drum kits). Normal voices use GM1-compatible program numbers (Bank MSB 0);
# the two drum kits use XG/XGlite numbering with Bank MSB 127.
VOICES = {
    (0, 0): "Grand Piano",
    (0, 4): "Electric Piano 1",
    (0, 5): "Electric Piano 2",
    (0, 2): "Electric Grand Piano",
    (0, 16): "Drawbar Organ",
    (0, 18): "Rock Organ",
    (0, 21): "Accordion",
    (0, 22): "Harmonica",
    (0, 24): "Nylon Guitar",
    (0, 25): "Steel Guitar",
    (0, 26): "Jazz Guitar",
    (0, 27): "Clean Guitar",
    (0, 29): "Overdriven Guitar",
    (0, 32): "Acoustic Bass",
    (0, 33): "Finger Bass",
    (0, 36): "Slap Bass",
    (0, 38): "Synth Bass",
    (0, 48): "Strings",
    (0, 45): "Pizzicato Strings",
    (0, 40): "Violin",
    (0, 42): "Cello",
    (0, 46): "Orchestral Harp",
    (0, 68): "Oboe",
    (0, 71): "Clarinet",
    (0, 73): "Flute",
    (0, 66): "Tenor Sax",
    (0, 61): "Brass Section",
    (0, 56): "Trumpet",
    (0, 57): "Trombone",
    (0, 60): "French Horn",
    (0, 62): "Synth Brass",
    (0, 82): "Gemini",
    (0, 84): "Punchy Chordz",
    (0, 80): "Square Lead",
    (0, 81): "Sawtooth Lead",
    (0, 88): "New Age Pad",
    (0, 89): "Warm Pad",
    (0, 100): "Brightness",
    (127, 0): "Standard Kit",
    (127, 27): "Dance Kit",
    (0, 11): "Vibraphone",
    (0, 12): "Marimba",
}

def _send(hexstr):
    subprocess.run(["amidi", "-p", DEVICE, "-S", hexstr], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def program_change(bank, pc):
    """Send a program change for (bank, pc) to the keyboard."""
    _send("B0 00 %02X" % bank)
    time.sleep(0.02)
    _send("C0 %02X" % pc)
    time.sleep(0.02)


def plan(quantized_notes, speed=1.0):
    """Build a replay timeline from quantized-note dicts.

    Returns (events, duration):

    - events: sorted list of [rel_time, kind, [(note, velocity), ...]] where
      simultaneous strikes are grouped into one chord batch and note-offs are
      ordered before note-ons when they tie. rel_time is seconds since the
      first onset (0.0), already scaled by `speed`.
    - duration: the scaled span from first onset to last release.

    Rests are skipped entirely: absolute scheduling preserves any silence. Notes
    with no 'off_time' fall back to 'on_time + duration'.
    """
    speed = float(speed) if speed and speed > 0 else 1.0
    ons = []
    offs = []
    t0 = None
    last = 0.0
    for qn in quantized_notes:
        if not qn or qn.get("rest") or qn.get("note") is None:
            continue
        try:
            note = int(qn["note"])
        except (TypeError, ValueError):
            continue
        if not (0 <= note <= 127):
            continue
        try:
            vel = max(1, min(127, int(qn.get("velocity") or 100)))
        except (TypeError, ValueError):
            vel = 100
        try:
            on_t = float(qn.get("on_time"))
        except (TypeError, ValueError):
            continue
        try:
            off_t = float(qn.get("off_time"))
        except (TypeError, ValueError):
            try:
                off_t = on_t + float(qn.get("duration") or 0.25)
            except (TypeError, ValueError):
                off_t = on_t + 0.25
        if t0 is None:
            t0 = on_t
        rel_on = (on_t - t0) * speed
        rel_off = (off_t - t0) * speed
        ons.append((rel_on, "on", (note, vel)))
        offs.append((rel_off, "off", (note, vel)))
        last = max(last, rel_off)
    raw = sorted(ons + offs, key=lambda e: (e[0], 0 if e[1] == "off" else 1))
    events = []
    for rel_t, kind, pair in raw:
        if events and events[-1][0] == rel_t and events[-1][1] == kind:
            events[-1][2].append(pair)
        else:
            events.append([rel_t, kind, [pair]])
    return events, last


class Replay:
    """Serialize a quantized take back to the keyboard on a background thread."""

    def __init__(self, device=DEVICE):
        self.device = device
        self._stop = threading.Event()
        self._loop = False
        self._thread = None
        self._last_error = None

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def looping(self):
        return self._loop

    @property
    def last_error(self):
        return self._last_error

    def stop(self):
        """Cancel any in-flight replay and cut the sound immediately."""
        self._stop.set()
        self._loop = False
        try:
            self._send("B0 7B 00")  # all notes off
        except Exception:
            pass

    def play(self, quantized_notes, speed=1.0, on_event=None, voice=None, loop=False):
        """Start playback on a background thread. Returns True if started.

        on_event receives dicts ({type:'replay', phase: ..., ...}) as progress
        is made (start/step/done/stopped/error); it may be the SSE hub publish.
        voice: (bank, pc) program change to send before playback; None = skip.
        loop: if True, replay the pattern continuously until stop() is called.
        Raises nothing; playback errors are reported via on_event instead.
        """
        if self.active:
            return False
        self._stop.clear()
        self._loop = bool(loop)
        self._last_error = None
        # Detect whether the caller passed raw MIDI events (note_on/note_off dicts)
        # or quantized note dicts, and plan accordingly.
        raw = bool(quantized_notes and isinstance(quantized_notes[0], dict) and "type" in quantized_notes[0])
        self._thread = threading.Thread(
            target=self._run, args=(list(quantized_notes), float(speed), on_event, raw, voice),
            name="replay", daemon=True)
        self._thread.start()
        return True

    def _run(self, notes, speed, on_event, raw, voice=None):
        def emit(phase, **kw):
            if on_event is not None:
                try:
                    on_event({"type": "replay", "phase": phase, "time": time.time(), **kw})
                except Exception:
                    pass

        while True:
            try:
                if voice is not None:
                    bank, pc = voice
                    program_change(bank, pc)
                if raw:
                    events, duration = plan_from_raw(notes, speed)
                else:
                    events, duration = plan(notes, speed)
                if not events:
                    emit("error", message="nothing to play (take is empty)")
                    return
                count = sum(len(b[2]) for b in events if b[1] == "on")
                emit("start", count=count, duration=round(duration, 3))
                base = time.monotonic()
                for rel_t, kind, batch in events:
                    target = base + rel_t
                    while True:
                        wait = target - time.monotonic()
                        if wait <= 0.001:
                            break
                        if self._stop.wait(wait):
                            self._all_off()
                            emit("stopped", elapsed=round(time.monotonic() - base, 2))
                            return
                    self._send(self._hex(kind, batch))
                    if kind == "on":
                        emit("step", notes=[n for n, _ in batch])
                self._all_off()
                emit("done", duration=round(duration, 3))
                if not self._loop:
                    return
                # Loop: clear stop flag and restart from beginning.
                self._stop.clear()
            except BaseException as exc:
                self._last_error = exc
                try:
                    self._all_off()
                except Exception:
                    pass
                emit("error", message="%s: %s" % (type(exc).__name__, exc))
                return

    def _hex(self, kind, batch):
        st = "90" if kind == "on" else "80"
        return st + " " + " ".join("%02X %02X" % (n, v) for n, v in batch)

    def _send(self, hexstr):
        subprocess.run(
            ["amidi", "-p", self.device, "-S", hexstr],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _all_off(self):
        try:
            self._send("B0 7B 00")  # all notes off
        except Exception:
            pass


def plan_from_raw(raw_events, speed=1.0):
    """Build a replay timeline from raw MIDI events (note_on/note_off dicts).
    
    Args:
        raw_events: list of dicts with keys: type ('note_on'/'note_off'), note, 
                   velocity (for note_on), time (absolute epoch time)
        speed: playback speed multiplier (1.0 = normal speed)
    
    Returns (events, duration):
        events: sorted list of [rel_time, kind, [(note, velocity), ...]] where
               simultaneous strikes are grouped into one chord batch and note-offs are
               ordered before note-ons when they tie. rel_time is seconds since the
               first onset (0.0), already scaled by `speed`.
        duration: the scaled span from first onset to last release.
    """
    speed = float(speed) if speed and speed > 0 else 1.0
    ons = []
    offs = []
    t0 = None
    last = 0.0
    
    # Group events by time for chord detection
    events_by_time = {}
    for ev in raw_events:
        if ev["type"] not in ("note_on", "note_off"):
            continue
        try:
            note = int(ev["note"])
            if not (0 <= note <= 127):
                continue
            t = float(ev["time"])
        except (TypeError, ValueError):
            continue
            
        if t not in events_by_time:
            events_by_time[t] = []
        events_by_time[t].append(ev)
    
    # Process each timestamp
    for t in sorted(events_by_time.keys()):
        # Find note_on and note_off events at this time
        note_ons = [ev for ev in events_by_time[t] if ev["type"] == "note_on"]
        note_offs = [ev for ev in events_by_time[t] if ev["type"] == "note_off"]
        
        # Process note_ons
        for ev in note_ons:
            note = int(ev["note"])
            try:
                vel = max(1, min(127, int(ev.get("velocity", 100))))
            except (TypeError, ValueError):
                vel = 100
            if t0 is None:
                t0 = t
            rel_on = (t - t0) * speed
            ons.append((rel_on, "on", (note, vel)))
            last = max(last, rel_on)
        
        # Process note_offs
        for ev in note_offs:
            note = int(ev["note"])
            # Velocity for note_off is typically 0
            if t0 is None:
                t0 = t
            rel_off = (t - t0) * speed
            offs.append((rel_off, "off", (note, 0)))  # velocity 0 for note_off
            last = max(last, rel_off)
    
    # Merge simultaneous events
    raw = sorted(ons + offs, key=lambda e: (e[0], 0 if e[1] == "off" else 1))
    events = []
    for rel_t, kind, pair in raw:
        if events and events[-1][0] == rel_t and events[-1][1] == kind:
            events[-1][2].append(pair)
        else:
            events.append([rel_t, kind, [pair]])
    
    return events, last if t0 is not None else 0.0
    
    return events, last if t0 is not None else 0.0