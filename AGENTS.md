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

## Status log
- 2026-08-28: spun off from generic troubleshooting agent to focus solely
  on keyboard. Project scaffold created. Baseline aseqdump capture worked.
- Ver 2: fixed chord root-octave bug + added dedupe (report once per
    held set). Verified: G4 min (G-Bb-D), F4 maj (F-A-C).
- Ver 3: added chords.py (voicing + chord name + inversion/bass flag +
    inferred key via key-profile). listen.py uses it w/ rolling key window.
    Verified live: B min (/D), G maj, G min, C maj, B maj. Limitation:
    dyads (2-note) report no-template; key is a best-guess, not gospel.
- Ver 4: fast.py (asap chord read). Fixed dedupe to key on exact notes so
    inversions (e.g. C/G) surface instead of being collapsed to pc-set.
- Ver 5: expanded chord table (sorted-keys fix unlocked 9/11/13/sus/add).
    fast.py dumps raw voicing on no-template. Tone clusters stay unnamed
    (honest). Verified: G maj, F# add9(no5), 7sus, sus4, extended 9ths.
- Ver 6: arpeggio.py detects chords played as broken notes (0.6s window);
    only names real chords, stays quiet through scalar runs. Verified
    live: C maj, G maj, E min arpeggios, C add9.
- Ver 7: melody.py records timestamped notes + durations + interval contour.
    Captured Mary Had a Little Lamb (in E) live. Eyeball recognition for
    now; real matcher can use music21/corpora dbs later if wanted.
- Ver 8: arpeggio.py now suppresses the add9(no5) shape (3 adjacent scale
    tones) to kill scalar-run false positives. Real arpeggios (maj/min/7/
    sus4) still report. Verified live: scalar runs silent.
- Ilk 2026-08-28: builtin edit/write tools now surfaced & work silently
    inside ~/ai; node -e fs workaround retired.
- Ver 9 (GUI): consolidated CLI scripts -> monitor/ web app (Flask :5050,
    SSE, full 88-key piano, chord/arp flashes). Verified: server up, 88-key
    render (52w/36b, A0-C8), offline resilience in UI, analysis pipeline
    unit-tested.
