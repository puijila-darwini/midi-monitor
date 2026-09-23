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
from .mididev import device_info
from .state import State
from .analysis import Analyser
from .replay import (Replay, plan_from_raw, VOICES, control_change, pitch_bend,
                     BEND_RANGE_ST,
                     gm_system_on, midi_panic, note_on, note_off, program_change)
from . import midiout
from . import sinks
from . import chords
from . import patterns
from . import arrange

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

PORT = 5050
FULL_KEYBOARD = False

# Throttle timestamps for received CC/pitch SSE publish (~4/s per source).
_ctrl_log_time = {}

# --- Launchable MIDI destinations (data-driven: see monitor/sinks.py) ---

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
replayer = Replay()  # plays the quantized take back out to chosen destinations


# Default out routing: the keyboard's raw device (internal voices) always on,
# plus any auto_route sink registry entry (sinks.py) that's currently up is
# auto-ticked. Both remain user-adjustable via /api/outs.
def _default_out_routing():
    return sinks.default_routing()


_init_seq, _init_raw = _default_out_routing()
state.seq_outs = _init_seq
state.raw_outs = _init_raw
replayer.set_outputs(_init_seq, _init_raw, channel=state.midi_channel)


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
            if state.echo_enabled:
                # Route the keyed note back to the board as an RX note so the
                # controls that only bind to received notes (program, sustain,
                # CC, pitch) apply to live playing. With local on this layers
                # against the panel voice; local off leaves the echo alone.
                # Ver 94: the press-time mapping is FROZEN (echo_hold) — a
                # mid-hold transform change can no longer make note_off
                # release a different pitch (stuck-note jank). Refcounted per
                # mapped pitch so snap-collapsed keys each hold the tone.
                mapped = state.echo_hold(event["note"], event.get("channel", 0))
                # Ver 95: the velocity compressor can also run on the echo
                # stream (applied live to each keyed note_on's velocity).
                vel = state.map_echo_velocity(event["velocity"])
                # Ver 96 mono tuning: pre-bend the channel to this strike's
                # detune when the tuning op opts into echo (None when
                # unchanged — skips the extra amidi hop).
                bend = state.tuning_strike_bend(mapped, event.get("channel", 0)) \
                    if state.echo_tuning else None
                if bend is not None:
                    pitch_bend(bend, channel=event.get("channel", 0))
                note_on(mapped, vel,
                        channel=event.get("channel", 0))
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
            # Release the pitch mapped at PRESS time (echo_hold); None while
            # another raw key still holds the same mapped tone (refcount) —
            # also None when the press was never echoed at all.
            released = state.echo_release(event["note"])
            if released:
                note_off(released["mapped"], channel=released["channel"])
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
            # Echo follow: with the echo voice on "auto" the echo stream is
            # meant to mirror the panel, but the RX voice is independent of the
            # panel voice - a panel voice change leaves the echoed sound stuck
            # on the old instrument until echo is re-toggled. Re-apply the
            # panel's bank+program to the RX side so "auto" really follows.
            if state.echo_enabled and state.echo_voice == "auto":
                state.receive_bank = event.get("bank", 0)
                state.receive_program = event["program"]
                program_change(state.receive_bank, state.receive_program)
        elif etype == "control_change":
            # Watch CCs arriving FROM the keyboard (wheel, aux resets). Throttle
            # to ~4/s per controller so a wiggled wheel can't flood the feed.
            controller = event["controller"]
            now_ms = time.time() * 1000.0
            if now_ms - _ctrl_log_time.get(controller, 0.0) >= 250:
                _ctrl_log_time[controller] = now_ms
                state.handle(event)
                hub.publish({"type": "ctrl", "controller": controller,
                             "value": event["value"], "channel": event["channel"],
                             "name": Capture.CC_NAMES.get(controller, "CC%d" % controller),
                             "time": t})
        elif etype == "pitch_bend":
            now_ms = time.time() * 1000.0
            if now_ms - _ctrl_log_time.get("pb", 0.0) >= 250:
                _ctrl_log_time["pb"] = now_ms
                prev = state.received_pitch_bend
                state.handle(event)
                hub.publish({"type": "pitch", "semitones": state.received_pitch_bend,
                             "value": event["value"], "time": t,
                             "down": state.received_pitch_bend - prev})
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
    # Resolved MIDI endpoints (dynamic - ALSA ids shift with boot order),
    # surfaced in the header status line. {"name", "seq", "raw"}.
    snap["device"] = device_info()
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


