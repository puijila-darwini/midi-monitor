"""Capture layer: owns the aseqdump subprocess and yields parsed MIDI events.

Survives keyboard disconnects by monitoring the subprocess and attempting
auto-reconnect whenever the raw stream dies or fails to start. When there
is no keyboard, events gracefully yield an explicit "offline" state.
"""
import re
import subprocess
import time

PORT = "24:0"

_NOTE_ON = re.compile(r"Note on\s+(\d+),\s*note (\d+),\s*velocity (\d+)")
_NOTE_OFF = re.compile(r"Note off\s+(\d+),\s*note (\d+)")
_KEY_PRESSURE = re.compile(r"Key pressure\s+(\d+),\s*note (\d+),\s*pressure (\d+)")
_CTRL_CHANGE = re.compile(r"Control change\s+(\d+),\s*controller (\d+),\s*value (\d+)")
_PGM_CHANGE = re.compile(r"P(?:rogram|gm) change\s+(\d+),\s*program (\d+)")
_CHAN_PRESSURE = re.compile(r"Channel pressure\s+(\d+),\s*pressure (\d+)")
_PITCH_BEND = re.compile(r"Pitch bend\s+(\d+),\s*value (\d+)")
_PITCH_BEND_OLD = re.compile(r"Pitch bend\s+(\d+),\s*value (\d+),\s*(\d+)")
_SYSEX = re.compile(r"System exclusive\s+(\d+),\s*data (.+)")
_SONG_POS = re.compile(r"Song position\s+(\d+),\s*position (\d+)")
_SONG_SEL = re.compile(r"Song select\s+(\d+),\s*song (\d+)")
_TIME_CODE = re.compile(r"Time code\s+(\d+),\s*data (.+)")
_TIME_SIG = re.compile(r"Time signature\s+(\d+),\s*(\d+)/(\d+),\s*(\d+),\s*(\d+)")
_KEY_SIG = re.compile(r"Key signature\s+(\d+),\s*([^,]+),\s*([^,]+)")
_START = re.compile(r"Start\s+(\d+)")
_CONTINUE = re.compile(r"Continue\s+(\d+)")
_STOP = re.compile(r"Stop\s+(\d+)")
_CLOCK = re.compile(r"Clock\s+(\d+)")
_TICK = re.compile(r"Tick\s+(\d+)")
_SENSING = re.compile(r"Active sensing\s+(\d+)")
_RESET = re.compile(r"System reset\s+(\d+)")

RECONNECT_DELAY = 1.0


