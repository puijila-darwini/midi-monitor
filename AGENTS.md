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

- Ver 29: PSS-A50 VOICE NAMES (NOT GM, GM-COMPATIBLE NUMBERING). The app previously labelled instruments with full General MIDI
    names — wrong for this keyboard. The PSS-A50 is NOT full GM: it has exactly 42 presets (40 normal voices + 2 drum kits = Standard
    Kit, Dance Kit). FIRST ATTEMPT (consecutive voice# = program-1) WAS WRONG and made many real voices show "Unknown". Root cause
    (Owner's Manual "Voice List"): normal voices use GM1-compatible program numbers (Bank MSB 0) at their GM positions; the 2 drum
    kits use XG/XGlite numbering with Bank MSB 127. So program 82 = Gemini (the "fat supersaw" the user heard — GM calliope at 82 was
    wrong), 84 = Punchy Chordz, 88 = New Age Pad, 61 = Brass Section, 68 = Oboe, 48 = Strings, 16 = Drawbar Organ. Fix: Capture
    .VOICE_BY_PROGRAM dict keyed (bank MSB, program)->name, 42 entries (40 @ bank0 at GM positions; drums Standard=127/0,
    Dance=127/27). Capture now tracks CC#0 Bank Select MSB (_bank); control_change CC#0 updates it; program_change events carry
    "bank". get_program_name() resolves via (bank,program). app.py publishes program_change with resolved name + bank. state.py
    tracks bank (exposed in /api/state). app.js adds PSSA50_VOICES map + resolves initial-state name instead of "Program N".
    Verified: all 42 entries; live-captured programs (0,16,24,32,48,61,68,82,84,88) resolve to correct Yamaha names; out-of-range ->
    Unknown; server restarted clean; page loads w/ no JS errors; banner "instrument: Grand Piano (prog 0)". NOTE: manual PC numbers
    are 1-128; subtract 1 for the real program byte. Committed agent: prefix, pushed.

- Ver 30: STAVE NOTE VALUE = INTER-ONSET SPACING (not held duration). Symptom: "too many notes joined together,
    impossible to get a quarter note" — playing steady melody produced stave full of beamed 8ths/16ths. Root cause:
    State._add_quantized_note computed each note's value from the HELD duration (off-on). On a piano you strike a
    quarter briefly and release fast, so held duration is short and noisy; every melody note collapsed to 8th/16th
    and got beamed. Fix: note VALUE now = the RHYTHMIC GAP since the previous note's ONSET (saved as self._last_qon,
    the previous grid-snapped onset), snapped to the grid. Steady quarter playing -> every note a quarter regardless
    of how briefly struck; steady 8ths still beam correctly. First note of a phrase (no prior onset) falls back to
    snapped held duration (so it may be short; acceptable). Verified via synthetic drive (steady 8ths->8ths,
    quarters->quarters) and LIVE capture: 99 quantized notes now show a real mix (quarters, 8ths, halves, dotted)
    matching actual playing instead of all 16ths. Note: this is "gap since previous onset", not "until next onset",
    so it needs no one-note-late render; identical result for even rhythm.

- Ver 31: QUANTIZATION STRICTNESS CONTROL IN UX. The stave sanded into 8ths/16ths partly because the grid was fixed
    at QUANTIZATION_DIVISIONS=4 (16th notes). Added a user-facing "quant:" dropdown (loose/normal/tight) in the
    stave-controls header. It maps to grid fineness (divisions per beat), a.k.a. how "strict"/coarse quantization is:
    - loose (2)  = 8th-note grid: smallest unit is an 8th, so you can't get 16ths -> fewer tiny beamed notes,
                   quarters appear easily. Good when you don't want fast detail.
    - normal (4) = 16th grid (default, prior behavior).
    - tight (8)  = 32nd grid: captures fast passages in detail.
    Implementation: state.py QUANTIZATION_DIVISIONS class-const -> instance attr self.quantization_divisions (default 4),
    grid_step = beat / max(1,self.quantization_divisions) in _quantize_time and _add_quantized_note; new
    State.set_quantization(divs) (resets _last_qon so grid change starts a fresh phrase, bumps version) + exposed as
    quantization_divisions in snapshot(). app.py: new POST /api/quant {"divisions":N} sets it. index.html: quant select
    (loose/normal/tight values 2/4/8). app.js: change handler POSTs to /api/quant and clears the stave (old durations
    no longer valid under new grid); initial /api/state fetch sets the select to the server's current value.
    style.css: .stave-controls select styling. Verified end-to-end: selectors drives server (loose=2, normal=4, tight=8),
    server default 4, no JS errors, python -m py_compile clean, server restarted. Committed agent:, pushed.

- Ver 32: USER-DEFINED TEMPO (FIXED AT RECORDING START, detected as suggestion). Symptom: "estimated tempo going up and
    down; it needs to be fixed at the beginning of a recording" — the auto tempo re-ran a rolling histogram on every
    note (State._estimate_tempo) and overwrote tempo_bpm, so the quantization grid (and derived note values) kept
    changing mid-take. Solution (per user: "detected tempo provided as just a suggestion + guide to how actual detected
    playing compares to user-defined"): the user can FIX a tempo; that becomes the stable quantization tempo, while the
    live estimate is kept separately as a suggestion/guide.
    Backend state.py: split tempo into three fields — tempo_bpm (EFFECTIVE, the grid tempo quantization uses),
    detected_bpm (live estimate), user_tempo_bpm (0 = auto). _estimate_tempo now writes to detected_bpm, and mirrors
    into tempo_bpm ONLY when user_tempo_bpm<=0 (so a fixed tempo locks the grid). New State.set_user_tempo(bpm):
    0/None = auto (revert effective to detected); else freeze effective = bpm; resets _last_qon (grid changed) + bumps
    version. snapshot() exposes tempo_bpm/detected_bpm/user_tempo_bpm. app.py: new POST /api/tempo {"bpm":N} (0 clears;
    val range 0-400), returns {bpm,effective}; quantized_note SSE event now also carries detected_bpm + user_tempo_bpm.
    Frontend: REMOVED the client-side noisy tempo estimator (updateTempo() computed rough BPM from a 2s rolling onset
    window and wrote to #tempo — one source of flapping). Header #tempo is now a control: number input (#tempo-input,
    blank=auto) + #tempo-tag ("auto <eff> BPM" / "fixed <eff> BPM") + #tempo-detected ("detected ~N BPM" as guide).
    renderTempo(eff,det,user) renders from /api/state (initial) and each quantized_note; input change/Enter POSTs to
    /api/tempo and clears the stave. Verified: unit test (auto->effective follows detected; set 94 locks effective even
    as detected drifts 110->149; clear reverts), live endpoint (set 96, auto, invalid 9999 rejected), browser (type
    tempo+Enter locks effective, tag "fixed 100 BPM" + "detected ~86 BPM", no JS errors).

- Ver 33: METRONOME (click at the effective tempo). New '♫ metronome' toggle button in the header tempo control +
    a beat LED (#metro-beat). Uses Web Audio API (square-wave click via 2 oscillators + gain envelope) at the EFFECTIVE
    tempo (tempoBpm): accent on the downbeat (beat 0 of 4/4, ~1800Hz) then offbeats (~1200Hz); button toggles to
    '♫ stop' while active; click immediately on start (no dead first beat). .metro-btn/.metro-beat/.metro-pulse/.metro-
    accent styling in style.css. Stops on page visibility-hidden; won't start with no tempo (tempoBpm<=0). Verified in
    browser: with fixed 100 BPM, clicking starts it (button '♫ stop', beat LED accent-pulsing, no JS errors).

- Ver 34: NOTE VALUE = TIME-TO-NEXT-ONSET (deferred emission), fixing unfair quarter->eighth/dotted-eighth demotion.
    Symptom (user: "unfairly marking some of my quarter notes as eighths -- check the rounding here"): a metronome-
    guided quarter scale at fixed 100 BPM produced 0.450s (dotted-8) notes. Root cause: Ver 30 derived note value from
    the gap SINCE the previous onset; when the PLAYER'S OWN timing jitter makes that look-behind gap short (~3/4 beat),
    an intended quarter is demoted to dotted-8. Data showed 0.45/0.75 complementary pairs = a single onset landing off
    its regular grid position. User explicitly chose "time-to-next onset" (over a median-smoothed gap), accepting that
    each note is emitted one onset LATE (and the final note needs a flush).
    Implementation (state.py): removed _last_qon and _add_quantized_note; added a pending-onset group self._pending
    {qon, notes:[(note,vel)]}. On note_on: (a) same snapped grid tick as pending -> chord member, join group no finalize;
    (b) later tick -> _finalize_pending(gap = snapped difference in grid steps), then open new pending; (c) no tempo yet
    (grid_step==0) -> raw gap. First note of a phrase is now finalized by the SECOND onset's arrival (no more held-duration
    fallback for note 1). _finalize_pending appends one quantized_note per group member (same on/dur -> VexFlow chord) and
    pushes them to _emit_queue. FLUSH DAEMON: a background thread (40Hz, RLock-guarded with the capture thread) finalizes a
    pending note once no new onset arrives within grace = 2*beat+0.5s, using _robust_gap_duration() (median of recent
    quantized durations -> snapped) so the trailing note still renders with a sensible value. app.py: quantized_note is now
    published from a loop-end drain of state.take_quantized_events() (fires on note_on and on the keyboard's periodic
    Clock/Active-sensing events), NOT on note_off. Verified: synthetic 100-BPM quarter scales with +-50ms jitter -> 13-17/17
    quarters (dot-8 only where a true adjacent gap is short); trailing-note flush works; server restarts clean, page loads
    w/o JS errors. NOTE: still not a silver bullet — a single onset that lands genuinely off-grid shadows either its
    look-behind (old model) or its look-ahead (this model); both demote one note. Real rhythm variation (e.g. an actual
    0.45s anticipation) still reads as dotted-8, which is correct notation.

- Ver 34b bugfix: TIME-BASE BUG IN FLUSH DAEMON ("clean eighths at ANY speed"). First live test after Ver 34
    showed EVERY note as an 8th even when the player slowed to ~1.2s gaps. Only ONE note_on per key reached
    state (no channel-dup problem), and quantized durations were a constant ~0.30s = 2 grid steps regardless of
    the real 1.2s gaps (which should have been 8-step half notes). Root cause: state.py _flush_stale_pending()
    aged the pending note with `time.time() - p["qon"]` — but capture._now() returns SECONDS SINCE CAPTURE START
    (~350), while time.time() is EPOCH seconds (~1.8e9). The age check was therefore ALWAYS > grace, so EVERY
    pending note was flushed ~0.4s after its onset with _robust_gap_duration()=median of recent durations, which
    self-sustained at ~0.30s 8ths forever. The synthetic test passed earlier because it only flushed at the END
    (after real next-onset finalization), never exercising the daemon's age math between notes. Fix: pending now
    stores `wall_t = time.time()` (epoch, same base) in addition to qon (capture-relative); the flush ages against
    wall_t. Re-verified: driven half-speed scale (1.2s gaps) now yields 8-step HALF notes with zero 1-2-step
    artifacts; quarter tests unchanged; server restarted. Lesson: when a golden-path test passes but live behavior
    is uniformly wrong, check that background/lazy paths use the same TIME BASE as the values they compare.

- Ver 35: USER-DEFINED TIME SIGNATURE + MEASURE (BAR) LINES ON THE STAVE. Previously the stave drew a
    "4/4" time signature and packed notes ~by count (16/line) with no barlines. Now the user can set the
    meter and the notation shows real measures (bar lines) that subdivide each line, like sheet music.
    Backend state.py: new `time_signature` (default "4/4"), `set_time_signature(numer, denom)` validating
    numer 1-16 and denom in {1,2,4,8,16} (resets _pending + bumps version), convenience props
    `time_sig_numer`/`time_sig_denom`, and `time_signature` exposed in snapshot(). app.py: new
    `POST /api/timesig {"numer":N,"denom":M}` (invalid -> 400, persists via state). Frontend index.html:
    new "time:" select `#timesig` (2/4,3/4,4/4,5/4,6/8,7/8,9/8,12/8) in the header next to tempo. app.js:
    `window.timesig {numer,denom}` global + `setTimesig()` helper; change handler POSTs /api/timesig and
    clears the stave (old bar boundaries invalid); initial /api/state sync sets selector + window.timesig;
    metronome accent now wraps at `timesig.numer` beats (was hardcoded 4/4). stave.js: `StavePanel.setTimeSignature`
    export; `redraw()` rewritten to `packMeasures()`: when a tempo exists (window.tempoBpm>0) each event's bar
    index = floor((ev.time - t0)/barSeconds) where barSeconds = (60/bpm)*numer; events packed per measure, then
    grouped MEASURES_PER_LINE=4 staves per line; each line's first measure draws clef + key sig + time sig, all
    measures get real bar lines (setEndBarType SINGLE between, END on the last of a line); each new line re-draws
    clef/keysig/timesig; beams are now per-measure (don't cross barlines). No tempo yet -> falls back to the old
    count-based packing (16/line). Verified in-browser (Playwright setTimeSignature + StavePanel.push, no live
    keyboard needed): 3/4 with 6 notes @0.5s = 2 measures (2 staves) with 1 clef + 1 time sig + real barlines;
    4/4 12/16/20 notes -> 3/4/5 staves; count of clefs == number of stave lines (each new line re-draws clef);
    selector change persisted server-side, initial-state sync restores it; metronome starts/stops clean under 3/4;
    zero JS errors throughout. Fixed during dev: first measure was merging with the second (off-by-one) because
    the bar-change flush was gated on `measures.length` being non-zero; rewrote to flush whenever `bar !== curBar`.
    Committed agent:, pushed. Server restarted after edits.

- Ver 35b bugfix: MEASURE RENDERING REWORK ("doesn't move on to the next bar properly").
    The first Ver 35 implementation rendered EACH measure as its own fixed-width VF.Stave
    (STAVE_W / MEASURES_PER_LINE), each with its own voice. In this VexFlow 5 build
    voice.draw() renders note groups as SIBLINGS of the stave groups (not descendants of
    the g.vf-stave they were drawn on), so all the measures' notes piled up detached from
    their bar staves and looked like they never advanced to the next bar. Root cause:
    per-measure VF.Stave composition is not the right pattern here. Fix: idiomatic VexFlow
    measure rendering — ONE continuous VF.Stave per LINE with a single voice, inserting a
    `new VF.BarNote(VF.Barline.SINGLE)` tickable at each measure boundary inside the voice,
    `stave.setEndBarType(VF.Barline.END)` on the final bar, and building beams per-measure
    so they never cross a barline. Clef + key signature + time signature are drawn once per
    line (each new line re-draws them, like real sheet music). Line wrap stays bar-atomic:
    whole measures are packed per line up to NOTES_PER_LINE=16 noteheads (NEVER split a bar
    across a line). Removed the unused MEASURES_PER_LINE. Highlight of the newest line now
    colours the trailing noteheads by count (noteheads render flat in this build, so there
    is no per-measure group to query). Verified deterministically in-browser (setTimeSignature +
    StavePanel.push, tempo forced): 4/4, 8 quarters @0.5s -> 1 line, 8 noteheads, a barline
    cleanly between note 4 (x~688) and note 5 (x~859); 3/4, 9 notes -> barlines after every
    3rd note (x~652, 933); 40 sixteenths -> 3 lines each re-drawing clef+timesig, 5 barlines;
    time-sig selector change still persists + restores; zero JS errors. Live keyboard at
    100 BPM 4/4 rendered 119 noteheads across 6 lines with 16 barlines. Committed agent:,
    pushed. Lesson: for VexFlow 5 measure rendering use BarNote tickables in one voice, not
    multiple fixed-width VF.Stave boxes — separate-stave composition detaches notes from bars
    in this build.

- Ver 36: NILOTIC GREENHOUSE THEME. Rewrote monitor UI to follow the canonical "Nilotic
    Greenhouse" pattern (see ~/ai/knowledge/aesthetics.md — the pattern is the DEFINITION,
    copied from police/dashboard/app.py). Full triadic palette on the page: phthalo green
    (--phthalo #0B1F1A, deep #071310 page bg, card #143329, border #2A4F44, muted #8FB3A3),
    straw yellow (#F2E6A6 headings/flash-chord, soft #E8D9A0, gold #D4C47A ok/up),
    royal purple (#6B3FA0 interactive, bright #8A5BC7 bad/offline, soft #9B7ED8 interval/
    arpeggio highlight). Concrete pattern vocabulary applied: pinstriped + radial-glow
    phthalo-deep body bg; .card wedge borders (4px royal top+left, 2px straw-gold bottom,
    radius 2px, octagon clip-path, fractal-noise overlay, inset straw hairline, hover warms
    to royal-soft); pill card-heads (border-radius 999px, straw border on #08110E, straw->gold
    gradient "tab" nub via ::after on feed/keysec/mini heads); brass-sole buttons (royal
    border, 2px straw bottom edge, translucent royal fill, hover solid royal, :active pressed
    down 1px); chevron badges/status (clip-path arrow ends, royal-soft border, straw text;
    status online=straw-gold, offline=royal-bright per semantics gold=up/purple=down); striped
    sunrise header band (royal->straw->phthalo gradient, 6px straw left edge) with chevron
    badge "walled garden · 127.0.0.1:5050". Stave stays on CREDAM paper (#F0E8C8 = --text
    cream) bordered straw-gold + royal left, so black VexFlow notes stay readable inside the
    dark cards (the "sheet in the garden"). Piano white keys cream-ivory (#EFE7C8), black keys
    deep phthalo, active notes royal-soft/bright purple glow (interactive=royal). Feed coloring
    remapped: chord=straw, arpeggio=straw-soft, interval=royal-soft, program_change=straw-gold
    italic, off/statusline=muted. Stave highlightLastNoteheads color changed #4c9aff ->
    #9B7ED8 royal-soft (was hardcoded blue in stave.js). Verified live in browser: zero JS
    errors, all computed styles correct (phthalo-deep bg, pinstripes, card wedge/clip/radius,
    pill head radius+bg, badge chevron, straw text on h1/tempo/feed-chord, cream stave paper).
    Server restarted.
- Ver 37: EXPLICIT RECORD/STOP + REST NOTATION. Rests are now visible on the
  notation stave when pauses occur between notes. Backend: `State._split_note_rest()`
  compares the held release time against the inter-onset gap and the player's
  prevailing beat (median of recent durations) to decide whether the gap is a
  genuine pause (→ note value keeps prevailing, rest fills remainder) vs normal
  phrasing (full gap, no rest). `release` timestamps tracked in the pending group;
  `note_off` updates them. `_finalize_pending` now produces both NOTE and REST
  quantized entries (`rest:True`). `_robust_gap_duration` skips rests so tempo
  median is unaffected by silence. `POST /api/record` {recording:bool} toggles a
  `State.recording` flag (default True for continuity): OFF flushes the trailing
  pending note immediately, ON clears the quantized buffer for a fresh take; both
  paths drain + publish quantized events and return them in the response body so
  the client can render the tail without an SSE race. Frontend: `#record-btn`
  (● rec / ■ stop) toggle in `.stave-controls`; client `recording` state gates ALL
  `StavePanel.push` calls (notes, chords, arps, intervals, rests). `quantized_rest`
  SSE events push rest StaveNotes (durationToVexFlow + "r" suffix, keys ["b/4"]).
  `StavePanel.finishTake()` computes the next barline after the last event and fills
  the remainder with a rest, called when STOP is pressed. Button + dot CSS via
  `.record-btn`/`.record-dot` classes (recording ↔ not). Verified: backend unit
  tests (even-phrase quarters → 0 rests; 2s pause → 1.5s rest; sustained held → no
  rest; set_recording OFF flushes); frontend rest glyph renders (U+E4E5 quarter
  rest visible in SVG); REC/STOP toggle flips `recording` class and syncs with
  `/api/state` on reload. Committed agent:, pushed.
- Ver 37b bugfix: REST SPAM (a lot of small rests). Root cause: the pause
  threshold was gap > 1.5x the player's prevailing beat, so ordinary phrasing
  and timing jitter (a "longer" quarter, dotted values, a brief breath) split
  the note into a quarter + a 16th/eighth rest. Also the note was clamped to
  exactly one prevailing beat even when the player actually HELD the key longer
  (e.g. a held 1.2s note became 0.5 + rest). Fix in `_split_note_rest`:
  (a) threshold raised to gap > 2x the prevailing beat — everything <= 2 beats
  of spacing (dotted notes, halves, jitter) is normal phrasing and keeps its
  full time-to-next value, no rest; rests only appear for true pauses.
  (b) note_dur = min(gap, max(prev, snapped held)) so an actually-held-longer
  note keeps that value instead of being clamped to one beat.
  (c) rest slivers are floored at one grid step (sub-grid silence merges back
  into the note). _robust_gap_duration already excludes rests so the median
  beat can't be dragged down by the rests themselves. Also hardened
  monitor.sh: it now probes for a flask-capable python3 explicitly (the shell
  PATH can point at a venv with no flask, which made 'restart' fail with
  ModuleNotFoundError) — verified restart works. Verified via drive tests:
  1.5x and ~2x gaps -> 0 rests; 6-beat pause -> one 2.5s rest; jittery
  quarters 0.48-0.72 -> 0 rests; held-1.2s pause -> 1.125 note + rest;
  steady halves -> 0 rests. Server restarted; page loads with no JS errors.
  Committed agent:, pushed.
- Ver 38: TONIC & SCALE GUIDE + FULL-INTERVAL KEYBOARD + WIDER STAVES. The old
  "intended key" dropdown is gone. The keysec now has **tonic** + **scale**
  selectors (12 pitch classes x ~27 scales in optgroups: diatonic modes,
  minor & classical, pentatonic & blues, bebop, symmetric & exotic). Picking a
  tonic+scale:
  - **Shades** every key whose pitch class is in the scale (green-teal
    gradient; all octaves) and gold-tinges the tonic key.
  - **Labels EVERY key** with its interval from the tonic (`1, m2, M2, m3, M3,
    P4, TT, P5, m6, M6, m7, M7`). In-scale keys get a bright label (#123c2c on
    white / straw on black); **out-of-scale keys get a dimmed grey-blue-green
    label** (`#6e837b` white, `#5d746b` black) with the `.outscale` class, no
    shading — so the whole tonal map is visible while the scale still pops.
  - **Drives the stave key signature**: `StavePanel.setKey(PC_MAJOR[(tonicPc +
    sig) % 12])` where each scale def has a `sig` (offset to its parent MAJOR
    key); scales with `sig:null` (whole-tone, diminished, chromatic, exotic)
    set the stave to "auto" (no signature). Detected-key auto-path unchanged
    (inert). Verified in-browser via Playwright (no keyboard): G minor-pent
    shades pcs {7,10,0,2,5}, 88 labels, 37 inscale / 51 outscale; G4 tonic gold
    "1", G#4 dim "m2" with transparent bg; zero JS errors.
  - **Bigger keyboard**: key sizes moved to CSS vars — whites 30px x 190px,
    blacks 19px x 120px (was 15x110 / 9x66); `buildPiano()` reads --key-w /
    --key-bw from getComputedStyle so JS+CSS can't drift; octave labels moved
    to the top of each key.
  - **Staves stretched to keyboard width**: stave.js previously fixed the
    renderer at 800px / line at 720px. Now `canvasWidth()` sizes off the #piano
    keybed (+ X_START + right pad) and `staveWidth()` = that minus margins, so
    each stave line is EXACTLY the same width as the on-screen keyboard
    (verified: line 1580px = keybed 1580px). `notesPerLine()` scales the
    per-line note cap (~45px/notehead) so wider lines hold more notes instead of
    wrapping early with gaps. Fallback path keeps 800px if the piano isn't
    measured yet.
  Committed agent:, pushed.
- Ver 39: PLAYING COLOUR PRECEDENCE REORDERED + MINI-STAVE LAST-CHORD BOX + TONIC
  CATCH BUTTON. (a) `.active` keys now take precedence over `.inscale`/`.tonic`
  shades in CSS (guide shades no longer overwrite the played-note purple glow).
  (b) The keysec's mini stave now also hosts the `#flash` banner above it,
  formatted tighter (.mini-row, wrap at 560px). (c) NEW "♬ catch" button
  (`#listen-tonic`): listen for a few notes and auto-set the tonic + scale.
  `triadFromPcs()` in app.js maps a heard triad to a scale ("major"/"aeolian");
  playback notes are buffered (unique pcs) with a 900ms `resolveCatchBuffer`
  timer; a flash event with >=3 notes resolves a triad immediately; catch
  auto-unarms after 15s. Verified: catch guitar chord -> G major, C maj -> major,
  A min -> aeolian; single note -> tonic only (scale unchanged); sus4 -> no
  scale (honest gap). No residual state on unarm.
- Ver 40: TWO REGRESSION BUGFIXES. (a) NOTESTREAM CRASH — `_robust_gap_duration()`
  in state.py divides by `self.tempo_bpm` (beat = 60/bpm); when tempo_bpm is
  still 0 (tempo needs ~6+ onsets but quantized history already exists) it threw
  ZeroDivisionError from the rest-notation path, crashing the capture thread and
  making the page look frozen. Added `if self.tempo_bpm <= 0: return None` guard
  (verified all tempo divisions guarded). Also capture.py now terminates its own
  aseqdump subprocess via new `_stop()` (used in `__iter__` finally) so a crashed
  capture loop no longer leaks zombie aseqdumps. (b) CATCH NOT FIRING FOR SINGLE
  NOTES — app.js line ~312 assigned `catchLast = ev.name` but `catchLast` was
  never declared; in `"use strict"` this throws ReferenceError on EVERY note
  event, aborting before `resolveCatchBuffer`'s setTimeout was scheduled. Chords
  still worked because they resolve via the flash path (which calls resolveCatch
  directly). Deleted the dead `catchLast` line; single-note catch now sets tonic
  only (verified live: C4 -> tonic C, scale untouched).
  Committed agent:, pushed.
- Ver 41: WACKY CHORD -> WACKY SCALE CATCHES (DATA ENTRY). The catch button is
  explicitly a DATA-ENTRY tool, not key detection (user: "essentially a data
  entry thing"), so mappings were made generous. `chordFromPcs()` in app.js now
  matches a played pc-set against the `CATCH_SHAPES` table (subset-tolerant:
  the played set may CONTAIN a shape; longer/more-specific shapes win; then
  table order). Bass-pc is a GLOBAL tiebreak (+1000 score when the shape's root
  equals the lowest heard pc) so musically-valid alternative roots resolve to
  what was actually played: Cm6 = Am7b5 as C dorian only when bass is C, Cadd9
  stays C major-pent not A minor-pent, C7#11 stays lydian-dominant not F#7alt.
  New 5-6 tone shapes: 7alt->super_locrian, 7b9->phrygian_dominant,
  7#11/7b5->lydian_dominant, m7b9->phrygian, m9->dorian, dom9->mixolydian,
  add9->major_pent, 5/6-tone minor_pent/blues/hirajoshi/whole_tone hex rec,
  7#5->whole_tone, mMaj7#5->harmonic_major. Vanilla major/aeolian remain ONLY
  settable by a bare triad; aug->whole_tone stays the one special 3-note case;
  sus4 -> no scale (tonic only). Verified: 28-case headless + live C7b9 flash
  -> phrygian_dominant, C7#11 -> lydian_dominant, C9 -> mixolydian.
  Committed agent:, pushed.
- Ver 42: CLICKABLE PIANO INJECTS MIDI + TEMPO CARD + CATCH TABLE TOOLTIP.
  (a) ON-SCREEN KEYBOARD PLAYS: pointerdown/pointerup on the 88-key piano now
  injects synthetic note_on/note_off into the notestream via new POST /api/note.
  Notes are queued onto the LIVE Capture instance (`_capture_instance` global,
  set by the supervisor thread) through `Capture.inject_note()`, stamped with
  the capture-relative clock, and drained by the capture loop BEFORE the
  offline/reconnect branch — so they ride the SAME pipeline as real MIDI:
  state/analyser/quantization/SSE/stave/catch. Velocity is imputed (const 90);
  the note_on duration is honest time-to-note_off. Frontend: `bindPianoClick()`
  sends one POST per press and one per release (per-pointerId map so drags &
  multitouch release correctly; `mouseHeld` guard blocks double-on; primary
  button only). Works even with no keyboard attached (injection is network
  traffic, not MIDI). Verified: click -> feed "C4 on (v90)"/"C4 off", key
  lights purple during press, and clicking a C-E-G roll with catch armed
  flashes "ARP: C4 maj" and sets tonic C + major. (b) TEMPO CARD:
  the tempo/metronome/time-signature controls MOVED OUT of the header into a
  `#tempo-card` ("tempo & meter") that sits in a `.control-row` flex LEFT of
  the "tonic & scale" card — neither card is full-width anymore (tempo-card
  flex 1 1 300px, keysec flex 2 1 420px, wrap on narrow screens). Header is
  just title/badge/status/instrument again. All IDs kept (#tempo-input, #tempo-
  tag, #tempo-detected, #metronome-btn, #metro-beat, #timesig) so JS handlers
  work unchanged; `renderTempo()` guard switched from the deleted `#tempo` div
  to `#tempo-input`. CSS: `.control-row`/`.tempo-card`/`.tempo-card-body`/
  `.tempo-row` replace the old `#tempo` rules. (c) CATCH TABLE TOOLTIP:
  a `?` button (`#catch-help`) in the tonic & scale pill-head and a
  `#catch-tooltip` popover document the catch mappings. The table is rendered
  from `CATCH_SHAPES`/`CATCH_MODE_NAMES` at load (`buildCatchTooltip()`) so the
  docs can never drift from the data; shows on hover/focus (CSS) and toggles on
  click (.show). Footer notes the honest edges: vanillas only via bare triad,
  aug->whole tone, lone note = tonic only, loose subset matching, bass breaks
  symmetric ties. Verified: tooltip hover shows all 22 shapes in a table + foot,
  click toggles; timesig 3/4 + fixed-tempo 100 still persist server-side from
  the relocated controls; zero JS errors/warnings. Committed agent:, pushed.