@app.route("/api/tuning", methods=["GET", "POST"])
def api_tuning():
    """Ver 96 mono microtonal tuning. GET returns the table; POST body (any of):
      {"enabled": bool}                 -> retune on/off (off re-centers bend)
      {"preset": "equal|just|pythagorean|meantone|rast|bayati|saba|sikah|blues"}
      {"cents": [12 numbers ±100]}      -> custom table (marks preset "custom")
      {"master": cents ±50}             -> constant detune on every pitch
                                           class (mirrors the board's Tuning)
      {"base": Hz 400-480}              -> the board's OWN concert pitch
                                           (unreadable over MIDI); every Hz
                                           readout derives from it
      {"tonic_root": bool}              -> voice the table root-relative on
                                           the key card's tonic (off: on C)
    The table rides on every echoed note_on + replay strike as a pre-bend.
    """
    if request.method == "GET":
        return jsonify({"ok": True, "enabled": state.tuning_enabled,
                        "cents": list(state.tuning_cents),
                        "preset": state.tuning_preset,
                        "master": state.tuning_master,
                        "base": state.tuning_base,
                        "tonic_root": state.tuning_tonic_root,
                        "a4_hz": round(state.tuning_hz(69), 2)})
    body = request.get_json(silent=True) or {}
    if "preset" in body and body.get("preset") not in (
            "equal", "just", "pythagorean", "meantone", "rast", "bayati",
            "saba", "sikah", "blues"):
        return jsonify({"ok": False,
                        "error": "preset must be equal|just|pythagorean|meantone|rast|bayati|saba|sikah|slendro|blues"}), 400
    if "cents" in body:
        try:
            vals = [float(c) for c in body.get("cents")]
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "cents must be 12 numbers"}), 400
        if len(vals) != 12 or any(abs(v) > 100 for v in vals):
            return jsonify({"ok": False,
                            "error": "cents must be 12 numbers within ±100"}), 400
    if "master" in body:
        try:
            mst = float(body.get("master"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "master must be a number"}), 400
        if abs(mst) > 50:
            return jsonify({"ok": False,
                            "error": "master must be within ±50"}), 400
    if "base" in body:
        try:
            bse = float(body.get("base"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "base must be a number"}), 400
        if not (400 <= bse <= 480):
            return jsonify({"ok": False,
                            "error": "base must be 400-480 Hz"}), 400
    state.set_tuning(enabled=body.get("enabled", None),
                     cents=body.get("cents", None),
                     preset=body.get("preset", None),
                     master=body.get("master", None),
                     base=body.get("base", None),
                     tonic_root=body.get("tonic_root", None))
    if not state.tuning_enabled:
        # Leave no detune behind on the board.
        try:
            pitch_bend(0.0, channel=state.midi_channel)
        except Exception:
            pass
    return jsonify({"ok": True, "enabled": state.tuning_enabled,
                    "cents": list(state.tuning_cents),
                    "preset": state.tuning_preset,
                    "master": state.tuning_master,
                    "base": state.tuning_base,
                    "tonic_root": state.tuning_tonic_root,
                    "a4_hz": round(state.tuning_hz(69), 2)})


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


@app.route("/api/articulation", methods=["POST"])
def api_articulation():
    """Set the release-articulation stage: the fraction (0..0.9) of each
    note's slot left SILENT before the next attack. 0 = legato; releases are
    always clamped to the next onset so no note rings into its successor.
    Body: {"gap": <float 0..0.9>}.
    """
    body = request.get_json(silent=True) or {}
    try:
        gap = float(body.get("gap", state.articulation_gap))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "gap must be a number"}), 400
    if not (0.0 <= gap <= 0.9):
        return jsonify({"ok": False, "error": "gap must be between 0 and 0.9"}), 400
    state.set_articulation(gap)
    return jsonify({"ok": True, "gap": state.articulation_gap})


