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
var loopActive = false;    // a take is currently looping
  var tempoBpm = 0;  // global tempo for quantization
window.tempoBpm = 0;  // expose on window for durationToVexFlow
  // Time signature (beats per measure). Exposed on window for stave (measure
  // rendering) and metronome (accent grouping). Stays at 4/4 until user changes.
  var timesig = { numer: 4, denom: 4 };
  window.timesig = timesig;

  // REC/STOP take state. REC resets the backend take and clears the stave;
  // STOP freezes the take and renders the notation from the raw buffer.
  // The stave is never pushed live — only the mini stave, feed, piano and
  // flash banner stay live either way. Default True = the take accumulates
  // in the background from page load; the user uses STOP to freeze/render.
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
    var tonicOk = !isNaN(tonicPc) && tonicPc >= 0 && tonicPc <= 11;
    // A bare tonic with no scale means major (saying "G" is G major) — so a
    // tonic change alone always moves the stave key signature + spelling.
    var def = SCALES[scaleId] || (tonicOk && SCALES.major);
    if (!tonicOk || !def) {
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

  // Last signals seen ARRIVING from the keyboard (wheel -> pb/CC1, panel).
  var ctrlRx = { cc: {}, pb: 0 };
  var CTRL_NAMES = {
    1: "mod", 5: "porta time", 7: "vol", 11: "expr", 64: "sustain",
    65: "porta", 71: "harm", 72: "release", 73: "attack", 74: "bright",
    84: "porta ctrl", 91: "fx1", 93: "fx3",
    120: "sound off", 121: "reset ctrl", 122: "local", 123: "notes off"
  };
  function setReceivedReadout() {
    var el = document.getElementById("ctrl-received");
    if (!el) return;
    var parts = [];
    Object.keys(ctrlRx.cc).sort(function (a, b) { return parseInt(a, 10) - parseInt(b, 10); })
      .forEach(function (c) {
        var v = ctrlRx.cc[c];
        parts.push((CTRL_NAMES[c] || ("cc" + c)) + " " +
          (parseInt(c, 10) >= 120 || c === 64 || c === 65 ? (v ? "on" : "off") : v));
      });
    if (ctrlRx.pb) parts.push("pb " + (ctrlRx.pb > 0 ? "+" : "") + ctrlRx.pb);
    el.textContent = parts.length ? parts.join(" \u00B7 ") : "nothing yet";
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
        // always shows the latest flash, mid-take or not. The main stave is
        // never pushed live — it renders from the raw buffer on STOP and on
        // quant/time-sig/tempo changes.
        if (window.StavePanel && ev.notes && ev.notes.length) {
          StavePanel.pushMini(ev.kind, ev.notes, ev.time, ev.label);
        }
        break;
      case "program_change":
        setInstrument(ev.program, ev.name);
        updateReplayVoiceDefault(ev.name);
        addFeed('<span class="time">' + fmtTime(ev.time) +
          '</span>  PGM CHANGE  ' + ev.name + " (prog " + ev.program + ", ch " + ev.channel + ")", "program_change");
        break;
      case "ctrl":
        ctrlRx.cc[ev.controller] = ev.value;
        addFeed('<span class="time">' + fmtTime(ev.time) +
          '</span>  CTRL  ' + ev.name + " = " + ev.value, "ctrl_in");
        setReceivedReadout();
        break;
      case "pitch":
        ctrlRx.pb = ev.semitones;
        addFeed('<span class="time">' + fmtTime(ev.time) + '</span>  PITCH BEND  ' +
          (ev.semitones > 0 ? "+" : "") + ev.semitones + " st",
          ev.semitones === 0 ? "pitch_center" : "pitch_in");
        setReceivedReadout();
        break;
      case "quantized_note":
        // Tempo display only now: the stave itself renders from the raw
        // buffer (STOP / quant / time-sig / tempo), never from live pushes.
        if (ev.tempo) {
          tempoBpm = ev.tempo;
          window.tempoBpm = ev.tempo;
        }
        renderTempo(ev.tempo, ev.detected_bpm || 0, ev.user_tempo_bpm || 0);
        break;
      case "quantized_rest":
        // Rest display: same as above, tempo bookkeeping only.
        if (ev.tempo) {
          tempoBpm = ev.tempo;
          window.tempoBpm = ev.tempo;
        }
        renderTempo(ev.tempo, ev.detected_bpm || 0, ev.user_tempo_bpm || 0);
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
          if (window.StavePanel) StavePanel.resetPlayback();
          if (window.PianoRoll) PianoRoll.resetPlayback();
          addFeed('<span class="time">' + fmtTime(ev.time || 0) +
            "</span>  REPLAY  playing back " + ev.count + " note" +
            (ev.count === 1 ? "" : "s") + " (~" + (ev.duration * 1000) +
            " ms)" , "replay");
        } else if (ev.phase === "step") {
          // Light the keys as notes sound back out the keyboard, bold the
          // matching raw-buffer entries, and purple the sounding notation.
          ev.notes.forEach(function (n) {
            activate(n);
            setTimeout(function () { deactivate(n); }, 250);
          });
          markRawPlaying(ev.notes);
          if (window.StavePanel) StavePanel.markPlaying(ev.notes);
          if (window.PianoRoll) {
            PianoRoll.showPlayhead(ev.t);
            PianoRoll.markPlaying(ev.notes);
          }
        } else if (ev.phase === "done") {
          replayActive = false;
          if (setReplayBtn) setReplayBtn();
          clearRawPlaying();
          if (window.PianoRoll) PianoRoll.resetPlayback();
          addFeed('<span class="time">' + fmtTime(ev.time || 0) +
            "</span>  REPLAY  done", "replay");
        } else if (ev.phase === "voice") {
          // Mid-stream program change (arrangement slots): follow the
          // instrument readout so it shows the voice actually sounding.
          var vn = PSSA50_VOICES[(ev.bank || 0) + ":" + ev.pc] ||
            ("bank " + ev.bank + " prog " + ev.pc);
          setInstrument(ev.pc, vn);
          addFeed('<span class="time">' + fmtTime(ev.time || 0) +
            "</span>  REPLAY  voice \u2192 " + vn, "replay");
        } else if (ev.phase === "stopped" || ev.phase === "error") {
          replayActive = false;
          loopActive = false;
          if (setReplayBtn) setReplayBtn();
          if (setLoopBtn) setLoopBtn();
          clearRawPlaying();
          if (window.PianoRoll) PianoRoll.resetPlayback();
          if (ev.phase === "stopped") {
            addFeed('<span class="time">' + fmtTime(ev.time || 0) +
              "</span>  REPLAY  stopped", "replay");
          } else {
            addFeed('<span class="time">' + fmtTime(ev.time || 0) +
              "</span>  REPLAY  " + ev.message, "replay");
          }
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

  // Chain status line: what the quantizer stage is doing right now.
  var QUANT_GRID_NAMES = { 16: "64ths", 8: "32nds", 4: "16ths", 2: "8ths",
                             1: "quarters", 0.5: "halves", 0.25: "wholes" };
  // Transposer stage shift (semitones). The raw buffer shows the SOURCE take,
  // so step matching un-transposes; the stave is derived post-shift already.
  var transposeSt = 0;
  function renderChainStatus(data) {
    var counts = document.getElementById("chain-counts");
    var status = document.getElementById("chain-status");
    var c = (data && data.counts) || {};
    if (counts) {
      counts.textContent = "in " + (c.in || 0) + " \u2192 out " + (c.out || 0);
    }
    if (typeof data.transpose === "number") transposeSt = data.transpose;
    if (status) {
      var parts = [];
      if (data && data.enabled === false) parts.push("bypass \u00B7 exact timing");
      else {
        var grid = QUANT_GRID_NAMES[data ? data.divisions : 0] || "";
        var bpm = (data && data.tempo > 0) ? Math.round(data.tempo) + "bpm" : "no tempo yet";
        parts.push((grid ? grid + " @ " : "") + bpm);
      }
      if (transposeSt) parts.push((transposeSt > 0 ? "+" : "") + transposeSt + "st");
      status.textContent = parts.join(" \u00B7 ");
    }
  }

  // Notation is rendered FROM the raw take buffer (/api/notation), never
  // pushed live: every render below rebuilds the whole stave from the buffer
  // under the current quantisation, so quant/time-sig/tempo changes re-hear
  // the same take instead of wiping it.
  function renderNotationFromBuffer() {
    if (!window.StavePanel) return;
    fetch("/api/notation", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok || !window.StavePanel) return;
        if (typeof data.tempo === "number" && data.tempo > 0) {
          tempoBpm = data.tempo;
          window.tempoBpm = data.tempo;
        }
        renderChainStatus(data);
        StavePanel.clear();
        (data.events || []).forEach(function (ev) {
          if (ev.kind === "rest") {
            StavePanel.push("rest", [], ev.off_time, null, ev.duration);
          } else {
            StavePanel.push(ev.kind, ev.notes, ev.off_time,
                            ev.label || null, ev.duration);
          }
        });
        StavePanel.finishTake(); // fill the final bar with a trailing rest
        // The piano roll is a second consumer of the SAME events, so it always
        // mirrors the notation (one fetch drives both cards).
        if (window.PianoRoll) window.PianoRoll.render(data.events || [], data);
      })
      .catch(function () { /* transient */ });
  }

  // REC/STOP take control. REC resets the backend take and clears the stave;
  // STOP freezes the take and renders the notation from the raw buffer.
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
      recording = next;
      renderButton();
      if (next) {
        // Start: backend clears the take, frontend clears the stave + roll.
        if (window.StavePanel) window.StavePanel.clear();
        if (window.PianoRoll) window.PianoRoll.clear();
      }
      fetch("/api/record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recording: next })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          recording = !!res.recording;
          renderButton();
          if (!recording) {
            // STOP: the take froze (backend flushed the trailing note into
            // the buffer) — render the whole notation from the raw buffer.
            renderNotationFromBuffer();
          }
        })
        .catch(function () { /* transient */ });
    });

    renderButton();
  })();
  // Let the raw card's clear button ("new empty buffer") drop out of
  // recording mode too, so the button UI can't disagree with the backend.
  window.syncRecording = function (on) {
    recording = !!on;
    var btn = document.getElementById("record-btn");
    var dot = document.getElementById("record-btn-dot");
    var lab = document.getElementById("record-btn-label");
    if (btn) btn.classList.toggle("recording", recording);
    if (dot) dot.classList.toggle("recording", recording);
    if (lab) lab.textContent = recording ? "stop" : "rec";
  };

  // Note stream clear: stream display only, never touches the raw buffer
  // or the notation derived from it (those belong to the raw card's clear).
  (function () {
    var btn = document.getElementById("feed-clear");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var feedList = document.getElementById("feed-list");
      if (feedList) feedList.innerHTML = "";
    });
  })();
  // Play/restart take replay. POSTs /api/replay (which serializes the
  // quantized buffer back to the keyboard's internal voices on a background
  // thread). The button always says "play": pressing it again while a take is
  // sounding restarts from the beginning. STOP is the separate halt control.
  var setReplayBtn = null;
  (function () {
    var btn = document.getElementById("replay-btn");
    var lab = document.getElementById("replay-btn-label");
    var glyph = document.getElementById("replay-btn-glyph");
    if (!btn) return;

    function startReplay() {
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
    }

    function render() {
      btn.classList.toggle("playing", replayActive);
      if (glyph) glyph.textContent = "\u25b6";
      if (lab) lab.textContent = "play";
    }
    setReplayBtn = render;

    btn.addEventListener("click", function () {
      if (replayActive) {
        // Already playing: restart from the beginning.
        fetch("/api/replay/stop", { method: "POST" })
          .then(function () { startReplay(); })
          .catch(function () { /* transient */ });
        return;
      }
      startReplay();
    });

    // Pinning: a hand-picked non-auto voice stops the default from following
    // the keyboard; choosing "auto" again resumes tracking.
    var voiceSel = document.getElementById("replay-voice");
    if (voiceSel) {
      voiceSel.addEventListener("change", function () {
        replayVoicePinned = voiceSel.value !== "auto";
      });
    }

    render();
  })();

