# PSS-A50 MIDI Reference (pssa50_en_mr_a0.pdf → MIDIREF.MD)

Condensed from the Yamaha PSS-A50 MIDI Reference sheet (PO-A0, July 2019),
augmented with live testing on this machine (USB, reports as PSR-E353,
client 24 / card 2 / port 24:0).

## Channel setup (MIDI Out Channel Selection)

| Role | Channel |
|---|---|
| Keyboard Voices | user-set, default **1** (01–16, wrap: 16 → 1) |
| Arpeggio sequence | keyboard voice channel **+1** |
| Recorded performance (playback) | keyboard voice channel **+2** |
| Recorded arpeggio | keyboard voice channel **+3** |

If keyboard voice transmit channel = OFF, nothing is transmitted.
Panel settings (voices etc.) are **not** affected by incoming MIDI.

## Local Control ON/OFF

- ON (default): keys drive the internal tone generator.
- OFF: keys only emit MIDI (sound must come back from the computer).
  Relevant for pass-through/echo modes to avoid double-sounding.
- MIDI message: `Bn 7A 7F` = ON, `Bn 7A 00` = OFF (`n` = channel).

## Program Change / Control Change

- Both transmit AND receive can be individually enabled/disabled.
- With transmit+receive ON, voice changes on the board can be driven
  from the computer (and vice versa); the currently selected panel voice
  is maintained regardless.

## MIDI data format

- `<MIDI Master Tuning>`: `F0 43 1n 27 30 00 00 mm ll cc F7` (all channels, mm/ll = tuning value; default mm=08, ll=00).
- `<GM System ON>`: `F0 7E 7F 09 01 F7`. This instrument does **not** support GM format, but GM system ON still resets non-tuning defaults.
- `<MIDI Master Volume>`: `F0 7F 7F 04 01 ll mm F7` (Universal SysEx; ll ignored).
- Recording/playback start transmits `FA`; stop transmits `FC`.

## Implementation chart (transmitted / recognized)

- Channels: 1–16 both ways (default 3; altered: transmitted only).
- Mode 3 (Omni ON, Poly) transmitted; Mode 2 (Omni ON, Mono) recognized.
- Note number 0–127 both ways; true voice.
- Velocity: Note ON `9nH v=1–127` both ways; Note OFF `9nH v=0` both ways.
- Pitch bend: transmitted; recognized 0–24 semitones.
- Bank select CC 0/32: both ways; CC 1,5,7,11 recognized only.
- Data Entry MSB CC 6 both ways; LSB CC 38 recognized only.
- Sustain CC 64: recognized only. Portamento CC 65: both ways.
- Sound controllers CC 71–74: both ways. Portamento CC 84: recognized.
- Effect1/3 depth CC 91/93: both ways. RPN Inc/Dec 96/97: recognized.
- RPN LSB/MSB 100/101: both ways.
- Program change: transmitted 0–100, recognized 0–127.
- SysEx: transmitted, not recognized.
- Common (Song Pos/Sel/Tune): neither way.
- System real-time: Clock transmitted; recognized.
- All Sound Off: transmitted; recognized (120,126,127).
- All Notes Off: transmitted; recognized (123–125).
- Local ON/OFF: transmitted; recognized (122).
- Active Sense: both ways. Reset: neither.

## Live-tested PSS-A50 USB profile (this machine)

- USB descriptor: both MIDI streaming endpoints (EP1 OUT host→device, EP2 IN device→host). ALSA seq only exposes capture port 24:0 — no seq output port exists.
- Send path: raw device `hw:2,0,0` via `amidi -p hw:2,0,0 -S <hex>`.
- The 42 usable voices (0-based program bytes, bank 0 = normal, bank 127 = kits):

```
bank=0  pc=0   Grand Piano          bank=0  pc=48  Strings
bank=0  pc=4   Electric Piano 1     bank=0  pc=56  Trumpet
bank=0  pc=5   Electric Piano 2     bank=0  pc=57  Trombone
bank=0  pc=2   Electric Grand       bank=0  pc=60  French Horn
bank=0  pc=16  Drawbar Organ        bank=0  pc=61  Brass Section
bank=0  pc=18  Rock Organ           bank=0  pc=62  Synth Brass
bank=0  pc=21  Accordion            bank=0  pc=82  Gemini (fat supersaw)
bank=0  pc=22  Harmonica            bank=0  pc=84  Punchy Chordz
bank=0  pc=24  Nylon Guitar         bank=0  pc=80  Square Lead
bank=0  pc=25  Steel Guitar         bank=0  pc=81  Sawtooth Lead
bank=0  pc=26  Jazz Guitar          bank=0  pc=88  New Age Pad
bank=0  pc=27  Clean Guitar         bank=0  pc=89  Warm Pad
bank=0  pc=29  Overdriven Guitar    bank=0  pc=100 Brightness
bank=0  pc=32  Acoustic Bass        bank=127 pc=0   Standard Kit
bank=0  pc=33  Finger Bass          bank=127 pc=27  Dance Kit
bank=0  pc=36  Slap Bass            bank=0  pc=11  Vibraphone
bank=0  pc=38  Synth Bass           bank=0  pc=12  Marimba
bank=0  pc=40  Violin
bank=0  pc=45  Pizzicato Strings
bank=0  pc=42  Cello
bank=0  pc=46  Orchestral Harp
bank=0  pc=68  Oboe
bank=0  pc=71  Clarinet
bank=0  pc=73  Flute
bank=0  pc=66  Tenor Sax
```

- Bank select: CC 0 MSB = bank (0 normal / 127 kits), then program change `C0 <pc>`. **Bank state is sticky on the board** — after drum kits you must reset MSB to 0 before a normal voice again.
- Drums: GM-mapped (36 = kick, 38 = snare, 42 = closed hat, …).
- Velocity range 1–127 on receive; the board emits minimal data over USB (note on/off only).

## Send-path helpers

See `midiout.py` at repo root (stdlib only, calls `amidi`):

```
python3 midiout.py voices                     # 42 names
python3 midiout.py voice "Gemini"            # program change
python3 midiout.py note C4 [vel] [dur]
python3 midiout.py chord "C4 E4 G4" [vel] [dur]
python3 midiout.py seq "C4 E4 G4 C5" [vel]   # one beat each
python3 midiout.py seq-file TAKE.txt [vel]   # lines: note dur | r 0.5
python3 midiout.py alloff                     # panic (CC123)
```

## Precautions (USB)

- A-micro B cable, < 3 m, **no USB 3.0**.
- Quit open apps before power/plug cycles.
- Wait ≥ 6 s between power toggle and plug/unplug cycles.
- If frozen: restart the app/computer or power-cycle the board.

## Open questions / not yet verified

- Whether the board also *receives* program changes (it does — but we haven't tested changing the panel voice from the computer live).
- Actual receive channel behavior (the sheet says data received on the keyboard's MIDI out channel is sent to its internal voice; our raw-device send path worked on ch1 already).
- Local Control toggle behavior during pass-through (not yet exercised).