@app.route("/api/transform", methods=["POST"])
def api_transform():
    """Ver 92 transform-chain ops: scale-snap, melodic invert, reverse, and
    the echo-stream opt-ins. Body: {"op": <op>, ...}.

      {"op": "snap",    "enabled": bool}                or {"bias": "nearest|up|down"}
      {"op": "invert",  "enabled": bool}                or {"pivot": 0-127}
                                                         or {"auto": bool}
                                                         or {"mode": "chromatic|diatonic"}
      {"op": "reverse", "enabled": bool}
      {"op": "echo",    "which": "transpose|snap|invert|velocity|tuning", "enabled": bool}
    Setters requantize() where the take is affected (the echo opt-ins only
    switch the live echo path, so they skip the rebuild).
    """
    body = request.get_json(silent=True) or {}
    op = body.get("op")
    if op == "snap":
        if "enabled" in body:
            state.set_snap(enabled=bool(body.get("enabled")))
        if body.get("bias") in ("nearest", "up", "down"):
            state.set_snap(bias=body.get("bias"))
        return jsonify({"ok": True, "op": "snap", "enabled": state.snap_enabled,
                        "bias": state.snap_bias})
    if op == "invert":
        if "enabled" in body:
            state.set_invert(enabled=bool(body.get("enabled")))
        if "auto" in body:
            state.set_invert(auto=bool(body.get("auto")))
        if "pivot" in body:
            try:
                state.set_invert(pivot=int(body.get("pivot")))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "pivot must be 0-127"}), 400
        if "mode" in body and body.get("mode") in ("chromatic", "diatonic"):
            state.set_invert(mode=body.get("mode"))
        return jsonify({"ok": True, "op": "invert", "enabled": state.invert_enabled,
                        "pivot": state.invert_pivot,
                        "auto": state.invert_pivot_auto,
                        "mode": state.invert_mode})
    if op == "reverse":
        state.set_reverse(enabled=bool(body.get("enabled")))
        return jsonify({"ok": True, "op": "reverse", "enabled": state.reverse_enabled})
    if op == "echo":
        which = body.get("which")
        if which not in ("transpose", "snap", "invert", "velocity", "tuning"):
            return jsonify({"ok": False, "error": "which must be transpose|snap|invert|velocity|tuning"}), 400
        state.set_echo_transform(which=which, enabled=bool(body.get("enabled")))
        attr = {"transpose": "echo_transpose",
                "snap": "echo_snap",
                "invert": "echo_invert",
                "velocity": "echo_velocity",
                "tuning": "echo_tuning"}[which]
        return jsonify({"ok": True, "op": "echo", "which": which,
                        "enabled": getattr(state, attr)})
    return jsonify({"ok": False, "error": "op must be snap|invert|reverse|echo"}), 400


@app.route("/api/scale", methods=["POST"])
def api_scale():
    """Set the key context (tonic·scale card, server copy): the scale-snap
    stage + echo snap resolve pitches onto this selection. Body:
    {"tonic": -1..11, "scale": "<scale id>"}.
    An EMULATED scale id (rast/bayati/saba/sikah/slendro/blues) voices the tuning
    table root-relative too (follow-tonic + retune + echo on) so it sounds
    immediately; a plain 12-TET id leaves the tuning flags alone.
    """
    from .state import EMU_SCALES
    body = request.get_json(silent=True) or {}
    if "tonic" in body:
        try:
            tonic = int(body.get("tonic"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "tonic must be -1..11"}), 400
        if not (-1 <= tonic <= 11):
            return jsonify({"ok": False, "error": "tonic must be -1..11"}), 400
        state.set_scale_context(tonic=tonic)
    emulated = False
    if "scale" in body:
        sid = str(body.get("scale"))
        if sid in EMU_SCALES:
            state.select_emulated_scale(sid)
            emulated = True
        else:
            state.set_scale_context(scale=sid)
    resp = {"ok": True, "tonic": state.key_tonic,
            "scale": state.key_scale, "emulated": emulated}
    if emulated:
        resp["tuning"] = {"enabled": state.tuning_enabled,
                          "preset": state.tuning_preset,
                          "tonic_root": state.tuning_tonic_root,
                          "echo": state.echo_tuning,
                          "cents": list(state.tuning_cents)}
    return jsonify(resp)