def _spawn(port):
    return subprocess.Popen(
        ["aseqdump", "-p", port],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _running(proc):
    return proc is not None and proc.poll() is None


class Capture:
    """Continuously parses aseqdump output into MIDI events.

    Events are plain dicts:
        {"type": "note_on",  "note": int, "velocity": int, "time": float}
        {"type": "note_off", "note": int, "time": float}
        {"type": "key_pressure", "note": int, "pressure": int, "time": float}
        {"type": "control_change", "controller": int, "value": int, "channel": int, "time": float}
        {"type": "program_change", "program": int, "channel": int, "time": float}
        {"type": "channel_pressure", "pressure": int, "channel": int, "time": float}
        {"type": "pitch_bend", "value": int, "channel": int, "time": float}
        {"type": "sysex", "data": str, "time": float}
        {"type": "song_position", "position": int, "time": float}
        {"type": "song_select", "song": int, "time": float}
        {"type": "time_code", "data": str, "time": float}
        {"type": "time_signature", "numerator": int, "denominator": int, "metronome": int, "thirtyseconds": int, "time": float}
        {"type": "key_signature", "sf": str, "mi": str, "time": float}
        {"type": "start", "time": float}
        {"type": "continue", "time": float}
        {"type": "stop", "time": float}
        {"type": "clock", "time": float}
        {"type": "tick", "time": float}
        {"type": "active_sensing", "time": float}
        {"type": "system_reset", "time": float}
        {"type": "offline",  "time": float}
        {"type": "online",   "time": float}
    """

    # Yamaha PSS-A50 voice names (program 0-41).
    # The PSS-A50 is NOT full GM: it has exactly 42 presets (40 normal voices + 2
    # drum kits). Voice #N (1-indexed, per the manual) = MIDI program N-1 (0-indexed).
    # Program 38 = Standard Kit, 39 = Dance Kit. Beyond 41 nothing is defined.
    GM_PROGRAMS = [
        "Grand Piano", "Electric Piano 1", "Electric Piano 2", "Electric Grand Piano",
        "Drawbar Organ", "Rock Organ", "Accordion", "Harmonica",
        "Nylon Guitar", "Steel Guitar", "Jazz Guitar", "Clean Guitar",
        "Overdriven Guitar", "Acoustic Bass", "Finger Bass",
        "Slap Bass", "Synth Bass", "Strings", "Pizzicato Strings",
        "Violin", "Cello", "Orchestral Harp", "Oboe",
        "Clarinet", "Flute", "Tenor Sax", "Brass Section",
        "Trumpet", "Trombone", "French Horn", "Synth Brass",
        "Gemini", "Punchy Chordz", "Square Lead", "Sawtooth Lead",
        "New Age Pad", "Warm Pad", "Brightness", "Standard Kit",
        "Dance Kit", "Vibraphone", "Marimba",
    ]

    # Common CC names for readability
    CC_NAMES = {
        0: "Bank Select MSB", 1: "Modulation Wheel", 2: "Breath Controller",
        4: "Foot Controller", 5: "Portamento Time", 6: "Data Entry MSB", 7: "Channel Volume",
        8: "Balance", 10: "Pan", 11: "Expression Controller", 12: "Effect Control 1",
        13: "Effect Control 2", 16: "General Purpose Controller 1", 17: "General Purpose Controller 2",
        18: "General Purpose Controller 3", 19: "General Purpose Controller 4",
        32: "Bank Select LSB", 33: "Modulation Wheel LSB", 34: "Breath Controller LSB",
        36: "Foot Controller LSB", 37: "Portamento Time LSB", 38: "Data Entry LSB", 39: "Channel Volume LSB",
        40: "Balance LSB", 42: "Pan LSB", 43: "Expression LSB",
        64: "Sustain Pedal", 65: "Portamento On/Off", 66: "Sostenuto", 67: "Soft Pedal",
        68: "Legato Footswitch", 69: "Hold 2", 70: "Sound Variation", 71: "Timbre/Harmonic Intensity",
        72: "Release Time", 73: "Attack Time", 74: "Brightness", 75: "Sound Controller 6",
        76: "Sound Controller 7", 77: "Sound Controller 8", 78: "Sound Controller 9", 79: "Sound Controller 10",
        80: "General Purpose Controller 5", 81: "General Purpose Controller 6",
        82: "General Purpose Controller 7", 83: "General Purpose Controller 8",
        84: "Portamento Control", 91: "Effects 1 Depth", 92: "Effects 2 Depth",
        93: "Effects 3 Depth", 94: "Effects 4 Depth", 95: "Effects 5 Depth",
        96: "Data Increment", 97: "Data Decrement",
        98: "NRPN LSB", 99: "NRPN MSB", 100: "RPN LSB", 101: "RPN MSB",
        120: "All Sound Off", 121: "Reset All Controllers", 122: "Local Control",
        123: "All Notes Off", 124: "Omni Mode Off", 125: "Omni Mode On", 126: "Mono Mode On", 127: "Poly Mode On",
    }

    def __init__(self, port=PORT, reconnect_delay=RECONNECT_DELAY):
        self.port = port
        self.reconnect_delay = reconnect_delay
        self._proc = None
        self._start = time.time()
        self._online = False
        self._program = 0  # current program number (0-127)

    def _now(self):
        return time.time() - self._start

    def _ensure_online(self):
        if _running(self._proc):
            if not self._online:
                self._online = True
                self.on_state_change(True)
            return True
        if self._proc is not None:
            # previous stream died
            try:
                self._proc.wait(timeout=0.5)
            except Exception:
                self._proc.kill()
            self._proc = None
            if self._online:
                self._online = False
                self.on_state_change(False)
        try:
            self._proc = _spawn(self.port)
            # give it a moment to error out on a missing port
            time.sleep(0.2)
            if not _running(self._proc):
                self._proc = None
                return False
            self._online = True
            self.on_state_change(True)
            return True
        except Exception:
            self._proc = None
            return False

    def on_state_change(self, online):
        """Hook for subclasses: called when connectivity toggles."""

    def _now(self):
        return time.time() - self._start

    def get_program(self):
        """Return current program number (0-127)."""
        return self._program

    def get_program_name(self):
        """Return the PSS-A50 voice name for the current program (0-41)."""
        if 0 <= self._program < len(self.GM_PROGRAMS):
            return self.GM_PROGRAMS[self._program]
        return "Unknown"

    def __iter__(self):
        self._reported_online = False
        while True:
            self._ensure_online()
            if not _running(self._proc):
                # keyboard unavailable
                yield {"type": "offline", "time": self._now()}
                time.sleep(self.reconnect_delay)
                continue
            if not self._reported_online:
                self._reported_online = True
                yield {"type": "online", "time": self._now()}
            line = self._proc.stdout.readline()
            if not line:
                # stream ended (keyboard detached / aseqdump quit)
                continue
            now = self._now()
            m = _NOTE_ON.search(line)
            if m:
                yield {
                    "type": "note_on",
                    "note": int(m.group(2)),
                    "velocity": int(m.group(3)),
                    "channel": int(m.group(1)),
                    "time": now,
                }
                continue
            mo = _NOTE_OFF.search(line)
            if mo:
                yield {
                    "type": "note_off",
                    "note": int(mo.group(2)),
                    "channel": int(mo.group(1)),
                    "time": now,
                }
                continue
            kp = _KEY_PRESSURE.search(line)
            if kp:
                yield {
                    "type": "key_pressure",
                    "note": int(kp.group(2)),
                    "pressure": int(kp.group(3)),
                    "time": now,
                }
                continue
            cc = _CTRL_CHANGE.search(line)
            if cc:
                yield {
                    "type": "control_change",
                    "controller": int(cc.group(2)),
                    "value": int(cc.group(3)),
                    "channel": int(cc.group(1)),
                    "time": now,
                }
                continue
            pc = _PGM_CHANGE.search(line)
            if pc:
                self._program = int(pc.group(2))
                yield {
                    "type": "program_change",
                    "program": self._program,
                    "channel": int(pc.group(1)),
                    "time": now,
                }
                continue
            cp = _CHAN_PRESSURE.search(line)
            if cp:
                yield {
                    "type": "channel_pressure",
                    "pressure": int(cp.group(2)),
                    "channel": int(cp.group(1)),
                    "time": now,
                }
                continue
            pb = _PITCH_BEND.search(line)
            if pb:
                yield {
                    "type": "pitch_bend",
                    "value": int(pb.group(2)),
                    "channel": int(pb.group(1)),
                    "time": now,
                }
                continue
            # Try old pitch bend format
            pb2 = _PITCH_BEND_OLD.search(line)
            if pb2:
                yield {
                    "type": "pitch_bend",
                    "value": int(pb2.group(2)),
                    "channel": int(pb2.group(1)),
                    "time": now,
                }
                continue
            sx = _SYSEX.search(line)
            if sx:
                yield {
                    "type": "sysex",
                    "data": sx.group(2).strip(),
                    "time": now,
                }
                continue
            sp = _SONG_POS.search(line)
            if sp:
                yield {
                    "type": "song_position",
                    "position": int(sp.group(2)),
                    "time": now,
                }
                continue
            ss = _SONG_SEL.search(line)
            if ss:
                yield {
                    "type": "song_select",
                    "song": int(ss.group(2)),
                    "time": now,
                }
                continue
            tc = _TIME_CODE.search(line)
            if tc:
                yield {
                    "type": "time_code",
                    "data": tc.group(2).strip(),
                    "time": now,
                }
                continue
            ts = _TIME_SIG.search(line)
            if ts:
                yield {
                    "type": "time_signature",
                    "numerator": int(ts.group(2)),
                    "denominator": int(ts.group(3)),
                    "metronome": int(ts.group(4)),
                    "thirtyseconds": int(ts.group(5)),
                    "time": now,
                }
                continue
            ks = _KEY_SIG.search(line)
            if ks:
                yield {
                    "type": "key_signature",
                    "sf": ks.group(2).strip(),
                    "mi": ks.group(3).strip(),
                    "time": now,
                }
                continue
            st = _START.search(line)
            if st:
                yield {"type": "start", "time": now}
                continue
            co = _CONTINUE.search(line)
            if co:
                yield {"type": "continue", "time": now}
                continue
            sp2 = _STOP.search(line)
            if sp2:
                yield {"type": "stop", "time": now}
                continue
            cl = _CLOCK.search(line)
            if cl:
                yield {"type": "clock", "time": now}
                continue
            tk = _TICK.search(line)
            if tk:
                yield {"type": "tick", "time": now}
                continue
            sa = _SENSING.search(line)
            if sa:
                yield {"type": "active_sensing", "time": now}
                continue
            rs = _RESET.search(line)
            if rs:
                yield {"type": "system_reset", "time": now}
                continue