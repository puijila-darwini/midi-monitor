"""Flask web app serving the live keyboard monitor on :5050."""
import itertools
import json
import queue
import threading
import time
import traceback

from flask import Flask, jsonify, render_template, Response

from .capture import Capture
from .state import State
from .analysis import Analyser
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


def _note_name(n):
    return chords.nm(n)


def _run_capture():
    """Background: read MIDI, update state + analyser, publish to hub."""
    for event in Capture():
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
            # Send quantized note data if available
            if state.quantized_notes:
                qn = state.quantized_notes[-1]
                hub.publish({"type": "quantized_note", "note": qn["note"],
                             "on_time": qn["on_time"], "off_time": qn["off_time"],
                             "duration": qn["duration"], "velocity": qn["velocity"],
                             "tempo": state.tempo_bpm})
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    snap = state.snapshot()
    snap["capture"] = capture_health_snapshot()
    return jsonify(snap)


@app.route("/api/key/reset", methods=["POST"])
def api_key_reset():
    analyser.reset_key()
    return jsonify({"ok": True})


@app.route("/events")
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


def capture_health_snapshot():
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
            _run_capture()
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