@app.route("/api/ctrl", methods=["GET", "POST"])
def api_ctrl():
    """Out control surface to the keyboard (raw path hw:2,0,0).

    GET: return the last out-sent values plus whatever we've seen ARRIVE from
    the keyboard (received_ctrl / received_pitch_bend).

    POST body (any of):
      {"cc": int 0-127, "value": int 0-127}      -> send a controller change
      {"pitch": float ±range}                    -> 14-bit pitch bend (semis;
                                                   board range BEND_RANGE_ST)
      {"action": "panic"}   all channels all-sound-off + all-notes-off
      {"action": "gmreset"} GM System ON SysEx
      {"action": "local", "value": 0|1}          -> CC122 Local Control off/on
    """
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "device": bool(state.online),
            "out": dict(state.control_values),
            "out_pitch_bend": state.control_pitch_bend,
            "local_control": state.local_control,
            "received": dict(state.received_ctrl),
            "received_pitch_bend": state.received_pitch_bend,
        })
    body = request.get_json(silent=True) or {}
    ch = state.midi_channel
    sent = False
    try:
        if "cc" in body:
            cc = int(body["cc"])
            value = int(body["value"])
            if not (0 <= cc <= 127 and 0 <= value <= 127):
                return jsonify({"ok": False, "error": "cc/value must be 0-127"}), 400
            sent = control_change(cc, value, channel=ch)
            state.control_values[cc] = value
            if cc == 122:
                state.local_control = value
            extra = {"cc": cc, "value": value}
        elif "pitch" in body:
            semi = float(body["pitch"])
            if not (-BEND_RANGE_ST <= semi <= BEND_RANGE_ST):
                return jsonify({"ok": False, "error": "pitch must be ±%.1f" % BEND_RANGE_ST}), 400
            sent = pitch_bend(semi, channel=ch)
            state.control_pitch_bend = round(semi, 2)
            # The tuning skip-record must track EVERY bend on the channel
            # (slider, motion ramps, defaults all land here) or the next
            # strike wrongly concludes "already bent" and stays silent.
            state._tuning_last_bend[ch] = semi
            extra = {"pitch": state.control_pitch_bend}
        else:
            action = body.get("action")
            if action == "panic":
                sent = midi_panic()
                # Reset All Controllers re-centers the board's bend; drop the
                # tuning skip-record with it (same for GM reset below).
                state._tuning_last_bend = {}
                extra = {"action": "panic"}
            elif action == "gmreset":
                sent = gm_system_on()
                state._tuning_last_bend = {}
                state.control_values.pop(0, None)
                extra = {"action": "gmreset"}
            elif action == "local":
                value = int(body.get("value", 0))
                sent = control_change(122, value, channel=ch)
                state.local_control = value
                extra = {"local_control": value}
            else:
                return jsonify({"ok": False, "error": "nothing to do"}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "bad numeric field"}), 400
    resp = {"ok": True, "device": bool(sent), **extra}
    if not sent:
        # Keyboard detached (NORMAL): the intent is recorded anyway, but the
        # UI should know the line stayed silent.
        resp["warning"] = "keyboard offline - send dropped"
    return jsonify(resp)


@app.route("/api/echo", methods=["POST"])
def api_echo():
    """Live-echo mode: route keyed notes back to the keyboard as RX notes.
    Received notes are the only ones the keyboard lets program change / CC /
    pitch bend affect, so echoing makes those controls apply to live playing.

    Local Control is deliberately LEFT ALONE: with local ON you get a layered
    / chorused double (the panel voice + the echo voice); use the 'keys'
    segmented control to pick local/echo off for echo alone or MIDI-only.

    Body: {"enabled": bool, "voice": "auto"|name}
      voice = program to put the echo on (so it can differ from the panel
      voice for layering); "auto" leaves the keyboard's current voice.
    """
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", True))
    voice_name = body.get("voice", "auto")
    if not enabled:
        # Ring off every echoed note still sounding (pressed while echo was
        # live) — otherwise flipping echo off mid-hold strands the board's
        # RX voice until a panic.
        for rel in state.echo_release_all():
            note_off(rel["mapped"], channel=rel["channel"])
    state.echo_enabled = enabled
    state.echo_voice = voice_name
    device = True
    if enabled and voice_name and voice_name != "auto":
        bank_pc = _voice_to_bank_pc(voice_name)
        if bank_pc is not None:
            bank, pc = bank_pc
            state.receive_program = pc
            state.receive_bank = bank
            device = program_change(bank, pc)
    resp = {"ok": True, "enabled": enabled, "voice": voice_name,
            "device": bool(device)}
    if not device:
        resp["warning"] = "keyboard offline - echo set but no device"
    return jsonify(resp)


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



@app.route("/api/outs", methods=["GET"])
def api_outs_get():
    """List all available MIDI output destinations + the current routing."""
    return jsonify({
        "ok": True,
        "available": midiout.list_outs(),
        "seq_outs": list(state.seq_outs),
        "raw_outs": list(state.raw_outs),
        "channel": state.midi_channel,
    })


@app.route("/api/outs", methods=["POST"])
def api_outs_set():
    """Set where replay goes. Body: {seq_outs: ["131:0", ...],
    raw_outs: ["hw:2,0,0", ...], channel: int}.
    Both lists must be valid (unknown targets are dropped); channel clamped
    0..15. Replaying is stopped so a new routing applies cleanly."""
    body = request.get_json(silent=True) or {}
    if replayer.active:
        return jsonify({"ok": False, "error": "stop replay first"}), 409

    known = {o["target"] for o in midiout.list_outs()}
    seq = [str(t) for t in (body.get("seq_outs") or []) if str(t) in known]
    raw = []
    for dev in (body.get("raw_outs") or []):
        dev = str(dev).strip()
        if dev:
            raw.append(dev)
    try:
        chan = int(body.get("channel", state.midi_channel or 0)) & 0x0F
    except (TypeError, ValueError):
        chan = state.midi_channel
    state.seq_outs = seq
    state.raw_outs = raw
    state.midi_channel = chan
    replayer.set_outputs(seq, raw, channel=chan)
    return jsonify({"ok": True, "seq_outs": seq, "raw_outs": raw, "channel": chan})


