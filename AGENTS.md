# MIDI Keyboard Project

Workspace for iterating on live MIDI capture/interpretation from the
PSS-A50 USB keyed into this machine.

## Hardware
- Device: PSS-A50 USB-MIDI (driver reports PSR-E353), client 24 / card 2 / port `24:0`
- Capture: `aseqdump -p 24:0`
- Keyboard is frequently powered OFF / detached. Absence from aconnect
  (or client 24 gone) is NORMAL — just tell the user, don't deep-investigate.
- The keyboard emits constant `Clock` and `Active Sensing` chatter -
  ALWAYS filter these out. The PSS-A50 emits MINIMAL MIDI information:
  only `Note on` / `Note off` events (plus Clock/Active Sensing).
  No Control Change, Pitch Bend, Channel Pressure, SysEx, or other
  controller data is emitted over USB.
- The PSS-A50 ALSO RECEIVES over the same USB (bidirectional). It plays its
  INTERNAL voices (no softsynth needed): note on/off and full chords sound via
  its own speakers. Send path is the raw device `hw:2,0,0` (amidi) because ALSA
  seq exposes ONLY the capture port `24:0` — there is no seq output port to
  route to. `amidi -p hw:2,0,0 -S '90 3C 7F ...'` sends note-ons (ch1 works).
  This opens up "output" features on the cheap: replay a recorded take back
  through the keyboard.
- The board has a LOCAL CONTROL setting (local ON = keys sound their own
  engine; OFF = keys only emit MIDI, sound must come back from a computer)
  — the standard caution for pass-through/echo modes (avoid double sounding).

## Current architecture: monitor web app
The one-off CLI scripts (fast.py/listen.py/arpeggio.py/melody.py) were
folded into a single web app package in `monitor/`:

- `monitor/chords.py`   - shared chord engine (naming, inversions, key)
- `monitor/capture.py`  - owns aseqdump subprocess; resilient reconnect
                          when keyboard is off/detached (emits offline)
- `monitor/state.py`    - live held-notes + note/melody buffers + connectivity
- `monitor/analysis.py` - progressive recognizer: chord flashes, arpeggio
                          detection (scalar add9no5 suppressed), dedupe
- `monitor/app.py`      - Flask on :5050. Routes: `/`, `/events` (SSE),
                          `/api/state`. Background capture thread -> hub pub/sub.
- `monitor/templates/index.html` + `static/` - full 88-key piano (A0-C8,
                          transpose-safe), scrolling note feed, chord/arp flash.

Start/stop (for dummies): use the helper script, no chmod needed:
    bash ~/ai/midi/monitor.sh start|stop|restart|status|log
  -> http://127.0.0.1:5050 ; pid in ~/ai/tmp/keymon/monitor.pid,
     log in ~/ai/tmp/keymon/monitor.log. Server needs no keyboard attached;
     it reconnects on its own. (Equivalent: python3 -m monitor.app inside
     ~/ai/midi.)

## Legacy CLI chord scripts
Superseded by the `monitor/` web app, kept for reference:
- `~/ai/tmp/midi-chords.py` — pair-buggy prototype
- `~/ai/tmp/midi-chords2.py` — full-triad naming

## Conventions
- Follow the house manual (~/ai/AGENTS.md): keep durable knowledge here.
- Mutate files with the builtin `edit`/`write` tools (they work silently
  inside ~/ai now); no need for node -e fs workarounds.
- Analyzer-unit checks: python3 -c import + drive monitor.analysis directly
  (keyboard-independent).

## Changelog
The running log of every change lives in `~/ai/midi/CHANGELOG.md` (kept out of
AGENTS.md so this file stays a lightweight project map). Append new entries there.
Keep the same "Ver N: ..." style and the agent: commit / push workflow.
