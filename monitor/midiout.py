"""ALSA sequencer output for replaying takes to arbitrary destinations.

The PSS-A50 plays internal voices when MIDI is written to its raw device
(hw:2,0,0) via amidi, but THAT path bypasses the ALSA sequencer entirely, so
listeners on sequencer ports (VCV Rack, other apps) never hear playback.

This module opens its own sequencer OUTPUT client over libasound (via ctypes
so no pip packages are needed) and lets Replay address the same note events to
any combination of sequencer destinations. ALSA seq events carry an explicit
destination (client:port), so no aconnect subscriptions are required: we just
set the event's dest field and snd_seq_event_output_direct delivers it.
"""
import ctypes
import ctypes.util
import re
import subprocess

SND_SEQ_OPEN_OUTPUT = 1
SND_SEQ_QUEUE_DIRECT = 253  # direct/bounced events, no real queue

# Port capabilities (seqmid.h)
SND_SEQ_PORT_CAP_READ = 0x01      # readable input
SND_SEQ_PORT_CAP_SUBS_READ = 0x10  # subscribable for read
SND_SEQ_PORT_TYPE_MIDI_GENERIC = 1 << 1  # (seqmid.h)



class _SeqOutPort:
    """Minimal ALSA seq output client over libasound via ctypes."""

    def __init__(self, name="Abora Out"):
        self.handle = ctypes.c_void_p()
        rc = _LIB.snd_seq_open(ctypes.byref(self.handle), b"default",
                               SND_SEQ_OPEN_OUTPUT, 0)
        if rc != 0:
            raise RuntimeError("snd_seq_open failed (rc=%d)" % rc)
        rc = _LIB.snd_seq_set_client_pool_output(self.handle, 2048)
        if rc != 0:
            _LIB.snd_seq_close(self.handle)
            raise RuntimeError("snd_seq_set_client_pool_output failed (rc=%d)" % rc)
        rc = _LIB.snd_seq_set_client_pool_output_room(self.handle, 1024)
        if rc != 0:
            _LIB.snd_seq_close(self.handle)
            raise RuntimeError("snd_seq_set_client_pool_output_room failed (rc=%d)" % rc)
        caps = SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ
        self.port_id = _LIB.snd_seq_create_simple_port(
            self.handle, name.encode(), caps, SND_SEQ_PORT_TYPE_MIDI_GENERIC)
        if self.port_id < 0:
            _LIB.snd_seq_close(self.handle)
            raise RuntimeError("snd_seq_create_simple_port failed (rc=%d)" % self.port_id)
        self.client_id = _LIB.snd_seq_client_id(self.handle)

# Event types (seq_event.h)
SND_SEQ_EVENT_CONTROLLER = 10
SND_SEQ_EVENT_PGMCHANGE = 11
SND_SEQ_EVENT_NOTEON = 6
SND_SEQ_EVENT_NOTEOFF = 7

# MIDI controller numbers
CC_ALL_SOUND_OFF = 120
CC_ALL_NOTES_OFF = 123


class _SeqAddr(ctypes.Structure):
    _fields_ = [("client", ctypes.c_ubyte), ("port", ctypes.c_ubyte)]


class _SeqRealTime(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_uint32), ("tv_nsec", ctypes.c_uint32)]


class _SeqTime(ctypes.Union):
    _fields_ = [("tick", ctypes.c_uint32), ("time", _SeqRealTime)]


class _SeqNote(ctypes.Structure):
    _fields_ = [
        ("channel", ctypes.c_ubyte),
        ("note", ctypes.c_ubyte),
        ("velocity", ctypes.c_ubyte),
        ("off_velocity", ctypes.c_ubyte),
        ("duration", ctypes.c_uint32),
    ]


class _SeqCtrl(ctypes.Structure):
    _fields_ = [
        ("channel", ctypes.c_ubyte),
        ("unused", ctypes.c_ubyte * 3),
        ("param", ctypes.c_uint32),
        ("value", ctypes.c_int32),
    ]


class _SeqData(ctypes.Union):
    _fields_ = [
        ("note", _SeqNote),
        ("control", _SeqCtrl),
        ("raw", ctypes.c_ubyte * 64),  # pad the union to a safe size
    ]


class _SeqEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ubyte),    # snd_seq_event_type_t is 1 byte (uapi)
        ("flags", ctypes.c_ubyte),
        ("tag", ctypes.c_char),
        ("queue", ctypes.c_ubyte),
        ("time", _SeqTime),
        ("source", _SeqAddr),
        ("dest", _SeqAddr),
        ("data", _SeqData),
    ]


SND_SEQ_ADDRESS_UNKNOWN = (1 << 8) | 255  # client=0, port=255 -> 0x00FF


