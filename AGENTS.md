# MIDI Keyboard Project

Workspace for iterating on live MIDI capture/interpretation from the
PSS-A50 USB keyed into this machine.

## Hardware
- Device: PSS-A50 USB-MIDI (driver reports PSR-E353, ALSA names it "Digital
  Keyboard"). The ALSA card + seq client numbers are NOT stable — they follow
  boot/plug enumeration order (was client 24 / card 2 for months; the
  2026-09-20 reboot put it at client 20 / card 1). `monitor/mididev.py`
  re-resolves BOTH endpoints by name on every (re)connect (seq via
  `aconnect -l`, raw via `amidi -l`; TTL-cached ~2s; legacy `24:0` /
  `hw:2,0,0` as fallback). capture/replay/sinks all go through it now.
- Capture: `aseqdump -p <found seq port>` (monitor/capture.py re-resolves on
  each reconnect attempt, so a reboot that shifts the client number heals).
- Keyboard is frequently powered OFF / detached. Absence from aconnect
  (regardless of client number) is NORMAL — just tell the user, don't
  deep-investigate.
- The keyboard emits constant `Clock` and `Active Sensing` chatter -
  ALWAYS filter these out. Played notes arrive as `Note on` / `Note off`;
  the board also TRANSMITS pitch bend + CC1 (mod wheel) and, on a panel/voice
  action (e.g. selecting a voice), Program Change + bank CC0/32 + a burst of
  controller data (CC6/11/71/72/74/100/101 etc.) and SysEx 120/121/123 aux.
  `capture.py` parses all of it; capture handles note/ctrl/pitch events (see
  the out · ctrl card's "received" readout).
- The PSS-A50 ALSO RECEIVES over the same USB (bidirectional). It plays its
  INTERNAL voices (no softsynth needed): note on/off and full chords sound via
  its own speakers. Send path is the raw device (amidi) because ALSA
  seq exposes ONLY the capture port — there is no seq output port to
  route to; the raw node is resolved dynamically (mididev.find_raw_device,
  e.g. `hw:1,0,0` post-2026-09-20 reboot). `amidi -p <found> -S '90 3C 7F ...'`
  sends note-ons (ch1 works).
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
- Transform card ops (RAW -> quantize -> transpose -> velocity ->
  articulation -> invert -> scale-snap -> reverse -> OUT): the ops grid which
  is also the whole point of the card. scale-snap maps pitches onto the
  tonic·scale card's selection (SCALE_SEMIS in state.py mirrors the JS guide
  table); invert reflects around a pivot (n' = 2·pivot − n) whose UI is a
  note + octave pair of dropdowns — the note DEFAULTS to the key tonic at
  octave 3 (C3 = 48 backend default) and auto-follows tonic·scale changes /
  catch until the user picks a pivot of their own (data-custom flag;
  refreshState treats backend pivot 48 as "un-custom", anything else as
  deliberate); reverse replays the take tail-first (mirrored timeline,
  durations kept). The LIVE-CAPABLE
  ops (transpose/snap/invert + velocity touch) each have an "echo" opt-in that
  applies them to the live echo stream too (state.echo_transform, a pure
  per-note map so note_off mirrors exactly, plus map_echo_velocity on each
  echoed note_on); quantize/humanize/reverse are buffer ops and cannot. /api/transform + /api/scale are the setters (requantize on
  change); both /api/state and settings_snapshot carry the new fields.
  Ver 94: echo is STABLE under mid-hold changes — the press-time mapping is
  frozen (state.echo_hold/release/release_all, per-mapped-note refcount for
  snap-collapsed keys); the invert pivot can be AUTO (the take's first note,
  state.invert_pivot_auto + invert_pivot_live; /api/state transform also
  emits invert_pivot_effective, the pivot actually in force). The piano
  visual language lives only in the echo world (keys routing layer/echo AND
  invert+echo-checked): bodies/scale/pressed colours invert, the pivot key
  wears a dashed straw frame, and each held key's echoed target lights as a
  hollow ghost (app.js echoMap mirrors state.echo_transform exactly, JS
  snapPitchAbs mirrors _snap_pitch — cross-validated 450/450). Snap-armed
  red-strips out-of-scale keys and shows the landing note above the
  struck-through played name. TONAL FIX: _snap_pitch builds pcs as
  (s + tonic) % 12 (subtraction was wrong for every non-zero tonic).
  Ver 95: velocity joins the echo opt-ins (echo_velocity flag, live threshold
  clip / compress-rescale via state.map_echo_velocity on each echoed note_on;
  quantize/humanize/reverse stay buffer-only); invert gains a chromatic /
  diatonic mode (state.invert_mode; diatonic reflects ON the scale ladder so
  results stay in-key, needs tonic·scale else chromatic fallback; JS
  invertPitch mirrors _invert_pitch — cross-validated 20740/20740).
  Ver 96: mono microtonal tuning op (retune + preset + 12 cents cells;
  state.tuning_cents/TUNING_PRESETS equal/just/pythagorean/meantone; pre-bend
  at strike time on echo via tuning_strike_bend skip-if-unchanged + on
  replay/arrange batches via Replay(play tuning=fn), bass detune wins chords,
  raw-path only; integer take untouched, persists in settings). PATH: card
  cells/preset select -> POST /api/tuning -> state.tuning_cents -> strike
  time: echo note_ons need retune AND the echo opt-in (state.echo_tuning),
  replay/arrange need retune alone; both send pitch_bend(cents/100) on the
  strike channel just before note_on via amidi raw (skip-if-unchanged, bend
  re-centers at phrase end / on disable). Live-verified with the all-+100c
  honky-tonk demo. Bend range is replay.BEND_RANGE_ST = 2.0, ear-calibrated
  (labeled +100c came out ~8c, so half-throw is 200c); shared by send, receive
  mapping, /api/ctrl validation, and the pitch slider. Master detune
  (state.tuning_master ±50c, mirrors the board Tuning: manual 427-453 Hz) adds
  to every pc at strike time; A4 Hz badge + per-cell C4 Hz tooltips assume the
  board at 440 (unreadable).
- `monitor/app.py`      - Flask on :5050. Routes: `/`, `/events` (SSE),
                          `/api/state`. Background capture thread -> hub pub/sub.
                          Replay entry points (/api/replay, /api/replay/loop,
                          /api/patterns/<slug>/play) share the
                          _replay_start_guard()/_play_events() helpers.
- `monitor/sinks.py`    - DATA-DRIVEN registry of launchable MIDI destinations
                          (VCV Rack, DAWs). Each entry declares cmd/detect/
                          auto_route (see ../Musica/Rack pattern); the out box
                          buttons + /api/sinks launch + boot auto-routing all
                          derive from it. Add a DAW = add one dict entry.
- `monitor/patterns.py` - pattern library: save/load named snapshots of the raw
                          (IN) / out (OUT) buffers as JSON in patterns/
                          (gitignored). A pattern = events + transform-chain
                          settings; load restores both into the raw buffer.
                          Endpoints /api/patterns list/save/load/delete. PLAY (/api/patterns/<slug>/play)
  runs a stored pattern's own events straight out via the shared replayer
  (no buffer load), and the patterns transport row's play button replays the
  current buffer (same as out-card play, press-again-to-stop).
                          Patterns carry a letter tag + bar length (auto/override)
                          for the arranger.
- `monitor/arrange.py` - arrangement tracker: 64 fixed slots (base64
                          A-Z a-z 0-9 +/), each pointing at a stored pattern
                          with its own transpose + voice (slots.json,
                          gitignored). The arrangement string is pure slot
                          characters in order, laid out on the bar grid at a
                          tempo, clipped per slot; arrangements persist in
                          arrangements/. Voices travel mid-stream as program
                          events through replay; /api/arrange/play uses the
                          shared replayer.
- `monitor/static/roll.js` - piano roll (pure SVG): a second consumer of the
                          SAME `/api/notation` events the stave uses, so it
                          always mirrors the notation. Time fits the card
                          width, pitch auto-fits the notes present. Renders on
                          the same triggers as the stave; the replay step's
                          relative time sweeps a playhead and lights the
                          sounding block. Built for future editing (render is a
                          pure function of a `model` of hit-testable blocks).
- `monitor/templates/index.html` + `static/` - full 88-key piano (A0-C8,
                          transpose-safe), scrolling note feed, chord/arp flash.
                          app.js keeps replay/loop state in a Transport store
                          (mini pub/sub; buttons subscribe, SSE events feed it).
                          Take recording is OFF by default (idle noodling never
                          accumulates; REC arms a fresh take); the Abora mark
                          monitor/static/abora-logo.png is the favicon and the
                          circular header emblem top-left.

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
