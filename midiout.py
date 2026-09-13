#!/usr/bin/env python3
"""Send MIDI back to the PSS-A50 over the raw device (hw:2,0,0 via amidi).

The keyboard plays its INTERNAL voices on received MIDI. There is no ALSA seq
output port for this device, so everything goes over the raw MIDI device.

Usage:
  python3 midiout.py voices                      list the 42 voice names
  python3 midiout.py voice "Gemini"              program change only
  python3 midiout.py note C4 [vel] [dur_sec]     single note (default vel 100, dur 1.0)
  python3 midiout.py chord "C4 E4 G4" [vel] [dur_sec]
  python3 midiout.py seq "C4 E4 G4 C5" [vel]     melody, one note per beat (bpm option)
  python3 midiout.py seq-file TAKE.txt [vel]     lines: "C4 0.5" / rest "r 0.25" / blank
  python3 midiout.py alloff                     panic: CC 123 all notes off

Options: --bpm N (default 120), --port hw:2,0,0
Note names: C4 D#4 Bb3 ... (sharp or flat, any octave 0-8). Drums use GM
numbers: kick=36 B2, snare=38 D3, hat=42 F#3.
"""

import argparse
import re
import subprocess
import sys
import time

DEVICE = "hw:2,0,0"

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

_PC_RE = re.compile(r"^([A-G])([#b]?)(-?\d)$")
_SCALE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ACC = {"": 0, "#": 1, "b": -1}


def note_to_midi(name):
    m = _PC_RE.match(name.strip())
    if not m:
        raise ValueError("bad note name: %r" % name)
    letter, acc, octv = m.group(1), m.group(2), int(m.group(3))
    return (octv + 1) * 12 + _SCALE[letter] + _ACC[acc]


def send(port, hexstr):
    subprocess.run(["amidi", "-p", port, "-S", hexstr], check=True)


def program_change(port, bank, pc):
    send(port, "B0 00 %02X" % bank)
    time.sleep(0.02)
    send(port, "C0 %02X" % pc)


def note_onoff(port, midi, vel, dur):
    send(port, "90 %02X %02X" % (midi % 128, vel))
    time.sleep(dur)
    send(port, "80 %02X 40" % (midi % 128))


def look_up_voice(name):
    name = name.strip().lower()
    for (bank, pc), vname in VOICES.items():
        if vname.lower() == name:
            return bank, pc
    for (bank, pc), vname in VOICES.items():
        if name in vname.lower():
            print("voice: matched %r -> %s" % (name, vname))
            return bank, pc
    try:
        pc = int(name)
    except ValueError:
        raise SystemExit("unknown voice: %r (see 'voices')" % name)
    bank = 127 if pc in (0, 27) else 0
    return bank, pc


def do_note(args):
    midi = note_to_midi(args.rest[1])
    vel = int(args.rest[2]) if len(args.rest) > 2 else 100
    dur = float(args.rest[3]) if len(args.rest) > 3 else 1.0
    note_onoff(args.port, midi, vel, dur)


def do_chord(args):
    notes = [note_to_midi(n) for n in args.rest[1].split()]
    vel = int(args.rest[2]) if len(args.rest) > 2 else 100
    dur = float(args.rest[3]) if len(args.rest) > 3 else 1.2
    ons = "90 " + " ".join("%02X %02X" % (n % 128, vel) for n in notes)
    offs = "80 " + " ".join("%02X 40" % (n % 128) for n in notes)
    send(args.port, ons)
    time.sleep(dur)
    send(args.port, offs)


def do_seq(args):
    notes = [note_to_midi(n) for n in args.rest[1].split()]
    vel = int(args.rest[2]) if len(args.rest) > 2 else 100
    beat = 60.0 / args.bpm
    for n in notes:
        send(args.port, "90 %02X %02X" % (n % 128, vel))
        time.sleep(beat * 0.9)
        send(args.port, "80 %02X 40" % (n % 128))
        time.sleep(beat * 0.1)


def do_seq_file(args):
    vel = int(args.rest[2]) if len(args.rest) > 2 else 100
    with open(args.rest[1]) as f:
        lines = [ln.split("#", 1)[0].split() for ln in f if ln.strip()]
    for toks in lines:
        name, dur = toks[0], float(toks[1]) if len(toks) > 1 else 1.0
        if name.lower() in ("r", "rest"):
            print("rest %.2fs" % dur)
            time.sleep(dur)
            continue
        note_onoff(args.port, note_to_midi(name), vel, dur)


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--bpm", type=int, default=120)
    ap.add_argument("--port", default=DEVICE)
    args, rest = ap.parse_known_args()
    args.rest = rest
    if not rest:
        ap.print_help()
        return
    cmd = rest[0].lower()
    if cmd == "voices":
        for (bank, pc), name in sorted(VOICES.items(), key=lambda kv: kv[1]):
            print("%-3s bank=%-3d pc=%-4d %s" % ("*" if bank else " ", bank, pc, name))
    elif cmd == "voice":
        bank, pc = look_up_voice(rest[1])
        program_change(args.port, bank, pc)
        print("voice set to %s (bank %d, pc %d)" % (VOICES[(bank, pc)], bank, pc))
    elif cmd == "note":
        do_note(args)
    elif cmd == "chord":
        do_chord(args)
    elif cmd == "seq":
        do_seq(args)
    elif cmd == "seq-file":
        do_seq_file(args)
    elif cmd == "alloff":
        send(args.port, "B0 7B 00")
        print("all notes off (CC123) sent")
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()