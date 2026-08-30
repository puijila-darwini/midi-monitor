"""Flask web app serving the live keyboard monitor on :5050."""
import itertools
import queue
import threading
import time

from flask import Flask, jsonify, render_template, Response

from .capture import Capture
from .state import State
from .analysis import Analyser
from . import chords

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

PORT = 5050
FULL_KEYBOARD = False


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
                         "channel": event["channel"], "name": Capture.GM_PROGRAMS[event["program"]] if event["program"] < len(Capture.GM_PROGRAMS) else "Unknown", "time": t})
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
    return jsonify(state.snapshot())


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
                yield f"data: {__import__('json').dumps(item)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    resp = Response(gen(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


def start_capture_thread():
    t = threading.Thread(target=_run_capture, daemon=True)
    t.start()


def main():
    start_capture_thread()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
