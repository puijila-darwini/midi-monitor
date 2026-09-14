(function () {
  "use strict";

  var LOW = 21;      // A0
  var HIGH = 108;    // C8
  var BLACK = {1:1, 3:1, 6:1, 8:1, 10:1};  // pc -> is black

  // PSS-A50 voices keyed by "bank:program" (mirrors Capture.VOICE_BY_PROGRAM).
  var PSSA50_VOICES = {
    "0:0":"Grand Piano","0:4":"Electric Piano 1","0:5":"Electric Piano 2","0:2":"Electric Grand Piano",
    "0:16":"Drawbar Organ","0:18":"Rock Organ","0:21":"Accordion","0:22":"Harmonica",
    "0:24":"Nylon Guitar","0:25":"Steel Guitar","0:26":"Jazz Guitar","0:27":"Clean Guitar","0:29":"Overdriven Guitar",
    "0:32":"Acoustic Bass","0:33":"Finger Bass","0:36":"Slap Bass","0:38":"Synth Bass",
    "0:48":"Strings","0:45":"Pizzicato Strings","0:40":"Violin","0:42":"Cello","0:46":"Orchestral Harp",
    "0:68":"Oboe","0:71":"Clarinet","0:73":"Flute","0:66":"Tenor Sax",
    "0:61":"Brass Section","0:56":"Trumpet","0:57":"Trombone","0:60":"French Horn","0:62":"Synth Brass",
    "0:82":"Gemini","0:84":"Punchy Chordz","0:80":"Square Lead","0:81":"Sawtooth Lead",
    "0:88":"New Age Pad","0:89":"Warm Pad","0:100":"Brightness",
    "127:0":"Standard Kit","127:27":"Dance Kit","0:11":"Vibraphone","0:12":"Marimba"
  };

  var keyEls = {};
  var held = new Set();
  var replayActive = false;  // a take is currently playing back out the keyboard
  var tempoBpm = 0;  // global tempo for quantization
window.tempoBpm = 0;  // expose on window for durationToVexFlow
  // Time signature (beats per measure). Exposed on window for stave (measure
  // rendering) and metronome (accent grouping). Stays at 4/4 until user changes.
  var timesig = { numer: 4, denom: 4 };
  window.timesig = timesig;

  // Recording gate: the notation stave accumulates ONLY while recording. REC
  // clears the stave and starts a fresh take (backend reset too); STOP freezes
  // the take (backend flushes the trailing note; the stave fills the final bar
  // with a rest). The feed/piano/flash banner stay live either way.
  // Default True = continuous behavior (notes flow onto the stave as before);
  // the user uses STOP to end/freeze a take.
  var recording = true;
  // Catch-tonic (the &#9834; catch button). When armed, the next note(s) from
  // the keyboard set the tonic. If those notes form a major or minor triad, an
  // appropriate scale (major / natural minor) is set too. Notes are buffered
  // briefly so a blocked chord resolves as a chord, not as its first note.
  var tonicListenActive = false;
  var catchBuffer = [];
  var catchBass = null;
  var catchLastAt = 0;
  var catchTimer = null;

  // Given the unique pitch classes heard, return {root, quality} if they form
  // a major or minor triad (any octave/voicing), else null.
  function triadFromPcs(pcs) {
    var set = {};
    pcs.forEach(function (p) { set[p] = true; });
    var checks = [
      { m3: 4, p5: 7, q: "major" },
      { m3: 3, p5: 7, q: "minor" }
    ];
    for (var i = 0; i < pcs.length; i++) {
      var r = pcs[i];
      for (var j = 0; j < checks.length; j++) {
        if (set[(r + checks[j].m3) % 12] && set[(r + checks[j].p5) % 12]) {
          return { root: r, quality: checks[j].q };
        }
      }
    }
    return null;
  }

  // Chord -> scale "catch" shapes. This is DATA ENTRY (tell the guide which
  // key/mode you mean), not key detection, so mappings are generous:
  //   - each shape lists its semitone offsets from the root;
  //   - a played pc-set matches when it CONTAINS the shape (subset-tolerant);
  //   - LONGER shapes win (more specific), then table order;
  //   - vanilla ionian ("major") / aeolian ("minor") are still ONLY selectable
  //     by a bare triad (that's the honest core; see chordFromPcs);
  //   - aug triad -> whole-tone is the special 3-note case (arpeggio path).
  //   - chromatic (below) is the ONE non-triadic 3-note catch: deliberate
  //     exotic scales stay 4+ notes so common scales remain the easiest to
  //     enter (m7/dom7=4 vs any exotic=4+).
  var CATCH_SHAPES = [
    // -- 6 tones ---------------------------------------------------------
    { name: "blues",           semis: [0, 3, 5, 6, 7, 10],    mode: "blues" },
    { name: "whole_tone",      semis: [0, 2, 4, 6, 8, 10],    mode: "whole_tone" },
    // -- 5 tones ---------------------------------------------------------
    { name: "hirajoshi",       semis: [0, 2, 3, 7, 8],        mode: "hirajoshi" },
    { name: "minor_pent",      semis: [0, 3, 5, 7, 10],       mode: "minor_pent" },
    { name: "add9",            semis: [0, 2, 4, 7, 9],        mode: "major_pent" },
    { name: "7alt",            semis: [0, 1, 4, 6, 10],       mode: "super_locrian" },
    { name: "m7b9",            semis: [0, 1, 3, 7, 10],       mode: "phrygian" },
    { name: "m9",              semis: [0, 2, 3, 7, 10],       mode: "dorian" },
    { name: "7b9",             semis: [0, 1, 4, 7, 10],       mode: "phrygian_dominant" },
    { name: "7#11",            semis: [0, 4, 6, 7, 10],       mode: "lydian_dominant" },
    { name: "dom9",            semis: [0, 2, 4, 7, 10],       mode: "mixolydian" },
    // -- 4 tones ---------------------------------------------------------
    { name: "dim7",            semis: [0, 3, 6, 9],           mode: "diminished" },
    { name: "m7b5",            semis: [0, 3, 6, 10],          mode: "locrian" },
    { name: "mMaj7",           semis: [0, 3, 7, 11],          mode: "harmonic_minor" },
    { name: "m6",              semis: [0, 3, 7, 9],           mode: "dorian" },
    { name: "m7",              semis: [0, 3, 7, 10],          mode: "dorian" },
    { name: "maj7",            semis: [0, 4, 7, 11],          mode: "lydian" },
    { name: "maj6",            semis: [0, 4, 7, 9],           mode: "mixolydian" },
    { name: "dom7",            semis: [0, 4, 7, 10],          mode: "mixolydian" },
    { name: "7#5",             semis: [0, 4, 8, 10],          mode: "whole_tone" },
    { name: "mMaj7#5",         semis: [0, 4, 8, 11],          mode: "harmonic_major" },
    { name: "7b5",             semis: [0, 4, 6, 10],          mode: "lydian_dominant" },
    // -- 3 tones (deliberately ONLY chromatic; keeps common scales easier) --
    { name: "chrom",            semis: [0, 1, 2],           mode: "chromatic" }
  ];

  // Plain-language description of each TARGET scale (what it sounds like), keyed
  // by mode id. The tooltip reads target-first — "want this scale -> play this
  // chord" — so all the explanation hangs off the scale, not the catch shape.
  var CATCH_NOTES = {
    "blues": "The 6-tone blues scale: 1 \u266d3 4 \u266d5 5 \u266d7 (C E\u266d F F\u266d/G\u266d G B\u266d).",
    "whole_tone": "Six whole steps, no perfect 5th — floating and ambiguous, any triad sound does.",
    "hirajoshi": "Japanese pentatonic (the In scale): 1 2 \u266d3 5 \u266d6. A minor-ish colour that is not Western minor.",
    "minor_pent": "The rock/blues minor pentatonic: 1 \u266d3 4 5 \u266d7 (C E\u266d F G B\u266d).",
    "major_pent": "The bright, open major pentatonic: 1 2 3 5 6 (C D E G A).",
    "super_locrian": "The altered dominant — every colour-tone in one chord: 1 \u266d9 \u266f9 3 \u266d5 \u266f5 \u266d7.",
    "phrygian": "The dark Spanish/flamenco minor: \u266d2, \u266d3, \u266d6, \u266d7 over a minor 7.",
    "dorian": "The brighter minor — its 6th is natural, not \u266d6: 1 2 \u266d3 4 5 6 \u266d7 (D E F G A B C).",
    "phrygian_dominant": "Spanish dominant — a Phrygian scale with a major 3rd: \u266d9 and 3 both ring at once.",
    "lydian_dominant": "The dominant with a \u266f4 (a.k.a. b5) instead of a \u266d9: 1 2 3 \u266f4 5 6 \u266d7.",
    "mixolydian": "The folk/bluesy major: a plain major scale with a \u266d7 (1 2 3 4 5 6 \u266d7).",
    "diminished": "The symmetric diminished scale — its home chord is the fully diminished 7th.",
    "locrian": "The darkest minor: \u266d2 and \u266d5 make it unstable; its home chord is half-diminished.",
    "harmonic_minor": "Natural minor with its leading tone raised: 1 2 \u266d3 4 5 \u266d6 7 — dramatic and dreamy.",
    "lydian": "A major scale with a raised 4th: 1 2 3 \u266f4 5 6 7 — bright, floating, cinematic.",
    "harmonic_major": "Major with a flattened 6th: 1 2 3 4 5 \u266d6 7. Brilliant, slightly bittersweet.",
    "chromatic": "All twelve tones, one after the other. Catch it with the tightest cluster there is: the root, its \u266d2, and its 2 stacked together."
  };

  // Match a played pc-set against the catch shapes (subset-tolerant, longer
  // first) and return {root, quality, mode}, or null -> callers fall back to
  // tonic-only. bassPc (optional) breaks symmetric-chord root ambiguity.
  // Order in the table is priority within equal length.
  function chordFromPcs(pcs, bassPc) {
    var set = {};
    var uniq = [];
    pcs.forEach(function (p) {
      p = p % 12;
      if (!set[p]) { set[p] = true; uniq.push(p); }
    });
    if (uniq.length >= 3) {
      // Collect EVERY (shape, root) match so the best one wins globally.
      // Many chords are subsets of themselves under a different root (Cm6 is
      // Am7b5, Cadd9 is A minor pent, ...), so we can't return early per shape.
      var best = null;
      for (var s = 0; s < CATCH_SHAPES.length; s++) {
        var shape = CATCH_SHAPES[s];
        if (shape.semis.length > uniq.length) continue;
        for (var i = 0; i < uniq.length; i++) {
          var r = uniq[i];
          var ok = true;
          for (var j = 0; j < shape.semis.length; j++) {
            if (!set[(r + shape.semis[j]) % 12]) { ok = false; break; }
          }
          if (!ok) continue;
          var cand = { root: r, quality: shape.name, mode: shape.mode };
          var score = 0;
          if (typeof bassPc === "number" && r === bassPc) score += 1000;
          score += shape.semis.length * 10;       // longest (most specific) wins
          score += CATCH_SHAPES.length - s;       // then earlier table order
          if (!best || score > best.score) best = { score: score, cand: cand };
        }
      }
      if (best) return best.cand;
    }
    if (uniq.length === 3) {
      var set3 = {};
      uniq.forEach(function (p) { set3[p] = true; });
      for (var a = 0; a < uniq.length; a++) {
        var ar = uniq[a];
        if (set3[(ar + 4) % 12] && set3[(ar + 8) % 12]) {
          return { root: ar, quality: "aug", mode: "whole_tone" };
        }
      }
      var tri = triadFromPcs(uniq);
      if (tri) {
        return { root: tri.root, quality: tri.quality,
                 mode: tri.quality === "major" ? "major" : "aeolian" };
      }
    }
    return null;
  }

  // Build the "how does catch work" tooltip by WALKING THE ACTUAL SCALE
  // DROPDOWN, so it lists every scale the guide offers, in exactly the menu's
  // grouping and order (and can never drift from it). Scales with a catch shape
  // get "play this chord"; scales with no catch chord show an explicit gap.
  // (Filling those gaps with new shapes is deliberately deferred.)
function buildCatchTooltip() {
    var tip = document.getElementById("catch-tooltip");
    if (!tip) return;
    var scaleSel = document.getElementById("key-scale");
    if (!scaleSel) return;

    // chord picks grouped by target scale (from the matching table)
    var byMode = {}; // mode id -> [{name, tones, n}]
    CATCH_SHAPES.forEach(function (s) {
      (byMode[s.mode] = byMode[s.mode] || []).push({
        name: s.name,
        tones: s.semis.map(function (semi) { return INTERVAL_NAMES[semi]; }).join(" "),
        n: s.semis.length
      });
    });
    // The two vanilla modes are caught by a bare triad rather than a shape in
    // CATCH_SHAPES; document them so they don't read as gaps.
    byMode["major"]   = [{ name: "maj triad", tones: "1 M3 P5", n: 3 }];
    byMode["aeolian"] = [{ name: "min triad", tones: "1 m3 P5", n: 3 }];

    function scaleLabel(id) {
      var opt = scaleSel.querySelector('option[value="' + id + '"]');
      return opt ? opt.textContent : id;
    }

    var rows = "";
    var groups = scaleSel.querySelectorAll("optgroup");
    for (var gi = 0; gi < groups.length; gi++) {
      rows += '<tr class="tt-group"><td colspan="2">' + groups[gi].label + "</td></tr>";
      var opts = groups[gi].querySelectorAll("option");
      for (var oi = 0; oi < opts.length; oi++) {
        var id = opts[oi].value;
        if (id === "-1") continue;
        var picks = (byMode[id] || []).slice().sort(function (a, b) { return a.n - b.n; });
        var playHtml;
        if (picks.length) {
          playHtml = picks.map(function (p) {
            return '<span class="pick"><b>' + p.name + "</b>" +
                   '<span class="tones">(' + p.tones + ")</span></span>";
          }).join("");
        } else {
          playHtml = '<span class="none">&#8709; no chord shape yet &mdash; ' +
                     "pick it from the menu</span>";
        }
        var note = CATCH_NOTES[id] || "";
        rows += '<tr><td class="cscale"><b>' + scaleLabel(id) + "</b>" +
                (note ? "<i>" + note + "</i>" : "") + "</td>" +
                '<td class="cplay">' + playHtml + "</td></tr>";
      }
    }
    tip.innerHTML =
      '<div class="tt-head">want this scale &#8594; play this chord</div>' +
      '<table><tr><th class="c-scale-col">scale</th>' +
      '<th class="c-play-col">any of these catches it</th></tr>' +
      rows + "</table>" +
      '<div class="tt-foot">' +
      "How to enter: set the tonic, press <b>\u266a catch</b>, then play one " +
      "of the chords in that scale&rsquo;s row (any octave, any order — only the " +
      "pitch classes matter). Tones in brackets are semitone distances from the " +
      "root: <b>m2</b> = flat 2nd, <b>M3</b> = major 3rd, <b>TT</b> = tritone, etc." +
      "<br><br>" +
      "<b>\u2205 no chord shape yet</b> = that scale can not be caught by any " +
      "chord in the current table; choose it from the drop-down for now " +
      "(these are scale colours, not chord colours)." +
      "<br><br>" +
      "Vanilla major / natural-minor only come from a bare triad. " +
      "Aug triad &#8594; whole tone. A lone note sets just the tonic. " +
      "Matching is loose (subset-tolerant) and the lowest note you play " +
      "breaks symmetric-chord ties (so Cmaj9 and Am11 pick the root you " +
      "actually played, not whichever is alphabetically first)." +
      "</div>";

    var btn = document.getElementById("catch-help");
    if (!btn) return;

    var hideTimer = null;
    var wasToggled = false; // track click-toggle vs hover

    function hide() { tip.classList.remove("show"); }
    function scheduleHide() {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, 220);
    }
    function position() {
      var r = btn.getBoundingClientRect();
      var tw = tip.offsetWidth || 500;
      var th = tip.offsetHeight || 440;
      // Prefer: right-edge of tooltip flush with right-edge of button,
      // and the tooltip hangs just below the button.
      var top  = r.bottom + 8;
      var left = r.right - tw;
      if (left < 8) left = 8;
      // If it would go off the bottom, open it above the button instead.
      if (top + th > window.innerHeight - 8)
        top = Math.max(8, r.top - th - 8);
      tip.style.top  = top + "px";
      tip.style.left = left + "px";
    }
    function show() {
      clearTimeout(hideTimer);
      tip.classList.add("show");
      position();
    }

    btn.addEventListener("mouseenter", function () {
      wasToggled = false;
      show();
    });
    btn.addEventListener("mouseleave", function () {
      if (!wasToggled) scheduleHide();
    });
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (tip.classList.contains("show") && wasToggled) {
        wasToggled = false;
        hide();
      } else {
        wasToggled = true;
        show();
      }
    });
    // Keep tooltip open while pointer is over it; close when it leaves.
    tip.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    tip.addEventListener("mouseleave", function () {
      if (!wasToggled) scheduleHide(); else hide();
    });
    // Close on any click outside the tooltip or the button.
    document.addEventListener("pointerdown", function (e) {
      if (!tip.contains(e.target) && !btn.contains(e.target)) {
        wasToggled = false;
        hide();
      }
    });
    // Reposition if window resizes while open.
    window.addEventListener("resize", function () {
      if (tip.classList.contains("show")) position();
    });
  }

  function resetCatch() {
    tonicListenActive = false;
    catchBuffer = [];
    catchBass = null;
    if (catchTimer) { clearTimeout(catchTimer); catchTimer = null; }
    var lst = document.getElementById("listen-tonic");
    if (lst) { lst.classList.remove("listening"); lst.textContent = "\u266a catch"; }
  }

  // Apply an armed-catch resolution: set the tonic select (and the scale select
  // when a scale is known), re-render the guide, announce on the feed and reset
  // the button. Used by both the single-note fallback and the triad path.
  function resolveCatch(rootPc, scaleId) {
    tonicListenActive = false;
    var tonSel = document.getElementById("key-tonic");
    var scSel = document.getElementById("key-scale");
    if (tonSel && scSel) {
      tonSel.value = String(rootPc);
      if (scaleId) scSel.value = scaleId;
      applyScaleGuide(tonSel.value, scSel.value);
    }
    var lst = document.getElementById("listen-tonic");
    if (lst) { lst.classList.remove("listening"); lst.textContent = "\u266a catch"; }
    var nm = (PC_MAJOR[rootPc] || "?");
    addFeed('<span class="time">' + fmtTime(catchLastAt) +
      '</span>  TONIC set to ' + nm + (scaleId ? " &middot; " + scaleId + " scale" : ""), "tonic");
  }

  // Fallback path: no chord flash arrived, so resolve from whatever notes were
  // buffered (last note wins if they don't form a triad or 7th chord).
  function resolveCatchBuffer() {
    if (catchTimer) { clearTimeout(catchTimer); catchTimer = null; }
    if (!tonicListenActive) return;
    var chord = catchBuffer.length ? chordFromPcs(catchBuffer, catchBass) : null;
    var root = chord ? chord.root : (catchBuffer.length ? catchBuffer[catchBuffer.length - 1] : null);
    if (root === null) { resetCatch(); return; }
    var scaleId = chord ? chord.mode : null;
    resolveCatch(root, scaleId);
    catchBuffer = [];
    catchBass = null;
  }

  function setTimesig(numer, denom) {
    timesig.numer = numer;
    timesig.denom = denom;
    window.timesig = timesig;
  }

  function isBlack(note) { return BLACK[note % 12] === 1; }
  function octLabel(note) {
    return "C" + (Math.floor(note / 12) - 1);
  }

  // ---- tonic & scale guide -------------------------------------------------
  // Interval labels shown on each in-scale key, indexed by pitch class relative
  // to the tonic. Repeats every octave.
  var INTERVAL_NAMES = ["1", "m2", "M2", "m3", "M3", "P4", "TT", "P5",
                        "m6", "M6", "m7", "M7"];
  // When the tonic root, stays "1" (labels are per-PC, not per-interval-class).

  // Scale definitions. semis = scale tones as semitone offsets from the tonic
  // (all measured from 0). sig = mode offset from tonic to the parent MAJOR
  // key's tonic (for driving the stave key signature); null = no standard key
  // signature (whole-tone/diminished/etc.) -> stave shows none.
  var SCALES = {
    "major":           { semis: [0, 2, 4, 5, 7, 9, 11],       sig: 0 },
    "dorian":          { semis: [0, 2, 3, 5, 7, 9, 10],       sig: -2 },
    "phrygian":        { semis: [0, 1, 3, 5, 7, 8, 10],       sig: -4 },
    "lydian":          { semis: [0, 2, 4, 6, 7, 9, 11],       sig: -5 },
    "mixolydian":      { semis: [0, 2, 4, 5, 7, 9, 10],       sig: -7 },
    "aeolian":         { semis: [0, 2, 3, 5, 7, 8, 10],       sig: -9 },
    "locrian":         { semis: [0, 1, 3, 5, 6, 8, 10],       sig: -11 },
    "harmonic_minor":  { semis: [0, 2, 3, 5, 7, 8, 11],       sig: -9 },
    "melodic_minor":   { semis: [0, 2, 3, 5, 7, 9, 11],       sig: -9 },
    "harmonic_major":  { semis: [0, 2, 4, 5, 7, 8, 11],       sig: 0 },
    "double_harmonic": { semis: [0, 1, 4, 5, 7, 8, 11],       sig: null },
    "phrygian_dominant": { semis: [0, 1, 4, 5, 7, 8, 10],     sig: null },
    "lydian_dominant": { semis: [0, 2, 4, 6, 7, 9, 10],       sig: null },
    "super_locrian":   { semis: [0, 1, 3, 4, 6, 8, 10],       sig: null },
    "major_pent":      { semis: [0, 2, 4, 7, 9],              sig: 0 },
    "minor_pent":      { semis: [0, 3, 5, 7, 10],             sig: -9 },
    "blues":           { semis: [0, 3, 5, 6, 7, 10],          sig: -9 },
    "hirajoshi":       { semis: [0, 2, 3, 7, 8],              sig: null },
    "bebop_major":     { semis: [0, 2, 4, 5, 7, 8, 9, 11],    sig: 0 },
    "bebop_dominant":  { semis: [0, 2, 4, 5, 7, 9, 10, 11],   sig: -7 },
    "bebop_dorian":    { semis: [0, 2, 3, 4, 5, 7, 9, 10],    sig: -2 },
    "whole_tone":      { semis: [0, 2, 4, 6, 8, 10],          sig: null },
    "diminished":      { semis: [0, 2, 3, 5, 6, 8, 9, 11],    sig: null },
    "chromatic":       { semis: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], sig: null },
    "enigmatic":       { semis: [0, 1, 4, 6, 8, 10, 11],      sig: null },
    "hungarian_minor": { semis: [0, 2, 3, 6, 7, 8, 11],       sig: null },
    "neapolitan_major": { semis: [0, 1, 3, 5, 7, 9, 11],      sig: null },
    "neapolitan_minor": { semis: [0, 1, 3, 5, 7, 8, 11],      sig: null }
  };
  // Conventional major-key spelling per pitch class (mirrors stave.js).
  var PC_MAJOR = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];

  function clearScaleGuide() {
    for (var n = LOW; n <= HIGH; n++) {
      var k = keyEls[n];
      if (!k) continue;
      k.classList.remove("inscale", "tonic", "outscale");
      var lab = k.querySelector(".ivl-label");
      if (lab) lab.parentNode.removeChild(lab);
    }
  }

  // Shade every key whose pitch class is in the chosen scale (in all octaves),
  // gold-tinge the tonic key, and label EVERY key with its interval from the
  // tonic (m2, M2, m3, ...) so the full tonal map is visible. In-scale keys
  // get shaded + a bright label; out-of-scale keys keep a dimmed label only.
  // Also drives the stave key signature when the scale maps to one (diatonic
  // modes, pentatonics); "off" or exotic scales clear it.
  function applyScaleGuide(tonic, scaleId) {
    clearScaleGuide();
    var tonicPc = parseInt(tonic, 10);
    var def = SCALES[scaleId];
    if (isNaN(tonicPc) || tonicPc < 0 || tonicPc > 11 || !def) {
      if (window.StavePanel) StavePanel.setKey("auto");
      return;
    }
    // inScale[pc] = true when that absolute pitch class is in the scale under
    // this tonic (pc 0..11). dist() = semitones up from the tonic to the note.
    var inScale = [];
    def.semis.forEach(function (s) { inScale[(s + tonicPc) % 12] = true; });
    for (var n = LOW; n <= HIGH; n++) {
      var pc = n % 12;
      var dist = (pc - tonicPc + 12) % 12;
      var k = keyEls[n];
      if (!k) continue;
      var lab = document.createElement("span");
      lab.className = "ivl-label";
      lab.textContent = INTERVAL_NAMES[dist];
      k.appendChild(lab);
      if (inScale[pc]) {
        k.classList.add("inscale");
        if (dist === 0) k.classList.add("tonic");
      } else {
        k.classList.add("outscale");
      }
    }
    if (window.StavePanel) {
      if (def.sig === null) {
        StavePanel.setKey("auto");
      } else {
        var parent = (((tonicPc + def.sig) % 12) + 12) % 12;
        StavePanel.setKey(PC_MAJOR[parent]);
      }
    }
  }

  // number of white keys strictly below `note`
  function whiteBelow(note) {
    var count = 0;
    for (var n = LOW; n < note; n++) {
      if (!isBlack(n)) count++;
    }
    return count;
  }

  function buildPiano() {
    var piano = document.getElementById("piano");
    // Key dimensions come from the CSS vars so JS and CSS can't drift apart.
    var cs = getComputedStyle(document.documentElement);
    var KW = parseFloat(cs.getPropertyValue("--key-w")) || 30;
    var BW = parseFloat(cs.getPropertyValue("--key-bw")) || 19;
    for (var n = LOW; n <= HIGH; n++) {
      var k = document.createElement("div");
      k.className = "key " + (isBlack(n) ? "black" : "white");
      var left;
      if (isBlack(n)) {
        // preceding white key index = whiteBelow(n)
        var wBefore = whiteBelow(n);         // white keys below this black key
        var boundaryKey = wBefore;           // count of whites up to preceding C
        left = (wBefore * KW) - (BW / 2);
      } else {
        left = whiteBelow(n) * KW;
      }
      k.style.left = left + "px";
      if (!isBlack(n) && n % 12 === 0) {
        var lab = document.createElement("span");
        lab.className = "oct-label";
        lab.textContent = octLabel(n);
        k.appendChild(lab);
      }
      k.dataset.note = n;
      piano.appendChild(k);
      keyEls[n] = k;
    }
    piano.style.width = (whiteBelow(HIGH + 1) * KW + 20) + "px";
  }

  function activate(note) {
    var el = keyEls[note];
    if (el) el.classList.add("active");
  }
  function deactivate(note) {
    var el = keyEls[note];
    if (el) el.classList.remove("active");
  }

  // ---- feed ----
  var feedList = document.getElementById("feed-list");
  var flashEl = document.getElementById("flash");
  var MAX_FEED = 400;

  function addFeed(html, cls) {
    var li = document.createElement("li");
    li.className = cls || "";
    li.innerHTML = html;
    feedList.appendChild(li);
    while (feedList.children.length > MAX_FEED) feedList.removeChild(feedList.firstChild);
    feedList.scrollTop = feedList.scrollHeight;
  }

  function fmtTime(t) {
    var s = (t % 60).toFixed(1);
    return String(s).padStart(4, "0") + "s";
  }

  function flash(text, cls) {
    flashEl.textContent = text;
    flashEl.className = "flash " + (cls || "");
    flashEl.classList.remove("pop");
    // force reflow to restart animation
    void flashEl.offsetWidth;
    flashEl.classList.add("pop");
  }

  function handleEvent(ev) {
    if (!ev) return;
    switch (ev.type) {
      case "status":
        setStatus(ev.online);
        addFeed('<span class="time">' + fmtTime(ev.time) + "</span>  " +
          (ev.online ? "keyboard online" : "keyboard offline"), "statusline");
        break;
      case "note":
        activate(ev.note);
        held.add(ev.note);
        addFeed('<span class="time">' + fmtTime(ev.time) +
          '</span>  <span class="nmark">' + ev.name + "</span>  on (v" +
          ev.velocity + ")", "on");
        if (tonicListenActive) {
          // Buffer the pitch class heard; keep (re)starting a short window so
          // a chord blocked over a few key-strikes collects into one buffer.
          if (catchBuffer.indexOf(ev.note % 12) < 0) catchBuffer.push(ev.note % 12);
          // Track the lowest (bass) pitch class heard for symmetric-chord
          // root disambiguation (dim7, aug).
          if (catchBass === null || (ev.note % 12) < catchBass) catchBass = ev.note % 12;
          catchLastAt = ev.time;
          if (catchTimer) clearTimeout(catchTimer);
          catchTimer = setTimeout(resolveCatchBuffer, 350);
        }
        // NOTE: do NOT push to stave here. The quantized_note event for the
        // same note adds it to the stave (with its proper duration). Pushing
        // here too renders each note twice (duplicate notes on the stave).
        break;
      case "noteoff":
        deactivate(ev.note);
        held.delete(ev.note);
        addFeed('<span class="time">' + fmtTime(ev.time) +
          '</span>  <span class="nmark">' + ev.name + "</span>  off", "off");
        break;
      case "flash":
        if (ev.kind === "chord") {
          flash(ev.label, "c-chord");
          addFeed('<span class="time">' + fmtTime(ev.time) +
            '</span>  CHORD  ' + ev.label, "chord");
        } else if (ev.kind === "arpeggio") {
          flash("ARP: " + ev.label, "c-arpeggio");
          addFeed('<span class="time">' + fmtTime(ev.time) +
            '</span>  ARP  ' + ev.label, "arpeggio");
        } else if (ev.kind === "interval") {
          flash(ev.label, "c-interval");
          addFeed('<span class="time">' + fmtTime(ev.time) +
            '</span>  INTERVAL  ' + ev.label, "interval");
        }
        // If the catch button is armed and the analyser names a chord or
        // arpeggio, use it right away: a major/minor triad sets the tonic AND
        // an appropriate scale (major / natural minor). Solving here beats the
        // buffer fallback and gives a correct root for chords/inversions.
        if (tonicListenActive && (ev.kind === "chord" || ev.kind === "arpeggio") &&
            ev.notes && ev.notes.length >= 3) {
          var pcsArr = [];
          var bass = null;
          ev.notes.forEach(function (n) {
            var p = n % 12;
            if (pcsArr.indexOf(p) < 0) pcsArr.push(p);
            if (bass === null || p < bass) bass = p;
          });
          var chord = chordFromPcs(pcsArr, bass);
          if (chord) {
            if (catchTimer) { clearTimeout(catchTimer); catchTimer = null; }
            catchBuffer = [];
            catchBass = null;
            catchLastAt = ev.time;
            resolveCatch(chord.root, chord.mode);
          }
        }
        // Decoupled from record/stop: the mini "last chord / interval" stave
        // always shows the latest flash, mid-take or not. The main stave push
        // stays recording-gated.
        if (window.StavePanel && ev.notes && ev.notes.length) {
          StavePanel.pushMini(ev.kind, ev.notes, ev.time, ev.label);
          if (recording) StavePanel.push(ev.kind, ev.notes, ev.time, ev.label);
        }
        break;
      case "program_change":
        setInstrument(ev.program, ev.name);
        addFeed('<span class="time">' + fmtTime(ev.time) +
          '</span>  PGM CHANGE  ' + ev.name + " (prog " + ev.program + ", ch " + ev.channel + ")", "program_change");
        break;
      case "quantized_note":
        // Update global tempo for quantization
        if (ev.tempo) {
          tempoBpm = ev.tempo;
          window.tempoBpm = ev.tempo;
        }
        renderTempo(ev.tempo, ev.detected_bpm || 0, ev.user_tempo_bpm || 0);
        if (recording && window.StavePanel) StavePanel.push("note", [ev.note], ev.off_time, null, ev.duration);
        break;
      case "quantized_rest":
        // A rest emitted by the recorder when a pause is detected between
        // notes (backend splits long gaps into note value + silence).
        if (ev.tempo) {
          tempoBpm = ev.tempo;
          window.tempoBpm = ev.tempo;
        }
        renderTempo(ev.tempo, ev.detected_bpm || 0, ev.user_tempo_bpm || 0);
        if (recording && window.StavePanel) StavePanel.push("rest", [], ev.off_time, null, ev.duration);
        break;
      case "capture_error":
        showCaptureError(ev.message, ev.restarts);
        break;
      case "replay":
        if (ev.phase === "start") {
          replayActive = true;
          if (setReplayBtn) setReplayBtn();
          replayRawCursor = 0;
          clearRawPlaying();
          addFeed('<span class="time">' + fmtTime(ev.time || 0) +
            "</span>  REPLAY  playing back " + ev.count + " note" +
            (ev.count === 1 ? "" : "s") + " (~" + (ev.duration * 1000) +
            " ms)" , "replay");
        } else if (ev.phase === "step") {
          // Light the keys as notes sound back out the keyboard, and bold
          // the matching entries in the raw midi buffer as they play.
          ev.notes.forEach(function (n) {
            activate(n);
            setTimeout(function () { deactivate(n); }, 250);
          });
          markRawPlaying(ev.notes);
        } else if (ev.phase === "done") {
          replayActive = false;
          if (setReplayBtn) setReplayBtn();
          clearRawPlaying();
          addFeed('<span class="time">' + fmtTime(ev.time || 0) +
            "</span>  REPLAY  done", "replay");
        } else if (ev.phase === "stopped") {
          replayActive = false;
          if (setReplayBtn) setReplayBtn();
          clearRawPlaying();
          addFeed('<span class="time">' + fmtTime(ev.time || 0) +
            "</span>  REPLAY  stopped", "replay");
        } else if (ev.phase === "error") {
          replayActive = false;
          if (setReplayBtn) setReplayBtn();
          clearRawPlaying();
          addFeed('<span class="time">' + fmtTime(ev.time || 0) +
            "</span>  REPLAY  " + ev.message, "replay");
        }
        break;
    }
  }

  // Show a transient strip indicating the capture loop crashed + is restarting.
  function showCaptureError(message, restarts) {
    var el = document.getElementById("capture-error");
    if (!el) return;
    el.textContent = "capture hiccup (" + (restarts || 1) + "x): " + message +
      " — retrying…";
    el.classList.add("visible");
    clearTimeout(el._t);
    el._t = setTimeout(function () {
      el.classList.remove("visible");
    }, 8000);
  }

  // render held keys from initial snapshot
  function seedHeld(notes) {
    notes.forEach(function (n) { activate(n); held.add(n); });
  }

  function setStatus(online) {
    var el = document.getElementById("status");
    el.textContent = online ? "keyboard online" : "keyboard offline";
    el.className = "status " + (online ? "online" : "offline");
  }

  // Same spelling as the backend (chords.nm): note 60 -> "C4".
  var MIDI_NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"];
  function midiNoteName(n) {
    return MIDI_NOTE_NAMES[n % 12] + (Math.floor(n / 12) - 1);
  }

  // Emergency recovery: close ALL monitor instances and restart the server.
  // The backend answers, then kills this process & respawns; we show a
  // "restarting" state and reload once the new server answers /api/state.
  (function () {
    var btn = document.getElementById("reset-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      if (btn.disabled) return;
      btn.disabled = true;
      var el = document.getElementById("status");
      if (el) {
        el.textContent = "restarting server...";
        el.className = "status offline";
      }
      fetch("/api/reset", { method: "POST" }).catch(function () {});
      var attempts = 0;
      (function poll() {
        attempts++;
        fetch("/api/state", { cache: "no-store" })
          .then(function (r) { return r.json(); })
          .then(function (s) {
            // fresh server is answering again
            location.reload();
          })
          .catch(function () {
            if (attempts < 40) setTimeout(poll, 1500);
            else location.reload();
          });
      })();
    });
  })();

  function setInstrument(program, name) {
    var el = document.getElementById("instrument");
    if (el) el.textContent = "instrument: " + name + " (prog " + program + ")";
  }

  // Render the tempo control from backend state.
  // effective = the BPM quantization actually uses (user-fixed or detected);
  // detected  = the live estimate, shown as a guide when a user tempo is set;
  // user      = the user-fixed value (0 = auto).
  function renderTempo(effective, detected, user) {
    var input = document.getElementById("tempo-input");
    if (!input) return;
    var tag = document.getElementById("tempo-tag");
    var det = document.getElementById("tempo-detected");

    // Don't clobber what the user is typing.
    if (document.activeElement !== input) {
      input.value = user > 0 ? String(Math.round(user)) : "";
    }
    if (tag) {
      tag.textContent = (user > 0 ? "fixed " : "auto ") +
        (effective > 0 ? Math.round(effective) + " BPM" : "\u2014");
    }
    if (det) {
      det.textContent = detected > 0
        ? "detected ~" + Math.round(detected) + " BPM"
        : "";
    }
  }

  // (stave-clear and feed-clear buttons were removed: the raw buffer's
  // clear is the single clear path for buffer + derived notation + stream.)

  // REC/STOP take control. REC clears the stave + resets the backend take and
  // starts accumulating; STOP ends the take: the backend flushes the trailing
  // pending note (returned in the response so the client can render it through
  // the recording gate), and the stave fills the final bar with a trailing rest.
  (function () {
    var btn = document.getElementById("record-btn");
    var dot = document.getElementById("record-btn-dot");
    var lab = document.getElementById("record-btn-label");
    if (!btn) return;

    function renderButton() {
      btn.classList.toggle("recording", recording);
      if (dot) dot.classList.toggle("recording", recording);
      if (lab) lab.textContent = recording ? "stop" : "rec";
    }

    btn.addEventListener("click", function () {
      var next = !recording;
      // Flip the gate synchronously: once STOP is issued, the SSE stream for
      // the flushed trailing note must be skipped (we render it from the POST
      // response body instead) — otherwise it would double-render.
      recording = next;
      renderButton();
      if (next) {
        // Start: backend clears the take, frontend clears the stave.
        if (window.StavePanel) window.StavePanel.clear();
      }
      fetch("/api/record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recording: next })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          recording = !!res.recording;
          renderButton();
          if (!recording && res.events && res.events.length && window.StavePanel) {
            // STOP flushed the trailing pending note (returned as both
            // quantized_note and quantized_rest) — render them here because the
            // recording gate is now off and the SSE stream would skip them.
            res.events.forEach(function (ev) {
              if (ev.type === "quantized_note") {
                StavePanel.push("note", [ev.note], ev.off_time, null, ev.duration);
              } else if (ev.type === "quantized_rest") {
                StavePanel.push("rest", [], ev.off_time, null, ev.duration);
              }
            });
          }
          if (!recording && window.StavePanel) {
            StavePanel.finishTake(); // fill the final bar with a trailing rest
          }
        })
        .catch(function () { /* transient */ });
    });

    renderButton();
  })();

  // (feed-clear button removed: see the single-clear note above.)
  // Play/stop take replay. POSTs /api/replay (which serializes the quantized
  // buffer back to the keyboard's internal voices on a background thread);
  // while a replay is active the button becomes a STOP that cancels it.
  // The SSE handler flips replayActive + feeds it back through setReplayBtn().
  var setReplayBtn = null;
  (function () {
    var btn = document.getElementById("replay-btn");
    var lab = document.getElementById("replay-btn-label");
    var glyph = document.getElementById("replay-btn-glyph");
    if (!btn) return;

    function render() {
      btn.classList.toggle("playing", replayActive);
      if (glyph) glyph.textContent = replayActive ? "\u25a0" : "\u25b6";
      if (lab) lab.textContent = replayActive ? "stop" : "play take";
    }
    setReplayBtn = render;

    btn.addEventListener("click", function () {
      if (replayActive) {
        fetch("/api/replay/stop", { method: "POST" })
          .catch(function () { /* transient */ });
        return;
      }
      var voiceSel = document.getElementById("replay-voice");
      var voiceVal = voiceSel ? voiceSel.value : "auto";
      fetch("/api/replay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speed: 1.0, voice: voiceVal })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res.ok) addFeed("REPLAY  " + (res.error || "failed"), "replay");
        })
        .catch(function () { /* transient */ });
    });

    render();
  })();

  // Tonic + scale selector: shade in-scale keys + interval labels on the piano,
  // and drive the stave key signature when the scale maps to one. The "catch"
  // button arms a one-shot listener: the next note (or chord) heard from the
  // keyboard becomes the tonic — a major/minor triad also sets a fitting scale.
  (function () {
    var tonicSel = document.getElementById("key-tonic");
    var scaleSel = document.getElementById("key-scale");
    if (tonicSel && scaleSel) {
      // selectors always hold a valid value (-1 initially = guide off)
      function current() {
        applyScaleGuide(tonicSel.value, scaleSel.value);
      }
      tonicSel.addEventListener("change", current);
      scaleSel.addEventListener("change", current);

      var lst = document.getElementById("listen-tonic");
      var armTimer = null;
      function unarm() {
        tonicListenActive = false;
        lst.classList.remove("listening");
        lst.textContent = "\u266a catch";
        clearTimeout(armTimer);
        armTimer = null;
      }
      lst.addEventListener("click", function () {
        if (tonicListenActive) { unarm(); return; }
        tonicListenActive = true;
        catchBuffer = [];
        catchBass = null;
        lst.classList.add("listening");
        lst.textContent = "\u266a listen\u2026";
        armTimer = setTimeout(unarm, 15000);
      });
    }
  })();

  // Intervals toggle
  (function () {
    var cb = document.getElementById("show-intervals");
    if (!cb) return;
    cb.addEventListener("change", function () {
      if (window.StavePanel) StavePanel.setShowIntervals(cb.checked);
    });
  })();

  // Quantization strictness selector (grid fineness)
  (function () {
    var sel = document.getElementById("quantization");
    if (!sel) return;
    sel.addEventListener("change", function () {
      var divs = parseInt(sel.value, 10);
      fetch("/api/quant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ divisions: divs })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (window.StavePanel) window.StavePanel.clear();
        })
        .catch(function () { /* ignore transient */ });
    });
  })();

  // Time-signature selector (beats per measure) for stave + metronome.
  (function () {
    var sel = document.getElementById("timesig");
    if (!sel) return;
    sel.addEventListener("change", function () {
      var parts = sel.value.split("/");
      var numer = parseInt(parts[0], 10);
      var denom = parseInt(parts[1], 10);
      setTimesig(numer, denom);
      if (window.StavePanel) window.StavePanel.setTimeSignature(numer, denom);
      fetch("/api/timesig", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ numer: numer, denom: denom })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (window.StavePanel) window.StavePanel.clear();
        })
        .catch(function () { /* ignore transient */ });
    });
  })();

  // Tempo control: enter a BPM to fix the quantization tempo; clear to auto.
  (function () {
    var input = document.getElementById("tempo-input");
    if (!input) return;
    function apply() {
      var raw = input.value.trim();
      if (raw === "") {
        fetch("/api/tempo", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bpm: 0 })
        }).then(function (r) { return r.json(); })
          .then(function (res) {
            if (window.StavePanel) window.StavePanel.clear();
          })
          .catch(function () {});
        return;
      }
      var bpm = parseInt(raw, 10);
      if (!isNaN(bpm) && bpm >= 30 && bpm <= 300) {
        fetch("/api/tempo", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bpm: bpm })
        }).then(function (r) { return r.json(); })
          .then(function (res) {
            if (window.StavePanel) window.StavePanel.clear();
          })
          .catch(function () {});
      }
    }
    input.addEventListener("change", apply);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { input.blur(); apply(); }
    });
  })();

  // Metronome: clicks at the effective tempo (tempoBpm) via Web Audio.
  (function () {
    var btn = document.getElementById("metronome-btn");
    var beatEl = document.getElementById("metro-beat");
    if (!btn) return;
    var ctx = null;
    var timer = null;
    var running = false;
    var beat = 0; // 0 = downbeat (accent), 1+ = offbeats

    function ensureCtx() {
      if (!ctx) {
        try { ctx = new (window.AudioContext || window.webkitAudioContext)(); }
        catch (e) { return null; }
      }
      if (ctx.state === "suspended") { ctx.resume().catch(function(){}); }
      return ctx;
    }

    function click(accent) {
      var c = ensureCtx();
      if (!c) return;
      var now = c.currentTime;
      // two short oscillators for a percussive click; accent = higher pitch
      var freq = accent ? 1800 : 1200;
      for (var i = 0; i < 2; i++) {
        var osc = c.createOscillator();
        var gain = c.createGain();
        osc.type = "square";
        osc.frequency.value = i === 0 ? freq : freq * 0.5;
        gain.gain.setValueAtTime(i === 0 ? 0.7 : 0.5, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.03);
        osc.connect(gain);
        gain.connect(c.destination);
        osc.start(now);
        osc.stop(now + 0.04);
      }
      if (beatEl) {
        beatEl.classList.remove("metro-accent", "metro-pulse");
        void beatEl.offsetWidth; // restart animation
        beatEl.classList.add(accent ? "metro-accent" : "metro-pulse");
      }
      // count in the current meter; accent every `numer` beats (downbeat)
      var beatsPerBar = timesig.numer > 0 ? timesig.numer : 4;
      beat = (beat + 1) % beatsPerBar;
    }

    function start() {
      var bpm = tempoBpm > 0 ? tempoBpm : 0;
      if (bpm <= 0) return; // no tempo yet
      stop();
      beat = 0;
      var intervalMs = 60000 / bpm;
      timer = setInterval(function () {
        click(beat === 0);
      }, intervalMs);
      running = true;
      btn.classList.add("active");
      btn.textContent = "\u266b stop";
      // click immediately on start so there's no dead wait
      click(true);
    }

    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      running = false;
      if (btn) {
        btn.classList.remove("active");
        btn.textContent = "\u266b metronome";
      }
      if (beatEl) { beatEl.classList.remove("metro-accent", "metro-pulse"); }
    }

    btn.addEventListener("click", function () {
      if (running) { stop(); }
      else { start(); }
    });

    window.__metro = { stop: stop };

    // Tidy up if the effective tempo disappears or the page hides.
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop();
    });
  })();

  // Reorder the replay voice selector so the current receive voice is first,
  // then "auto", then the remaining voices.
  function orderReplayVoices(currentVoice) {
    var sel = document.getElementById("replay-voice");
    if (!sel || !currentVoice || currentVoice === "Unknown") return;
    var opts = Array.prototype.slice.call(sel.options);
    var current = null;
    var auto = null;
    for (var i = 0; i < opts.length; i++) {
      if (opts[i].value === currentVoice) current = opts[i];
      if (opts[i].value === "auto") auto = opts[i];
    }
    if (!current || !auto) return;
    // Rebuild in correct order: current voice, then auto, then rest
    var remaining = opts.filter(function (opt) { return opt !== current && opt !== auto; });
    sel.innerHTML = "";
    sel.appendChild(current);
    sel.appendChild(auto);
    remaining.forEach(function (opt) { sel.appendChild(opt); });
    sel.value = currentVoice;
  }

  // initial state
  fetch("/api/state")
    .then(function (r) { return r.json(); })
    .then(function (s) {
      setStatus(s.online);
      orderReplayVoices(s.receive_voice);
      if (typeof s.program !== "undefined") {
        var pname = PSSA50_VOICES[(s.bank || 0) + ":" + s.program] || "Unknown";
        setInstrument(s.program, pname);
      }
      if (typeof s.tempo_bpm !== "undefined" && s.tempo_bpm > 0) {
        tempoBpm = s.tempo_bpm;
        window.tempoBpm = s.tempo_bpm;
      }
      renderTempo(s.tempo_bpm || 0, s.detected_bpm || 0, s.user_tempo_bpm || 0);
      if (typeof s.quantization_divisions !== "undefined") {
        var qsel = document.getElementById("quantization");
        if (qsel && qsel.querySelector('option[value="' + s.quantization_divisions + '"]')) {
          qsel.value = String(s.quantization_divisions);
        }
      }
      if (typeof s.time_signature === "string" && s.time_signature.indexOf("/") > 0) {
        var tp = s.time_signature.split("/");
        setTimesig(parseInt(tp[0], 10), parseInt(tp[1], 10));
        if (window.StavePanel) window.StavePanel.setTimeSignature(parseInt(tp[0], 10), parseInt(tp[1], 10));
        var tsel = document.getElementById("timesig");
        if (tsel && tsel.querySelector('option[value="' + s.time_signature + '"]')) {
          tsel.value = s.time_signature;
        }
      }
      seedHeld(s.held || []);
      // Sync the REC/STOP control with the backend recording state.
      if (typeof s.recording !== "undefined" && s.recording !== recording) {
        recording = !!s.recording;
        var rbtn = document.getElementById("record-btn");
        var dot = document.getElementById("record-btn-dot");
        var lab = document.getElementById("record-btn-label");
        if (rbtn) {
          rbtn.classList.toggle("recording", recording);
          if (dot) dot.classList.toggle("recording", recording);
          if (lab) lab.textContent = recording ? "stop" : "rec";
        }
      }
    })
    .catch(function () { /* server just started? SSE will catch us up */ });

  // raw midi buffer card
  var rawTakeEl = document.getElementById("raw-take");
  var rawTakeClearBtn = document.getElementById("raw-take-clear");
  var rawTakeCleared = false;
  // Monotonic cursor into the rendered raw buffer so replay step events can
  // bold the entry that is currently sounding (progressive illumination).
  var replayRawCursor = 0;

  function clearRawPlaying() {
    if (!rawTakeEl) return;
    var marked = rawTakeEl.querySelectorAll("li.playing");
    for (var i = 0; i < marked.length; i++) {
      marked[i].classList.remove("playing");
    }
  }

  function markRawPlaying(noteNums) {
    // Highlight the next unplayed note_on entry per sounded note. Entries are
    // consumed in buffer order, matching replay which serializes raw events
    // in the same order. No-ops harmlessly if the buffer shows other content
    // (e.g. replaying quantized notes while the raw buffer is empty).
    if (!rawTakeEl || !noteNums || !noteNums.length) return;
    var lis = rawTakeEl.querySelectorAll("li.on[data-note]");
    var updated = false;
    noteNums.forEach(function (n) {
      var want = String(n);
      for (var i = replayRawCursor; i < lis.length; i++) {
        if (lis[i].getAttribute("data-note") === want) {
          lis[i].classList.add("playing");
          if (i + 1 > replayRawCursor) replayRawCursor = i + 1;
          updated = true;
          break;
        }
      }
    });
    if (updated) {
      var played = rawTakeEl.querySelectorAll("li.playing");
      var cur = played.length ? played[played.length - 1] : null;
      if (cur && cur.scrollIntoView) {
        try { cur.scrollIntoView({ block: "nearest" }); } catch (e) { /* noop */ }
      }
    }
  }

  function renderRawTake(events) {
    if (!rawTakeEl) return;
    if (!events || !events.length) {
      rawTakeEl.innerHTML = '<li class="statusline">no raw events yet</li>';
      return;
    }
    // Mirror the note stream markup exactly: each raw on/off event renders as
    // <li class="on">|"off">  <span class="time">00.4s</span>  <span
    // class="nmark">D#4</span>  on (v23)|off  so both panels share the look.
    var frag = document.createDocumentFragment();
    events.forEach(function (ev, idx) {
      var li = document.createElement("li");
      var isOn = ev.type === "note_on";
      li.className = isOn ? "on" : "off";
      // data-idx / data-note let the replay step handler find the entry that
      // is currently sounding so it can be highlighted (bold) in the buffer.
      li.setAttribute("data-idx", String(idx));
      li.setAttribute("data-note", String(ev.note));
      var html = '<span class="time">' + fmtTime(ev.time) + "</span>  " +
        '<span class="nmark">' + midiNoteName(ev.note) + "</span>";
      if (isOn) {
        html += '  on (v' + ev.velocity + ")";
      } else {
        html += "  off";
      }
      li.innerHTML = html;
      frag.appendChild(li);
    });
    rawTakeEl.innerHTML = "";
    rawTakeEl.appendChild(frag);
    replayRawCursor = 0;
    rawTakeEl.scrollTop = rawTakeEl.scrollHeight;
  }