@app.route("/api/sinks", methods=["GET"])
def api_sinks():
    """Registry of launchable MIDI destinations with live up/down state.
    The out box renders one launch button per entry."""
    return jsonify(sinks.status())


@app.route("/api/sinks/<key>/launch", methods=["POST"])
def api_sinks_launch(key):
    """Launch destination `key` (from the registry) if it isn't already up.
    Detached, in its own session, so it survives independent of the server."""
    ok, msg, running, launching = sinks.launch(key)
    if not ok:
        return jsonify({"ok": False, "error": msg, "running": running,
                        "launching": launching}), 500
    return jsonify({"ok": True, "key": key, "message": msg,
                    "running": running, "launching": launching})


# Backward-compatible aliases for the Ver 63 /api/vcv endpoints.
@app.route("/api/vcv", methods=["GET"])
def api_vcv():
    """Deprecated alias for /api/sinks filtered to the 'vcv' entry."""
    data = sinks.status()
    vcv = next((s for s in data["sinks"] if s["key"] == "vcv"), None)
    if vcv is None:
        return jsonify({"ok": False, "error": "vcv not in registry"}), 404
    return jsonify({"ok": True, "running": vcv["running"],
                    "cmd": os.path.basename(vcv.get("cmd") or ""),
                    "path": vcv.get("cmd")})


@app.route("/api/vcv/launch", methods=["POST"])
def api_vcv_launch():
    """Deprecated alias for /api/sinks/vcv/launch."""
    ok, msg, running, launching = sinks.launch("vcv")
    if not ok:
        return jsonify({"ok": False, "error": msg, "running": running,
                        "launching": launching}), 500
    return jsonify({"ok": True, "message": msg, "running": running,
                    "launching": launching})


@app.route("/api/replay", methods=["POST"])
def api_replay():
    """Play the current quantized take back out to every selected destination
    (keyboard raw device, VCV Rack, Midi Through, ...).

    Needs a non-empty take and at least one configured out. Runs in a
    background thread; progress is published on SSE ('replay' events) so the
    on-screen keys light up as notes sound. Replays the whole buffer at a
    user-selectable speed multiplier (default 1.0 = original timing).
    """
    body = request.get_json(silent=True) or {}
    err = _replay_start_guard()
    if err:
        return err
    # OUT side of the transform chain: re-derive the quantized take from the
    # raw buffer under current settings, then play the transformed MIDI.
    state.requantize()
    played = state.transformed_events[-500:]  # limit to last 500 events
    if not played:
        return jsonify({"ok": False, "error": "take is empty"}), 400
    return _play_events(played, body, loop=bool(body.get("loop", False)))


@app.route("/api/replay/loop", methods=["POST"])
def api_replay_loop():
    """Loop the current take until stopped. Equivalent to /api/replay with loop=True."""
    body = request.get_json(silent=True) or {}
    err = _replay_start_guard()
    if err:
        return err
    state.requantize()
    played = state.transformed_events[-500:]
    if not played:
        return jsonify({"ok": False, "error": "take is empty"}), 400
    return _play_events(played, body, loop=True)


def _replay_start_guard():
    """Shared gate for anything that plays through the shared replayer. Returns
    an error (jsonify, status) tuple when a replay is already running or there
    are no output destinations, else None."""
    if replayer.active:
        return jsonify({"ok": False, "error": "already replaying"}), 409
    if not state.seq_outs and not state.raw_outs:
        return jsonify({"ok": False, "error": "no output destinations"}), 400
    return None