// STOP button: halt playback immediately (all notes off).
  (function () {
    var btn = document.getElementById("replay-stop-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      fetch("/api/replay/stop", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && !res.active) {
            replayActive = false;
            loopActive = false;
            setReplayBtn && setReplayBtn();
            setLoopBtn && setLoopBtn();
          }
        })
        .catch(function () { /* transient */ });
    });
  })();

  // LOOP button: start replay looping until STOP is clicked.
  var setLoopBtn = null;
  (function () {
    var btn = document.getElementById("replay-loop-btn");
    if (!btn) return;

    function renderLoop() {
      btn.classList.toggle("active", loopActive);
      btn.classList.toggle("recording", loopActive);
    }
    setLoopBtn = renderLoop;

    btn.addEventListener("click", function () {
      if (loopActive) {
        fetch("/api/replay/stop", { method: "POST" })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            loopActive = false;
            renderLoop();
            if (res && !res.active) {
              replayActive = false;
              setReplayBtn && setReplayBtn();
            }
          })
          .catch(function () { /* transient */ });
        return;
      }
      var voiceSel = document.getElementById("replay-voice");
      var voiceVal = voiceSel ? voiceSel.value : "auto";
      fetch("/api/replay/loop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speed: 1.0, voice: voiceVal })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            loopActive = true;
            replayActive = true;
            renderLoop();
            setReplayBtn && setReplayBtn();
          } else {
            addFeed("LOOP  " + (res.error || "failed"), "replay");
          }
        })
        .catch(function () { /* transient */ });
    });
  })();

  // Output routing ("midi spaghetti zone"): checkboxes for every available
  // MIDI sink + raw device, loaded from /api/outs and saved on change.
  (function () {
    var listEl = document.getElementById("routing-list");
    if (!listEl) return;

    var state = { seq: [], raw: [], channel: 0 };
    var boxes = [];

    // Launchable-apps row ("spaghetti zone" sources): one button per entry in
    // the sinks registry (/api/sinks), data-driven — adding a DAW to
    // monitor/sinks.py just adds a button here. Each button shows up/down
    // state, spawns the app on click, then polls until it appears as an ALSA
    // sink (or a short timeout). When one just came up, the destination list
    // reloads so its checkbox shows up immediately.
    var appsEl = document.getElementById("launchable-apps");
    var polls = {}; // key -> {timer, tries, lastRunning}

    // Pull latest /api/outs so newly-appeared sinks (e.g. an app right after
    // launch) show up as checkboxes immediately, honouring server routing.
    function reloadOuts() {
      fetch("/api/outs", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            state.seq = res.seq_outs || [];
            state.raw = res.raw_outs || [];
            state.channel = res.channel || 0;
            window.__outsAvail = res.available || [];
            render();
          }
        })
        .catch(function () { /* transient */ });
    }

    function renderApps(sinks) {
      if (!appsEl) return;
      appsEl.innerHTML = "";
      var buttons = {};
      sinks.forEach(function (s) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "app-launch-btn";
        btn.dataset.key = s.key;
        var glyph = document.createElement("span");
        glyph.className = "app-launch-glyph";
        var label = document.createElement("span");
        label.className = "app-launch-label";
        btn.appendChild(glyph);
        btn.appendChild(label);
        btn.title = "Launch " + s.name + " if it isn't already running (needs its MIDI input module for the loop to reach it)";
        btn.addEventListener("click", function () { launchApp(s.key); });
        buttons[s.key] = { btn: btn, glyph: glyph, label: label };
        appsEl.appendChild(btn);
      });
      refreshApps(buttons);
      setInterval(function () { refreshApps(buttons); }, 10000); // keep state honest
    }

    function refreshApps(buttons) {
      fetch("/api/sinks", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || !res.ok || !res.sinks) return;
          res.sinks.forEach(function (s) {
            var ref = buttons[s.key];
            if (!ref) return;
            var poll = polls[s.key];
            var busy = !!s.launching || !!(poll && poll.tries && poll.tries > 0);
            ref.btn.classList.toggle("running", !!s.running);
            ref.btn.classList.toggle("busy", busy);
            ref.btn.disabled = busy && !s.running;
            ref.glyph.textContent = s.running ? "\u2713" : (busy ? "\u2026" : "\u25b6");
            ref.label.textContent = s.running
              ? s.name.toLowerCase() + " is up"
              : (busy ? "launching\u2026" : "launch " + (s.name || s.key).toLowerCase());
            // Just came up while we were polling it -> refresh the sink list.
            if (poll && poll.tries && s.running && !poll.lastRunning) reloadOuts();
            if (poll) poll.lastRunning = !!s.running;
          });
        })
        .catch(function () { /* transient */ });
    }

    function paintBusy(ref) {
      if (!ref) return;
      ref.classList.remove("running");
      ref.classList.add("busy");
      ref.disabled = true;
      ref.children[0].textContent = "\u2026";
      ref.children[1].textContent = "launching\u2026";
    }

    function launchApp(key) {
      var ref = null;
      if (appsEl) {
        for (var i = 0; i < appsEl.children.length; i++) {
          if (appsEl.children[i].dataset.key === key) { ref = appsEl.children[i]; break; }
        }
      }
      if (ref && (ref.classList.contains("running") || ref.classList.contains("busy"))) return;
      var poll = polls[key] || (polls[key] = { tries: 0, lastRunning: false });
      poll.tries = 1;
      poll.lastRunning = false;
      paintBusy(ref);
      fetch("/api/sinks/" + encodeURIComponent(key) + "/launch", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            addFeed((res.message || "launching"), "replay");
            if (res.running) { poll.tries = 0; refreshApps(buttonsByKey()); return; }
          } else if (res && res.error) {
            addFeed("LAUNCH  " + res.error, "replay");
            poll.tries = 0;
            refreshApps(buttonsByKey());
            return;
          }
          if (poll.timer) clearInterval(poll.timer);
          poll.timer = setInterval(function () {
            poll.tries += 1;
            refreshApps(buttonsByKey());
            if (poll.tries >= 14) { // ~21s cap
              clearInterval(poll.timer);
              poll.tries = 0;
              refreshApps(buttonsByKey());
            }
          }, 1500);
        })
        .catch(function () {
          poll.tries = 0;
          refreshApps(buttonsByKey());
        });
    }

    function buttonsByKey() {
      var out = {};
      if (appsEl) {
        for (var i = 0; i < appsEl.children.length; i++) {
          var b = appsEl.children[i];
          out[b.dataset.key] = { btn: b, glyph: b.children[0], label: b.children[1] };
        }
      }
      return out;
    }

    fetch("/api/sinks", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (res) { if (res && res.ok) renderApps(res.sinks); })
      .catch(function () { /* transient */ });

    function save() {
      return fetch("/api/outs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seq_outs: state.seq, raw_outs: state.raw, channel: state.channel })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res.ok) addFeed("ROUTE  " + (res.error || "failed"), "replay");
          return res;
        })
        .catch(function () { /* transient */ });
    }

    function render() {
      listEl.innerHTML = "";
      boxes = [];
      // raw devices first (keyboard internal voices) with a lock hint
      state.raw.forEach(function (dev) {
        var lab = document.createElement("label");
        lab.className = "routing-item";
        var box = document.createElement("input");
        box.type = "checkbox";
        box.checked = true;
        box.disabled = true; // raw list is server-managed (keyboard always on)
        var span = document.createElement("span");
        span.textContent = "keyboard \u2014 " + dev;
        span.className = "routing-name";
        lab.appendChild(box);
        lab.appendChild(span);
        listEl.appendChild(lab);
        boxes.push(box);
      });
      // seq destinations
      var seq = state.seq;
      var avail = (window.__outsAvail || []);
      avail.forEach(function (o) {
        var lab = document.createElement("label");
        lab.className = "routing-item";
        var box = document.createElement("input");
        box.type = "checkbox";
        box.checked = seq.indexOf(o.target) !== -1;
        box.dataset.target = o.target;
        var span = document.createElement("span");
        span.textContent = o.name + " \u2014 " + o.target;
        span.className = "routing-name";
        lab.appendChild(box);
        lab.appendChild(span);
        listEl.appendChild(lab);
        boxes.push(box);
        box.addEventListener("change", function () {
          var t = box.dataset.target;
          var idx = state.seq.indexOf(t);
          if (box.checked && idx === -1) state.seq.push(t);
          if (!box.checked && idx !== -1) state.seq.splice(idx, 1);
          save();
        });
      });
    }

    fetch("/api/outs", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res && res.ok) {
          state.seq = res.seq_outs || [];
          state.raw = res.raw_outs || [];
          state.channel = res.channel || 0;
          window.__outsAvail = res.available || [];
          render();
        }
      })
      .catch(function () { /* transient */ });
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

  // Transposer stage: semitone shift applied to the transformed take
  // (notation + OUT hear it; the raw buffer keeps the source pitches).
  (function () {
    var input = document.getElementById("transpose-input");
    if (!input) return;
    function apply() {
      var raw = input.value.trim();
      var st = raw === "" ? 0 : parseInt(raw, 10);
      if (isNaN(st)) return;
      st = Math.max(-24, Math.min(24, st));
      input.value = String(st);
      fetch("/api/transpose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ semitones: st })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && typeof res.semitones === "number") transposeSt = res.semitones;
          renderNotationFromBuffer();
        })
        .catch(function () { /* ignore transient */ });
    }
    input.addEventListener("change", apply);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { input.blur(); apply(); }
    });
  })();

  // Release articulation (staccato gap): % of each note's slot left silent
  // before the next attack. 0 = legato; releases never ring into successors.
  (function () {
    var input = document.getElementById("articulation-input");
    if (!input) return;
    function apply() {
      var raw = input.value.trim();
      var pct = raw === "" ? 0 : parseInt(raw, 10);
      if (isNaN(pct)) return;
      pct = Math.max(0, Math.min(90, pct));
      input.value = String(pct);
      fetch("/api/articulation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gap: pct / 100 })
      }).then(function (r) { return r.json(); })
        .then(function () { renderNotationFromBuffer(); })
        .catch(function () { /* ignore transient */ });
    }
    input.addEventListener("change", apply);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { input.blur(); apply(); }
    });
  })();

  // Out control surface: send CCs / pitch to the keyboard (raw hw:2,0,0) and
  // track what comes back from it. Wire the knobs + panic/gm reset buttons.
  (function () {
    var ctrlStatusEl = document.getElementById("ctrl-status");
    var ctrlStatusTimer = null;
    function flashCtrlStatus(text, bad) {
      if (!ctrlStatusEl) return;
      ctrlStatusEl.textContent = text;
      ctrlStatusEl.classList.toggle("bad", !!bad);
      ctrlStatusEl.hidden = false;
      if (ctrlStatusTimer) clearTimeout(ctrlStatusTimer);
      ctrlStatusTimer = setTimeout(function () { ctrlStatusEl.hidden = true; }, 2600);
    }
    function describeCtrl(body) {
      if (body.cc) return "CC" + body.cc + " = " + body.value;
      if (body.pitch !== undefined) return "pitch " + (body.pitch > 0 ? "+" : "") + body.pitch;
      if (body.action) return body.action;
      return "send";
    }
    function postCtrl(label, body) {
      fetch("/api/ctrl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            addFeed('SENT \u2192 ' + label + (res.device === false ? " (board offline)" : ""), "ctrl_out");
            if (res.warning) flashCtrlStatus("keyboard offline \u2014 " + label + " dropped", true);
            else flashCtrlStatus(label + " sent", false);
          } else if (res && res.error) {
            flashCtrlStatus(res.error, true);
          }
        })
        .catch(function () { flashCtrlStatus("send failed", true); });
    }
    function wireRange(id, bodyFn, label) {
      var el = document.getElementById(id);
      if (!el) return;
      var out = document.getElementById(id + "-out");
      el.addEventListener("input", function () {
        if (out) out.textContent = el.value;
        postCtrl(label + " " + el.value, bodyFn(el));
      });
    }
    wireRange("ctrl-porta-time", function (el) { return { cc: 5, value: parseInt(el.value, 10) }; }, "porta time");
    wireRange("ctrl-volume", function (el) { return { cc: 7, value: parseInt(el.value, 10) }; }, "volume");
    wireRange("ctrl-expression", function (el) { return { cc: 11, value: parseInt(el.value, 10) }; }, "expression");
    wireRange("ctrl-mod", function (el) { return { cc: 1, value: parseInt(el.value, 10) }; }, "mod");
    wireRange("ctrl-pitch", function (el) { return { pitch: parseFloat(el.value) }; }, "pitch");
    // Pitch snap-back: on release the slider springs to 0 like a real wheel,
    // unless "snap" is unchecked (sticky bend stays where you leave it).
    (function () {
      var pel = document.getElementById("ctrl-pitch");
      var psnap = document.getElementById("ctrl-pitch-snap");
      if (!pel) return;
      pel.addEventListener("change", function () {
        if (psnap && !psnap.checked) return;
        pel.value = "0";
        var pout = document.getElementById("ctrl-pitch-out");
        if (pout) pout.textContent = "0";
        postCtrl("pitch 0", { pitch: 0 });
      });
    })();
    function wireCheck(id, cc, label) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("change", function () {
        var v = el.checked ? 127 : 0;
        if (cc) postCtrl(label + " " + (el.checked ? "on" : "off"), { cc: cc, value: v });
        else postCtrl(label + " " + (el.checked ? "on" : "off"), { action: "local", value: v });
      });
    }
    wireCheck("ctrl-sustain", 64, "sustain");
    wireCheck("ctrl-porta", 65, "portamento");
    function wireBtn(id, bodyFn, label) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("click", function () { postCtrl(label, bodyFn()); });
    }
    wireBtn("ctrl-panic", function () { return { action: "panic" }; }, "panic");
    wireBtn("ctrl-gmreset", function () { return { action: "gmreset" }; }, "gm reset");
    // Keys routing: 'echo' (notes routed back from the app) and 'local'
    // (board sounds its own keys) are two switches with four combined modes.
    // One segmented control sets both so they can't drift apart.
    //   keys  = local on,  echo off   (normal play)
    //   layer = local on,  echo on    (panel voice + echo voice)
    //   echo  = local off, echo on    (echo alone)
    //   midi  = local off, echo off   (keys emit MIDI only, silent)
    var KEYS_MODE_LOCAL = { keys: 1, layer: 1, echo: 0, midi: 0 };
    var KEYS_MODE_ECHO = { keys: 0, layer: 1, echo: 1, midi: 0 };
    var keysSeg = document.getElementById("ctrl-keys-mode");
    var keysMode = "keys";

    function echoVoiceValue() {
      var sel = document.getElementById("replay-voice");
      return sel ? sel.value : "auto";
    }
    function setKeysSeg(mode) {
      keysMode = mode;
      if (!keysSeg) return;
      var btns = keysSeg.querySelectorAll("button");
      for (var i = 0; i < btns.length; i++) {
        btns[i].classList.toggle("active", btns[i].getAttribute("data-mode") === mode);
      }
    }
    function sendEcho(enabled) {
      fetch("/api/echo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: enabled, voice: echoVoiceValue() })
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            var lbl = "echo " + (enabled ? "on" : "off");
            var v = (res.voice && res.voice !== "auto") ? " \u00b7 " + res.voice : "";
            addFeed("SENT \u2192 " + lbl + v +
                    (res.device === false ? " (board offline)" : ""), "ctrl_out");
            if (res.warning) flashCtrlStatus("keyboard offline \u2014 " + lbl + " dropped", true);
          } else if (res && res.error) {
            flashCtrlStatus(res.error, true);
          }
        })
        .catch(function () { flashCtrlStatus("echo toggle failed", true); });
    }
    function applyKeysMode(mode) {
      if (!(mode in KEYS_MODE_ECHO)) mode = "keys";
      setKeysSeg(mode);
      var localOn = KEYS_MODE_LOCAL[mode];
      postCtrl("local " + (localOn ? "on" : "off"),
               { action: "local", value: localOn ? 127 : 0 });
      sendEcho(!!KEYS_MODE_ECHO[mode]);
      flashCtrlStatus("keys: " + mode, false);
    }
    if (keysSeg) {
      keysSeg.addEventListener("click", function (e) {
        var b = e.target.closest("button");
        if (b && b.getAttribute("data-mode")) applyKeysMode(b.getAttribute("data-mode"));
      });
    }
    // Boot-sync from server state (local_control + echo_enabled) without sending.
    window.syncKeysMode = function (localOn, echoOn) {
      var mode = echoOn ? (localOn ? "layer" : "echo") : (localOn ? "keys" : "midi");
      setKeysSeg(mode);
    };
    // Changing the OUT voice while echo is on re-applies it to the echo path.
    var rvSel = document.getElementById("replay-voice");
    if (rvSel) {
      rvSel.addEventListener("change", function () {
        if (KEYS_MODE_ECHO[keysMode]) sendEcho(true);
      });
    }
  })();

  // Quantization grid selector (explicit note values, off = bypass)
  (function () {
    var sel = document.getElementById("quantization");
    if (!sel) return;
    sel.addEventListener("change", function () {
      var divs = parseFloat(sel.value);
      if (isNaN(divs)) return;
      fetch("/api/quant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ divisions: divs })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          renderNotationFromBuffer();
        })
        .catch(function () { /* ignore transient */ });
    });
  })();

  // Velocity compressor stage: standard velocity, width and mode.
  // Standard is the center of the target band; blank / detect = auto
  // (median of note-on velocities in the raw buffer). Width is the band
  // half-width. Mode: "compress" = linearly rescale the whole buffer into
  // the band; "threshold" = clip values outside the band to the edges.
  (function () {
    var stdInput = document.getElementById("vel-standard");
    var widthInput = document.getElementById("vel-width");
    var modeSel = document.getElementById("vel-mode");
    var autoBtn = document.getElementById("vel-auto");
    var enabledChk = document.getElementById("vel-enabled");
    if (!stdInput && !widthInput && !modeSel && !autoBtn && !enabledChk) return;

    function apply() {
      var body = {};
      if (enabledChk) body.enabled = enabledChk.checked;
      if (stdInput && stdInput.value.trim() !== "") {
        var std = parseInt(stdInput.value, 10);
        if (!isNaN(std)) body.standard = std;
      } else {
        body.standard = null;  // auto-detect
      }
      if (widthInput && widthInput.value.trim() !== "") {
        var w = parseInt(widthInput.value, 10);
        if (!isNaN(w)) body.width = w;
      }
      if (modeSel) body.mode = modeSel.value;
      fetch("/api/velocity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            if (typeof res.enabled === "boolean" && enabledChk) {
              enabledChk.checked = res.enabled;
            }
            if (typeof res.standard === "number" && stdInput) {
              stdInput.value = String(res.standard);
            }
            if (typeof res.width === "number" && widthInput) {
              widthInput.value = String(res.width);
            }
            if (res.mode && modeSel) modeSel.value = res.mode;
            renderNotationFromBuffer();
          }
        })
        .catch(function () { /* ignore transient */ });
    }

    if (stdInput) stdInput.addEventListener("change", apply);
    if (widthInput) widthInput.addEventListener("change", apply);
    if (modeSel) modeSel.addEventListener("change", apply);
    if (autoBtn) autoBtn.addEventListener("click", apply);
    if (enabledChk) enabledChk.addEventListener("change", apply);
  })();

  // Humanizer stage: subtle timing and velocity variation applied at the
  // very end of the transform chain (to the final OUT MIDI events).
  (function () {
    var enabledChk = document.getElementById("humanizer-enabled");
    var timingInput = document.getElementById("humanizer-timing");
    var velocityInput = document.getElementById("humanizer-velocity");
    if (!enabledChk && !timingInput && !velocityInput) return;

    function apply() {
      var body = {};
      if (enabledChk) body.enabled = enabledChk.checked;
      if (timingInput && timingInput.value.trim() !== "") {
        var t = parseInt(timingInput.value, 10);
        if (!isNaN(t)) body.timing_ms = t;
      }
      if (velocityInput && velocityInput.value.trim() !== "") {
        var v = parseInt(velocityInput.value, 10);
        if (!isNaN(v)) body.velocity = v;
      }
      fetch("/api/humanizer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            if (typeof res.enabled === "boolean" && enabledChk) {
              enabledChk.checked = res.enabled;
            }
            if (typeof res.timing_ms === "number" && timingInput) {
              timingInput.value = String(res.timing_ms);
            }
            if (typeof res.velocity === "number" && velocityInput) {
              velocityInput.value = String(res.velocity);
            }
            renderNotationFromBuffer();
          }
        })
        .catch(function () { /* ignore transient */ });
    }

    if (enabledChk) enabledChk.addEventListener("change", apply);
    if (timingInput) timingInput.addEventListener("change", apply);
    if (velocityInput) velocityInput.addEventListener("change", apply);
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
          renderNotationFromBuffer();
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
            renderNotationFromBuffer();
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
            renderNotationFromBuffer();
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

  // Keep the replay voice default tracking the keyboard's receive voice
  // (same source as the title-bar instrument label), but never stomp an
  // explicit user pick: once the user hand-selects a non-auto voice the
  // default stops following until they choose "auto" again.
  var replayVoicePinned = false;
  function updateReplayVoiceDefault(voiceName) {
    if (replayVoicePinned) return;
    orderReplayVoices(voiceName);
  }

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

  // initial state — also re-runnable as an in-place resync (e.g. after a
  // pattern load), so loading a pattern never needs a full page reload.
  function refreshState() {
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
        if (qsel) {
          // Bypass ("no quantization") shows as off; otherwise the grid.
          var qv = s.quantize_enabled === false ? "0" : String(s.quantization_divisions);
          if (qsel.querySelector('option[value="' + qv + '"]')) qsel.value = qv;
        }
      }
      if (typeof s.transpose_semitones !== "undefined") {
        transposeSt = s.transpose_semitones;
        var tinput = document.getElementById("transpose-input");
        if (tinput && document.activeElement !== tinput) {
          tinput.value = String(s.transpose_semitones);
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
        // Sync velocity compressor settings from backend state
        if (typeof s.velocity_standard !== "undefined") {
          var stdInput = document.getElementById("vel-standard");
          if (stdInput && document.activeElement !== stdInput) {
            stdInput.value = s.velocity_standard === null ? "" : String(s.velocity_standard);
          }
        }
        if (typeof s.velocity_width !== "undefined") {
          var widthInput = document.getElementById("vel-width");
          if (widthInput && document.activeElement !== widthInput) {
            widthInput.value = String(s.velocity_width);
          }
        }
        if (typeof s.velocity_mode !== "undefined") {
          var modeSel = document.getElementById("vel-mode");
          if (modeSel && document.activeElement !== modeSel) {
            modeSel.value = s.velocity_mode;
          }
        }
        if (typeof s.velocity_enabled !== "undefined") {
          // We assume it's always enabled for UI purposes; the control set enables/disables it
          // but we keep UI showing it as enabled so user can adjust parameters
          // (disabled state is handled by the backend; UI always allows tweaking)
        }
        // Sync humanizer settings from backend state
        if (typeof s.humanizer_enabled === "boolean") {
          var hchk = document.getElementById("humanizer-enabled");
          if (hchk && document.activeElement !== hchk) hchk.checked = s.humanizer_enabled;
        }
        if (typeof s.humanizer_timing_ms !== "undefined") {
          var htim = document.getElementById("humanizer-timing");
          if (htim && document.activeElement !== htim) htim.value = String(s.humanizer_timing_ms);
        }
        if (typeof s.humanizer_velocity !== "undefined") {
          var hvel = document.getElementById("humanizer-velocity");
          if (hvel && document.activeElement !== hvel) hvel.value = String(s.humanizer_velocity);
        }
        if (typeof s.articulation_gap !== "undefined") {
          var art = document.getElementById("articulation-input");
          if (art && document.activeElement !== art) {
            art.value = String(Math.round(s.articulation_gap * 100));
          }
        }
        // Sync the OUT control surface (last values we sent) + the received
        // watch (signals arriving from the keyboard).
        var cv = s.control_values || {};
        function chk(id, on) {
          var el = document.getElementById(id);
          if (el && document.activeElement !== el) el.checked = !!on;
        }
        function setRange(id) {
          var el = document.getElementById(id);
          if (el && document.activeElement !== el) el.value = String(arguments[1]);
          var out = document.getElementById(id + "-out");
          if (out) out.textContent = arguments[1];
        }
        chk("ctrl-sustain", cv[64]);
        chk("ctrl-porta", cv[65]);
        if (window.syncKeysMode) {
          window.syncKeysMode(s.local_control !== 0, !!s.echo_enabled);
        }
        setRange("ctrl-porta-time", typeof cv[5] === "number" ? cv[5] : 8);
        setRange("ctrl-volume", typeof cv[7] === "number" ? cv[7] : 100);
        setRange("ctrl-expression", typeof cv[11] === "number" ? cv[11] : 127);
        setRange("ctrl-mod", typeof cv[1] === "number" ? cv[1] : 0);
        setRange("ctrl-pitch", typeof s.control_pitch_bend === "number" ? s.control_pitch_bend : 0);
        ctrlRx.cc = s.received_ctrl || {};
        ctrlRx.pb = s.received_pitch_bend || 0;
        setReceivedReadout();
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
      // Restore the stave + chain status from any take already in the buffer
      // (e.g. after a page reload while the server kept running).
      renderNotationFromBuffer();
    })
    .catch(function () { /* server just started? SSE will catch us up */ });
  }
  window.refreshState = refreshState;
  refreshState();

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
    // The raw buffer shows SOURCE pitches: un-transpose the sounded notes
    // before matching (the stave is derived post-shift and needs no fixup).
    if (!rawTakeEl || !noteNums || !noteNums.length) return;
    var lis = rawTakeEl.querySelectorAll("li.on[data-note]");
    var updated = false;
    noteNums.forEach(function (n) {
      var want = String(n - transposeSt);
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
        var n = (data.raw_events || []).length;
        window.__rawTakeCount = n;
        if (window.__onRawTakeCount) {
          window.__onRawTakeCount({ in: data.in_notes || 0, out: data.out_notes || 0 });
        }
        renderRawTake(data.raw_events || []);
      }
    })
    .catch(function () {
      /* server just started or offline */
    });
}