- Ver 9b: fixed offline->online status flip in capture.py (wasn't emitting
    online event / tracking _online). Verified end-to-end LIVE with keyboard:
    notes light up, arpeggio flash (B4 maj /D#4), status flips online, low
    latency. Monitor is in use.
- Ver 9c: fixed chord+arpeggio double-flash. When a held chord is announced,
    the arpeggio for the same note simultaneity is now suppressed (played
    block = chord only; rolled = arpeggio only). Verified via unit test.
- Ver 10: new announcement kind -- INTERVAL. When exactly two notes are held,
    name the dyad (maj 3rd, perf 5th, dim 5th, aug 4th, octave...). Tritone
    spelled via letter gap (B-F=dim 5th, F-B=aug 4th); C-F# (sharp) = honest
    "tritone". Feed flashes INTERVAL + label. Unit-verified across ranges.
- Ver 11: colour coding -- flash banner + feed lines now coloured by kind:
    chords #4da3ff (blue), arpeggios #9fd4ff (light blue), intervals
    #ff8fd0 (pink). app.js flash() takes a kind class; css c-chord/c-arpeggio/
    c-interval (banner) + li.chord/li.arpeggio/li.interval (feed).
- Ver 12: arpeggio detection rework. root cause of "staccato/held arps not
    showing": a rolled chord (notes briefly overlapping) tripped held_chord
    announce, and its suppress_notes killed the follow-on arpeggio. Now:
    - Analyser tracks onset_of[note]; _is_block() = all onsets <= 90ms apart.
    - _roll_in_progress() (>=2 onsets spread >90ms) suppresses transient
      interval/chord confirms mid-roll.
    - arpeggio only suppressed when the just-announced held chord was a true
      simultaneous block.
    Verified: staccato roll==ARP, rolled-overlap chord==ARP, block==CHORD
    (no arp). Arps finally show for both staccato and held rolls.
- Ver 13: same chord played fast repeatedly wasn't re-flashing. Two fixes:
    (a) RE_COOLDOWN=0.2s time-based re-announce (was pure "same-key" dedupe
    that stuck forever); (b) ATTACK_GAP=0.15s -- on_note resets the onset
    buffer when a clear gap separates attacks, so a repeated stab doesn't
    blend with the prior one (which had made _roll_in_progress suppress the
    CHORD and merge bursts). Verified: repeated block/staccato/roll each
    flash per stab; single block still CHORD-only (no arp regression).
- Ver 14: added monitor.sh helper (start/stop/restart/status/log) so the
    server is easy to fire up from a cold session w/o remembering the
    python command. Runs as `bash ~/ai/midi/monitor.sh ...` (no chmod).
    Pidfile/log under ~/ai/tmp/keymon/. Verified all 5 subcommands.
- Ver 15: added README.md (non-technical friendly): how to start/stop/restart/
    status/log via monitor.sh, what the colours mean (chord=blue, arp=light
    blue, interval=pink), playing tips, and a short "under the hood" map of
    monitor/ modules. No image referenced (kept it text-only/accurate).
- Ver 16: MODAL KEY / MODE detection with ranked hypotheses. New in chords.py:
    `infer_modes(pc_weights, top=3)` returns the top-N modal keys each as
    {label, score, certainty}, scoring all 84 (12 tonic x 7 church-mode)
    candidates in the spirit of Krumhansl-Schmuckler extended to modes: heard
    pcs that fall in the mode's scale add weight (3x if tonic, +0.5 for the
    mode-appropriate 5th); stray chromatics ADD NOTHING (tolerated, not fatal)
    so a live player hitting a wrong note doesn't kill detection. Runs on the
    analyser's rolling key_window (KEY_WINDOW=12s) with KEY_COOLDOWN=4s change
    gating; `key_announce` emits {kind:"key",label,hypotheses:[...]}, with
    re-announce only when the top hypothesis changes or cooldown elapses.
    Frontend: NEW "key / mode" section under the piano showing the top 3
    hypotheses as name + horizontal probability bar + proportional percentage
    (share of top-candidates' scores), top highlighted blue, alternatives grey
    (renderKey() in app.js, .key/.key-row/.key-bar/.key-pct in style.css, #key
    element in index.html). Detector unit-verified: all 7 modes + flat keys
    (Bb ionian), chromatic blob = near-even low-confidence split (honest).
    Live render + proportional bars verified against a running server; server
    restarted. Backend keeps `infer_mode` for a single best label.
- Ver 17: NOTATION STAVE + KEY RESET + ACCIDENTALS. Added VexFlow 5 (offline-bundled in
    static/vendor/vexflow.js + embedded fonts). New "notation" section under
    key panel shows a **single continuous treble stave** where musical events
    (chord/arpeggio/interval/note) flow left-to-right as **quarter notes**, wrapping
    to new stave lines when full (16 per line). **White background** on stave-wrap.
    Sharp accidentals rendered via VexFlow Accidental modifiers (C major base,
    accidentals added for all sharp notes). Wired into live SSE: every
    `note` event and `flash` event (with `notes` array) calls
    `StavePanel.push(kind, notes, time)` (app.js → stave.js). Uses
    `voice.setStrict(false)` before adding tickables to exceed VexFlow's default
    16384-tick limit. Clear button clears the stave. Verified: VexFlow loads,
    renders chords/intervals/notes with accidentals correctly; live keyboard play
    populates the stave (13 wrapped lines = ~30s of play). Key reset button
    (`/api/key/reset`) clears the rolling key window and hypotheses.
- Ver 18: STAVE BUG FIXES. Clear button now properly resets renderer state
    (`renderer = null; context = null`) so stave re-renders cleanly after clear.
    Added **chord suppression**: when a chord/arpeggio/interval event is pushed,
    any recent individual "note" events that are subsets of the chord notes are
    removed from the stave buffer, preventing double-rendering of chord notes.
    Both fixes verified: clear empties stave immediately (re-renders on next push);
    chord events suppress constituent note events.
- Ver 19: ENHARMONIC SPELLING + INTERVALS TOGGLE + MINI STAVE. 
    **Spelling key selector** (dropdown with all 15 major keys + auto) controls
    flat/sharp rendering across both main and mini staves. F major now renders
    Bb/Ab/Eb/Db as flats; G major renders F# as sharp; C major uses sharps.
    **Intervals toggle** (checkbox) shows/hides interval events on main stave
    without losing the constituent notes. **Mini stave** (smaller stave below
    main) displays last chord/interval/arpeggio as half notes with same
    accidentals. Fixed chord suppression logic to only suppress for chords/
    arpeggios (not intervals), so toggling intervals OFF doesn't lose notes.
    VexFlow accidental modifiers now use natural base notes + Accidental
    modifiers for proper flat/sharp rendering (U+E260/U+E263 for flats,
    U+E262 for sharps).)
