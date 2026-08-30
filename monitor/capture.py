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

    # Yamaha PSS-A50 voice list, keyed by (bank select MSB, program) -> name.
    # The PSS-A50 is NOT full GM: it has exactly 42 presets (40 normal voices +
    # 2 drum kits). Normal voices use GM1-compatible program numbers (Bank MSB 0);
    # the two drum kits use XG/XGlite numbering with Bank MSB 127 (Standard Kit,
    # Dance Kit). Program bytes below are 0-indexed (the Owner's Manual lists
    # 1-128; subtract 1). Source: PSS-A50 Owner's Manual "Voice List".
    VOICE_BY_PROGRAM = {
        (0, 0): "Grand Piano",          # voice 1  (PC 1  -> 0)
        (0, 4): "Electric Piano 1",     # voice 2  (PC 5  -> 4)
        (0, 5): "Electric Piano 2",     # voice 3  (PC 6  -> 5)
        (0, 2): "Electric Grand Piano", # voice 4  (PC 3  -> 2)
        (0, 16): "Drawbar Organ",       # voice 5  (PC 17 -> 16)
        (0, 18): "Rock Organ",          # voice 6  (PC 19 -> 18)
        (0, 21): "Accordion",           # voice 7  (PC 22 -> 21)
        (0, 22): "Harmonica",           # voice 8  (PC 23 -> 22)
        (0, 24): "Nylon Guitar",        # voice 9  (PC 25 -> 24)
        (0, 25): "Steel Guitar",        # voice 10 (PC 26 -> 25)
        (0, 26): "Jazz Guitar",         # voice 11 (PC 27 -> 26)
        (0, 27): "Clean Guitar",        # voice 12 (PC 28 -> 27)
        (0, 29): "Overdriven Guitar",   # voice 13 (PC 30 -> 29)
        (0, 32): "Acoustic Bass",       # voice 14 (PC 33 -> 32)
        (0, 33): "Finger Bass",         # voice 15 (PC 34 -> 33)
        (0, 36): "Slap Bass",           # voice 16 (PC 37 -> 36)
        (0, 38): "Synth Bass",          # voice 17 (PC 39 -> 38)
        (0, 48): "Strings",             # voice 18 (PC 49 -> 48)
        (0, 45): "Pizzicato Strings",   # voice 19 (PC 46 -> 45)
        (0, 40): "Violin",              # voice 20 (PC 41 -> 40)
        (0, 42): "Cello",               # voice 21 (PC 43 -> 42)
        (0, 46): "Orchestral Harp",     # voice 22 (PC 47 -> 46)
        (0, 68): "Oboe",                # voice 23 (PC 69 -> 68)
        (0, 71): "Clarinet",            # voice 24 (PC 72 -> 71)
        (0, 73): "Flute",               # voice 25 (PC 74 -> 73)
        (0, 66): "Tenor Sax",           # voice 26 (PC 67 -> 66)
        (0, 61): "Brass Section",       # voice 27 (PC 62 -> 61)
        (0, 56): "Trumpet",             # voice 28 (PC 57 -> 56)
        (0, 57): "Trombone",            # voice 29 (PC 58 -> 57)
        (0, 60): "French Horn",         # voice 30 (PC 61 -> 60)
        (0, 62): "Synth Brass",         # voice 31 (PC 63 -> 62)
        (0, 82): "Gemini",              # voice 32 (PC 83 -> 82)  <- the "fat supersaw"
        (0, 84): "Punchy Chordz",       # voice 33 (PC 85 -> 84)
        (0, 80): "Square Lead",         # voice 34 (PC 81 -> 80)
        (0, 81): "Sawtooth Lead",       # voice 35 (PC 82 -> 81)
        (0, 88): "New Age Pad",         # voice 36 (PC 89 -> 88)
        (0, 89): "Warm Pad",            # voice 37 (PC 90 -> 89)
        (0, 100): "Brightness",         # voice 38 (PC 101 -> 100)
        (127, 0): "Standard Kit",       # voice 39 (MSB 127, PC 1  -> 0)
        (127, 27): "Dance Kit",         # voice 40 (MSB 127, PC 28 -> 27)
        (0, 11): "Vibraphone",          # voice 41 (PC 12 -> 11)
        (0, 12): "Marimba",             # voice 42 (PC 13 -> 12)
    }

    # Kept for backward compatibility: program -> name for bank 0 (normal voices).
    GM_PROGRAMS = {pc: name for (bank, pc), name in VOICE_BY_PROGRAM.items() if bank == 0}

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
        self._bank = 0     # current bank select MSB (0 = normal, 127 = drums)

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
        """Return the PSS-A50 voice name for the current (bank, program)."""
        return self.VOICE_BY_PROGRAM.get((self._bank, self._program), "Unknown")

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
                controller = int(cc.group(2))
                value = int(cc.group(3))
                # Track Bank Select MSB (CC#0): 0 = normal voices, 127 = drums.
                if controller == 0:
                    self._bank = value
                yield {
                    "type": "control_change",
                    "controller": controller,
                    "value": value,
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
                    "bank": self._bank,
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