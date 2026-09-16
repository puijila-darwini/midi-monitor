# MIDI Keyboard Project

Workspace for iterating on live MIDI capture/interpretation from the
PSS-A50 USB keyed into this machine.

## Hardware
- Device: PSS-A50 USB-MIDI (driver reports PSR-E353), client 24 / card 2 / port `24:0`
- Capture: `aseqdump -p 24:0`
- Keyboard is frequently powered OFF / detached. Absence from aconnect
  (or client 24 gone) is NORMAL — just tell the user, don't deep-investigate.
- The keyboard emits constant `Clock` and `Active Sensing` chatter -
  ALWAYS filter these out. Played notes arrive as `Note on` / `Note off`;
  the board also TRANSMITS pitch bend + CC1 (mod wheel) and, on a panel/voice
  action (e.g. selecting a voice), Program Change + bank CC0/32 + a burst of
  controller data (CC6/11/71/72/74/100/101 etc.) and SysEx 120/121/123 aux.
  `capture.py` parses all of it; capture handles note/ctrl/pitch events (see
  the out · ctrl card's "received" readout).
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
- IMPORTANT hardware behavior: incoming Program Change, CC (incl. sustain
  CC64) and pitch bend affect RECEIVED (MIDI-IN) notes ONLY — the local
  keybed sound bypasses that control path. So sending sustain/pitch/voice
  does nothing to keys you play by hand unless the notes come back over MIDI.
  The app's "echo" mode (see CHANGELOG Ver 70) re-sends keybed notes back to
  the board to close this gap; with local ON you get a layered double, local
  OFF the echo alone. Local and RX voices are independent, so echo can layer
  a different voice against the panel voice.

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
- `monitor/sinks.py`    - DATA-DRIVEN registry of launchable MIDI destinations
                          (VCV Rack, DAWs). Each entry declares cmd/detect/
                          auto_route (see ../Musica/Rack pattern); the out box
                          buttons + /api/sinks launch + boot auto-routing all
                          derive from it. Add a DAW = add one dict entry.
- `monitor/patterns.py` - pattern library: save/load named snapshots of the raw
                          (IN) / out (OUT) buffers as JSON in patterns/
                          (gitignored). A pattern = events + transform-chain
                          settings; load restores both into the raw buffer.
                          Endpoints /api/patterns list/save/load/delete.
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