def _play_events(events, body, loop, extra=None):
    """Fire `events` through the shared replayer at the request's speed+voice.
    Resolves the voice, updates the receive-voice state, publishes on SSE, and
    returns the {ok, notes, speed, voice, loop} response (plus any extra keys)."""
    body = body or {}
    try:
        speed = float(body.get("speed", 1.0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "speed must be a number"}), 400
    if speed <= 0:
        return jsonify({"ok": False, "error": "speed must be > 0"}), 400
    # Optional voice selection: send a program change before playback so the
    # keyboard uses the chosen voice instead of whatever it was last on.
    voice = _voice_to_bank_pc(body.get("voice", "auto"))
    # If a specific voice is selected, update the receive voice state.
    if voice is not None:
        state.receive_program = voice[1]
        state.receive_bank = voice[0]
    # Ver 96 mono tuning: the replayer pre-bends each strike batch when on.
    tuning_fn = state.tuning_cents_for if state.tuning_enabled else None
    replayer.play(events, speed=speed, on_event=hub.publish, voice=voice, loop=loop,
                  tuning=tuning_fn)
    count = sum(1 for e in events if e.get("type") == "note_on")
    resp = {"ok": True, "notes": count, "speed": speed,
            "voice": body.get("voice", "auto"), "loop": loop}
    if extra:
        resp.update(extra)
    return jsonify(resp)


@app.route("/api/replay/stop", methods=["POST"])
def api_replay_stop():
    """Cancel any in-flight replay and send all-notes-off (panic)."""
    replayer.stop()
    return jsonify({"ok": True, "active": replayer.active})


@app.route("/api/take", methods=["GET"])
def api_take():
    """Return the raw take events (semi-raw MIDI events) for piano roll display."""
    raw_events = getattr(state, "raw_take_events", [])
    out_events = getattr(state, "transformed_events", [])

    def _notes(evs):
        return sum(1 for e in evs if e.get("type") == "note_on")

    return jsonify({"ok": True, "raw_events": raw_events, "recording": state.recording,
                    "in_notes": _notes(raw_events), "out_notes": _notes(out_events)})


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
    """New empty buffer: stop any recording (an open pending note is
    discarded, not flushed) and wipe the take plus every derived buffer, so
    the next notes start from nothing instead of appending to the old take."""
    state.reset_take()
    return jsonify({"ok": True, "cleared": True, "recording": False})


@app.route("/api/patterns", methods=["GET"])
def api_patterns_list():
    """The pattern library: metadata for every saved buffer snapshot."""
    return jsonify({"ok": True, "patterns": patterns.list_patterns()})


@app.route("/api/patterns", methods=["POST"])
def api_patterns_save():
    """Save the current buffer as a named pattern. Body:
    {"name": <string>, "kind": "raw"|"out"}.

    kind "raw" snapshots the IN side (raw_take_events); "out" snapshots the
    OUT side (transformed_events — the take after quantize/transpose/
    velocity/humanize). Both are stored with the transform-chain settings so
    loading an OUT pattern replays exactly what was saved. Name is optional
    (an auto timestamp name is used when blank); the file slug is derived."""
    body = request.get_json(silent=True) or {}
    kind = body.get("kind", "raw")
    if kind == "out":
        # The OUT side is derived on demand (notation/replay); derive it from
        # the current buffer so an untouched take is still saveable.
        if not state.transformed_events:
            state.requantize()
        events = list(state.transformed_events)
    elif kind == "raw":
        events = list(state.raw_take_events)
    else:
        return jsonify({"ok": False, "error": "kind must be 'raw' or 'out'"}), 400
    if not events:
        return jsonify({"ok": False, "error": "buffer is empty — play something first"}), 400
    try:
        meta = patterns.save_pattern(body.get("name"), kind, events,
                                     state.settings_snapshot())
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    hub.publish({"type": "patterns", "action": "save",
                 "filename": meta["filename"], "name": meta["name"],
                 "kind": meta["kind"], "time": time.time()})
    return jsonify({"ok": True, "pattern": meta})


@app.route("/api/patterns/<slug>/load", methods=["POST"])
def api_patterns_load(slug):
    """Load a saved pattern into the raw buffer + chain settings.

    Events land in the raw take buffer (the two buffers share the same
    note_on/note_off shape) and the saved transform settings are restored, so
    an OUT snapshot replays true. The buffer is re-quantized and the notation
    card is rebuilt; the requesting client reloads the page to re-sync every
    control to the restored settings."""
    try:
        pat = patterns.load_pattern(slug)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    state.raw_take_events = pat["events"]
    state.apply_settings(pat["settings"])
    state.requantize()
    hub.publish({"type": "patterns", "action": "load",
                 "filename": slug, "name": pat["name"], "kind": pat["kind"],
                 "note_count": (pat["meta"] or {}).get("note_count", 0),
                 "time": time.time()})
    return jsonify({"ok": True, "name": pat["name"], "kind": pat["kind"],
                    "note_count": (pat["meta"] or {}).get("note_count", 0)})


