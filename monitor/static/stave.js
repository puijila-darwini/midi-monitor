// Notation stave renderer using VexFlow 5.
// Renders a single continuous treble stave where notes flow left-to-right,
// wrapping to new stave lines like real sheet music.
// Also provides a mini stave for the last chord/interval/arpeggio.
(function () {
  "use strict";

  var VF = window.VexFlow;
  if (!VF) return;

  // Key signatures: number of sharps (+) or flats (-)
  var KEY_SIGS = {
    "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
    "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7
  };

  // Sharp names for pitch classes
  var SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  // Flat names for pitch classes
  var FLAT  = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

  // Current spelling key setting
  var spellingKey = "auto";

  // Key signature to render on the clef, derived from the manually chosen
  // intended key. Value is a VexFlow major-key name (e.g. "C", "G", "F#",
  // "Bb") or null (no signature shown).
  var currentKeySig = null;

  // Tonic name -> pitch class (0-11). Handles sharps and flats spellings.
  var NAME_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4,
    "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
    "A#": 10, "Bb": 10, "B": 11
  };
  // Conventional major-key spelling for each pitch class (for key signature)
  var PC_MAJOR = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
  // Mode -> semitone offset from the modal tonic to its parent MAJOR key's
  // tonic (the major key with the same set of accidentals).
  var MODE_OFFSET = {
    "ionian": 0, "dorian": -2, "phrygian": -4, "lydian": -5,
    "mixolydian": -7, "aeolian": -9, "minor": -9, "locrian": -11
  };

  // Convert a key selector value into the VexFlow major-key signature name to
  // render, or null for no signature. Accepts:
  //   - "auto" / "none"                       -> null
  //   - a bare major key ("G", "Bb")          -> that key
  //   - a bare minor key ("Am", "Em")         -> its relative major
  //   - a modal label ("C ionian", "D dorian")-> parent major of the mode
  function toKeySig(input) {
    if (!input) return null;
    var s = input.trim();
    if (/^(auto|none|none\/auto)$/i.test(s)) return null;

    // Bare minor key "Xm" -> relative major (minor tonic + 3 semitones).
    // Only whole-token matches ("Am", "Bbm", "C#m") — major names don't end in m.
    var minorMatch = s.match(/^(.+?)m$/i);
    if (minorMatch) {
      var mb = NAME_PC[minorMatch[1]];
      if (mb !== undefined) return PC_MAJOR[(mb + 3) % 12];
    }

    var parts = s.split(/\s+/);
    var tonicName = parts[0];
    var mode = parts.slice(1).join(" ").toLowerCase();
    var tonicPc = NAME_PC[tonicName];
    if (tonicPc === undefined) return null;
    var offset = MODE_OFFSET[mode];
    // Default to ionian (major) for unknown modes / bare major labels like "C"
    if (offset === undefined) offset = 0;
    var parentPc = ((tonicPc + offset) % 12 + 12) % 12;
    return PC_MAJOR[parentPc];
  }

  // Whether to show intervals on main stave
  var showIntervals = false;

  var naturalPCs = {0: true, 2: true, 4: true, 5: true, 7: true, 9: true, 11: true};

  // Determine if a pitch class should be spelled as flat based on key signature
  function useFlatForPC(pc, keySig) {
    if (keySig === 0) return false; // C major - no accidentals in key sig
    if (keySig > 0) return false;   // Sharp keys - prefer sharps
    // Flat keys - prefer flats for all non-natural notes (accidentals should be flats)
    return !naturalPCs[pc];
  }

  // Convert MIDI to VexFlow key string (natural note + octave)
  // Notehead positions only carry the natural staff slot; the
  // accidental glyph itself is overlaid by placeAccidentals, which
  // follows the spelling key (sharp vs flat choice).
  function midiToKey(midi) {
    var pc = midi % 12;
    var oct = Math.floor(midi / 12) - 1;
    // Base natural note names
    var NATURAL = ["c", "c", "d", "d", "e", "f", "f", "g", "g", "a", "a", "b"];
    var name = NATURAL[pc];
    return name + "/" + oct;
  }

  var MAX_EVENTS = 200;
  var STAVE_H = 90;
  var X_START = 30;
  var Y_START = 40;

  // The notation extends to the same width as the on-screen keyboard above it:
// canvasWidth() sizes the renderer from the #piano keybed (falling back to the
// stave container, then 800). staveWidth() is the drawn line length minus the
// leading clef/keysig offset + right pad.
  function canvasWidth() {
    var piano = document.getElementById("piano");
    if (piano && piano.getBoundingClientRect().width > 200) {
      return Math.round(piano.getBoundingClientRect().width) + X_START + 20;
    }
    if (div && div.clientWidth > 200) return div.clientWidth;
    return 800;
  }
  function staveWidth() {
    return canvasWidth() - X_START - 20;
  }
  // Notes per stave line, scaled so a wider stave holds more notes instead of
  // wrapping early with big gaps. ~45px per notehead.
  function notesPerLine() {
    return Math.max(16, Math.round(staveWidth() / 45));
  }

  var div = document.getElementById("stave");
  var events = [];

  var renderer = null;
  var context = null;

  // Mini stave state
  var miniDiv = document.getElementById("mini-stave");
  var miniRenderer = null;
  var miniContext = null;
  var lastChordEvent = null; // last chord/arpeggio/interval for mini stave

  function initRenderer() {
    if (renderer) return;
    renderer = new VF.Renderer(div, VF.Renderer.Backends.SVG);
    renderer.resize(canvasWidth(), 600);
    context = renderer.getContext();
  }

  function clear() {
    events = [];
    tintedStaveEvent = null;
    stavePlayCursor = 0;
    if (div) div.innerHTML = "";
    renderer = null;
    context = null;
    redraw();
  }

  function initMiniRenderer() {
    if (miniRenderer) return;
    if (!miniDiv) return;
    miniRenderer = new VF.Renderer(miniDiv, VF.Renderer.Backends.SVG);
    miniRenderer.resize(190, 150);
    miniContext = miniRenderer.getContext();
  }

  function clearMini() {
    lastChordEvent = null;
    if (miniDiv) miniDiv.innerHTML = "";
    miniRenderer = null;
    miniContext = null;
  }

  // Set spelling key
  function setSpellingKey(key) {
    spellingKey = key;
    redraw();
  }

  // Set intervals visibility
  function setShowIntervals(val) {
    showIntervals = val;
    redraw();
  }

  // Build StaveNote objects from an event
  function buildStaveNotes(ev) {
    var dur = "q";
    // Use quantized duration if available
    if (ev.duration !== undefined) {
      // Convert duration to VexFlow duration
      dur = durationToVexFlow(ev.duration);
    }
    var sn;
    if (ev.kind === "rest") {
      // A rest: VexFlow rest duration = the note duration string plus "r"
      // (e.g. "q" -> "qr", "8d" -> "8dr"; full/whole = "wr"). Keys are a
      // dummy slot; VexFlow renders the rest glyph on the staff directly.
      return [new VF.StaveNote({ keys: ["b/4"], duration: dur + "r" })];
    }
    if (ev.kind === "chord" || ev.kind === "arpeggio" || ev.kind === "interval") {
      var keys = ev.notes.map(midiToKey);
      sn = new VF.StaveNote({ keys: keys, duration: dur });
    } else if (ev.notes.length > 1) {
      // Shouldn't happen (simultaneous notes group upstream) — legacy
      // fallback draws each head untagged rather than dropping notes.
      return ev.notes.map(function(midi) {
        var mkey = midiToKey(midi);
        var msn = new VF.StaveNote({ keys: [mkey], duration: dur });
        return msn;
      });
    } else {
      // Single-note events carry exactly one pitch (grouped upstream).
      var one = ev.notes.length ? ev.notes[0] : 60;
      var key = midiToKey(one);
      sn = new VF.StaveNote({ keys: [key], duration: dur });
    }
    // Tag the rendered group with the event id so playback can tint exactly
    // the noteheads that are sounding. NOTE: this VexFlow build does not
    // propagate attrs.id onto the SVG group (verified: no stavev- ids land),
    // so the tint instead uses the eventHeadMap built by placeAccidentals.
    // The assignment below is kept as a hint for builds that do propagate.
    try { sn.attrs.id = "stavev-" + ev.id; } catch (e) { /* older builds */ }
    return [sn];
  }

  // Accidental glyph choice for a pitch class under the current spelling key.
  // Returns "#" / "b" / null. Glyphs are drawn as a Bravura overlay (see
  // placeAccidentals): this VexFlow build silently drops addModifier
  // accidentals, so spelling lives here and position in midiToKey.
  var ACC_SHARP = "\uE262";
  var ACC_FLAT = "\uE260";
  function accidentalFor(pc) {
    var keySig = KEY_SIGS[spellingKey] ?? 0;
    if (spellingKey === "auto") keySig = 0;
    if (!requiresAccidental(pc, keySig)) return null;
    return useFlatForPC(pc, keySig) ? ACC_FLAT : ACC_SHARP;
  }

  // Overlay accidental glyphs onto a rendered SVG. VexFlow groups noteheads
  // as g.vf-notehead in tickable order, which matches our event order with
  // notes ascending — so walk display events and DOM heads in lockstep:
  // each non-rest event consumes ev.notes.length heads. While walking, also
  // record the event->heads map that playback tinting uses (no reliance on
  // VexFlow id propagation). Texts are tagged with the event id so the tint
  // can recolour glyphs together with their heads.
  var eventHeadMap = {};  // event id -> [g.vf-notehead...] of the last render
  function placeAccidentals(svg, displayEvents, recordMap) {
    if (!svg) return;
    if (recordMap) eventHeadMap = {};
    var heads = svg.querySelectorAll("g.vf-notehead");
    var hi = 0;
    for (var i = 0; i < displayEvents.length; i++) {
      var ev = displayEvents[i];
      if (ev.kind === "rest" || !ev.notes) continue;
      var evHeads = [];
      for (var j = 0; j < ev.notes.length; j++) {
        if (hi >= heads.length) return;
        var head = heads[hi++];
        evHeads.push(head);
        var glyph = accidentalFor(ev.notes[j] % 12);
        if (!glyph) continue;
        try {
          var bb = head.getBBox();
          var t = document.createElementNS("http://www.w3.org/2000/svg", "text");
          t.setAttribute("x", bb.x - 3);
          t.setAttribute("y", bb.y + bb.height / 2);
          t.setAttribute("text-anchor", "end");
          t.setAttribute("dominant-baseline", "central");
          t.setAttribute("font-family", "Bravura");
          t.setAttribute("font-size", "28");
          t.setAttribute("data-ev", String(ev.id));
          t.textContent = glyph;
          svg.appendChild(t);
        } catch (e) { /* decorative: never break notation */ }
      }
      if (recordMap) eventHeadMap[ev.id] = evHeads;
    }
  }
    function requiresAccidental(pc, keySig) {
    if (keySig === 0) {
      // C major - all sharps/flats need accidentals
      var sharpPCs = {1: true, 3: true, 6: true, 8: true, 10: true};
      return sharpPCs[pc];
    } else if (keySig > 0) {
      // Sharp keys - accidentals for flats not in key, or sharps beyond key
      var keySharps = keySig;
      // The sharps in this key: F#, C#, G#, D#, A#, E#, B#
      var sharpOrder = [6, 1, 8, 3, 10, 5, 0];
      var keySharpPCs = {};
      for (var i = 0; i < keySharps; i++) keySharpPCs[sharpOrder[i]] = true;
      // Need accidental if: it's a flat (1,3,6,8,10 not in keySharps) or sharp beyond key
      var flatPCs = {1: true, 3: true, 6: true, 8: true, 10: true};
      if (flatPCs[pc]) return !keySharpPCs[pc]; // flat not in key = accidental
      // sharp beyond key signature
      return !keySharpPCs[pc];
    } else {
      // Flat keys
      var keyFlats = -keySig;
      // Flats in this key: Bb, Eb, Ab, Db, Gb, Cb, Fb
      var flatOrder = [10, 3, 8, 1, 6, 11, 4];
      var keyFlatPCs = {};
      for (var i = 0; i < keyFlats; i++) keyFlatPCs[flatOrder[i]] = true;
      var sharpPCs = {1: true, 3: true, 6: true, 8: true, 10: true};
      if (sharpPCs[pc]) return !keyFlatPCs[pc]; // sharp not in key = accidental
      // flat beyond key signature
      return !keyFlatPCs[pc];
    }
  }

  function pcToNumber(name) {
    var map = {c:0, "c#":1, d:2, "d#":3, e:4, f:5, "f#":6, g:7, "g#":8, a:9, "a#":10, b:11};
    return map[name.toLowerCase()] ?? 0;
  }

  // Convert duration in seconds to VexFlow duration string.
  // NOTE: VexFlow uses "8" (not "e") for eighth notes and a trailing "d" suffix
  // for dotted notes (e.g. "qd", "8d"), NOT a trailing dot.
  function durationToVexFlow(seconds) {
    if (!window.tempoBpm || window.tempoBpm <= 0) return "q";

    // Calculate beat duration (quarter note) in seconds
    var beatDuration = 60.0 / window.tempoBpm;

    // Find closest standard duration
    var ratio = seconds / beatDuration;

    // Standard VexFlow durations (value in quarter-note beats)
    var durations = [
      { name: "w", value: 4.0 },      // whole
      { name: "h", value: 2.0 },      // half
      { name: "q", value: 1.0 },      // quarter
      { name: "qd", value: 1.5 },     // dotted quarter
      { name: "8", value: 0.5 },      // eighth
      { name: "8d", value: 0.75 },    // dotted eighth
      { name: "16", value: 0.25 },    // sixteenth
      { name: "16d", value: 0.375 },  // dotted sixteenth
      { name: "32", value: 0.125 },   // thirty-second
    ];

    // Find closest duration
    var best = durations[2]; // default to quarter
    var bestDiff = Math.abs(ratio - best.value);
    for (var i = 0; i < durations.length; i++) {
      var diff = Math.abs(ratio - durations[i].value);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = durations[i];
      }
    }

    return best.name;
  }

  // Export to window for use by buildStaveNotes
  window.durationToVexFlow = durationToVexFlow;

  // Durations that can be beamed together (8th or faster). Dotted variants use
  // the same stem direction so they beam fine with plain ones.
  var BEAMABLE = { "8": true, "8d": true, "16": true, "16d": true, "32": true, "32d": true };

  // Is a StaveNote a chord (multiple keys)? Chords shouldn't be beamed.
  function isChordNote(sn) {
    return sn && sn.keys && sn.keys.length > 1;
  }

  // For a line's array of StaveNotes (single-voice, in order), return an array
  // of VexFlow Beam objects grouping consecutive beamable single notes that are
  // no farther apart than a half note gap (i.e. at least 2 notes of ~1/8 or
  // faster). Beams never cross a whole-note worth of space, keeping each beam
  // tidy and within a beat-ish span.
  function buildBeams(notes) {
    var beams = [];
    var start = -1;
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      var beamable = n && !isChordNote(n) && BEAMABLE[n.getDuration && n.getDuration()];
      // getDuration may not exist on all builds; fall back to duration property
      if (!beamable && n) {
        var d = n.duration;
        beamable = !isChordNote(n) && BEAMABLE[d];
      }
      if (beamable) {
        if (start === -1) start = i;
      } else {
        if (start !== -1 && i - start > 1) {
          beams.push(new VF.Beam(notes.slice(start, i)));
        }
        start = -1;
      }
    }
    if (start !== -1 && notes.length - start > 1) {
      beams.push(new VF.Beam(notes.slice(start, notes.length)));
    }
    return beams;
  }

  // Current time signature ("4/4", "3/4", ...). Kept in sync with the header
  // selector; used for measure width (bar duration in seconds) and the bar
  // count per measure.
  var tsNumer = 4;
  var tsDenom = 4;

  // Notes (noteheads) per stave line before wrapping. With measure barlines
  // the actual wrap is on whole-bar boundaries, but this keeps a line from
  // getting over-full / too many bars on one row. The cap is scaled to the
  // line width in notesPerLine(), so wider staves hold more notes.

  // Called from app.js when the user changes the time signature selector.
  function setTimeSignature(numer, denom) {
    tsNumer = numer || 4;
    tsDenom = denom || 4;
    redraw();
  }

  // Compute each display event's bar index from its onset time relative to the
  // first buffered event (bar duration = (60/tempo)*numer seconds). With no
  // tempo yet, fall back to count-based pseudo-measures.
  function assignBars(displayEvents) {
    var t0 = displayEvents.length ? (displayEvents[0].time || 0) : 0;
    var bpm = window.tempoBpm > 0 ? window.tempoBpm : 0;
    var barSeconds = 0;
    if (bpm > 0) barSeconds = (60.0 / bpm) * tsNumer;
    return displayEvents.map(function (ev, i) {
      var bar = 0;
      if (barSeconds > 0) {
        var t = (typeof ev.time === "number") ? ev.time : t0;
        bar = Math.floor((t - t0) / barSeconds);
        if (bar < 0) bar = 0;
      } else {
        bar = Math.floor(i / notesPerLine());
      }
      return bar;
    });
  }

  // Group displayEvents into stave lines. Each line is a list of measures;
  // each measure is { notes:[StaveNote...], eventIds:[...] }. Lines break on
  // whole-bar boundaries once a line's note count would exceed NOTES_PER_LINE.
  function packLines(displayEvents) {
    var bars = assignBars(displayEvents);

    // Assemble contiguous same-bar runs into measures.
    var measures = [];
    var curNotes = [];
    var curIds = [];
    var curBar = null;
    for (var i = 0; i < displayEvents.length; i++) {
      if (curBar !== null && bars[i] !== curBar) {
        if (curNotes.length) measures.push({ notes: curNotes, eventIds: curIds, bar: curBar });
        curNotes = [];
        curIds = [];
      }
      curNotes = curNotes.concat(buildStaveNotes(displayEvents[i]));
      curIds.push(displayEvents[i].id);
      curBar = bars[i];
    }
    if (curNotes.length) measures.push({ notes: curNotes, eventIds: curIds, bar: curBar });

    // Pack whole measures into lines (never split a bar across a line wrap).
    var maxPerLine = notesPerLine();
    var staveLines = [];
    var line = [];
    var count = 0;
    for (var m = 0; m < measures.length; m++) {
      if (line.length && count + measures[m].notes.length > maxPerLine) {
        staveLines.push(line);
        line = [];
        count = 0;
      }
      line.push(measures[m]);
      count += measures[m].notes.length;
    }
    if (line.length) staveLines.push(line);
    return staveLines;
  }

  function redraw() {
    if (!div) return;
    if (!events.length) { div.innerHTML = ""; renderer = null; context = null; return; }
    initRenderer();

    context.clear();
    // Drop any empty-state placeholder from an earlier empty render — fresh
    // notation draws into the same div.
    var stalePh = div.querySelector(".stave-empty");
    if (stalePh) stalePh.remove();

    // Filter events based on showIntervals setting
    var displayEvents = showIntervals ? events : events.filter(function(e) { return e.kind !== "interval"; });
    if (!displayEvents.length) {
      // Never go silently blank: if events exist but all are filtered out,
      // say so (otherwise a take of pure intervals looks like a dead stave).
      // Drop the cached renderer too: it points at the replaced SVG, and the
      // next redraw must bind a fresh one (same staleness rule as clear()).
      div.innerHTML = events.length
        ? '<div class="stave-empty">only interval events &mdash; toggle intervals on to show them</div>'
        : "";
      renderer = null;
      context = null;
      return;
    }

    var staveLines = packLines(displayEvents);
    var lastId = displayEvents[displayEvents.length - 1].id;
    var ts = tsNumer + "/" + tsDenom;

    var y = Y_START;
    var totalHeight = Y_START;

    for (var si = 0; si < staveLines.length; si++) {
      var line = staveLines[si];

      // One continuous voice per line: the line's notes with a VexFlow BarNote
      // (barlines) inserted between measures. VexFlow lays these out with real
      // bar lines at the measure boundaries (the idiomatic VexFlow approach).
      var tickables = [];
      var allNotes = [];
      var allBeams = [];
      var lastMeasureIdx = line.length - 1;

      for (var mi = 0; mi < line.length; mi++) {
        var measure = line[mi];
        // A BarNote draws a single barline BEFORE every measure after the first
        // on the line (the line's own leading barline is the stave's begin bar).
        if (mi > 0) tickables.push(new VF.BarNote(VF.Barline.SINGLE));
        tickables = tickables.concat(measure.notes);
        // Beams are computed per measure so they never cross a barline.
        allNotes = allNotes.concat(measure.notes);
        allBeams = allBeams.concat(buildBeams(measure.notes));
      }

      var stave = new VF.Stave(X_START, y, staveWidth());
      stave.addClef("treble");
      if (currentKeySig) stave.addKeySignature(currentKeySig);
      stave.addTimeSignature(ts);
      stave.setEndBarType(VF.Barline.END);
      stave.setContext(context);
      stave.draw();

      var voice = new VF.Voice({ num_beats: tsNumer, beat_value: tsDenom });
      voice.setStrict(false);
      voice.addTickables(tickables);

      var formatter = new VF.Formatter();
      formatter.joinVoices([voice]);
      formatter.format([voice], stave.getNoteEndX());
      voice.draw(context, stave);

      for (var bi = 0; bi < allBeams.length; bi++) {
        allBeams[bi].setContext(context).draw();
      }

      y += STAVE_H;
      totalHeight = y;
    }

    if (renderer) renderer.resize(canvasWidth(), totalHeight + 40);

    // Spelling overlay: accidental glyphs follow the current key.
    placeAccidentals(div.querySelector("svg"), displayEvents, true);

    // Auto-scroll stave-wrap to bottom
    var staveWrap = document.getElementById('stave-wrap');
    if (staveWrap) {
      staveWrap.scrollTop = staveWrap.scrollHeight;
    }
  }

  // Playback notehead tint: black noteheads go royal purple while their
  // event sounds during replay, then back to black. Driven per replay step
  // (see markStavePlaying): each "on" step batch is one onset group, so the
  // cursor walks the non-rest stave events in order — the same order the
  // transform chain serializes. Replaces the old always-on trailing-line
  // tint: purple now means "sounding right now".
  var PLAY_TINT = "#9B7ED8";
  var tintedStaveEvent = null;  // onset event currently tinted (or null)
  var stavePlayCursor = 0;      // onset-event cursor for step matching

  function staveNonRestEvents() {
    return events.filter(function (e) { return e.kind !== "rest"; });
  }

  function headsForEvent(ev) {
    // Skip rest events — they have no noteheads and nothing to tint.
    if (!ev || ev.kind === "rest" || !ev.notes || !ev.notes.length) return [];
    if (eventHeadMap[ev.id]) return eventHeadMap[ev.id];
    var g = document.getElementById("stavev-" + ev.id);
    if (!g) return [];
    return g.querySelectorAll(".vf-notehead");
  }

  function untintStaveEvent(ev) {
    if (!ev) return;
    var heads = headsForEvent(ev);
    for (var i = 0; i < heads.length; i++) {
      heads[i].removeAttribute("fill");
      heads[i].removeAttribute("stroke");
    }
    // Overlay accidental glyphs tint with their heads.
    var glyphs = document.querySelectorAll('text[data-ev="' + ev.id + '"]');
    for (var k = 0; k < glyphs.length; k++) {
      glyphs[k].removeAttribute("fill");
    }
  }

  function tintStaveEvent(ev) {
    var heads = headsForEvent(ev);
    if (!heads.length) return false;
    for (var i = 0; i < heads.length; i++) {
      heads[i].setAttribute("fill", PLAY_TINT);
      heads[i].setAttribute("stroke", PLAY_TINT);
    }
    var glyphs = document.querySelectorAll('text[data-ev="' + ev.id + '"]');
    for (var k = 0; k < glyphs.length; k++) {
      glyphs[k].setAttribute("fill", PLAY_TINT);
    }
    try { heads[0].scrollIntoView({ block: "nearest" }); } catch (e) { /* noop */ }
    return true;
  }

  function clearStavePlaying() {
    // End of replay (done/stopped/error): sounding notes back to black.
    untintStaveEvent(tintedStaveEvent);
    tintedStaveEvent = null;
  }

  function resetStavePlayback() {
    // Start of replay: rewind the onset cursor as well.
    untintStaveEvent(tintedStaveEvent);
    tintedStaveEvent = null;
    stavePlayCursor = 0;
  }

  function markStavePlaying(stepNotes) {
    if (!stepNotes || !stepNotes.length) return;
    var list = staveNonRestEvents();
    var safeList = list.filter(function (e) { return e.notes && e.notes.length; });
    var pick = null;
    for (var i = stavePlayCursor; i < safeList.length; i++) {
      var evn = list[i].notes || [];
      for (var j = 0; j < evn.length; j++) {
        if (stepNotes.indexOf(evn[j]) >= 0) {
          pick = list[i];
          stavePlayCursor = i + 1;
          break;
        }
      }
      if (pick) break;
    }
    // No unplayed onset overlaps this step (e.g. a bypass re-strike that
    // notation merged away): hold the last tint instead of going dark.
    if (!pick) pick = tintedStaveEvent;
    if (!pick || pick === tintedStaveEvent) return;
    untintStaveEvent(tintedStaveEvent);
    if (tintStaveEvent(pick)) tintedStaveEvent = pick;
    else tintedStaveEvent = null;
  }

  function redrawMini() {
    if (!miniDiv) return;
    if (!lastChordEvent) { miniDiv.innerHTML = ""; return; }
    initMiniRenderer();
    miniContext.clear();

    var keys = lastChordEvent.notes.map(midiToKey);
    var dur = "h"; // half note for mini stave
    var sn = new VF.StaveNote({ keys: keys, duration: dur });

    // One bar is all a single chord/interval ever needs — the mini card
    // stays compact beside the keyboard.
    var stave = new VF.Stave(10, 20, 130);
    stave.addClef("treble");
    stave.setContext(miniContext);
    stave.draw();

    var voice = new VF.Voice({ num_beats: 2, beat_value: 2 });
    voice.setStrict(false);
    voice.addTickables([sn]);

    var formatter = new VF.Formatter();
    formatter.joinVoices([voice]);
    formatter.format([voice], stave.getNoteEndX());
    voice.draw(miniContext, stave);

    if (miniRenderer) miniRenderer.resize(190, 130);
    // Spelling overlay for the mini chord too (never playback-tinted).
    placeAccidentals(miniDiv.querySelector("svg"),
                     [{ kind: "chord", notes: lastChordEvent.notes, id: "mini" }]);
  }

  // Update ONLY the mini "last chord / interval" stave. Independent of the
  // record/stop system: the mini stave always reflects the most recent
  // chord/arpeggio/interval, even mid-take or while not recording.
  function pushMini(kind, notes, time, label) {
    if (!notes || !notes.length) return;
    var sortedNotes = notes.slice().sort(function (a, b) { return a - b; });

    if (kind === "chord" || kind === "arpeggio" || kind === "interval") {
      lastChordEvent = { kind: kind, notes: sortedNotes, time: time, label: label };
      redrawMini();
    } else if (kind !== "rest") {
      // Single notes only fill an empty mini stave.
      if (!lastChordEvent) {
        lastChordEvent = { kind: kind, notes: sortedNotes, time: time };
        redrawMini();
      }
    }
  }

  function push(kind, notes, time, label, duration) {
    // Rests are empty note events; skip the "no notes" bail for them.
    if (kind !== "rest" && (!notes || !notes.length)) return;
    var sortedNotes = notes ? notes.slice().sort(function (a, b) { return a - b; }) : [];

    // If this is a chord/arpeggio, suppress recent individual notes
    if (kind === "chord" || kind === "arpeggio") {
      events = events.filter(function(ev) {
        if (ev.kind !== "note") return true;
        var evNotes = ev.notes.slice().sort(function (a, b) { return a - b; });
        var isSubset = evNotes.every(function(n) { return sortedNotes.indexOf(n) >= 0; });
        return !isSubset;
      });

      // Update mini stave for chord/arpeggio/interval
      pushMini(kind, sortedNotes, time, label);
    } else if (kind !== "rest") {
      // For single notes, don't update mini stave unless it's empty. Rests
      // never touch the mini stave (no noteheads to show).
      pushMini(kind, sortedNotes, time, undefined);
    }

    var ev = {
      kind: kind,
      notes: sortedNotes,
      time: time,
      id: Date.now() + Math.random()
    };
    if (duration !== undefined) ev.duration = duration;
    events.push(ev);
    if (events.length > MAX_EVENTS) events.shift();
    redraw();
  }

  // Fill out the remainder of the final measure with a trailing rest (used
  // when the user presses STOP: the take freezes, and the unfinished bar shows
  // its empty beats as a rest instead of ending abruptly on a downbeat edge).
  // Requires a tempo + time signature so bar boundaries are computable.
  function finishTake() {
    if (!window.tempoBpm || window.tempoBpm <= 0) return;
    if (!events.length) return;
    var barSeconds = (60.0 / window.tempoBpm) * tsNumer;
    if (barSeconds <= 0) return;
    var t0 = events[0].time || 0;
    var last = events[events.length - 1];
    var lastEnd = (typeof last.time === "number" ? last.time : t0) + (last.duration || 0);
    // Next barline after the final note's end.
    var barsElapsed = Math.floor((lastEnd - t0) / barSeconds);
    var nextBarStart = t0 + (barsElapsed + 1) * barSeconds;
    var gap = nextBarStart - lastEnd;
    // Don't add a tiny sliver of a rest (sub-16th at current tempo) or when the
    // take already ends exactly on the barline.
    var gridStep = (60.0 / window.tempoBpm) / 4;
    if (gap <= gridStep) return;
    // The rest occupies the empty beats of the final bar: start time = end of
    // the last event (assignBars computes the bar from time), duration = gap.
    var rid = Date.now() + Math.random() + 1;
    events.push({ kind: "rest", notes: [], time: lastEnd, duration: gap, id: rid });
    if (events.length > MAX_EVENTS) events.shift();
    redraw();
  }

  // Set the detected key (from a backend key-announce label like "C ionian")
  // so the clef shows the appropriate key signature.
  function setKey(label) {
    var ks = toKeySig(label);
    if (ks !== currentKeySig) {
      currentKeySig = ks;
      redraw();
    }
    // Align the spelling key so accidentals match the intended key; reset to
    // auto when no key is selected.
    if (ks) setSpellingKey(ks);
    else setSpellingKey("auto");
  }

  // Remove the last rendered event (Backspace editing).
  function backspace() {
    if (!events.length) return;
    // A chord/arp/interval flash may have suppressed constituent notes; just
    // drop the most recent event from the buffer and rebuild.
    events.pop();
    redraw();
  }

  window.StavePanel = {
    push: push,
    pushMini: pushMini,
    clear: clear,
    redraw: redraw,
    setSpellingKey: setSpellingKey,
    setShowIntervals: setShowIntervals,
    setKey: setKey,
    setTimeSignature: setTimeSignature,
    backspace: backspace,
    finishTake: finishTake,
    markPlaying: markStavePlaying,
    clearPlaying: clearStavePlaying,
    resetPlayback: resetStavePlayback,
  };

  // Editing: Backspace deletes the last note on the stave. Guard so it never
  // fires while the user is typing in an input/select/textarea.
  document.addEventListener("keydown", function (e) {
    if (e.key === "Backspace") {
      var tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      backspace();
    }
  });
})();