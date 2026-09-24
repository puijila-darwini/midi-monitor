"""Play a recorded take back out to keyboard + sequencer destinations.

The PSS-A50 has no ALSA seq output port (only a capture port), so historically
playback went out over the raw MIDI device (hw:2,0,0) via amidi. That path
reaches the keyboard's internal voices, but BYPASSES the ALSA sequencer, so
sequencer listeners (VCV Rack etc.) never heard the playback.

This module now opens its own ALSA seq output client (midiout.SeqOut) and
routes the quantized-note buffer to any selected "client:port" targets, plus
opt-in raw amidi devices. One path reaches the keyboard, VCV Rack, Midi
Through, and any other seq sink simultaneously.

Timeline construction is a pure function (plan) so it can be unit-tested
without the keyboard; Replay only handles the real-time serialization.
"""
import subprocess
import threading
import time

from .midiout import SeqOut, list_outs, CC_ALL_NOTES_OFF, CC_ALL_SOUND_OFF
from .mididev import find_raw_device

# Pitch-bend range of the PSS-A50 in semitones (Ver 96: was wrongly assumed
# ±24; ear-calibrated 2026-09-22 — labeled +100c detunes came out ~8c, i.e.
# half-throw is 200c). Single source of truth for send + receive + UI.
BEND_RANGE_ST = 2.0