function fetchRawTake() {
  // While a replay is running the buffer is frozen so the playback
  // highlighting isn't wiped by the 1s re-render; resume polling after.
  if (typeof replayActive !== "undefined" && replayActive) return;
  fetch("/api/take")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data && data.ok) {
        // If we're in a cleared state, only update if there are new events
        if (rawTakeCleared && data.raw_events && data.raw_events.length === 0) {
          // Still empty, keep showing cleared state
          return;
        }
        rawTakeCleared = false;
        renderRawTake(data.raw_events || []);
      }
    })
    .catch(function () {
      /* server just started or offline */
    });
}

function clearRawTake() {
  // THE single clear path: the raw buffer is the source take, so clearing it
  // also clears the notation derived from it and the note stream. (REC-start
  // still wipes via the backend as part of beginning a new take.)
  if (rawTakeEl) {
    rawTakeEl.innerHTML = '<li class="statusline">no raw events yet</li>';
  }
  replayRawCursor = 0;
  var feedList = document.getElementById("feed-list");
  if (feedList) feedList.innerHTML = "";
  if (window.StavePanel) window.StavePanel.clear();
  rawTakeCleared = true;
  fetch("/api/take/clear", { method: "POST" })
    .then(function (r) { return r.json(); })
    .catch(function () {
      /* server just started or offline */
    });
  // Temporarily increase polling rate to catch when buffer gets new events
  clearInterval(rawTakeTimer);
  rawTakeTimer = setInterval(fetchRawTake, 200);
  // Resume normal polling after 3 seconds
  setTimeout(function () {
    if (rawTakeTimer) {
      clearInterval(rawTakeTimer);
      rawTakeTimer = setInterval(fetchRawTake, 1000);
    }
  }, 3000);
}