@app.route("/api/patterns/<slug>/play", methods=["POST"])
def api_patterns_play(slug):
    """Play a stored pattern's OWN events straight out to the destinations via
    the shared replayer (raw path — original timing kept). Does NOT touch the
    buffer or chain settings, unlike load. Progress runs through the same SSE
    'replay'/'step' events, so the roll playhead and key lights follow along."""
    err = _replay_start_guard()
    if err:
        return err
    try:
        pat = patterns.load_pattern(slug)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    events = pat.get("events") or []
    if not events:
        return jsonify({"ok": False, "error": "pattern is empty"}), 400
    return _play_events(events, {"voice": "auto", "speed": 1.0, "loop": False},
                        loop=False, extra={"name": pat.get("name", slug)})


@app.route("/api/patterns/<slug>", methods=["DELETE"])
def api_patterns_delete(slug):
    if not patterns.delete_pattern(slug):
        return jsonify({"ok": False, "error": "no such pattern"}), 404
    # Never leave slots pointing at a deleted pattern: empty them and report.
    cleared = arrange.clear_pattern_slots(slug)
    hub.publish({"type": "patterns", "action": "delete",
                 "filename": slug, "cleared_slots": cleared,
                 "time": time.time()})
    return jsonify({"ok": True, "deleted": slug, "cleared_slots": cleared})


@app.route("/api/patterns/<slug>/bars", methods=["POST"])
def api_patterns_bars(slug):
    """Override a pattern's bar length (int), or clear with null/""."""
    body = request.get_json(silent=True) or {}
    bars, err = patterns.set_pattern_bars(slug, body.get("bars"))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    hub.publish({"type": "patterns", "action": "bars",
                 "filename": slug, "bars": bars, "time": time.time()})
    return jsonify({"ok": True, "filename": slug, "bars": bars})


def _slots_view():
    """64 slot dicts enriched for the UI (char, pattern name, bars)."""
    slots = arrange.load_slots(patterns.list_patterns())
    meta = {}
    for m in patterns.list_patterns():
        meta[m["filename"]] = m
    view = []
    for i, ch in enumerate(arrange.SLOT_ALPHABET):
        s = slots[i]
        m = meta.get(s["pattern"] or "")
        view.append({"index": i, "slot": ch, "pattern": s["pattern"],
                     "name": (m["name"] if m else None),
                     "transpose": s["transpose"], "voice": s["voice"],
                     "bars": (m["bars"] if m else None),
                     "bars_auto": (m["bars_auto"] if m else True)})
    return view


@app.route("/api/slots", methods=["GET"])
def api_slots_list():
    """The 64 arrangement slots (base64 addresses A-Z a-z 0-9 +/)."""
    return jsonify({"ok": True, "slots": _slots_view()})


@app.route("/api/slots/<int:index>", methods=["POST"])
def api_slots_set(index):
    """Assign a slot. Body: {"pattern": slug|null, "transpose": int,
    "voice": name|null}. Omitted keys keep their current values."""
    if not 0 <= index < 64:
        return jsonify({"ok": False, "error": "slot index out of range 0-63"}), 404
    body = request.get_json(silent=True) or {}
    slots = arrange.load_slots(patterns.list_patterns())
    cur = slots[index]
    pattern = body.get("pattern", cur["pattern"])
    if pattern is not None:
        pattern = str(pattern).strip() or None
    if pattern is not None:
        try:
            patterns.load_pattern(pattern)
        except ValueError:
            return jsonify({"ok": False,
                            "error": "no such pattern: %s" % pattern}), 400
    transpose = body.get("transpose", cur["transpose"])
    voice = body.get("voice", cur["voice"])
    if isinstance(voice, str):
        voice = voice.strip() or None
    if voice:
        if _voice_to_bank_pc(voice) is None:
            return jsonify({"ok": False,
                            "error": "unknown voice '%s'" % voice}), 400
    try:
        slot = arrange.set_slot(slots, index, pattern, transpose, voice)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    try:
        arrange.save_slots(slots)
    except (OSError, ValueError) as e:
        return jsonify({"ok": False, "error": "could not save slots: %s" % e}), 500
    hub.publish({"type": "slots", "action": "set", "index": index,
                 "slot": arrange.SLOT_ALPHABET[index], "time": time.time()})
    return jsonify({"ok": True, "index": index,
                    "slot": arrange.SLOT_ALPHABET[index], **slot})


@app.route("/api/arrangements", methods=["GET"])
def api_arrangements_list():
    """Saved arrangement strings (name -> text)."""
    return jsonify({"ok": True, "arrangements": arrange.list_arrangements()})