# Legacy fallback raw device: the real node is resolved dynamically per send
# (find_raw_device) because the card number depends on boot enumeration order.
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
    """Send a raw MIDI hex string to the keyboard (raw path).

    The raw device node (hw:N,0,0) is re-resolved by name on each send
    (TTL-cached in mididev) because the ALSA card number depends on boot
    enumeration order — it was 2 before the 2026-09-20 reboot, 1 after.
    Returns True if amidi accepted it. amidi failing (returncode != 0) means
    the board is simply absent/detached — NORMAL per AGENTS.md — so this never
    raises; callers decide how to surface it.
    """
    try:
        r = subprocess.run(["amidi", "-p", find_raw_device(), "-S", hexstr],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False


def program_change(bank, pc):
    """Send a program change for (bank, pc) to the keyboard (raw path)."""
    ok = _send("B0 00 %02X" % bank)
    time.sleep(0.02)
    ok = _send("C0 %02X" % pc) and ok
    time.sleep(0.02)
    return ok


def control_change(cc, value, channel=0):
    """Send a control change to the keyboard (raw path, Bn CC VV)."""
    ch = max(0, min(15, int(channel)))
    cc = max(0, min(127, int(cc)))
    value = max(0, min(127, int(value)))
    ok = _send("B%X %02X %02X" % (ch, cc, value))
    time.sleep(0.01)
    return ok


def pitch_bend(semitones, channel=0):
    """Send a 14-bit pitch bend to the keyboard. The PSS-A50 bends
    ±BEND_RANGE_ST over the full range (center 8192)."""
    ch = max(0, min(15, int(channel)))
    val = int(round(8192 + max(-BEND_RANGE_ST, min(BEND_RANGE_ST, float(semitones))) / BEND_RANGE_ST * 8192))
    val = max(0, min(16383, val))
    ok = _send("E%X %02X %02X" % (ch, val & 0x7F, (val >> 7) & 0x7F))
    time.sleep(0.01)
    return ok


def bend_range(semitones=2, channel=0):
    """Lock the board's pitch-bend sensitivity via RPN 00 00 + Data Entry
    (MIDI Reference: settable 0-24 st, default ±2). Makes BEND_RANGE_ST
    certain by construction instead of ear-calibrated — call when the echo
    path goes live (RPN persists until a GM reset, which also defaults ±2).
    Closes with a NULL RPN so later Data Entry messages can't retune it."""
    ch = max(0, min(15, int(channel)))
    v = max(0, min(24, int(semitones)))
    ok = _send("B%X 65 00" % ch)   # RPN MSB = 0
    ok = _send("B%X 64 00" % ch) and ok   # RPN LSB = 0 -> bend sensitivity
    time.sleep(0.01)
    ok = _send("B%X 06 %02X" % (ch, v)) and ok   # Data Entry MSB = range
    time.sleep(0.01)
    ok = _send("B%X 65 7F" % ch) and ok   # NULL RPN (politeness)
    ok = _send("B%X 64 7F" % ch) and ok
    time.sleep(0.01)
    return ok


def yamaha_master_tuning(cents, device=0):
    """Yamaha MIDI Master Tune SysEx (recognized per the MIDI Reference; it
    tunes the PANEL voices too, not just RX notes). V = (mm<<7)|ll in 0.1c
    steps, center 08 00 = concert, range ±102.4c. device = device number
    nibble (any value accepted)."""
    v = max(0, min(2047, int(round(1024 + float(cents) * 10.0))))
    mm = (v >> 7) & 0x7F
    ll = v & 0x7F
    dev = max(0, min(15, int(device)))
    ok = _send("F0 43 1%X 27 30 00 00 %02X %02X 00 F7" % (dev, mm, ll))
    time.sleep(0.02)
    return ok


def note_on(note, velocity, channel=0):
    """Send a note-on (raw path, 9n NN VV) — used by live-echo mode."""
    ch = max(0, min(15, int(channel)))
    note = max(0, min(127, int(note)))
    velocity = max(0, min(127, int(velocity)))
    return _send("9%X %02X %02X" % (ch, note, velocity))


def note_off(note, channel=0):
    """Send a note-off (raw path, 8n NN 00) — used by live-echo mode."""
    ch = max(0, min(15, int(channel)))
    note = max(0, min(127, int(note)))
    return _send("8%X %02X 00" % (ch, note))


def gm_system_on():
    """GM System ON SysEx (F0 7E 7F 09 01 F7): wholesale re-initializer."""
    ok = _send("F0 7E 7F 09 01 F7")
    time.sleep(0.05)
    return ok


def midi_panic():
    """Kill all sound on every channel, then reset controllers (ch1)."""
    parts = []
    for ch in range(16):
        parts.append("B%X 78 00" % ch)  # All Sound Off (120)
        parts.append("B%X 7B 00" % ch)  # All Notes Off (123)
    parts.append("B0 79 00")            # Reset All Controllers (121)
    ok = _send(" ".join(parts))
    time.sleep(0.05)
    return ok


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
    """Serialize a quantized take out to seq targets + raw devices."""

    def __init__(self, device=DEVICE):
        self.device = device
        self._stop = threading.Event()
        self._loop = False
        self._thread = None
        self._last_error = None
        # Routing: seq targets are ALSA "client:port" strings (VCV Rack, the
        # keyboard's seq port, Midi Through, ...). raw devices are amidi
        # hardware paths (hw:2,0,0) for the keyboard's internal voices.
        self.seq_targets = []
        self.raw_devices = []
        self.channel = 0

    def set_outputs(self, seq_targets, raw_devices=(), channel=0):
        """Set where replay notes go. seq_targets: list of "client:port".
        raw_devices: list of amidi device names ("" disables raw path)."""
        self.seq_targets = list(seq_targets or ())
        self.raw_devices = list(raw_devices or ())
        self.channel = int(channel or 0) & 0x0F

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
            self._all_off()
        except Exception:
            pass

    def play(self, quantized_notes, speed=1.0, on_event=None, voice=None, loop=False,
             tuning=None):
        """Start playback on a background thread. Returns True if started.

        on_event receives dicts ({type:'replay', phase: ..., ...}) as progress
        is made (start/step/done/stopped/error); it may be the SSE hub publish.
        voice: (bank, pc) program change to send before playback; None = skip.
        loop: if True, replay the pattern continuously until stop() is called.
        tuning: callable(note)->cents (or None) for Ver 96 mono microtonal
        playback — a pitch pre-bend is sent to the keyboard before each
        strike batch (bass note's detune; chords share one channel).
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
            target=self._run, args=(list(quantized_notes), float(speed), on_event, raw, voice, tuning),
            name="replay", daemon=True)
        self._thread.start()
        return True

    def _run(self, notes, speed, on_event, raw, voice=None, tuning=None):
        def emit(phase, **kw):
            if on_event is not None:
                try:
                    on_event({"type": "replay", "phase": phase, "time": time.time(), **kw})
                except Exception:
                    pass

        seq = None
        if self.seq_targets:
            try:
                seq = SeqOut("Abora Out")
            except Exception as exc:
                self._last_error = exc
                emit("error", message="seq out failed: %s: %s" % (type(exc).__name__, exc))
                return

        # Ver 96 mono tuning: bend state for this run (keyboard raw path
        # only — seq targets like VCV get the unbent notes).
        tune_last = 0.0

        def tune_reset():
            nonlocal tune_last
            if tune_last != 0.0 and self.raw_devices:
                try:
                    pitch_bend(0.0, channel=self.channel)
                except Exception:
                    pass
                tune_last = 0.0

        while True:
            try:
                if voice is not None and seq is not None:
                    bank, pc = voice
                    for t in self.seq_targets:
                        seq.send_program_change(t, bank, pc, channel=self.channel)
                    seq.flush()
                    time.sleep(0.02)
                if voice is not None and self.raw_devices:
                    bank, pc = voice
                    program_change(bank, pc)
                if raw:
                    events, duration = plan_from_raw(notes, speed)
                else:
                    events, duration = plan(notes, speed)
                if not events:
                    emit("error", message="nothing to play (take is empty)")
                    if seq is not None:
                        seq.close()
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
                            self._all_off(seq)
                            tune_reset()
                            emit("stopped", elapsed=round(time.monotonic() - base, 2))
                            if seq is not None:
                                seq.close()
                            return
                    if kind == "pc":
                        # Mid-stream voice change (arrangement slots). Last one
                        # at a tied timestamp wins; the board applies PC to
                        # received notes only, which is exactly this path.
                        bank, pc = batch[-1]
                        if seq is not None:
                            for t in self.seq_targets:
                                try:
                                    seq.send_program_change(t, bank, pc,
                                                            channel=self.channel)
                                except Exception:
                                    pass
                            try:
                                seq.flush()
                            except Exception:
                                pass
                        if self.raw_devices:
                            program_change(bank, pc)
                        emit("voice", bank=bank, pc=pc)
                        continue
                    if kind == "on" and tuning is not None and self.raw_devices and batch:
                        # Mono pre-bend: the chord shares one channel, so the
                        # bass note's detune wins (documented mono caveat).
                        try:
                            semis = float(tuning(min(n for n, _ in batch))) / 100.0
                        except (TypeError, ValueError):
                            semis = 0.0
                        if abs(semis - tune_last) > 0.005:
                            try:
                                pitch_bend(semis, channel=self.channel)
                            except Exception:
                                pass
                            tune_last = semis
                    self._send_batch(seq, kind, batch)
                    if kind == "on":
                        # t = seconds since this pass's first onset (resets each
                        # loop), so the piano roll can sweep its playhead.
                        emit("step", notes=[n for n, _ in batch],
                             t=round(rel_t, 4))
                self._all_off(seq)
                tune_reset()
                emit("done", duration=round(duration, 3))
                if not self._loop:
                    if seq is not None:
                        seq.close()
                    return
                # Loop: clear stop flag and restart from beginning.
                self._stop.clear()
            except BaseException as exc:
                self._last_error = exc
                try:
                    self._all_off(seq)
                except Exception:
                    pass
                tune_reset()
                emit("error", message="%s: %s" % (type(exc).__name__, exc))
                if seq is not None:
                    seq.close()
                return

    def _send_batch(self, seq, kind, batch):
        """Send one chord/note batch to every configured destination."""
        # Raw amidi path (keyboard internal voices)
        if self.raw_devices:
            hexstr = _hexstr(kind, batch)
            for dev in self.raw_devices:
                try:
                    subprocess.run(
                        ["amidi", "-p", dev, "-S", hexstr],
                        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
        # Sequencer path (VCV Rack etc.)
        if seq is not None:
            for t in self.seq_targets:
                try:
                    seq.send_notes(t, kind, batch, channel=self.channel)
                except Exception:
                    pass
            seq.flush()

    def _all_off(self, seq=None):
        for t in self.seq_targets:
            if seq is not None:
                try:
                    seq.send_cc(t, CC_ALL_NOTES_OFF, 0, channel=self.channel)
                    seq.send_cc(t, CC_ALL_SOUND_OFF, 0, channel=self.channel)
                except Exception:
                    pass
        if seq is not None:
            try:
                seq.flush()
            except Exception:
                pass
        if self.raw_devices:
            for dev in self.raw_devices:
                try:
                    subprocess.run(
                        ["amidi", "-p", dev, "-S", "B0 7B 00 B0 78 00"],
                        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass


def _hexstr(kind, batch):
    st = "90" if kind == "on" else "80"
    return st + " " + " ".join("%02X %02X" % (n, v) for n, v in batch)


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
        if not isinstance(ev, dict):
            continue
        kind = ev.get("type")
        if kind == "program":
            # Mid-stream voice change (arrangement slots): {bank, pc, time}.
            try:
                bank = int(ev.get("bank", 0))
                pc = int(ev.get("pc", 0))
                t = float(ev["time"])
            except (TypeError, ValueError):
                continue
            if not (0 <= bank <= 127 and 0 <= pc <= 127):
                continue
        elif kind in ("note_on", "note_off"):
            try:
                note = int(ev["note"])
                if not (0 <= note <= 127):
                    continue
                t = float(ev["time"])
            except (TypeError, ValueError):
                continue
        else:
            continue

        if t not in events_by_time:
            events_by_time[t] = []
        events_by_time[t].append(ev)
    
    # Process each timestamp
    pcs = []
    # Anchor the timeline on the earliest note OR program event, so a slot's
    # leading program change (voice at the slot start) keeps its head start
    # over a pattern with leading silence.
    t0 = None
    for t in sorted(events_by_time.keys()):
        if any(ev.get("type") in ("note_on", "note_off", "program")
               for ev in events_by_time[t]):
            t0 = t
            break
    for t in sorted(events_by_time.keys()):
        # Find note_on and note_off events at this time
        note_ons = [ev for ev in events_by_time[t] if ev.get("type") == "note_on"]
        note_offs = [ev for ev in events_by_time[t] if ev.get("type") == "note_off"]
        progs = [ev for ev in events_by_time[t] if ev.get("type") == "program"]

        # Voice changes (bank/pc already validated above)
        for ev in progs:
            bank = int(ev.get("bank", 0))
            pc = int(ev.get("pc", 0))
            rel_pc = (t - t0) * speed
            pcs.append((rel_pc, "pc", (bank, pc)))
            last = max(last, rel_pc)

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
    
    # Merge simultaneous events. At a tie, offs go first (release the old
    # chord), then program changes (voice before the notes that use it),
    # then ons.
    _ORDER = {"off": 0, "pc": 1, "on": 2}
    raw = sorted(ons + offs + pcs, key=lambda e: (e[0], _ORDER.get(e[1], 2)))
    events = []
    for rel_t, kind, pair in raw:
        if events and events[-1][0] == rel_t and events[-1][1] == kind:
            events[-1][2].append(pair)
        else:
            events.append([rel_t, kind, [pair]])
    
    return events, last if t0 is not None else 0.0
    
    return events, last if t0 is not None else 0.0