- Ver 20: MIDI QUANTIZATION PIPELINE. End-to-end rhythm quantization pipeline:
    - **Tempo detection**: Histogram-based BPM estimation with perceptual weighting (log-Gaussian centered at 120 BPM) and octave ambiguity resolution via interval matching. Robust against trills/tremolos (filters intervals <100ms).
    - **Quantization grid**: Dynamic grid based on detected tempo (beat = quarter note), subdivided by `QUANTIZATION_DIVISIONS=4` (16th notes). Notes snapped to nearest grid point.
    - **Quantized note pipeline**: `note_off` → `State._add_quantized_note()` → `State.quantized_notes` → `/api/state` + SSE `quantized_note` event → `StavePanel.push(kind="note", duration=...)` → `durationToVexFlow()` → VexFlow `StaveNote` with proper duration.
    - **Frontend**: `window.tempoBpm` sync'd via SSE `quantized_note.tempo`, `durationToVexFlow()` on `window` converts seconds to VexFlow duration strings (`w`, `h`, `q`, `e`, `16`, etc.). `StavePanel.push()` accepts `duration` param and passes to `buildStaveNotes()`.
    - Verified: Quantization active at 120 BPM (detects ~119 BPM), notes render as proper note values (eighth=0.25s, quarter=0.5s at 120 BPM). Known issue: octave ambiguity at extreme tempos (60→120, 180→90).
- Ver 21 bugfix: FROZEN PAGE FIX. Root cause: `app.py` referenced `Capture.GM_PROGRAMS` as a
    CLASS attribute, but `GM_PROGRAMS`/`CC_NAMES` were module-level. On any `program_change`
    event this threw `AttributeError`, crashing the capture thread -> feed/stave silently stop
    updating (page appears frozen). Fixed by moving BOTH constants inside the `Capture` class
    as class attributes (also fixed duplicate CC key 124->125 for "Omni Mode On"), and updated
    `get_program_name()` to use `self.GM_PROGRAMS`. Server restart verified clean (no new errors),
    `Capture.GM_PROGRAMS`/`CC_NAMES` resolvable as class attrs. Lesson: keep shared constants
    accessible via the class when other modules import the symbol off the class.
- Ver 22 bugfix: EMPTY STAVE (no notes rendered). Root cause: `durationToVexFlow()` returned
    VexFlow-INVALID duration strings: `"e"` for eighth (VexFlow uses `"8"`) and trailing-dot
    dotted notes `"q."/`"e."/`"16."` (VexFlow uses trailing `"d"`: `"qd"/"8d"/"16d"`). When a
    single event got such a duration, `buildStaveNotes()` threw
    `BadArguments: Invalid note initialization object`, aborting the ENTIRE `redraw()` loop
    (which re-renders ALL buffered events). Once one bad note entered `events`, every subsequent
    redraw crashed -> stave SVG exists but stays empty forever. Fixed duration table to valid
    VexFlow names (`w/h/q/qd/8/8d/16/16d/32`). Verified in-browser: `durationToVexFlow` now
    emits valid names and `StavePanel.push(note,duration)` renders noteheads+staves. Gotcha to
    remember: VexFlow duration strings differ from conventional notation (8 not e; d-suffix
    dotted, not trailing dot).