// ... existing code ...

fetchRawTake();
var rawTakeTimer = setInterval(fetchRawTake, 1000);

if (rawTakeClearBtn) {
  rawTakeClearBtn.addEventListener("click", clearRawTake);
}

  // SSE live stream with robust reconnection
  var es = null;
  var esRetryCount = 0;
  var esMaxRetries = 10;
  var esBaseRetryDelay = 1000;
  var esHeartbeatTimeout = null;
  var esHeartbeatInterval = 20000; // expect data at least every 20s (server sends keepalive every 15s)
  var esLastMessageTime = 0;
  var esIsConnecting = false;

  function connectSSE() {
    if (esIsConnecting) return;
    if (esRetryCount >= esMaxRetries) {
      console.error("SSE: Max retries reached, giving up");
      return;
    }
    esIsConnecting = true;
    console.log("SSE: Connecting (attempt " + (esRetryCount + 1) + "/" + esMaxRetries + ")");
    
    var newEs = new EventSource("/api/events");
    
    newEs.onopen = function() {
      console.log("SSE: Connected");
      esIsConnecting = false;
      esRetryCount = 0;
      esLastMessageTime = Date.now();
      startHeartbeat(newEs);
    };
    
    newEs.onmessage = function (msg) {
      esLastMessageTime = Date.now();
      try { handleEvent(JSON.parse(msg.data)); } catch (e) { /* ignore */ }
    };
    
    newEs.onerror = function(err) {
      console.warn("SSE: Error, readyState:", newEs.readyState);
      stopHeartbeat();
      if (newEs.readyState === EventSource.CLOSED) {
        // Exponential backoff with jitter
        var delay = Math.min(esBaseRetryDelay * Math.pow(2, esRetryCount), 30000);
        delay += Math.random() * 1000; // jitter
        esRetryCount++;
        console.log("SSE: Reconnecting in " + delay + "ms (attempt " + esRetryCount + ")");
        setTimeout(connectSSE, delay);
      }
    };
    
    es = newEs;
  }
  
  function startHeartbeat(es) {
    stopHeartbeat();
    esHeartbeatTimeout = setInterval(function() {
      // Check if we've received a message recently (server sends keepalive every 15s)
      if (Date.now() - esLastMessageTime > esHeartbeatInterval) {
        console.warn("SSE: Heartbeat timeout, forcing reconnect");
        es.close();
      }
    }, esHeartbeatInterval);
  }
  
  function stopHeartbeat() {
    if (esHeartbeatTimeout) {
      clearInterval(esHeartbeatTimeout);
      esHeartbeatTimeout = null;
    }
  }
  
  // Handle page visibility changes
  document.addEventListener("visibilitychange", function() {
    if (document.hidden) {
      // Page is hidden, don't reconnect immediately
      stopHeartbeat();
    } else {
      // Page visible, ensure connection is alive
      if (es && es.readyState === EventSource.OPEN) {
        if (Date.now() - esLastMessageTime > esHeartbeatInterval * 2) {
          console.log("Page visible, forcing SSE reconnect");
          es.close();
        }
      } else if (!es || es.readyState === EventSource.CLOSED) {
        connectSSE();
      }
    }
  });
  
  connectSSE();

  // On-screen piano: pointer-clicks PLAY notes. Each press/release POSTs a
  // synthetic MIDI note (via /api/note) that the backend queues onto the live
  // capture stream, so an injected note goes through the SAME pipeline as a
  // real key press: state/feed/analysis/quantization/SSE/stave. Velocity is
  // imputed (this UI has no touch), and the SSE echo lights the keys. Guarded
  // so a held mouse click can't double-inject a note_on.
  var mouseHeld = new Set();
  var pointerNotes = {};  // pointerId -> note (so drags/multitouch each release)

  function injectNote(note, on) {
    if (on) {
      if (mouseHeld.has(note)) return;
      mouseHeld.add(note);
    } else {
      if (!mouseHeld.has(note)) return;
      mouseHeld.delete(note);
    }
    fetch("/api/note", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: note, velocity: 90, on: on })
    }).catch(function () { /* transient; SSE catches up */ });
  }

  function bindPianoClick() {
    var piano = document.getElementById("piano");
    if (!piano) return;
    piano.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      var k = e.target.closest ? e.target.closest(".key") : null;
      if (!k || !k.dataset.note) return;
      e.preventDefault();
      var note = parseInt(k.dataset.note, 10);
      pointerNotes[e.pointerId] = note;
      injectNote(note, true);
    });
    function release(e) {
      var note = pointerNotes[e.pointerId];
      if (note !== undefined) {
        delete pointerNotes[e.pointerId];
        injectNote(note, false);
      }
    }
    piano.addEventListener("pointerup", release);
    piano.addEventListener("pointercancel", release);
    // An injected note off can't fire on the piano itself if the pointer left
    // it mid-press; catch stragglers on the window so nothing stays stuck.
    window.addEventListener("pointerup", release);
  }

  buildCatchTooltip();
  buildPiano();
  bindPianoClick();
})();
