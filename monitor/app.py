"""Flask web app serving the live keyboard monitor on :5050."""
import itertools
import json
import os
import queue
import subprocess
import threading
import time
import traceback

from flask import Flask, jsonify, render_template, request, Response

from .capture import Capture
from .state import State
from .analysis import Analyser
from .replay import Replay, plan_from_raw, VOICES
from . import chords

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

PORT = 5050
FULL_KEYBOARD = False

# --- Capture watchdog / health ---
# The capture thread runs an infinite stream loop. If it ever throws (a bug,
# unexpected MIDI input, a crash inside a handler), the thread used to die
# silently while the HTTP server kept serving -- making the app look "up"
# while no notes flow. This supervised wrapper restarts the loop with
# exponential backoff and exposes the health via /api/state + SSE so failures
# are visible and self-healing.
CAPTURE_BASE_DELAY = 1.0     # seconds before first retry
CAPTURE_MAX_DELAY = 30.0     # capped backoff between restarts

_capture_lock = threading.Lock()
_capture_health = {
    "alive": False,
    "error": None,        # last error message (None when healthy/restarting)
    "restarts": 0,        # cumulative capture-loop restarts
    "last_error_time": None,
}
# The live Capture instance, so the on-screen piano (/api/note) can inject
# synthetic notes into the same stream as the real keyboard. Set by the
# supervisor thread on each (re)start of the capture loop.
_capture_instance = None


# buffer of recent events/flashes for late-joining SSE clients
class Hub:
    def __init__(self, keep=200):
        self.lock = threading.Lock()
        self.buffer = []
        self.keep = keep
        self.subscribers = set()
        self._id = itertools.count(1)

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.subscribers.add(q)
            # seed with buffered history so a new client catches up
            for item in self.buffer[-self.keep:]:
                self._put_nolock(q, item)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subscribers.discard(q)

    def publish(self, item):
        with self.lock:
            item["id"] = next(self._id)
            self.buffer.append(item)
            if len(self.buffer) > self.keep * 3:
                self.buffer = self.buffer[-self.keep:]
            for q in list(self.subscribers):
                self._put_nolock(q, item)

    @staticmethod
    def _put_nolock(q, item):
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
                q.put_nowait(item)
            except (queue.Empty, queue.Full):
                pass


hub = Hub()
state = State()
analyser = Analyser()
replayer = Replay()  # plays the quantized take back out to the keyboard


def _note_name(n):
    return chords.nm(n)


