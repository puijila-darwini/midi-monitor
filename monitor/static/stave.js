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
  // Accidentals are added separately via addAccidentals
  function midiToKey(midi) {
    var pc = midi % 12;
    var oct = Math.floor(midi / 12) - 1;
    // Base natural note names
    var NATURAL = ["c", "c", "d", "d", "e", "f", "f", "g", "g", "a", "a", "b"];
    var name = NATURAL[pc];
    return name + "/" + oct;
  }

  var MAX_EVENTS = 200;
  var STAVE_W = 720;
  var STAVE_H = 90;
  var X_START = 30;
  var Y_START = 40;

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
    renderer.resize(800, 600);
    context = renderer.getContext();
  }

  function clear() {
    events = [];
    if (div) div.innerHTML = "";
    renderer = null;
    context = null;
    redraw();
  }

  function initMiniRenderer() {
    if (miniRenderer) return;
    if (!miniDiv) return;
    miniRenderer = new VF.Renderer(miniDiv, VF.Renderer.Backends.SVG);
    miniRenderer.resize(400, 150);
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
    if (ev.kind === "chord" || ev.kind === "arpeggio" || ev.kind === "interval") {
      var keys = ev.notes.map(midiToKey);
      var sn = new VF.StaveNote({ keys: keys, duration: dur });
      addAccidentals(sn, ev.notes);
      return [sn];
    } else {
      return ev.notes.map(function(midi) {
        var key = midiToKey(midi);
        var sn = new VF.StaveNote({ keys: [key], duration: dur });
        addAccidentals(sn, [midi]);
        return sn;
      });
    }
  }

  // Add Accidental modifiers for notes outside the key signature
function addAccidentals(staveNote, midiNotes) {
    var keySig = KEY_SIGS[spellingKey] ?? 0;
    if (spellingKey === "auto") keySig = 0;
    for (var i = 0; i < midiNotes.length; i++) {
      var pc = midiNotes[i] % 12;
      if (requiresAccidental(pc, keySig)) {
        var acc = new VF.Accidental(useFlatForPC(pc, keySig) ? 'b' : '#');
        staveNote.addModifier(acc, i);
      }
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
  // getting over-full / too many bars on one row.
  var NOTES_PER_LINE = 16;

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
        bar = Math.floor(i / NOTES_PER_LINE);
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
    var staveLines = [];
    var line = [];
    var count = 0;
    for (var m = 0; m < measures.length; m++) {
      if (line.length && count + measures[m].notes.length > NOTES_PER_LINE) {
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
    if (!events.length) { div.innerHTML = ""; return; }
    initRenderer();

    context.clear();

    // Filter events based on showIntervals setting
    var displayEvents = showIntervals ? events : events.filter(function(e) { return e.kind !== "interval"; });
    if (!displayEvents.length) { div.innerHTML = ""; return; }

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

      var stave = new VF.Stave(X_START, y, STAVE_W);
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

      // Highlight the most recent line's notes (older notes stay dark).
      // Noteheads render flat in the SVG in this VexFlow build, so colour the
      // trailing `noteCount` notehead groups (the last line was drawn last).
      var lastNoteCount = 0;
      for (var n2 = 0; n2 < line.length; n2++) lastNoteCount += line[n2].notes.length;
      if (line.some(function (m) { return m.eventIds.indexOf(lastId) >= 0; })) {
        highlightLastNoteheads(lastNoteCount);
      }

      y += STAVE_H;
      totalHeight = y;
    }

    if (renderer) renderer.resize(800, totalHeight + 40);

    // Auto-scroll stave-wrap to bottom
    var staveWrap = document.getElementById('stave-wrap');
    if (staveWrap) {
      staveWrap.scrollTop = staveWrap.scrollHeight;
    }
  }

  // Colour the trailing `count` notehead groups (the most recent line's notes).
  function highlightLastNoteheads(count) {
    var svg = div.querySelector('svg');
    if (!svg || count <= 0) return;
    var heads = svg.querySelectorAll('g.vf-notehead');
    if (!heads.length) return;
    var start = Math.max(0, heads.length - count);
    for (var i = start; i < heads.length; i++) {
      heads[i].setAttribute('fill', '#4c9aff');
      heads[i].setAttribute('stroke', '#4c9aff');
    }
  }

  function redrawMini() {
    if (!miniDiv) return;
    if (!lastChordEvent) { miniDiv.innerHTML = ""; return; }
    initMiniRenderer();
    miniContext.clear();

    var keys = lastChordEvent.notes.map(midiToKey);
    var dur = "h"; // half note for mini stave
    var sn = new VF.StaveNote({ keys: keys, duration: dur });
    addAccidentals(sn, lastChordEvent.notes);

    var stave = new VF.Stave(10, 20, 360);
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

    // Add label below the mini stave
    var labelEl = document.getElementById("mini-stave-label");
    if (labelEl && lastChordEvent.label) {
      labelEl.textContent = lastChordEvent.label;
    } else if (labelEl) {
      labelEl.textContent = "";
    }

    if (miniRenderer) miniRenderer.resize(400, 100);
  }

  function push(kind, notes, time, label, duration) {
    if (!notes || !notes.length) return;
    var sortedNotes = notes.slice().sort(function (a, b) { return a - b; });

    // If this is a chord/arpeggio, suppress recent individual notes
    if (kind === "chord" || kind === "arpeggio") {
      events = events.filter(function(ev) {
        if (ev.kind !== "note") return true;
        var evNotes = ev.notes.slice().sort(function (a, b) { return a - b; });
        var isSubset = evNotes.every(function(n) { return sortedNotes.indexOf(n) >= 0; });
        return !isSubset;
      });

      // Update mini stave for chord/arpeggio/interval
      lastChordEvent = { kind: kind, notes: sortedNotes, time: time, label: label };
      redrawMini();
    } else {
      // For single notes, don't update mini stave unless it's empty
      if (!lastChordEvent) {
        lastChordEvent = { kind: kind, notes: sortedNotes, time: time };
        redrawMini();
      }
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
    clear: clear,
    redraw: redraw,
    setSpellingKey: setSpellingKey,
    setShowIntervals: setShowIntervals,
    setKey: setKey,
    setTimeSignature: setTimeSignature,
    backspace: backspace,
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