function clearRawTake() {
  // New empty buffer: stop any recording and wipe the take plus the notation
  // derived from it, so the next notes start from nothing instead of
  // appending to the old take. (REC-start still wipes via the backend as
  // part of beginning a new take.) The note stream has its own clear button
  // (stream display only).
  if (window.syncRecording) window.syncRecording(false);
  if (rawTakeEl) {
    rawTakeEl.innerHTML = '<li class="statusline">no raw events yet</li>';
  }
  replayRawCursor = 0;
  if (window.StavePanel) window.StavePanel.clear();
  rawTakeCleared = true;
  window.__rawTakeCount = 0;
  if (window.__onRawTakeCount) window.__onRawTakeCount({ in: 0, out: 0 });
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
  // so a held mouse click can't double-inject a note_on. Sounding is handled
  // purely by the echo path in the capture loop (layer/echo modes); keys/midi
  // stay silent for analysis only.
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

  // Pattern library ("patterns" card): save the current buffer as a named
  // pattern, then load or delete from the list. Patterns are the raw material
  // the slot grid attaches to; deleting one empties any slots that pointed at
  // it (the backend does the clearing and reports the slots back). Saving
  // stores the events plus the current transform settings; loading restores
  // both, then the whole page reloads so every control re-syncs.
  (function () {
    var box = document.getElementById("patterns-box");
    if (!box) return;
    var nameInput = document.getElementById("pattern-name");
    var saveBtn = document.getElementById("patterns-save");
    var srcSeg = document.getElementById("pattern-source");
    var listEl = document.getElementById("pattern-list");
    var countEl = document.getElementById("pattern-count");
    var selDetail = document.getElementById("pattern-selected");
    var barsInput = document.getElementById("pattern-bars");
    var barsBtn = document.getElementById("patterns-set-bars");
    var statusEl = document.getElementById("patterns-status");
    var bufferEl = document.getElementById("buffer-status");
    var attachEl = document.getElementById("attach-pattern");
    var source = "raw";      // IN raw | OUT, from the segmented control
    var chosen = null;       // slug of the highlighted row (shared selection)
    var cache = [];
    var counts = { in: 0, out: 0 };

    function status(msg, cls) {
      if (statusEl) {
        statusEl.textContent = msg || "";
        statusEl.className = "patterns-status" + (cls ? " " + cls : "");
      }
    }

    function metaText(p) {
      var n = (typeof p.note_count === "number") ? p.note_count + "n" : "";
      var b = (typeof p.bars === "number") ? p.bars + "b" + (p.bars_auto ? "" : "*") : "";
      var k = p.kind === "out" ? "OUT" : "IN";
      return [n, b, k].filter(Boolean).join(" \u00b7 ");
    }

    function renderDetail() {
      var p = null;
      for (var i = 0; i < cache.length; i++) {
        if (cache[i].filename === chosen) { p = cache[i]; break; }
      }
      if (barsBtn) barsBtn.disabled = !p;
      if (selDetail) {
        if (!p) {
          selDetail.textContent = cache.length ? "no pattern selected"
                                               : "no patterns saved yet";
        } else {
          selDetail.textContent = "selected: " + p.name + " \u2014 " + metaText(p);
        }
      }
      if (barsInput && document.activeElement !== barsInput) {
        barsInput.value = (p && !p.bars_auto) ? String(p.bars) : "";
      }
    }

    function render() {
      if (!listEl) return;
      listEl.innerHTML = "";
      if (!cache.length) {
        var empty = document.createElement("div");
        empty.className = "pattern-empty";
        empty.textContent = "nothing saved \u2014 record in the raw midi buffer, name it, save";
        listEl.appendChild(empty);
      }
      cache.forEach(function (p) {
        var row = document.createElement("div");
        row.className = "pattern-row" + (p.filename === chosen ? " sel" : "");
        row.setAttribute("data-slug", p.filename);
        row.title = "slot chars " + ((p.used_slots || []).join(" ") || "(none)") +
                    " use this pattern";

        var nm = document.createElement("span");
        nm.className = "pr-name";
        nm.textContent = p.name;
        row.appendChild(nm);

        var mt = document.createElement("span");
        mt.className = "pr-meta";
        mt.textContent = metaText(p);
        row.appendChild(mt);

        var chips = document.createElement("span");
        chips.className = "pattern-chips";
        (p.used_slots || []).forEach(function (ch) {
          var c = document.createElement("span");
          c.className = "pattern-chip";
          c.textContent = ch;
          chips.appendChild(c);
        });
        row.appendChild(chips);

        var loadB = document.createElement("button");
        loadB.type = "button";
        loadB.className = "mini-btn";
        loadB.textContent = "load";
        loadB.title = "Load this pattern into the raw midi buffer + settings";
        loadB.addEventListener("click", function (e) {
          e.stopPropagation();
          load(p.filename, p.name);
        });
        row.appendChild(loadB);

        var delB = document.createElement("button");
        delB.type = "button";
        delB.className = "mini-btn danger";
        delB.textContent = "del";
        delB.title = "Delete this pattern";
        delB.addEventListener("click", function (e) {
          e.stopPropagation();
          del(p);
        });
        row.appendChild(delB);

        row.addEventListener("click", function () {
          chosen = p.filename;
          render();
        });
        listEl.appendChild(row);
      });

      if (countEl) {
        countEl.textContent = cache.length ? cache.length + " saved" : "";
      }

      renderAttach();
      renderDetail();
    }

    function refresh() {
      fetch("/api/patterns", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || !res.ok) return;
          cache = res.patterns || [];
          if (chosen) {
            var still = false;
            for (var i = 0; i < cache.length; i++) {
              if (cache[i].filename === chosen) { still = true; break; }
            }
            if (!still) chosen = null;
          }
          render();
        })
        .catch(function () { /* transient */ });
    }

    function updateBufferStatus() {
      var n = source === "out" ? counts.out : counts.in;
      if (bufferEl) {
        bufferEl.textContent = n
          ? "source buffer: " + n + (n === 1 ? " note" : " notes") +
            " \u00b7 " + (source === "out" ? "OUT" : "IN raw")
          : "source buffer: empty \u2014 press rec";
        bufferEl.className = "buffer-status" + (n ? "" : " empty");
      }
      if (saveBtn) {
        saveBtn.title = n
          ? ("Save the " + (source === "out" ? "OUT" : "raw midi") +
             " buffer as a pattern")
          : "Buffer is empty \u2014 press rec in the transport row, play, then save";
      }
    }
    // Fed by the shared /api/take poll (fetchRawTake). Never disables save:
    // the server refuses an empty buffer and we show its message, so a stale
    // count can't silently eat a click.
    window.__onRawTakeCount = function (c) {
      if (c && typeof c === "object") counts = c;
      else counts = { in: c || 0, out: counts.out };
      updateBufferStatus();
    };
    window.__refreshPatterns = refresh; // slots card refreshes chips after attach

    // The selected pattern is shared app-wide (the slots card attaches it),
    // so both cards read one selection instead of two pickers.
    function renderAttach() {
      window.__selectedPattern = chosen;
      if (!attachEl) return;
      var p = null;
      for (var i = 0; i < cache.length; i++) {
        if (cache[i].filename === chosen) { p = cache[i]; break; }
      }
      attachEl.textContent = p ? ("attach: " + p.name) : "no pattern selected";
      attachEl.className = "attach-readout" + (p ? "" : " empty");
    }

    function save() {
      status("saving " + (source === "out" ? "OUT" : "IN raw") + " buffer\u2026");
      fetch("/api/patterns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: source, name: (nameInput.value || "").trim() })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            status("saved \u201C" + res.pattern.name + "\u201D (" +
                   res.pattern.note_count + " notes)", "ok");
            chosen = res.pattern.filename;
            if (nameInput) nameInput.value = "";
            refresh();
          } else {
            status((res && res.error) || "save failed", "err");
          }
        })
        .catch(function () { status("save failed", "err"); });
    }

    function load(slug, name) {
      status("loading \u201C" + name + "\u201D\u2026");
      fetch("/api/patterns/" + encodeURIComponent(slug) + "/load", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            status("loaded \u201C" + res.name + "\u201D (" + res.note_count +
                   " notes)", "ok");
            // In-place resync instead of a full page reload: refreshState()
            // re-applies every restored setting (quantize/tempo/transpose/
            // velocity/humanizer/key) and rebuilds the stave; fetchRawTake()
            // re-renders the buffer list.
            if (window.refreshState) window.refreshState();
            fetchRawTake();
          } else {
            status((res && res.error) || "load failed", "err");
          }
        })
        .catch(function () { status("load failed", "err"); });
    }

    function del(p) {
      var used = p.used_slots || [];
      if (used.length) {
        var ok = window.confirm(
          "\u201C" + p.name + "\u201D is used in slots " + used.join(", ") +
          ".\n\nDelete it and empty those slots?");
        if (!ok) return;
      }
      status("deleting \u201C" + p.name + "\u201D\u2026");
      fetch("/api/patterns/" + encodeURIComponent(p.filename), { method: "DELETE" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            var extra = (res.cleared_slots && res.cleared_slots.length)
              ? " \u2014 emptied slots " + res.cleared_slots.join(", ") : "";
            status("deleted \u201C" + p.name + "\u201D" + extra, "ok");
            chosen = null;
            refresh();
            if (window.__refreshSlots) window.__refreshSlots();
          } else {
            status((res && res.error) || "delete failed", "err");
          }
        })
        .catch(function () { status("delete failed", "err"); });
    }

    function setBars() {
      if (!chosen) { status("select a pattern first", "err"); return; }
      var val = barsInput ? (barsInput.value || "").trim() : "";
      status("setting bar length\u2026");
      fetch("/api/patterns/" + encodeURIComponent(chosen) + "/bars", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bars: val === "" ? null : val })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            var shown = (res.bars === null || res.bars === undefined)
              ? "(auto)" : res.bars + " bars";
            status("bar length \u2192 " + shown, "ok");
            refresh();
          } else {
            status((res && res.error) || "set failed", "err");
          }
        })
        .catch(function () { status("set failed", "err"); });
    }

    if (srcSeg) {
      srcSeg.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-src]");
        if (!b) return;
        source = b.getAttribute("data-src");
        Array.prototype.forEach.call(srcSeg.querySelectorAll("button"), function (x) {
          x.classList.toggle("active", x === b);
        });
        updateBufferStatus();
      });
    }
    if (saveBtn) saveBtn.addEventListener("click", save);
    if (barsBtn) barsBtn.addEventListener("click", setBars);
    if (nameInput) {
      nameInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); save(); }
      });
    }
    box.classList.remove("hidden");
    updateBufferStatus();
    refresh();
    setInterval(refresh, 15000); // keep the library honest across tabs
  })();

  // Slot grid: 64 fixed arrangement slots (base64 A-Z a-z 0-9 +/). Click a
  // cell to select it, then assign the pattern chosen in the strip above
  // with its own transpose + voice. The arrangement string is just slot
  // characters in order; repetition = repeat the character.
  (function () {
    var grid = document.getElementById("slot-grid");
    if (!grid) return;
    var detail = document.getElementById("slot-detail");
    var transpEl = document.getElementById("slot-transpose");
    var voiceEl = document.getElementById("slot-voice");
    var assignBtn = document.getElementById("slot-assign");
    var clearBtn = document.getElementById("slot-clear");
    var statusEl = document.getElementById("slots-status");
    var selIndex = 0;
    var cache = [];

    // Voice choices mirror the replay voice list (blank = leave the voice).
    (function () {
      var src = document.getElementById("replay-voice");
      if (!src || !voiceEl) return;
      for (var i = 0; i < src.options.length; i++) {
        var o = document.createElement("option");
        o.value = src.options[i].value;
        o.textContent = src.options[i].textContent;
        voiceEl.appendChild(o);
      }
    })();

    function status(msg, cls) {
      if (statusEl) {
        statusEl.textContent = msg || "";
        statusEl.className = "patterns-status" + (cls ? " " + cls : "");
      }
    }

    function fmtTranspose(t) {
      t = parseInt(t, 10) || 0;
      return (t > 0 ? "+" + t : String(t));
    }

    function renderDetail() {
      var s = cache[selIndex];
      if (!s) {
        if (detail) detail.textContent = "slot –";
        return;
      }
      var parts = ["slot " + s.slot];
      parts.push(s.name || "(empty)");
      if (s.pattern) {
        if (s.transpose) parts.push(fmtTranspose(s.transpose));
        if (s.voice) parts.push(s.voice);
        if (typeof s.bars === "number") parts.push(s.bars + "b");
      }
      if (detail) detail.textContent = parts.join(" · ");
      if (transpEl && document.activeElement !== transpEl) {
        transpEl.value = s.transpose ? String(s.transpose) : "";
      }
      if (voiceEl && document.activeElement !== voiceEl) {
        voiceEl.value = s.voice || "";
      }
      var has = !!s.pattern;
      if (assignBtn) assignBtn.disabled = false;
      if (clearBtn) clearBtn.disabled = !has;
    }

    function renderGrid(slots) {
      cache = slots || [];
      grid.innerHTML = "";
      cache.forEach(function (s, i) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "slot-cell" + (s.pattern ? " filled" : "") +
                      (i === selIndex ? " sel" : "");
        b.textContent = s.slot;
        var tip = "slot " + s.slot;
        if (s.pattern) {
          tip += ": " + (s.name || s.pattern);
          if (s.transpose) tip += ", " + fmtTranspose(s.transpose);
          if (s.voice) tip += ", " + s.voice;
          if (typeof s.bars === "number") tip += ", " + s.bars + " bars";
          tip += " \u2014 click to append to the arrangement, shift-click to select";
        } else {
          tip += " (empty) \u2014 click to select";
        }
        b.title = tip;
        b.setAttribute("aria-label", tip);
        b.addEventListener("click", function (ev) {
          // A filled slot appends its char to the arrangement on a plain click
          // (the obvious thing); shift-click selects it for assign/transpose.
          // Empty slots have nothing to append, so they just select.
          if (s.pattern && !ev.shiftKey && window.__appendSlotChar) {
            window.__appendSlotChar(s.slot);
            return;
          }
          selectSlot(i);
        });
        grid.appendChild(b);
      });
      renderDetail();
    }

    function selectSlot(i) {
      selIndex = i;
      var cells = grid.querySelectorAll(".slot-cell");
      for (var k = 0; k < cells.length; k++) {
        cells[k].classList.toggle("sel", k === selIndex);
      }
      renderDetail();
    }

    function refresh() {
      fetch("/api/slots", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) renderGrid(res.slots);
        })
        .catch(function () { /* transient */ });
    }

    function assign() {
      var slug = window.__selectedPattern || "";
      if (!slug) { status("no pattern selected \u2014 pick one in the patterns card first", "err"); return; }
      var body = { pattern: slug };
      var tv = transpEl ? (transpEl.value || "").trim() : "";
      body.transpose = tv === "" ? 0 : parseInt(tv, 10);
      if (isNaN(body.transpose)) { status("transpose must be a number", "err"); return; }
      body.voice = voiceEl ? (voiceEl.value || "") : "";
      if (!body.voice) body.voice = null;
      status("assigning slot " + (cache[selIndex] || {}).slot + "\u2026");
      fetch("/api/slots/" + selIndex, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            status("slot " + res.slot + " \u2192 " + slug, "ok");
            refresh();
            if (window.__refreshPatterns) window.__refreshPatterns();
          } else {
            status((res && res.error) || "assign failed", "err");
          }
        })
        .catch(function () { status("assign failed", "err"); });
    }

    function clear() {
      status("clearing slot " + (cache[selIndex] || {}).slot + "\u2026");
      fetch("/api/slots/" + selIndex, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pattern: null })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) { status("slot " + res.slot + " emptied", "ok"); refresh(); if (window.__refreshPatterns) window.__refreshPatterns(); }
          else status((res && res.error) || "clear failed", "err");
        })
        .catch(function () { status("clear failed", "err"); });
    }

    if (assignBtn) assignBtn.addEventListener("click", assign);
    if (clearBtn) clearBtn.addEventListener("click", clear);
    window.__refreshSlots = refresh; // patterns card refreshes slots after delete
    refresh();
    setInterval(refresh, 15000);
  })();

  // Arrangement tracker: a text string of slot characters ("AABCCDAA",
  // base64 addresses A-Z a-z 0-9 +/) is concatenated on the bar grid and
  // played through the shared replayer (so the replay stop button stops it
  // too). Saved strings live in arrangements/ next to patterns/.
  (function () {
    var textEl = document.getElementById("arrange-text");
    if (!textEl) return;
    var playBtn = document.getElementById("arrange-play");
    var stopBtn = document.getElementById("arrange-stop");
    var loopEl = document.getElementById("arrange-loop");
    var tempoEl = document.getElementById("arrange-tempo");
    var nameEl = document.getElementById("arrange-name");
    var saveBtn = document.getElementById("arrange-save");
    var selEl = document.getElementById("arrange-select");
    var loadBtn = document.getElementById("arrange-load");
    var delBtn = document.getElementById("arrange-del");
    var statusEl = document.getElementById("arrange-status");
    var previewEl = document.getElementById("arrange-preview");
    var LS_KEY = "midi.arrange.draft";
    var slotByChar = {};   // slot char -> slot dict (for the live preview)
    var noteBySlug = {};   // pattern slug -> note count

    function status(msg, cls) {
      if (statusEl) {
        statusEl.textContent = msg || "";
        statusEl.className = "patterns-status" + (cls ? " " + cls : "");
      }
    }

    // Working string survives a refresh / pattern load (loading a pattern used
    // to reload the page, which silently discarded whatever you'd typed).
    function saveDraft() {
      try {
        localStorage.setItem(LS_KEY, JSON.stringify({
          text: textEl.value,
          name: nameEl ? nameEl.value : "",
          tempo: tempoEl ? tempoEl.value : "",
          loop: !!(loopEl && loopEl.checked)
        }));
      } catch (e) { /* storage disabled */ }
    }
    function loadDraft() {
      try {
        var d = JSON.parse(localStorage.getItem(LS_KEY) || "null");
        if (!d) return;
        if (typeof d.text === "string") textEl.value = d.text;
        if (nameEl && typeof d.name === "string") nameEl.value = d.name;
        if (tempoEl && typeof d.tempo === "string") tempoEl.value = d.tempo;
        if (loopEl && d.loop) loopEl.checked = true;
      } catch (e) { /* ignore */ }
    }

    // Live preview: bars + notes the string will produce, before you play it.
    // Computed client-side from the slot grid (bars) and the pattern list
    // (note counts), flagging empty slots and unknown characters.
    function previewData() {
      fetch("/api/slots", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          slotByChar = {};
          (res.slots || []).forEach(function (s) { slotByChar[s.slot] = s; });
          renderPreview();
        }).catch(function () {});
      fetch("/api/patterns", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          noteBySlug = {};
          (res.patterns || []).forEach(function (p) {
            noteBySlug[p.filename] = p.note_count || 0;
          });
          renderPreview();
        }).catch(function () {});
    }
    function renderPreview() {
      if (!previewEl) return;
      var chars = (textEl.value || "").replace(/[\s|]/g, "").split("");
      if (!chars.length) { previewEl.textContent = ""; previewEl.className = "arrange-preview"; return; }
      var bars = 0, notes = 0, empty = [], unknown = [];
      chars.forEach(function (c) {
        var s = slotByChar[c];
        if (!s) { if (unknown.indexOf(c) < 0) unknown.push(c); return; }
        if (!s.pattern) { if (empty.indexOf(c) < 0) empty.push(c); return; }
        bars += (typeof s.bars === "number" ? s.bars : 1);
        notes += noteBySlug[s.pattern] || 0;
      });
      var msg = [chars.length + (chars.length === 1 ? " slot" : " slots"),
                 bars + (bars === 1 ? " bar" : " bars"),
                 notes + (notes === 1 ? " note" : " notes")].join(" \u00b7 ");
      var cls = "arrange-preview";
      if (unknown.length) { msg += "   unknown: " + unknown.join(" "); cls += " bad"; }
      if (empty.length) { msg += "   empty slots: " + empty.join(" "); cls += " warn"; }
      previewEl.textContent = msg;
      previewEl.className = cls;
    }

    // Clicking a filled slot cell calls this to build the string.
    window.__appendSlotChar = function (ch) {
      textEl.value = (textEl.value || "") + ch;
      saveDraft();
      renderPreview();
      textEl.focus();
    };

    function renderList(items) {
      if (!selEl) return;
      selEl.innerHTML = "";
      (items || []).forEach(function (a) {
        var opt = document.createElement("option");
        opt.value = a.filename;
        opt.textContent = a.name;
        opt.title = a.text || "";
        selEl.appendChild(opt);
      });
      var has = selEl.options.length !== 0;
      if (loadBtn) loadBtn.disabled = !has;
      if (delBtn) delBtn.disabled = !has;
      if (!has) status("no arrangements saved yet");
    }

    function refresh() {
      fetch("/api/arrangements", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) renderList(res.arrangements);
        })
        .catch(function () { /* transient */ });
    }

    function play() {
      var text = (textEl.value || "").trim();
      if (!text) { status("type an arrangement first", "err"); return; }
      if (playBtn) playBtn.disabled = true;
      status("playing\u2026");
      var body = { text: text, loop: !!(loopEl && loopEl.checked) };
      var tv = tempoEl ? (tempoEl.value || "").trim() : "";
      if (tv) body.tempo = tv;
      fetch("/api/arrange/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (playBtn) playBtn.disabled = false;
          if (res && res.ok) {
            var seq = (res.slots || []).map(function (s) { return s.slot; }).join(" ");
            status("playing " + seq + " \u2014 " + res.bars + " bars, " +
                   res.notes + " notes (~" + Math.round(res.duration * 1000) +
                   " ms)" + (res.loop ? " [loop]" : ""), "ok");
          } else {
            status((res && res.error) || "play failed", "err");
          }
        })
        .catch(function () {
          if (playBtn) playBtn.disabled = false;
          status("play failed", "err");
        });
    }

    function stop() {
      fetch("/api/replay/stop", { method: "POST" })
        .then(function () { status("stopped"); })
        .catch(function () { status("stop failed", "err"); });
    }

    function save() {
      var text = (textEl.value || "").trim();
      if (!text) { status("nothing to save", "err"); return; }
      status("saving\u2026");
      fetch("/api/arrangements", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: (nameEl.value || "").trim(), text: text })
      }).then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            status("saved \u201C" + res.arrangement.name + "\u201D", "ok");
            if (nameEl) nameEl.value = "";
            refresh();
          } else {
            status((res && res.error) || "save failed", "err");
          }
        })
        .catch(function () { status("save failed", "err"); });
    }

    function load() {
      var slug = selEl.value;
      if (!slug || (loadBtn && loadBtn.disabled)) return;
      fetch("/api/arrangements/" + encodeURIComponent(slug))
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) {
            textEl.value = res.text || "";
            saveDraft();
            renderPreview();
            status("loaded \u201C" + res.name + "\u201D", "ok");
          } else {
            status((res && res.error) || "load failed", "err");
          }
        })
        .catch(function () { status("load failed", "err"); });
    }

    function del() {
      var slug = selEl.value;
      if (!slug || (delBtn && delBtn.disabled)) return;
      fetch("/api/arrangements/" + encodeURIComponent(slug), { method: "DELETE" })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res && res.ok) { status("deleted", "ok"); refresh(); }
          else status((res && res.error) || "delete failed", "err");
        })
        .catch(function () { status("delete failed", "err"); });
    }

    if (playBtn) playBtn.addEventListener("click", play);
    if (stopBtn) stopBtn.addEventListener("click", stop);
    if (saveBtn) saveBtn.addEventListener("click", save);
    if (loadBtn) loadBtn.addEventListener("click", load);
    if (delBtn) delBtn.addEventListener("click", del);
    textEl.addEventListener("input", function () { saveDraft(); renderPreview(); });
    if (nameEl) nameEl.addEventListener("input", saveDraft);
    if (tempoEl) tempoEl.addEventListener("input", saveDraft);
    if (loopEl) loopEl.addEventListener("change", saveDraft);
    loadDraft();
    renderPreview();
    previewData();
    setInterval(previewData, 15000); // keep bars/notes honest if slots change
    refresh();
  })();
})();