- Ver 23: DURATION-JITTER FIX + INTERVALS DEFAULT OFF. (a) show "intervals" checkbox is now
    OFF by default (removed `checked` in index.html; `showIntervals=false` in stave.js).
    (b) Fixed the "quarter notes interspersed with shorter notes" + perceived-duplication bug:
    `State._add_quantized_note` was quantizing on_time AND off_time independently, so a note
    straddling a beat boundary got an artifact duration (e.g. 0.49s q vs 0.12s sixteenth for an
    evenly played scale). Rewrote it to snap the ONSET to the grid, snap the RAW held duration
    (off-on) to the nearest grid multiple, and derive off = snapped_on + snapped_duration.
    Live capture of a scale now yields regular durations (all 16th vs 8th, clean duplicates).
    Also added `channel` to note_on/note_off events in capture.py (regex already parsed it) for
    diagnosing cross-channel (arp) duplication later. Verified live: C/G scales render regular
    note values, each scale degree once, no stray interspersed longs.
- Ver 23b bugfix: DUPLICATE NOTES ON STAVE (user still saw dupes on simple scales even though
    backend stream was clean). Root cause was FRONTEND dual-push: `app.js` called
    `StavePanel.push("note", ...)` on BOTH the raw `note` event (default quarter duration) AND
    the `quantized_note` event (quantized duration) for the same key press -> every note rendered
    twice. Backend `/events` quantized stream was always correct (each note once); the dupes were
    only visual. Fixed by REMOVING the `StavePanel.push` from the `note` handler case (kept key
    activation + feed + tempo there); notes now reach the stave ONLY via `quantized_note`. Live
    verified: 95 quantized events for 95 played scale notes; stave notehead count matches play
    (no doubling). Lesson: when adding a second publish path (quantized_note) for data already
    pushed by an existing event (note), remove the old push or you double-render.
- Ver 24: DOTTED NOTES + BEAMING. (a) Dotted notes: `durationToVexFlow` already maps a held
    duration to the nearest note value including dotted variants (`qd`/`8d`/`16d`), so a note
    ~1.5x a base length now renders as a dotted note (verified 0.375s->8d, 0.75s->qd at 120bpm).
    (b) Beaming: added `buildBeams()` + BEAMABLE set in stave.js. `redraw()` now groups
    consecutive beamable single notes (8th & faster, incl. dotted; chords excluded via isChordNote)
    per stave-line into VexFlow `Beam` objects, drawn after the voice. Verified: 8 consecutive
    eighth notes render as one beam. Note: beaming is per stave-line (beams don't cross line
    wraps) and only for single-note events (chords/arps/intervals are not beamed).
- Ver 25: KEY SIGNATURE ON CLEF + BASIC EDITING (BACKSPACE). (a) The main stave now renders the
    DETECTED key signature on each clef via `stave.addKeySignature(ks)`. New `StavePanel.setKey(label)`
    parses a key-announce label ("C ionian", "Bb aeolian", "D dorian", ...) -- tonic name mapped to
    pitch class, MODE_OFFSET shifts to the parent MAJOR key's tonic (ionian 0, dorian -2, phrygian -4,
    lydian -5, mixolydian -7, aeolian -9, locrian -11), then PC_MAJOR name is rendered. Wired from
    app.js `key` event (ev.label). Also auto-aligns spellingKey to the key so accidental logic matches.
    (b) BACKSPACE editing: `StavePanel.backspace()` pops the last buffered event and redraws; a document
    keydown listener fires it (guarded to ignore when typing in INPUT/SELECT/TEXTAREA). Verified: G ionian
    renders key sig, A aeolian (Am) maps to C major (0 flats/sharps), backspace 3->2 noteheads, 8 eighths
    still beam with key sig shown. Note: key sig reflects the DETECTED key; single notes before the key
    is known have no signature yet.
