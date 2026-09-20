# MIDI Monitor Changelog

Running log of every change to this project. Transposed out of AGENTS.md to keep
that file lean. History is chronological; most lines start with a version tag.

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
- Ver 43: CATCH TOOLTIP FIXES (stacking + explain-the-chords).
  (a) STACKING: the tooltip previously lived INSIDE `.keysec.card`, whose
  `clip-path` polygon technically trims descendants and whose stack order sat
  below later cards — so the popover was "swallowed"/clipped by the cards below
  it. Fix: `#catch-tooltip` moved OUT of the card to be a direct child of
  `<body>`, styled `position: fixed` with `z-index: 9999` so nothing can paint
  above it or clip it. All show/hide is now JS-driven (CSS sibling `:hover+
  .show` selectors were removed): hover-in shows (with a 220ms delayed hide on
  mouseleave), click PINPINS the tooltip open (stays open even when the pointer
  leaves; handled via a `wasToggled` flag), click-again or any pointerdown
  OUTSIDE the button/tooltip dismisses, and the tooltip re-positions (right-
  edge flush with the button, hangs below; flips ABOVE when it would run off
  the bottom) on open and on window resize. Verified via elementFromPoint:
  at a probe point overlapping the stave card's bounding box the topmost
  painted element is a `.civ` cell inside `#catch-tooltip` — the popover now
  truly renders above the cards. All hover/click/outside-dismiss state
  transitions verified; console clean. (b) CONTENT: every `CATCH_SHAPES` row
  grew a plain-language `note` field, and the table now has THREE columns:
  `chord | tones from root | scale`. The tones column is computed from each
  shape's `semis` through the SAME `INTERVAL_NAMES` vocabulary the keyboard
  labels use (1 m2 M2 m3 M3 P4 TT P5 m6 M6 m7 M7), so "hirajoshi" reads as
  `1 M2 m3 P5 m6` next to a one-line description ("Japanese pentatonic — the In
  scale…"), "7alt" explains it's every colour-tone crammed in (b9 #9 3 b5 b7),
  etc. Footer now spells out the interval abbreviations (m2=flat 2nd, TT=
  tritone, M7=major 7…), keeps the honest edges, and notes the bass tiebreak
  in concrete terms (Cmaj9 vs Am11 pick what you played). Tooltip widened to
  500px with `table-layout: fixed` column widths; max-height 64vh scrolls the
  long table. Verified: all 22 rows render with spellings + descriptions,
  scrollHeight 1680 > clientHeight 808 (scrolls), foot text correct, node
   --check clean, server restarted. Committed agent:, pushed.
- Ver 44: TOOLTIP REVERSED TO SCALE-FIRST (DATA-ENTRY DIRECTION). The table
  now reads "want this scale → play this chord" instead of the opposite, since
  the catch button is a data-entry tool ("i want this scale, what chord do
  i play?"). Reversed: `CATCH_SHAPES` stays as the matching engine (unchanged
  detection logic); the tooltip builder regroups shapes BY TARGET SCALE,
  sorted alphabetically by pretty scale name (Blues → Dorian → Mixolydian →
  … → Whole tone). Each scale row has a two-column layout: `scale` (name +
  italic plain-language description) | `any of these catches it` (inline
  chord picks, simplest first — fewest tones before extensions; each pick is
  `m7 (1 m3 P5 m7)` format). Per-scale descriptions keyed in a new
  `CATCH_NOTES` map (no longer on individual shapes), written from the
  "what does this scale sound like?" angle: "Dorian — the brighter minor: a
  natural 6th, 1 2 ♭3 4 5 6 ♭7"; "Hirajoshi — Japanese pentatonic, the In
  scale: 1 2 ♭3 5 ♭6, a minor-ish colour that is not Western minor"; "Altered
  dominant — every colour-tone: 1 ♭9 ♯9 3 ♭5 ♯5 ♭7", etc. Footer rewritten
  as "How to enter: set the tonic, press ♬ catch, then play one of the
  chords in that scale's row" + interval abbreviations + honest edges.
  Tooltip stacking unchanged (position:fixed/z:9999/child of body). CSS:
  `.cscale`/`.cplay`/`.pick` replace old `.cshape`/`.civ`/`.cmode` rules;
  two column widths `c-scale-col:46%`/`c-play-col:54%`. Verified: 16 scales,
  22 picks total, sorted alphabetically, scrollHeight 1091 > clientHeight
  (scrolls), topIsTooltip true via elementFromPoint, console 0 errors.
  Committed agent:, pushed.
- Ver 45: TOOLTIP = FULL DROPDOWN LIST (SAME ORDER) + EXPLICIT GAPS. The
  tooltip's ordering is now the DROPDOWN's ordering, by construction:
  `buildCatchTooltip()` walks the live `#key-scale` <select> DOM (optgroups +
  options) and emits one row per scale-group in the menu's exact sequence
  (Diatonic modes / Minor & classical / Pentatonic & blues / Bebop / Symmetric
  & exotic) — so if the menu is ever reordered, the tooltip follows
  automatically. Scale labels also come from the <option> text (single source
  of truth; old `CATCH_MODE_NAMES` map deleted). Every one of the 28 dropdown
  scales now appears. Scales that have a catch chord show their picks
  (`CATCH_SHAPES` grouped by target scale + bare-triads faked in for
  major/aeolian so those two don't read as gaps); scales with NO catch chord
  render a muted `∅ no chord shape yet — pick it from the menu` row, and the
  footer defines that marker ("these are scale colours, not chord colours").
  GAP-FILLING IS DELIBERATELY DEFERRED: no new shapes added yet — the 10 gap
  scales (melodic_minor, double_harmonic, bebop_major, bebop_dominant,
  bebop_dorian, chromatic, enigmatic, hungarian_minor, neapolitan_major,
  neapolitan_minor) are acknowledged but not yet catchable; user will review
  gap-filling separately. CSS: `.tt-group` header rows (straw-gold uppercase)
  + `.none` (muted italic gap note). Removed `.cshape/.civ/.cmode` leftovers.
  Verified: 34 table rows = 28 scale rows + 5 group headers + 1 header row,
  10 `.none` gaps in the right places, order matches menu exactly, topIsTooltip
  still true, scrollHeight 1530 > clientHeight 808, 0 console errors. Server
  restarted. Committed agent:, pushed.
- Ver 46: CHROMATIC = FIRST NON-TRIADIC 3-NOTE CATCH (pin in it). After analysis
  of which gap scales could be caught by a 3-tone input, the "common scales must
  stay the easiest" rule was kept: it only makes sense for chromatic (arguably
  more fundamental than any mode) — giving bebop_dorian (1-♭3-3) or
  neapolitan_major (1-♭2-6) a 3-note catch would make exotic scales EASIER to
  enter than dorian/mixolydian (m7/dom7 = 4 notes), inverting the hierarchy.
  Implementation: new `chrom` shape `semis:[0,1,2]` -> chromatic in CATCH_SHAPES
  (3-tone section, comment explains the one-exception policy); `chordFromPcs`
  match guard lowered from `uniq.length >= 4` to `>= 3`. Nothing else
  regressed — verified exhaustive: chrom cluster at any root resolves
  chromatic; major/minor/aug triads still fall through to their own 3-note
  paths (returning null from shapes so the triad path runs); a 4+ chord
  CONTAINING the cluster {0,1,2,4,7,10,7} still resolves phrygian_dominant (7b9,
  longer wins) and Cadd9 stays major_pent with bass tiebreak; gap scales remain
  unfilled (melodic_minor, double_harmonic, bebop_*, enigmatic, hungarian_minor,
  neapolitan_* still show ∅). Tooltip: chromatic row now shows `chrom (1 m2 M2)`
  + a CATCH_NOTES description ("all twelve tones... the root, its ♭2, and its 2
  stacked together"); gap count 10 -> 9. LIVE verified via piano-injection:
  catch armed + C–C♯–D cluster -> tonic C + chromatic scale; C–E–G still ->
  major (no hijack). Console 0 errors. Committed agent:, pushed.
- Hw: PSS-A50 IS BIDIRECTIONAL (receive confirmed). Live-tested from the shell:
  `amidi -p hw:2,0,0 -S '90 3C 7F 40 7F 43 7F'` (C4-E4-G4 note-ons) sounded a full
  C major triad through the board's speakers, then note-offs silenced it. USB
  descriptor shows both MIDI streaming endpoints (EP1 OUT host->device,
  EP2 IN device->host); `amidi -l` lists hw:2,0,0 as IO. Consequence: ALSA seq
  still only exposes capture port 24:0 (no seq output port), so sending must go
  to the raw device hw:2,0,0. The board plays its INTERNAL voices on received
  MIDI — no softsynth/fluidsynth needed; this is the cheap "output" path (replay
  a recorded take back through the keyboard). Also noted: LOCAL CONTROL setting
  exists on the board — leave ON for pure capture; flip OFF only for
  pass-through/echo modes to avoid double sounding. Docs updated (AGENTS.md
  Hardware section). Committed agent:, pushed.
- Ver 47: midiout.py glue script (stdlib only). Every playback test so far had
  been hand-typed amidi hex; folded the whole send path into one repeatable
  tool. Commands: `voices` (all 42, bank/pc), `voice "Name"` (fuzzy; always
  sends bank-select + program change so drum-kit/normal swaps can't leave the
  board on the wrong bank), `note C4 [vel] [dur]`, `chord "C4 E4 G4" ...`,
  `seq "C4 E4 G4 C5"` (one note per beat, --bpm), `seq-file TAKE.txt`
  (lines `note dur` / rests `r 0.5`), `alloff` (CC123 panic). Note-name parsing
  (C4, D#3, Bb2), drums via GM numbers. Debuted with a demo take
  `examples/take-frag.txt` (C-E-G rests + finish on C5). Verified live: voice
  swaps (incl. drum kit -> piano bank restore), single note, chord, melody seq,
  seq-file playback, panic reset. Found+fixed one indexing bug in seq-file
  during testing. Committed agent:, pushed.
- Ver 48: REPLAY = FROZEN TAKE. The replay endpoint now plays the notation
  buffer (the take) instead of the live quantized stream. Backend: state.py
  gains `take_notes` — cleared on REC, mirrors finalized quantized notes
  (including rests) while recording, frozen on STOP. app.py /api/replay now
  reads state.take_notes; replay stops automatically if keyboard goes offline.
  Frontend: "▶ play take" button in stave controls; toggles to "stop" while
  active; SSE "replay" events drive key flashes (step) and feed lines
  (start/done/stopped/error). Stave and replay now always show/play the
  same frozen take. Live verified: REC C-E-G + next note + STOP → 4 notes in
  take → PLAY → C-E-G-D sounds back correctly.
- Ver 49: RAW MIDI BUFFER CARD. Added a "raw midi buffer" card to the main
  area that fetches /api/take and renders the stored note_on/note_off events
  (index, time, kind, channel, note, velocity) in a monospace panel with a
  clear button and periodic refresh. Backend /api/take returns the
  raw_take_events buffer and recording state.
- Ver 50: raw midi buffer card clear fix. Backend POST /api/take/clear now properly
  empties state.raw_take_events; frontend clearRawTake() posts to endpoint, shows
  cleared state, and resumes polling to pick up new events after clearing.
- Ver 51: voice-memory clarification. Verified from the PSS-A50 MIDI reference that
  incoming program changes update the receive voice (used for playback of stored/
  received MIDI), while the panel voice (used for keys pressed on the keyboard) is
  maintained. UI now labels the "auto" option as "auto (current receive voice)";
  MIDIREF.md updated to describe the two voice settings and mark the receive-voice
  behavior as verified. Backend/replay code unchanged; auto already leaves the receive
  voice untouched so "auto" inherits the current receive voice.
- Ver 52: voice selector for playback. Added a voice dropdown (42 PSS-A50 voices +
  "auto") to the replay controls. Selecting a specific voice sends a program change
  before playback; "auto" uses the current receive voice (no program change). The
  dropdown reorders at load time so the current receive voice is first, "auto" second,
  then the remaining voices. State tracks receive_program/receive_bank separately from
  panel program/bank. MIDIREF.md updated with verified notes from pssa50_en_om_e0.pdf.
  Manuals added to .gitignore.
- Hw: MIDIREF.MD created from pssa50_en_mr_a0.pdf (channel routing, Local
  Control, program/control change, SysEx, implementation chart, live USB
  profile, voices table, send-path helpers, open questions).
- Ver 53: emergency server reset + shared raw-buffer styling. Root cause of the
  frozen-while-keyboard-on page: stale monitor.app/aseqdump instances were
  holding :5050 (supervisor log "Port 5050 is in use") and a leftover aseqdump
  kept the UI reporting "online". Added a red "reset server" button in the
  header: POST /api/reset spawns "bash monitor.sh reset" detached, which sleeps
  1s (lets the HTTP response flush), kills supervisor first, then monitor.app +
  aseqdump, removes pidfiles, and starts fresh. Verified end-to-end (curl +
  real click): new PID, one aseqdump, online again.
  Raw midi buffer reworked to mirror the note stream exactly: same li classes
  ("on"/"off"), the .time + .nmark spans and "on (vXX)"/"off" text, so both
  panels share the same straw/green look (note names straw-soft, off lines
  muted-green). Moved out of the bottom of the main area into a new 240px
  middle column between the note stream and the last-chord card, scrollable.
  Scrollbars all themed for Nilotic Greenhouse: phthalo-green tracks,
  straw-gold-bordered thumbs (purple on hover), webkit + Firefox variants.
  Reset-server button also doubles as the recovery path for "site won't come
  back after keyboard on".
- Ver 54: left column stacked (note stream half-height, raw buffer under it)
  + raw buffer owns record/play/clear + single clear path + playback
  highlighting. Layout is now 2 columns (280px 1fr): the left column stacks
  the note stream (top half) over the raw midi buffer (bottom half), each
  half scrolls internally. REC/STOP, play take and the voice selector moved
  out of the notation card into the raw buffer card (the buffer is the
  source take; notation will be derived from it). Clearing rationalised to
  ONE button: raw buffer clear wipes the raw buffer (API) plus the derived
  notation and the note stream; stave-clear and feed-clear buttons removed.
  During replay each sounded raw entry goes bold (li.playing, straw wash)
  via a monotonic cursor matching step note numbers to data-note entries;
  raw polling pauses mid-replay so highlights aren't wiped, cursor resets on
  start/render. Verified live: stacked half-height cards, unique control IDs,
  clear/stop/rec all functional (replay 400 on empty take is the expected
  backend reject), highlight algorithm unit-checked in-page (chord marks in
  order, repeated notes advance past offs, offs never marked).
- Ver 55: stream owns its clear again, purple playback highlight, replay
  voice tracks the keyboard. The note stream got its own clear button back
  (stream display only); the raw card's clear now wipes just the buffer +
  derived notation, so each clear owns its own territory. Replay step
  highlighting moved from straw to royal purple (bold + purple wash +
  purple note name; purple was otherwise unused in the raw buffer). The
  replay voice default now follows the keyboard's receive voice live: every
  program_change (the same event feeding the title-bar instrument label)
  re-points the selector via orderReplayVoices — unless the user hand-picked
  a non-auto voice, in which case the default stays pinned until "auto" is
  chosen again. Verified live: clear split (stream survives raw clear, dies
  on its own), purple computed styles, voice selector ordered to the live
  receive voice at load, zero console errors.
- Ver 56: notation card rendered FROM the raw buffer. New
  State.notation_from_buffer() replays raw_take_events through a scratch
  State (same grid anchor, same pending-group pipeline as live capture)
  with tempo/divisions locked to current values — no live-state pollution,
  no thread leaks (checked). Simultaneous onsets group into chords (3+,
  chords.name_only label) / intervals (dyads, chords.interval_of);
  same-pitch re-strikes in one tick dedupe to a single note. New GET
  /api/notation returns the events + tempo/TS/divisions. Frontend
  renderNotationFromBuffer() clears + pushes + finishTake; wired to STOP,
  quant, time-sig and tempo changes (all re-render instead of wiping);
  live StavePanel.push paths removed (flash keeps banner + mini stave,
  quantized SSE keeps tempo display). Verified live with the keyboard:
  quant change rendered full notation from a 39-row buffer (89 paths),
  STOP/time-sig/REC all re-render correctly, zero console errors.
- Ver 57: RAW -> quantizer BOX -> OUT chain. New canonical transform output:
  State.requantize() rebuilds quantized_take + transformed_events (MIDI
  on/off expansion, rests dropped) on demand, so notation and playback hear
  the same take. Bypass ("no quantization", quant select now offers off):
  exact on/off pairs matched from raw, no rests, hanging notes closed at
  buffer end. New chain row under the control row, above notation:
  transform card (quant select incl. off, in->out counts, grid status like
  "16ths @ 120bpm" / "bypass - exact timing") + out card (play take + voice
  moved out of the raw card; REC/STOP/clear stay on raw as input controls).
  /api/replay now plays the transformed buffer (gate moved with it — this
  also fixes stale replays after a raw clear, which used to fall back to
  old take_notes); /api/notation serves the canonical take + counts with an
  unchanged event shape; /api/quant accepts 0 (validated 0-16); wipes
  (REC-start, raw clear) drop the transform output too; page load restores
  stave + chain status from a surviving buffer. Two real bugs found live
  while testing bypass: (1) fast legato runs grouped into intervals under
  the 90ms window, blanking the stave with intervals hidden — bypass
  grouping now needs overlap + tighter 50ms window; (2) stave renderer went
  stale (placeholder/empty renders kept drawing into a detached SVG, and a
  stale placeholder could linger) — renderer/context now reset on empty
  renders and placeholders are removed on redraw. Verified live with the
  keyboard: quantized + bypass replays both sound with purple step
  highlighting, counts track (in 370 -> out 370 bypass), chord labels
  survive, zero console errors.
- Ver 58: quantization grid extended to 0.25 (whole notes) and coarser (half, 8th, 16th, 32nd, 64th); replaced loose/normal/tight labels with explicit values; stave tint now uses event->heads map (headsForEvent) to recolour playback notes regardless of VexFlow id propagation; key change re-render confirmed via tonic+scale selector
- Ver 59: stave tint now uses eventHeadMap built during render (placeAccidentals called with recordMap=true) so playback purple works regardless of VexFlow id propagation; headsForEvent skips rest events; project renamed to Abora in title/header
- Ver 60: VELOCITY COMPRESSOR + HUMANIZER + STOP/LOOP REPLAY BUTTONS. Added velocity compressor stage (after quantization/transposition, before expansion) with threshold/compress modes and auto-detect standard velocity. Added humanizer stage (at end of chain) with ±timing_ms and ±velocity jitter for organic feel. Enhanced replay controls with dedicated STOP (immediate halt) and LOOP (continuous repeat until stopped) buttons alongside voice selector. All features integrate into existing transform chain and expose via /api/velocity, /api/humanizer, /api/replay/loop endpoints with real-time UI sync.
- Ver 61: UI POLISH — nilotic cartouches, op-stage transform card, restart-on-play.
  Every card title is now an official cartouche: unified .cartouche pill with the
  straw bar on the right (::after nub) on ALL nine headers (note stream, raw midi
  buffer, keyboard, tempo & meter, tonic & scale, transform, out, notation, last
  chord/interval) — stave-head bar restored, chain-head + raw-take-head gained
  theirs. Each cartouche carries a small circular medallion icon (28px straw-gold
  ring, phthalo radial fill, inline SVG glyph: notes/midi/piano/metro/key/
  sliders/out/staff/spark) matching the walled-garden dashboard idiom.
  The transform card now reads as FOUR distinct stages, each in its own .op
  module with a labelled cartouche head (dot + uppercase title), its own accent
  from the triadic palette (quantize royal / transpose straw-gold / velocity
  royal-bright / humanize straw) and dashed divider: quantize (grid + live chain
  status), transpose (semitones), velocity (compress checkbox, std/detect, width,
  mode), humanize (on/timing/vel). Duplicate humanizer control removed from the
  tempo card (was clashing duplicate IDs); snapshot now syncs humanizer enabled/
  timing/velocity to the single UI instance. Base select restyled to match the
  reference (appearance:none, custom straw chevron, ui-monospace, straw-soft on
  phthalo); timesig/keysec/stave select overrides merged down.
  The out card play button is now a simple ▶ play that RESTARTS from the
  beginning when pressed while a take is sounding (stop-then-start); the label no
  longer flips to "stop", so STOP stays the dedicated halt control (crimson
  danger styling) and LOOP gets a straw "armed" state. Section labels
  (capture / interpret & tune / transform & play) added above the card rows.
  Piano scrollwrapped (.piano-scroll) so its cartouche no longer scrolls with
  the keys. Verified live in the browser: zero console errors, all 9 cartouches
  bar-nubbed, all 9 icons present, no duplicate ids, catch-tooltip still works.
  Committed agent:, pushed.
- Ver 62: MIDI SPAGHETTI ZONE — replay now routes to a chosen mix of ALSA
  sequencer destinations + raw device(s). Root problem: replay used amidi
  to hw:2,0,0 (rawmidi, sounds keyboard internal voices) which BYPASSES the
  ALSA sequencer, so VCV Rack etc never heard playback. New monitor/midiout.py
  talks to libasound through ctypes (no pip libs available): snd_seq_open
  OUTPUT mode, big pool, explicit per-event dest addressing (no aconnect
  subscriptions needed). Kernel event struct mapped exactly (type is c_ubyte;
  snd_seq_event_output returns a BYTE COUNT, not 0 — rc<0 is the only error).
  Replay holds seq_targets + raw_devices + channel, opens a fresh SeqOut
  ("Abora Out") per run when seq targets are ticked, sends program change +
  notes + all-notes-off. /api/outs GET lists available sinks (aconnect -o
  parse: Midi Through 14:0, Digital Keyboard 24:0, VCV Rack 131:0,
  aseqdump) + current routing; POST sets seq_outs/raw_outs/channel (unknown
  seq targets dropped, channel clamped 0-15). Boot default: auto-tick VCV
  Rack if present + keep keyboard raw always (raw list server-managed,
  locked checkbox in UI). Out card renamed "out · midi", gains "route to"
  checkbox list. Replay no longer requires keyboard online (any ticked dest
  suffices). Verified: notes + Warm Pad PC echoed through Midi Through via
  web replay; zero JS errors; VCV 131:0 receives (write success; input port
  not dump-able with aseqdump by design). Committed agent:, pushed.
- Ver 63: VCV LAUNCH BUTTON in the out card's "route to" block. /api/vcv GET
  reports running (detected as an ALSA sink by name) + cmd path; POST
  /api/vcv/launch spawns /home/pthag/Musica/Rack/Rack detached (own session,
  survives the server) iff it isn't already up, guarded by a launch lock so
  double-clicks can't double-spawn while it boots. Button states: "▶ launch
  vcv" (down), "… launching" (busy), "✓ vcv is up" (detected); polls every
  10s to stay honest + 1.5s during launch, and when VCV first appears the
  destination list reloads so its checkbox shows up (and follows server
  routing) without a page reload. Clicking while up is a no-op. Verified
  live: launched Rack from a cold state via the endpoint, detected as
  running ~4s later; zero JS console errors.
- Ver 64: DATA-DRIVEN DESTINATIONS — the out box's launch buttons are no longer
  VCV-specific. New monitor/sinks.py is a registry of launchable MIDI apps; one
  dict entry (key, name, cmd, cwd, detect, auto_route) is all a new DAW needs.
  Detection is generic (any aconnect -o client name substring from `detect`),
  launching is generic (detached subprocess, per-key lock against double-
  spawn), boot auto-routing is generic (auto_route entries present at boot get
  ticked). /api/sinks GET + /api/sinks/<key>/launch POST replace /api/vcv
  (kept as backward-compat aliases). UI: #launchable-apps renders one
  .app-launch-btn per registry entry from /api/sinks, generic busy/running
  paint + 10s honesty poll + post-launch sink-list reload (checkbox appears
  without page reload). Verified: /api/sinks/vcv/launch spawned Rack from
  cold; boot reset with VCV up auto-ticked 131:0; old /api/vcv alias still
  answers; zero JS console errors. Committed agent:, pushed.

- Ver 65: PATTERN LIBRARY — save + load the raw (IN) and out (OUT) buffers
  as named patterns. New monitor/patterns.py: JSON files in the gitignored
  patterns/ dir (one per pattern), atomic write, slug-sanitized filenames
  (path-traversal safe). A pattern = the events list (raw_take_events or
  transformed_events — same note_on/note_off shape) PLUS the transform-chain
  settings snapshot, so an OUT pattern replays exactly as saved even if the
  chain was changed in between.
  State gains settings_snapshot() + apply_settings() (bounds-checked
  per-field restore of quantize/transpose/velocity/humanizer/tempo/timesig/
  midi_channel). Endpoints: GET /api/patterns (list), POST /api/patterns
  (save raw|out; "save out" auto-derives the OUT side via requantize if the
  buffer is untouched), POST /api/patterns/<slug>/load (restores events +
  settings into the raw buffer and requantizes), DELETE /api/patterns/<slug>.
  Raw midi buffer card gains a pattern strip: name input, save raw / save
  out buttons, a select of saved patterns + load/del, and a status line;
  loading shows "… reloading" then a full page reload so every control
  re-syncs to the restored settings (no settings-sync parser needed).
  Verified: save/load/delete via HTTP and UI, settings restored on load
  (transpose 5 probe), empty-buffer/empty-library guards, slug sanitization;
  zero JS console errors. Committed agent:, pushed.

- Ver 66: RELEASE ARTICULATION — fix quantized-note ring-overlap (the root
  cause of "notes continuing when it's time for a new one"). Quantized notes
  extend their duration to the next grid onset; when the player's raw timing
  isn't an exact grid multiple the extended duration overshoots the true next
  attack → two notes sounding simultaneously, especially audible on pad/sustained
  voices through the keyboard's own synth.
  State gains articulation_gap (fraction 0..0.9 of the slot left SILENT before
  the next attack) with set_articulation() and _apply_articulation(notes) — a
  post-pass over quantized takes: no note's off_time may ever exceed the next
  note's on_time (hard clamp at gap=0; at higher gaps each note ends early for
  staccato articulation). Chord members (same on_time) are never pruned against
  each other. The pass sits in requantize() before _expand_midi, so notation,
  replay (amidi + seq) and the stave all reflect the clamp.
  Verified offline: the exact earlier overlap failure (51ms on 67→9, 118ms on a
  sub-grid chord roll) now produces zero overlaps at gap=0, and clean 60%
  trimmed staccato durations at gap=0.3; live UI end-to-end: input →
  /api/articulation → requantize → notation re-render, boot-sync from /api/state,
  zero JS console errors. New: state.py _apply_articulation + set_articulation,
  app.py POST /api/articulation, index.html release spinbutton in the quantize
  module, app.js change handler + initial state sync. Committed agent:, pushed.

- Ver 66b: RELEASE-ARTICULATION REGRESSION FIX — the Ver 66 clamp destroyed
  real chords in the NO-QUANTIZE (bypass) path. Symptom (user report): played
  a chord with natural 1-8ms roll; in the bypass path the take's first two
  members rendered as 1ms blips while only the last-struck note kept its true
  ~1.85s duration. Root cause: _apply_articulation walked notes sorted by
  on_time and treated each later-struck chord member as a "successor attack"
  to clamp against, cutting every member whose onset was a few ms after the
  previous one. It only handled chords with byte-identical on_times.
  Fix: (1) the pass now returns early when quantize_enabled is False — in the
  bypass path the take already carries the player's real durations, chords
  legitimately overlap, and a clamp is destructive (the release-gap knob is a
  grid/articulation concept and stays off-grid too); (2) in the gridded path
  the walker groups notes struck within a 100ms ROLL_WINDOW and still sounding
  as CHORD MEMBERS — they keep true durations and are only capped/trimmed
  against the NEXT group's attack, never against each other. Monophonic
  successive notes still cut the previous note (Ver 66's guarantee preserved:
  the gridded 67→69 extension-overlap still clamps to zero overlap).
  Verified offline on the user's exact 4-chord raw data (bypass: all 12 notes
  keep 1.5-1.9s durations, zero blips), plus gridded roll-chord (4 members kept
  0.5s, no blips) and gridded monophonic overlap (clamped). Live round-trip
  reaffirmed; zero JS console errors. Committed agent:, pushed.

- Ver 67: OUT CONTROL SURFACE (interface-level, not qwerty) — send and watch
  the keyboard's extra control messages over the same USB on hw:2,0,0.
  replay.py: control_change(cc,value), pitch_bend(semitones), gm_system_on(),
  midi_panic() (all-ch GUI 120/123 + ch1 121) via amidi. state.py: received_ctrl,
  received_pitch_bend (14-bit -> ±24 semi), control_values, control_pitch_bend,
  local_control, all in snapshot(). app.py: POST /api/ctrl ({"cc","value"},
  {"pitch"}, {"action":"panic"|"gmreset"|"local","value"}), GET returns
  out/received; capture loop publishes throttled "ctrl"/"pitch" SSE events.
  UI: "out · ctrl" card — panic, gm reset, sustain (CC64), portamento (CC65),
  porta time (CC5), volume (CC7), expression (CC11), mod (CC1), pitch bend
  (-24..24), local control (CC122); #ctrl-received readout shows what the
  KEYBOARD transmits back. Live first probe: keyboard shipped CCs 6/11/71/72/
  74/100/101 (voice-load RPN + sound controllers), sustain/pitch round-trips
  updated out state. Committed agent:, pushed.

- Ver 68: LAST CHORD/INTERVAL CARD SHRUNK + PARKED BESIDE THE KEYBOARD —
  the mini "last chord / interval" stave moved out of the bottom row into a
  top flex row right next to the piano card. It renders only a single
  chord/interval, so the full 520px stave line was pure waste; redrawMini now
  draws one ~130px bar (VexFlow Stave(10,20,130)) in a 190px canvas, card
  width 560 -> 220px, so the piano keeps the full remaining width (same row,
  verified 220px card / piano fills the rest). The big stave/notation, record/
  stop and flash logic untouched. Added out-ctrl wiring (ranges/checks/buttons
  -> POST /api/ctrl) + boot-sync; removed a stale merge-artifact comment in
  app.js. Zero JS console errors on fresh load + clear. Committed agent:,
  pushed.

- Ver 69: CONTROL SURFACE ROBUSTNESS + FEEDBACK — "buttons not working"
  investigation. Root cause was a 1-line bug: replay._send() raised
  CalledProcessError when amidi hit a transiently-absent device (board
  unplugged/replug handling is NORMAL per AGENTS.md), so POST /api/ctrl
  returned a 500 on the very send the user was testing and the frontend
  swallowed it silently -> controls appeared dead. Fix: _send() never
  raises; returns bool. replay helpers (control_change/pitch_bend/
  gm_system_on/midi_panic/program_change) pass it through. /api/ctrl
  records the intent in state even when the board is off, returns
  {"ok":true,"device":false,"warning":...} instead of a crash; GET now
  reports "device". UI: every control send posts a "SENT -> ..." feed
  line + a status flash in the card ("keyboard offline - dropped" when
  the board is gone). Verified: valid amidi -> device:true, bogus hex ->
  graceful False, gm reset + sliders round-trip with SENT feed lines,
  zero 500s. Committed agent:, pushed.

- Ver 70: LIVE ECHO MODE + COUPLED KEYS ROUTING + PITCH SNAP —
  "sustain button does nothing" root cause was NOT our code: the PSS-A50
  applies incoming program change / CC (incl. sustain CC64) / pitch bend to
  RECEIVED (MIDI-IN) notes ONLY. Local keybed sound bypasses the MIDI-IN
  control path. Proven: CC64 held an RX note until sustain-off, but with
  sustain ON a locally-played-and-released note cut immediately; likewise
  echo played Grand Piano while the OUT voice only affected replay.

  Echo mode closes the gap: the capture loop re-sends each keybed note back
  to the board as an RX note (replay.note_on/note_off), so sustain/porta/mod/
  pitch bend now audibly apply to live playing. Echo also applies the
  OUT-MIDI voice (program_change on enable + whenever the voice picker
  changes), giving TRUE LAYERING — verified: local keys stay on the panel
  voice while the echo plays the selected voice (board keeps the two paths
  independent). /api/echo {"enabled","voice"}; state.echo_enabled/echo_voice;
  startup normalizes CC122 local ON so a restart can't leave keys silent.

  UI: echo and local are now one coupled 'keys' segmented control with all
  four combinations — keys (local on/echo off), layer (local on/echo on),
  echo (local off/echo on), midi (local off/echo off) — so they can't drift
  apart. Pitch bend gains a 'snap' checkbox: checked springs to 0 on release
  (wheel-like), unchecked is sticky. Dropped the earlier detune slider (the
  pitch wheel already bends the echo; local keys never bend). Fixed a JS
  syntax error introduced mid-edit (restored the poll() IIFE closer).
  Verified via browser: all four modes set local/echo state correctly, zero
  console errors. Committed agent:, pushed.

- Ver 70b: ON-SCREEN PIANO AUDITION — clicks inject into the capture
  stream (always, for analysis/stave/feed) AND, because the capture
  loop re-sends keybed notes to the board when echo is on, they sound
  through the board PURELY VIA THE ECHO PATH — so they only play in
  LAYER and ECHO modes. In keys/midi they stay silent for analysis.
  No second send path (/api/audition) — one mechanism, the echo
  capture-loop note_on/note_off, handles both.
  Committed agent:, pushed.

- Ver 71: ARRANGEMENT TRACKER (text string) — chain tagged patterns into
  songs like "AA BC AA BC D BC A". Patterns get a single-letter tag (unique,
  set in the strip) and a bar length (auto = ceil to the grid at the recorded
  tempo, or a stored override shown as 2b*). New monitor/arrange.py (pure,
  unit-tested): paren-aware tokenizer (voice names hold spaces), bare runs
  ("AA" = A-twice), *N repeat, +/-N transpose, (Voice) per-slot voice, |
  separators. Slots lay out on the bar grid at the arrangement tempo (slot
  seconds->beats at recorded tempo->seconds), clipped to the window with
  ringing notes cut at the edge and every on paired to an off. Voices go
  mid-stream as program events: replay.plan_from_raw passes them through
  (off < pc < on at ties) and the player sends the PC on raw + seq paths,
  emitting a "voice" SSE phase so the instrument readout follows. Endpoints:
  /api/patterns/<slug>/tag|/bars, /api/arrangements CRUD, /api/arrange/play
  {text, tempo, loop} on the shared replayer (replay/stop stops it).
  UI: strip labels "[A] name – 12n – 2b", tag/bars setters, arrange box with
  play/stop/loop/tempo/save/load. Verified live: "A B(Strings)" = 4 bars,
  11 notes (was 171 unclipped), Strings PC fires at the slot, readout
  follows; zero console errors. Committed agent:, pushed.

- Ver 71b: NEW EMPTY BUFFER — the raw card's clear button now does a full
  reset (state.reset_take): stops any recording (open notes discarded, not
  flushed) and wipes the take + frozen take + quantizer window + derived
  buffers, so new notes start from nothing instead of appending to the old
  take. Needed because recording defaults ON from page load (the take
  accumulates in the background) and the old clear left recording running.
  Frontend drops the rec button back to "rec" via window.syncRecording.
  /api/take/clear returns recording:false. Verified: rec -> 2 events ->
  clear -> 0 events, recording false. Committed agent:, pushed.

- Ver 72: SLOTS, NOT TAGS — arrangement addressing rebuilt on 64 fixed
  slots (base64 A-Z a-z 0-9 +/). Each slot points at one stored pattern and
  carries its own transpose + voice; the arrangement string is pure slot
  characters ("AABCCDAA", repetition = repeat the char, spaces/| ignored).
  monitor/arrange.py: paren-aware tokenizer replaced by char validation,
  build takes slot chars + a slot resolver, slots persist in slots.json
  (index-addressed API dodges +// URL-encoding), legacy pattern tags seed
  matching slots once on first run. Tag machinery removed from patterns/UI.
  UI reworked from scratch: 8x8 slot grid (filled/selected states, tooltips),
  detail line, transpose + voice (cloned from the replay voice list),
  assign/clear; strip keeps bars only. Endpoints /api/slots list/set,
  /api/arrange/play takes slot chars (empty slot = "assign a pattern
  first"). Verified: 64 cells, assign/select/play end-to-end in the browser,
  "AAB" = 3 bars with transpose + Strings PC, clean errors for bad chars
  and empty slots, zero console errors. Committed agent:, pushed.

- Ver 72b: CARD SPLIT — the left column's "raw midi buffer" card no longer
  houses the library: it keeps head + rec/stop + clear + the event list,
  and a new sibling "pattern arranger" card holds patterns-box + slot grid
  + arrange box. Pure HTML move (no JS ID changes); verified live that
  rec/clear/raw-take sit in the raw card and patterns/slots/arrange-text
  in the arranger, zero console errors. Committed agent:, pushed.

- Ver 73: THE ARRANGER LEAVES THE SIDEBAR — the left column is again just
  the two live streams (note stream + raw midi buffer), and a full-width
  "patterns & arrangement" row now sits below NOTATION in three named cards
  in pipeline order: patterns, slots, arrangement.
  patterns card: a real library list (not a combobox) — rows show name,
  "5n · 1b* · IN/OUT", and chips for the slot chars that use them, each with
  its own load/del; a "new pattern" block (name + source seg IN raw|OUT +
  save) whose save button is disabled with an explanatory tooltip while the
  buffer is empty; and the bar-length override moved under the selected row.
  slots card: the grid + selected-slot detail, then an "assign" block whose
  pattern picker is now labeled and lives next to transpose/voice/attach/empty.
  arrangement card: unchanged controls.
  Backend: list_patterns() gains used_slots; arrange gains read_slots(),
  pattern_usage() and clear_pattern_slots(); DELETE /api/patterns/<slug> now
  empties any slots pointing at the pattern and returns cleared_slots, so
  deleting can never leave a dangling slot (the UI confirms first, naming the
  slots). Attach/clear refresh the library chips; delete refreshes the grid.
  Layout: .main-grid is now content-height with align-items:start and the
  left column is viewport-capped + sticky, so the streams stay put while the
  page scrolls down to the arranger.
  Verified live: left col = 2 cards; arrange row below notation in the right
  order; create (Enter or save), OUT/IN source, select + bar length, attach
  to a slot (chips update), delete-with-refs confirm -> slots emptied (grid
  updates), unreferenced delete no confirm, arrangement "AAB" plays, sticky
  pins at top, zero console errors. Committed agent:, pushed.

- Ver 73b: SSE heartbeat was an SSE comment (": keepalive"), which never
  fires onmessage, so the client watchdog (app.js) never saw it and forced a
  bogus reconnect every 20s whenever the board was idle. Server now emits a
  real `data: {"type":"heartbeat"}` on the queue timeout instead; the client
  switch ignores the unknown type, so only the server needs the change.
  Verified: stream shows one heartbeat per idle window, no reconnect churn.

- Ver 74: transport belongs to the pattern workflow. A data VIEW must not own
  transport, so rec/stop + clear left the raw midi buffer card (which is now a
  pure read-only view: title + event list) and moved into a transport row at
  the top of the patterns card: [rec/stop] [clear] | source buffer: N notes ·
  IN raw. The buffer line is fed by the shared /api/take poll and names the
  ACTIVE source (IN raw / OUT), so "saving what" is always explicit.
  Save is no longer disabled by a client-side count guess — the server already
  refuses an empty buffer, and the UI now shows that message, so a stale count
  can't silently eat a click (the old disabled-button no-op was the whole bug).
  /api/take gains in_notes/out_notes for the status line.
  One shared "selected pattern": the slots card's separate dropdown is gone,
  replaced by an "attach: <name>" readout that reads the patterns card's
  selection, so there's a single source of truth. Save auto-selects the new
  pattern; delete clears it; assigning an empty selection errors clearly.
  Arrangement: clicking a filled slot cell appends its char to the string
  (shift-click selects it for assign/transpose; empty slots just select), so
  you compose the arrangement on the grid. A live preview under the field
  shows "<n> slots · <n> bars · <n> notes" computed from /api/slots (bars) and
  /api/patterns (note_count), flagging unknown chars and empty slots. The
  working string/name/tempo/loop persist in localStorage, and loading a
  pattern now does an in-place refreshState() + fetchRawTake() instead of a
  full page reload — no more losing the arrangement you were building.
  Verified live: raw card has no rec/clear; transport row + buffer status
  render and count real input; empty save shows the server's error; shift vs
  plain slot click; click-built "DABCABC" -> 7 bars/22 notes; draft survives
  reload; load leaves the page alive (probe intact) and resyncs the stave;
  zero console errors. Committed agent:, pushed.

- Ver 75: piano roll. A big new full-width card sits between the transform &
  play row and the notation card, as a second consumer of the SAME
  /api/notation events the stave renders — so it always shows whatever the
  notation shows, under the same quantize/tempo/time-sig, with no new data
  endpoint. renderNotationFromBuffer() now feeds both cards from its one fetch.
  New self-contained monitor/static/roll.js (pure SVG, no deps): time fits the
  card width (whole take visible), pitch auto-fits the notes present (+2
  semitone pad, clamped A0-C8, min one octave), one row per semitone with black
  rows shaded, a mini-piano gutter with C labels, a top ruler with bar numbers,
  bar/beat/subdivision gridlines (subdivisions only when they won't turn to
  mush), and note blocks sized by duration and shaded by velocity. REC clears
  the roll with the stave; a live meta readout shows notes/seconds/bpm.
  Replay: replay.py now includes the step's relative time (t, reset each loop)
  in its "step" event, and the app sweeps a playhead across the roll while
  lighting the currently sounding block — reset on start, hidden on
  done/stopped/error. Built with editing in mind: render() is a pure function
  of a `model` of hit-testable blocks (`data-idx`/`data-note`), so a later
  add/delete/drag is a model mutation + re-render.
  Verified live: roll sits in DOM order chain-row -> roll-wrap -> stave-wrap at
  the same full width as notation; 9 injected notes -> 9 blocks matching
  /api/notation; tempo 60 -> 1 bar, 3/4 -> 2 bars; playhead swept 491->1840px
  with the sounding block lit, then hid on done; REC shows the empty state;
  full A0-C8 take grows the card (66 rows, 488px) without error; zero console
  errors. AGENTS.md gains a roll.js architecture bullet. Committed agent:,
  pushed.

- Ver 76: patterns get a one-click PLAY. The obvious gap — replaying a
  pattern, or the current buffer, from where you are — is now closed in the
  patterns card:
  - Transport row gains a play button right after rec: [rec] [play] [clear].
    It's a toggle like out-card play but press-again-to-stop: POST /api/replay
    to start the current buffer, POST /api/replay/stop while sounding. Uses the
    same global replay-voice selection, and its ▶/■ + green "playing" state
    rides the shared replayActive flag (SSE replay events + stop/loop buttons
    all toggle it), so it stays in sync with the out-card play button.
  - Each pattern row now reads [play] [load] [del]. play does NOT load: new
    POST /api/patterns/<slug>/play loads the stored events server-side and runs
    them straight out through the shared replayer at original timing (raw
    path), so the buffer and chain settings stay untouched and the roll
    playhead + key lights / feed follow along via the normal replay events. The
    status line reports name + note count, or the server error (409 if a
    replay/arrangement is already running, 400 if no out destinations).
  Verified live: transport play flipped to ▪ stop and replayed the 21-note
  buffer (~4.5s) then reverted on toggle; pattern oii played back its 6 stored
  notes (~2.5s) with feed entries and "playing "oii" (6 notes)" status; rows
  show play before load/del; zero console errors. Committed agent:, pushed.

- Ver 77: refactor — one transport store client-side, one replay path server-side.
  Backend: /api/replay and /api/replay/loop were near-duplicates (same guard,
  requantize, voice handling, parse). Both now funnel through a shared
  _replay_start_guard() (already-replaying / no-outputs gate) + _play_events()
  (speed parse, voice resolution + receive-voice state update, replayer.play
  with SSE, and the {ok, notes, speed, voice, loop} response, with optional
  extra keys). /api/patterns/<slug>/play drops its copies of the guards/voice
  handling and routes through the same pair — same behavior, name carried via
  extra={"name": ...}.
  Client: replay state is no longer scattered writable globals + a growing set
  of hand-wired setter callbacks (the thing that made Ver 76 touch 8 spots to
  add one button). New Transport store — an IIFE-local mini pub/sub
  (set/subscribe/playing/looping) — is the single source of truth for
  replay/loop state. Every lifecycle change routes through Transport.set():
  SSE replay start/done/stopped/error, the out-card stop button, the loop
  button, and the buffer-play button. The three buttons (out-card play, loop,
  buffer play) and the fetchRawTake poll guard subscribe to / read the
  accessor; setReplayBtn/setLoopBtn/setBufferPlayBtn plumbing is gone.
  Verified live: buffer play flips out-card + loop-aware states together;
  loop arm then stop reverts all three; SSE stopped reverts after an external
  halt; pattern oii play still reports "playing "oii" (6 notes)" and finishes
  clean; replay of a 29s multi-take buffer played to completion; zero console
  errors. Committed agent:, pushed.

- Ver 78: take-recording defaults OFF + Abora logo. REC no longer auto-arms on
  page load: state.py recording starts False and app.js mirrors it, so idle
  noodling and background board chatter (clock/active-sensing, sustained
  pad-washing while thinking) never accumulate into a take, stave or roll —
  you have to press REC to start a take, STOP to freeze it. The live key
  lighting, feed and chord/arp flash were already separate from the take path
  and stay live either way. New monitor/static/abora-logo.png (800x800 PNG,
  local copy of the Deity/Abora mark from the graphics box) replaces the
  inline-SVG data-URI favicon via <link rel="icon">, and sits as a circular
  emblem in the header top-left (44px, straw ring + royal glow, clipped
  round). Verified: fresh server reports recording:false; logo + favicon serve
  at /static/abora-logo.png (200); header shows the emblem next to "Abora".
  Committed agent:, pushed.

- Ver 79: sound & fx controls in the out·ctrl card. The board is not a simple
  "mod wheel": its chip takes a richer controller set the panel can't reach
  (the MOTION EFFECT holder drives filter/pitch/modulation patterns over time,
  but there's no direct filter/effect surface). New "sound & fx" group next
  to the mod wheel — six sliders sent raw to the keyboard via the existing
  /api/ctrl path (it already accepted any CC 0-127): filter CC74 (brightness/
  cutoff), resonance CC71 (harmonic content), attack CC73, release CC72 (the
  motion-effect "filter" family), reverb CC91 and chorus CC93 (effect 1/3
  depths). All six are marked receive-capable "o" in the PSS-A50 MIDI
  Implementation Chart. Front-end only (template + app.js wireRange wiring);
  TEMPLATES_AUTO_RELOAD picks it up on refresh, no server restart, no take
  loss. Verified: page serves all six controls + label, app.js syntax clean.
  Committed agent:, pushed.

- Ver 80: "defaults" button in the sound & fx group. One click snaps mod +
  all six timbre/fx sliders back to their markup defaults and fires the whole
  set at the keyboard in a single quiet burst: postCtrl gained an optional
  `quiet` arg (skips per-item feed/flash) and now returns its promise;
  resetSoundFx() collects one post per control (values read from
  el.defaultValue, so the HTML markup stays the single source of truth) and
  emits one aggregated SENT line ("defaults: mod 0 · filter 100 · ..."),
  flagging "(board offline)" if any send dropped. Button lives in the sound &
  fx seg-label row, wired to resetSoundFx. Verified: page serves the button,
  app.js syntax clean. Committed agent:, pushed.

- Ver 81: corrected sound & fx defaults to the instrument's real (GM/XG)
  neutral values. Ver 79 had picked arbitrary ones - release 0 chopped the
  piano tail early and reverb 40 left the effect carrying the sound. Now:
  filter CC74 / resonance CC71 / attack CC73 / release CC72 all default to
  64 (midpoint = no change to the voice), reverb CC91 / chorus CC93 default
  to 0 (off); mod CC1 stays 0. The defaults button reads el.defaultValue so
  it inherits the correction automatically. Verified live on :5050: all six
  sliders serve value=64/64/64/64/0/0. Committed agent:, pushed.

- Ver 82: motion pattern buttons - the Motion Effect families as scripted CC
  ramps. New "motion patterns" group in the out·ctrl card (below sound & fx):
  nine one-click patterns mirroring the board's A/B/C families, built as
  absolute-time step queues from linear ramp tracks and fired client-side
  through the existing /api/ctrl path (quiet posts, single running/done feed
  line). A - filter: sweep (CC74 127->20->127), wah (4 Hz 60/127 osc), filter
  +mod (CC74 squeeze + CC1 swell). B - pitch: whole-note rise (+2 st, hold,
  back), choke (fast grab + snap), rise+slice (+1.5 st with CC11 gates). C -
  modulation: swell (CC1 0->127->0), slices (CC11 gates on a 187ms grid),
  mod+rise (CC1 + pitch lift together). A 25ms ticker scans the queue; the
  lit button stops the run, and defaults/panic cancel it too. CSS: .pat-btn
  active gets a straw ring. Verified: page serves all nine data-pat buttons,
  app.js syntax clean. Committed agent:, pushed.

- Ver 83: motion patterns reworked - armed + note-triggered like the board's
  real [MOTION EFFECT] button, and now visible. Ver 82's patterns were a
  fixed wall-clock window, which was confusing: they swept whatever note
  happened to be sounding when they fired, returned to neutral, and did not
  re-trigger on later notes ("applies to the first note, falls off"); also
  filter+mod ended with the filter closed, and nothing in the UI moved.
  Now: clicking a pattern ARMS it (button lights, feed "MOTION -> armed:
  <name> - play a note"); every note-on (hooked in handleEvent via
  window.motion.note()) re-runs the ramp from the start, with a 120ms
  debounce so chords don't thrash-restart. Every step is mirrored onto the
  out·ctrl sliders (cc->slider map 1/71-74/91/93 + pitch->bend wheel) so the
  motion is VISIBLE while it runs. All patterns now start AND end at
  neutral (filmod returns the filter 30->127; riseslice returns pitch
  1.5->0), so the sound snaps back to normal when the movement finishes -
  no more muffled follow-up notes. Click the lit button again to disarm;
  defaults + panic also disarm. Verified: app.js syntax clean, served
  tooltip explains arming. Committed agent:, pushed.

- Ver 84: echo auto-follow + dejank TODO. BUG (user): changing the instrument
  was not reaching the echo stream unless the keys routing was toggled out of
  and back into echo/layer. The echo voice on "auto" was meant to mirror the
  panel, but the RX voice is independent of the panel voice, so a panel
  program change left the echoed sound on the old instrument. Fix in the
  capture event loop: when a program_change arrives from the board while
  state.echo_enabled and echo_voice=="auto", re-apply the panel's bank+program
  to the RX side via program_change() (same raw path /api/echo uses), and sync
  state.receive_bank/program. Pinned echo voices still layer deliberately
  (untouched). The dropdown -> echo path (rvSel change -> sendEcho(true)) was
  already wired and still works for hand-picked voices. Also: TODO(dejank)
  comment block above the MOTION module in app.js documenting the known jank
  (25ms client tick approximation, one POST per step, 120ms chord debounce
  swallowing retriggers, slider mirroring) with the proper server-side
  scheduling fix sketched. Server restarted for the Python change (take
  buffer reset). Verified: py_compile + node --check clean, :5050 root 200,
  /api/state healthy. Committed agent:, pushed.

- Ver 85: out·ctrl tidying. Removed the sustain checkbox (CC64 - the board's
  own panel handles sustain; a pedal would arrive as RX anyway, shown in the
  received readout). Portamento collapsed from checkbox + porta-time slider
  into ONE slider: 0 = off (CC65 switch 0), >0 = glide time (CC5) with the
  switch (CC65 127) flipped on at the 0 boundary. Custom input handler sends
  the boundary switch change only when crossing on/off, then CC5 as it slides.
  Boot-sync updated: the unified slider restores to the CC5 time when the
  stored CC65 is on, else 0. Verified: node --check clean, served page has
  one ctrl-porta slider, no sustain wiring left (prose tooltips only).
  Committed agent:, pushed.