def _load():
    lib = ctypes.CDLL(ctypes.util.find_library("asound") or "libasound.so.2")

    f = lib.snd_seq_open
    f.restype = ctypes.c_int
    f.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p,
                  ctypes.c_int, ctypes.c_int]

    f = lib.snd_seq_close
    f.restype = ctypes.c_int
    f.argtypes = [ctypes.c_void_p]

    f = lib.snd_seq_client_id
    f.restype = ctypes.c_int
    f.argtypes = [ctypes.c_void_p]

    f = lib.snd_seq_create_simple_port
    f.restype = ctypes.c_int
    f.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint]

    f = lib.snd_seq_event_output
    f.restype = ctypes.c_int
    f.argtypes = [ctypes.c_void_p, ctypes.POINTER(_SeqEvent)]

    f = lib.snd_seq_drain_output
    f.restype = ctypes.c_int
    f.argtypes = [ctypes.c_void_p]

    f = lib.snd_seq_set_client_pool_output
    f.restype = ctypes.c_int
    f.argtypes = [ctypes.c_void_p, ctypes.c_size_t]

    f = lib.snd_seq_set_client_pool_output_room
    f.restype = ctypes.c_int
    f.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    return lib


_LIB = _load()


def list_outs():
    """Enumerate available ALSA sequencer output destinations via aconnect.

    Returns a list of dicts: {client, port, name, target}. target is the
    "client:port" string used for routing (e.g. "131:0" = VCV Rack input).
    The keyboard's seq port (24:0) also appears here so it can be used as a
    destination instead of (or alongside) the raw amidi path.
    """
    try:
        out = subprocess.run(["aconnect", "-o"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    outs = []
    cur = None
    for line in out.splitlines():
        m = re.match(r"^\s*client\s+(\d+):\s*'(.*?)'", line)
        if m:
            cur = {"client": int(m.group(1)), "name": m.group(2).strip()}
            continue
        m = re.match(r"^\s+(\d+)\s+'(.*?)'\s*$", line)
        if m and cur is not None:
            port = int(m.group(1))
            pname = m.group(2).strip()
            outs.append({
                "client": cur["client"],
                "port": port,
                "name": cur["name"],
                "port_name": pname,
                "target": "%d:%d" % (cur["client"], port),
            })
    return outs


def parse_target(target):
    """Turn 'client:port' into (client, port)."""
    c, _, p = str(target).partition(":")
    return int(c), int(p)


def _make_event(evtype):
    ev = _SeqEvent()
    ctypes.memset(ctypes.byref(ev), 0, ctypes.sizeof(ev))
    ev.type = evtype
    ev.flags = 0
    ev.tag = b" "
    ev.queue = SND_SEQ_QUEUE_DIRECT
    ev.time.tick = 0
    ev.source.client = 0
    ev.source.port = 255  # SND_SEQ_ADDRESS_UNKNOWN -> kernel fills our client
    return ev


class SeqOut(_SeqOutPort):
    """A throwaway ALSA seq output client that sends to explicit addresses."""

    def __init__(self, name="Abora Out"):
        super().__init__(name)

    def close(self):
        try:
            self.flush()
        except Exception:
            pass
        if self.handle.value:
            _LIB.snd_seq_close(self.handle)
            self.handle.value = 0

    def _source_event(self, evtype):
        ev = _make_event(evtype)
        ev.source.client = self.client_id & 0xFF
        ev.source.port = self.port_id & 0xFF
        return ev

    def _emit(self, ev):
        rc = _LIB.snd_seq_event_output(self.handle, ctypes.byref(ev))
        if rc < 0:
            raise RuntimeError("snd_seq_event_output failed (rc=%d)" % rc)

    def flush(self):
        _LIB.snd_seq_drain_output(self.handle)

    def send_notes(self, target, kind, pairs, channel=0):
        """Send note on/off for [(note, velocity), ...] to one seq target."""
        evtype = SND_SEQ_EVENT_NOTEON if kind == "on" else SND_SEQ_EVENT_NOTEOFF
        dst_c, dst_p = parse_target(target)
        for note, vel in pairs:
            vel = max(1, min(127, int(vel)))
            ev = self._source_event(evtype)
            ev.dest.client = dst_c & 0xFF
            ev.dest.port = dst_p & 0xFF
            ev.data.note.channel = channel & 0x0F
            ev.data.note.note = note
            ev.data.note.velocity = vel
            ev.data.note.off_velocity = 0
            ev.data.note.duration = 0
            self._emit(ev)

    def send_cc(self, target, cc, value, channel=0):
        dst_c, dst_p = parse_target(target)
        ev = self._source_event(SND_SEQ_EVENT_CONTROLLER)
        ev.dest.client = dst_c & 0xFF
        ev.dest.port = dst_p & 0xFF
        ev.data.control.channel = channel & 0x0F
        ev.data.control.param = cc
        ev.data.control.value = value
        self._emit(ev)

    def send_program_change(self, target, bank, pc, channel=0):
        self.send_cc(target, 0, bank, channel=channel)
        dst_c, dst_p = parse_target(target)
        ev = self._source_event(SND_SEQ_EVENT_PGMCHANGE)
        ev.dest.client = dst_c & 0xFF
        ev.dest.port = dst_p & 0xFF
        ev.data.control.channel = channel & 0x0F
        ev.data.control.param = 0
        ev.data.control.value = pc
        self._emit(ev)

    def all_notes_off(self, targets, channel=0):
        for t in targets:
            try:
                self.send_cc(t, CC_ALL_NOTES_OFF, 0, channel=channel)
                self.send_cc(t, CC_ALL_SOUND_OFF, 0, channel=channel)
            except Exception:
                pass
        try:
            self.flush()
        except Exception:
            pass