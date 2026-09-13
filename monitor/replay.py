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
        self._thread = None
        self._last_error = None

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self):
        return self._last_error

    def stop(self):
        """Cancel any in-flight replay and cut the sound immediately."""
        self._stop.set()
        try:
            self._send("B0 7B 00")  # all notes off
        except Exception:
            pass

    def play(self, quantized_notes, speed=1.0, on_event=None):
        """Start playback on a background thread. Returns True if started.

        on_event receives dicts ({type:'replay', phase: ..., ...}) as progress
        is made (start/step/done/stopped/error); it may be the SSE hub publish.
        Raises nothing; playback errors are reported via on_event instead.
        """
        if self.active:
            return False
        self._stop.clear()
        self._last_error = None
        self._thread = threading.Thread(
            target=self._run, args=(list(quantized_notes), float(speed), on_event),
            name="replay", daemon=True)
        self._thread.start()
        return True

    def _run(self, notes, speed, on_event):
        def emit(phase, **kw):
            if on_event is not None:
                try:
                    on_event({"type": "replay", "phase": phase, "time": time.time(), **kw})
                except Exception:
                    pass

        try:
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
        except BaseException as exc:
            self._last_error = exc
            try:
                self._all_off()
            except Exception:
                pass
            emit("error", message="%s: %s" % (type(exc).__name__, exc))

    def _hex(self, kind, batch):
        st = "90" if kind == "on" else "80"
        return st + " " + " ".join("%02X %02X" % (n, v) for n, v in batch)

    def _send(self, hexstr):
        subprocess.run(
            ["amidi", "-p", self.device, "-S", hexstr],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _all_off(self):
        try:
            self._send("B0 7B 00")
        except Exception:
            pass