@app.route("/api/arrangements", methods=["POST"])
def api_arrangements_save():
    """Save an arrangement string. Body: {"name", "text"}."""
    body = request.get_json(silent=True) or {}
    try:
        meta = arrange.save_arrangement(body.get("name"), body.get("text", ""))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "arrangement": meta})


@app.route("/api/arrangements/<slug>", methods=["GET"])
def api_arrangements_get(slug):
    try:
        data = arrange.load_arrangement(slug)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    return jsonify({"ok": True, **data})


@app.route("/api/arrangements/<slug>", methods=["DELETE"])
def api_arrangements_delete(slug):
    if not arrange.delete_arrangement(slug):
        return jsonify({"ok": False, "error": "no such arrangement"}), 404
    return jsonify({"ok": True, "deleted": slug})


@app.route("/api/arrange/play", methods=["POST"])
def api_arrange_play():
    """Play an arrangement string through every selected destination.

    Body: {"text": "AABCCDAA", "tempo": <bpm, default current>, "loop": bool}.
    Each character is a base64 slot address (A-Z a-z 0-9 +/); whitespace and
    "|" are ignored. Slots are laid out on the bar grid at the arrangement
    tempo; per-slot transpose/voice come from the slot assignment. Uses the
    shared replayer, so /api/replay/stop stops it too.
    """
    if replayer.active:
        return jsonify({"ok": False, "error": "already replaying"}), 409
    if not state.seq_outs and not state.raw_outs:
        return jsonify({"ok": False, "error": "no output destinations"}), 400
    body = request.get_json(silent=True) or {}
    chars, err = arrange.parse_arrangement(body.get("text", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    try:
        tempo = float(body.get("tempo") or state.tempo_bpm or 120.0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "tempo must be a number"}), 400
    if tempo <= 0:
        return jsonify({"ok": False, "error": "tempo must be > 0"}), 400
    sig = state.time_signature or "4/4"
    slots = arrange.load_slots(patterns.list_patterns())

    def resolve(ch):
        i = arrange.slot_index(ch)
        s = slots[i]
        if not s.get("pattern"):
            raise ValueError("slot '%s' is empty — assign a pattern first" % ch)
        try:
            pat = patterns.load_pattern(s["pattern"])
        except ValueError:
            raise ValueError("slot '%s' points at a missing pattern" % ch)
        return {"pattern": {"events": pat["events"], "settings": pat["settings"],
                            "bars": pat.get("bars"), "name": pat["name"]},
                "transpose": s["transpose"], "voice": s["voice"]}

    try:
        built = arrange.build_arrangement(chars, resolve, tempo, sig,
                                          _voice_to_bank_pc)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if not built["events"]:
        return jsonify({"ok": False, "error": "arrangement is empty"}), 400
    loop = bool(body.get("loop", False))

    def on_event(ev):
        if ev.get("phase") == "voice":
            state.receive_program = ev.get("pc", state.receive_program)
            state.receive_bank = ev.get("bank", state.receive_bank)
        try:
            hub.publish(ev)
        except Exception:
            pass

    tuning_fn = state.tuning_cents_for if state.tuning_enabled else None
    replayer.play(built["events"], speed=1.0, on_event=on_event,
                  voice=None, loop=loop, tuning=tuning_fn)
    hub.publish({"type": "arrange", "action": "play", "slots": built["slots"],
                 "bars": built["total_bars"], "time": time.time()})
    return jsonify({"ok": True, "slots": built["slots"],
                    "bars": built["total_bars"],
                    "duration": built["duration"], "notes": built["notes"],
                    "tempo": tempo, "loop": loop})


@app.route("/api/events")
def events():
    q = hub.subscribe()
    def gen():
        yield "retry: 2000\n\n"
        while True:
            # Heartbeat so the connection stays alive. MUST be a real `data:`
            # event, not an SSE comment: the client's watchdog resets its timer
            # only in onmessage, and comments never fire onmessage, so a
            # `: keepalive` leaves the client thinking the stream is dead and
            # forcing a reconnect every esHeartbeatInterval whenever idle.
            try:
                item = q.get(timeout=15)
                yield f"data: {json.dumps(item)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
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
    # Normalize the keyboard on startup: echo defaults OFF and the UI defaults
    # to 'keys' mode, so make sure Local Control is ON. Otherwise a restart
    # that left local off (echo/midi mode) would leave the keys silent.
    # Fire-and-forget.
    threading.Thread(
        target=lambda: control_change(122, 127, channel=state.midi_channel),
        daemon=True).start()
    start_capture_thread()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