def _run_capture(cap):
    """Background: read MIDI (from the given Capture), update state + analyser,
    publish to hub. Guarded by the supervisor so any crash self-heals."""
    for event in cap:
        etype = event["type"]
        t = event["time"]
        if etype == "note_on":
            state.handle(event)
            analyser.on_note(t, event["note"])
            hub.publish({"type": "note", "note": event["note"],
                         "name": _note_name(event["note"]),
                         "velocity": event["velocity"], "time": t,
                         "held": sorted(state.held)})
            ann = analyser.held_chord_announce(state.held, t)
            if ann:
                hub.publish({"type": "flash", **ann,
                             "notes": sorted(state.held), "time": t})
            # Chord and arpeggio are both built from the held note set; if we
            # just flashed a held chord for these exact notes, don't also flash
            # an arpeggio for the same simultaneity (they'd fight for the banner).
            aann = analyser.arpeggio_announce(t, suppress_notes=state.held if ann else None)
            if aann:
                hub.publish({"type": "flash", **aann, "time": t})
            # tonal key/mode sensing from the rolling note window
            kann = analyser.key_announce(t)
            if kann:
                hub.publish({"type": "key", **kann, "time": t})
        elif etype == "note_off":
            state.handle(event)
            hub.publish({"type": "noteoff", "note": event["note"],
                         "name": _note_name(event["note"]),
                         "time": t, "held": sorted(state.held)})
        elif etype == "program_change":
            state.handle(event)
            hub.publish({"type": "program_change", "program": event["program"],
                         "bank": event.get("bank", 0),
                         "channel": event["channel"],
                         "name": Capture.VOICE_BY_PROGRAM.get((event.get("bank", 0), event["program"]), "Unknown"),
                         "time": t})
        elif etype == "offline":
            state.handle(event)
            hub.publish({"type": "status", "online": False, "time": t})
        elif etype == "online":
            state.handle(event)
            hub.publish({"type": "status", "online": True, "time": t})

        # Publish any quantized notes produced by the trailing-note flush daemon
        # (idle keyboard still lets Queued = clock/active-sensing events through,
        # so a flushed note reaches SSE without waiting for the next note_on).
        for qn in state.take_quantized_events():
            if qn.get("rest"):
                hub.publish({"type": "quantized_rest",
                             "on_time": qn["on_time"], "off_time": qn["off_time"],
                             "duration": qn["duration"],
                             "tempo": state.tempo_bpm,
                             "detected_bpm": state.detected_bpm,
                             "user_tempo_bpm": state.user_tempo_bpm})
            else:
                hub.publish({"type": "quantized_note", "note": qn["note"],
                             "on_time": qn["on_time"], "off_time": qn["off_time"],
                             "duration": qn["duration"], "velocity": qn["velocity"],
                             "tempo": state.tempo_bpm,
                             "detected_bpm": state.detected_bpm,
                             "user_tempo_bpm": state.user_tempo_bpm})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Emergency: close ALL monitor instances (server + aseqdump + supervisor)
    and restart fresh. The current process is killed by the reset script, so we
    spawn it detached and answer before it lands."""
    return _spawn_reset()


def _spawn_reset():
    """Launch `monitor.sh reset` detached so it survives this process dying.

    Returns a JSON response first (the shutdown happens after a 1s grace in the
    script); the browser then reloads once the new server is up.
    """
    monitor_sh = os.path.join(os.path.dirname(__file__), "..", "monitor.sh")
    monitor_sh = os.path.abspath(monitor_sh)
    try:
        subprocess.Popen(
            ["bash", monitor_sh, "reset"],
            cwd=os.path.dirname(monitor_sh),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"could not launch reset: {exc}"}), 500
    return jsonify({"ok": True, "restarting": True})


@app.route("/api/state")
def api_state():
    snap = state.snapshot()
    snap["capture"] = _capture_health_snapshot()
    return jsonify(snap)


@app.route("/api/note", methods=["POST"])
def api_note():
    """Inject a synthetic note_on/note_off (played on the on-screen piano) into
    the notestream.

    The event is queued onto the live Capture's injection queue, so it is
    processed by the SAME pipeline as a real key press: state tracking, tempo
    detection, quantization, chord/arpeggio analysis, SSE feed and stave. Only
    the velocity is synthetic (this UI has no touch), imputed as a constant.
    """
    body = request.get_json(silent=True) or {}
    raw_note = body.get("note")
    if isinstance(raw_note, bool) or not isinstance(raw_note, int):
        return jsonify({"ok": False, "error": "note must be an int"}), 400
    if raw_note < 0 or raw_note > 127:
        return jsonify({"ok": False, "error": "note out of range 0-127"}), 400
    on = bool(body.get("on", True))
    try:
        velocity = int(body.get("velocity", 90))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "velocity must be an int"}), 400
    velocity = 90 if not (1 <= velocity <= 127) else velocity
    cap = _capture_instance
    if cap is None:
        return jsonify({"ok": False, "error": "capture not started"}), 503
    cap.inject_note(raw_note, velocity, on)
    return jsonify({"ok": True, "note": raw_note, "on": on,
                    "velocity": velocity})


@app.route("/api/key/reset", methods=["POST"])
def api_key_reset():
    analyser.reset_key()
    return jsonify({"ok": True})


@app.route("/api/quant", methods=["POST"])
def api_quant():
    """Set the quantization grid resolution (steps per beat, explicit note
    values: 16 = 64ths … 0.25 = wholes). 0 = bypass ("no quantization":
    the transform chain passes exact timing through)."""
    try:
        body = request.get_json(silent=True) or {}
        divisions = float(body.get("divisions", 4))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "divisions must be a number"}), 400
    if not state.set_quantization(divisions):
        return jsonify({"ok": False,
                        "error": "divisions must be 0 or one of 0.25,0.5,1,2,4,8,16"}), 400
    return jsonify({"ok": True, "divisions": state.quantization_divisions,
                    "enabled": state.quantize_enabled})


@app.route("/api/transpose", methods=["POST"])
def api_transpose():
    """Set the transposer stage shift in semitones (-24..+24, 0 = off)."""
    try:
        body = request.get_json(silent=True) or {}
        st = int(body.get("semitones", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "semitones must be an int"}), 400
    if not state.set_transpose(st):
        return jsonify({"ok": False, "error": "semitones must be -24..24"}), 400
    return jsonify({"ok": True, "semitones": state.transpose_semitones})


@app.route("/api/velocity", methods=["POST"])
def api_velocity():
    """Set the velocity compressor stage. Body:
    {"standard": <1-127>, "width": <1-127>, "mode": "threshold"|"compress",
     "enabled": <bool>}. Any field omitted leaves it unchanged.
     Standard velocity is auto-detected from the buffer when set to null.
    """
    body = request.get_json(silent=True) or {}
    try:
        standard = body.get("standard", None)
        if standard is not None:
            standard = float(standard)
        width = body.get("width", None)
        if width is not None:
            width = float(width)
        mode = body.get("mode", None)
        enabled = body.get("enabled", None)
        if mode is not None and mode not in ("threshold", "compress"):
            return jsonify({"ok": False,
                            "error": "mode must be 'threshold' or 'compress'"}), 400
        state.set_velocity_compressor(
            standard=standard, width=width, mode=mode, enabled=enabled)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({
        "ok": True,
        "standard": state.velocity_standard,
        "width": state.velocity_width,
        "mode": state.velocity_mode,
        "enabled": state.velocity_enabled,
        "detected": state.compute_velocity_stats(),
    })


@app.route("/api/humanizer", methods=["POST"])
def api_humanizer():
    """Set the humanizer stage (applied at the end of the transform chain).
    Body: {"enabled": <bool>, "timing_ms": <float>, "velocity": <int>}.
    Any field omitted leaves it unchanged.
    """
    body = request.get_json(silent=True) or {}
    try:
        enabled = body.get("enabled", None)
        if enabled is not None:
            enabled = bool(enabled)
        timing_ms = body.get("timing_ms", None)
        if timing_ms is not None:
            timing_ms = float(timing_ms)
        velocity = body.get("velocity", None)
        if velocity is not None:
            velocity = int(velocity)
        state.set_humanizer(enabled=enabled, timing_ms=timing_ms, velocity=velocity)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({
        "ok": True,
        "enabled": state.humanizer_enabled,
        "timing_ms": state.humanizer_timing_ms,
        "velocity": state.humanizer_velocity,
    })


@app.route("/api/record", methods=["POST"])
def api_record():
    """Start or stop a recording take. Stopping flushes the trailing pending
    note immediately (so the last-played note is captured) and drains any
    quantized events (note + rest) it produced into the SSE stream. The same
    events are returned in the response body so the requesting client can render
    the trailing note even though it just switched its SSE gate off."""
    body = request.get_json(silent=True) or {}
    state.set_recording(bool(body.get("recording", False)))
    out_events = []
    for qn in state.take_quantized_events():
        if qn.get("rest"):
            ev = {"type": "quantized_rest",
                  "on_time": qn["on_time"], "off_time": qn["off_time"],
                  "duration": qn["duration"],
                  "tempo": state.tempo_bpm,
                  "detected_bpm": state.detected_bpm,
                  "user_tempo_bpm": state.user_tempo_bpm}
        else:
            ev = {"type": "quantized_note", "note": qn["note"],
                  "on_time": qn["on_time"], "off_time": qn["off_time"],
                  "duration": qn["duration"], "velocity": qn["velocity"],
                  "tempo": state.tempo_bpm,
                  "detected_bpm": state.detected_bpm,
                  "user_tempo_bpm": state.user_tempo_bpm}
        hub.publish(ev)
        out_events.append(ev)
    return jsonify({"ok": True, "recording": state.recording, "events": out_events})


@app.route("/api/tempo", methods=["POST"])
def api_tempo():
    """Set (or clear) the user-fixed tempo used for quantization.

    Body: {"bpm": <number>}. 0 / null clears the override so quantization
    reverts to the live detected estimate (which stays as a suggestion).
    """
    body = request.get_json(silent=True) or {}
    raw = body.get("bpm", 0)
    try:
        bpm = float(raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bpm must be a number"}), 400
    if bpm < 0 or bpm > 400:
        return jsonify({"ok": False, "error": "bpm out of range"}), 400
    state.set_user_tempo(bpm)
    return jsonify({"ok": True, "bpm": state.user_tempo_bpm,
                    "effective": state.tempo_bpm})


@app.route("/api/timesig", methods=["POST"])
def api_timesig():
    """Set the user time signature for measure (bar) rendering on the stave.

    Body: {"numer": <num>, "denom": <den>}. Resets bar boundaries so the new
    meter takes effect immediately.
    """
    body = request.get_json(silent=True) or {}
    if state.set_time_signature(body.get("numer"), body.get("denom")):
        return jsonify({"ok": True, "time_signature": state.time_signature})
    return jsonify({"ok": False,
                    "error": "invalid time signature"}, 400)



@app.route("/api/replay", methods=["POST"])
def api_replay():
    """Play the current quantized take back through the keyboard's internal
    voices (raw MIDI out to hw:2,0,0 via amidi).

    Requires a connected keyboard and a non-empty take. Runs in a background
    thread; progress is published on SSE ('replay' events) so the on-screen
    keys light up as notes sound. Replays the whole buffer at a user-selectable
    speed multiplier (default 1.0 = original timing).
    """
    if replayer.active:
        return jsonify({"ok": False, "error": "already replaying"}), 409
    if not state.online:
        return jsonify({"ok": False, "error": "keyboard offline"}), 503
    body = request.get_json(silent=True) or {}
    try:
        speed = float(body.get("speed", 1.0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "speed must be a number"}), 400
    if speed <= 0:
        return jsonify({"ok": False, "error": "speed must be > 0"}), 400
    # OUT side of the transform chain: re-derive the quantized take from the
    # raw buffer under current settings, then play the transformed MIDI.
    state.requantize()
    played = state.transformed_events[-500:]  # limit to last 500 events
    if not played:
        return jsonify({"ok": False, "error": "take is empty"}), 400
    # Optional voice selection: send a program change before playback so the
    # keyboard uses the chosen voice instead of whatever it was last on.
    voice = _voice_to_bank_pc(body.get("voice", "auto"))
    # If a specific voice is selected, update the receive voice state.
    if voice is not None:
        state.receive_program = voice[1]
        state.receive_bank = voice[0]
    # Play the transformed MIDI through the keyboard's internal voices.
    loop = bool(body.get("loop", False))
    replayer.play(played, speed=speed, on_event=hub.publish, voice=voice, loop=loop)
    count = sum(1 for e in played if e["type"] == "note_on")
    return jsonify({"ok": True, "notes": count, "speed": speed, "voice": body.get("voice", "auto"), "loop": loop})


@app.route("/api/replay/loop", methods=["POST"])
def api_replay_loop():
    """Loop the current take until stopped. Equivalent to /api/replay with loop=True."""
    body = request.get_json(silent=True) or {}
    try:
        speed = float(body.get("speed", 1.0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "speed must be a number"}), 400
    if speed <= 0:
        return jsonify({"ok": False, "error": "speed must be > 0"}), 400
    if replayer.active:
        return jsonify({"ok": False, "error": "already replaying"}), 409
    if not state.online:
        return jsonify({"ok": False, "error": "keyboard offline"}), 503
    state.requantize()
    played = state.transformed_events[-500:]
    if not played:
        return jsonify({"ok": False, "error": "take is empty"}), 400
    voice = _voice_to_bank_pc(body.get("voice", "auto"))
    if voice is not None:
        state.receive_program = voice[1]
        state.receive_bank = voice[0]
    replayer.play(played, speed=speed, on_event=hub.publish, voice=voice, loop=True)
    count = sum(1 for e in played if e["type"] == "note_on")
    return jsonify({"ok": True, "notes": count, "speed": speed, "voice": body.get("voice", "auto"), "loop": True})


@app.route("/api/replay/stop", methods=["POST"])
def api_replay_stop():
    """Cancel any in-flight replay and send all-notes-off (panic)."""
    replayer.stop()
    return jsonify({"ok": True, "active": replayer.active})


@app.route("/api/take", methods=["GET"])
def api_take():
    """Return the raw take events (semi-raw MIDI events) for piano roll display."""
    raw_events = getattr(state, "raw_take_events", [])
    return jsonify({"ok": True, "raw_events": raw_events, "recording": state.recording})


@app.route("/api/notation")
def api_notation():
    """Notation events re-derived from the raw take buffer under the current
    quantisation/tempo/time-signature — the notation card's source of truth.
    Shares the canonical transform output with OUT (see requantize)."""
    events = state.notation_from_buffer()
    return jsonify({"ok": True, "events": events,
                    "tempo": state.tempo_bpm,
                    "time_signature": state.time_signature,
                    "divisions": state.quantization_divisions,
                    "enabled": state.quantize_enabled,
                    "transpose": state.transpose_semitones,
                    "counts": {"in": len(state.raw_take_events),
                               "out": len(state.transformed_events)}})


@app.route("/api/take/clear", methods=["POST"])
def api_take_clear():
    """Clear the raw take events buffer (plus the transform output derived
    from it, so nothing stale survives)."""
    state.raw_take_events = []
    state.quantized_take = []
    state.transformed_events = []
    return jsonify({"ok": True, "cleared": True})


@app.route("/api/events")
def events():
    q = hub.subscribe()
    def gen():
        yield "retry: 2000\n\n"
        while True:
            # heartbeat so the connection stays alive
            try:
                item = q.get(timeout=15)
                yield f"data: {json.dumps(item)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    resp = Response(gen(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


def _voice_to_bank_pc(voice_name):
    """Convert voice name to (bank, pc) tuple for PSS-A50."""
    if voice_name == "auto":
        return None
    return {name: (bank, pc) for (bank, pc), name in VOICES.items()}.get(voice_name)


def _bank_pc_to_voice(bank, pc):
    """Convert (bank, pc) tuple to voice name for PSS-A50."""
    return VOICES.get((bank, pc), "Unknown")


def _capture_health_snapshot():
    """Copy for /api/state so the supervisor + UI can see capture health."""
    with _capture_lock:
        return dict(_capture_health)


def _run_capture_supervised():
    """Run the capture loop forever, restarting it after any crash.

    The inner _run_capture() drives `for event in Capture():` which is an
    infinite stream that already self-heals around keyboard disconnects. If it
    throws, we record the error, surface it on SSE, back off, and restart so
    a single bug never leaves the app silently deaf.
    """
    delay = CAPTURE_BASE_DELAY
    while True:
        with _capture_lock:
            _capture_health["error"] = None
            _capture_health["alive"] = True
        try:
            cap = Capture()
            global _capture_instance
            _capture_instance = cap
            _run_capture(cap)
        except BaseException as exc:  # noqa: BLE001 - deliberate full restart
            # Mark dead and surface immediately so the UI isn't left guessing.
            with _capture_lock:
                _capture_health["alive"] = False
                _capture_health["error"] = f"{type(exc).__name__}: {exc}"
                _capture_health["last_error_time"] = time.time()
                _capture_health["restarts"] += 1
            traceback.print_exc()
            try:
                hub.publish({"type": "capture_error",
                             "message": _capture_health["error"],
                             "restarts": _capture_health["restarts"],
                             "time": time.time()})
            except Exception:
                pass
            time.sleep(delay)
            delay = min(delay * 2, CAPTURE_MAX_DELAY)
            continue
        else:
            # Loop returned cleanly (shouldn't happen for an infinite stream);
            # treat as a dead capture too and restart without error noise.
            with _capture_lock:
                _capture_health["alive"] = False
                _capture_health["restarts"] += 1
            time.sleep(delay)
            delay = min(delay * 2, CAPTURE_MAX_DELAY)


def start_capture_thread():
    t = threading.Thread(target=_run_capture_supervised, daemon=True)
    t.start()


def main():
    start_capture_thread()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