- Ver 26: MANUAL KEY SELECTOR (AUTO KEY DETECTION UNHOOKED). Replaced the auto key/mode detection entirely:
    the rolling Krumhansl-style hypothesis panel, `key`/`reset` buttons, and the separate spelling-key
    dropdown are REMOVED from the UI and no longer drive the stave. Auto-detected `key` SSE events are now
    ignored on the frontend (removed the `key` case in app.js). Instead, a simple "intended key" dropdown
    (`#intended-key` in index.html, 15 major + 15 minor) drives the stave key signature via a single
    `StavePanel.setKey(value)` on change. stave.js: `keySigFromLabel` renamed to `toKeySig`, which now
    accepts (a) "auto"/"none" -> null (no signature), (b) bare major key ("G","Bb"), (c) bare minor key
    ("Xm" -> relative major, minor tonic +3 semitones), (d) modal labels (kept for compat). `setKey` also
    resets spellingKey to "auto" when no key is selected. Backend analysis.py key detection still runs
    (inert) but is no longer wired to the stave/UI. Verified in-browser: 29/30 dropdown values render a
    key signature (only Cb major, a 7-flat edge case that maps to enharmonic B, shows none); G major,
    Dm->F, Am->C signatures correct; "auto" shows none; no JS errors. Dead CSS (.key-row, .key-reset,
    #key-toggle, .keysec.collapsed) removed.

- Ver 27: GIT/AUTH METHODS — Version control uses git init in ~/ai/midi/ with ssh://git@github.com/puijila-darwini/midi-monitor.git remote.
    Agents push via SSH (no auth tokens required if ssh keys configured). All commits prefixed "agent:" to
    distinguish AI-made changes; use `git commit -m "agent: <desc>"` before pushing. Remote URL set via
    `ssh://git@github.com/<username>/<repo>.git`. Local identity: git config user.name "opencode-agent" plus
    your email. Workflow: (1) git add . ; (2) commit -m "agent: ..."; (3) push origin master. Before major
    updates: pull --rebase origin master; handle conflicts if any. Git hooks reject commits without proper
    prefix. Runtime data excluded: __pycache__/*.pyc, *.log files, monitor.log, opencode.json (security config).

- Ver 28: CAPTURE RESILIENCE (WATCHDOG + SUPERVISOR + UI SURFACING). We hit a real failure: a server
    started on pre-Ver-21 code kept its capture thread crashing with `AttributeError: type object 'Capture'
    has no attribute 'GM_PROGRAMS'`, so the HTTP server stayed "up" while no notes flowed (silently deaf),
    plus zombie aseqdump processes accumulated. Fixed with 3 layers:
    (a) IN-PROCESS WATCHDOG (app.py): `_run_capture()` is now driven by `_run_capture_supervised()`, an
        infinite retry loop with exponential backoff (1s -> 30s cap). Any exception in the capture loop is
        caught, health is recorded, a `capture_error` SSE event is published, the loop sleeps and restarts.
        Health lives in module-level `_capture_health` (alive/error/restarts/last_error_time, guarded by
        `_capture_lock`) and is merged into `/api/state` under `capture: {...}`. `events()` now uses the
        imported `json` (was `__import__('json')`).
    (b) FRONTEND SURFACING: new `#capture-error` banner element in index.html (between header and grid), a
        `capture_error` SSE case in app.js that calls `showCaptureError()` to show a transient amber strip
        ("capture hiccup (Nx): <msg> — retrying…"), styled in style.css (`.capture-error`, `.visible`).
    (c) SUPERVISOR (monitor/supervisor.py): a second line of defense. Stdlib-only (urllib/json/subprocess)
        health-checker that polls /api/state every 5s; if the server is unreachable OR `capture.alive` is
        false with an error for 3 consecutive polls (~15s), it restarts the whole server via
        `bash monitor.sh restart`. Spawned by monitor.sh `start` (pid in supervisor.pid); `stop` kills it
        too so an intentional stop isn't auto-restarted. Restart verified live: killed server pid, supervisor
        restarted it after ~15s, fresh pid serving 200 on /api/state. Note supervisor.log lives in
        ~/ai/tmp/keymon/. (supervisor also cures the "page wedges / SSE flaps" symptom by recycling the
        whole server when capture stays dead.)
    Cleanup: removed 4 orphaned aseqdump processes accumulated from stale sessions (only the monitor's own
    aseqdump should ever be running; check with `pgrep -af aseqdump`). Lesson: restart the server after any
    code edit so it isn't running pre-fix Python; the supervisor now babysits this.
