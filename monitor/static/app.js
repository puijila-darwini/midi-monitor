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

  function resetCatch() {
    tonicListenActive = false;
    catchBuffer = [];
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
  // buffered (last note wins if they don't form a triad).
  function resolveCatchBuffer() {
    if (catchTimer) { clearTimeout(catchTimer); catchTimer = null; }
    if (!tonicListenActive) return;
    var triad = catchBuffer.length ? triadFromPcs(catchBuffer) : null;
    var root = triad ? triad.root : (catchBuffer.length ? catchBuffer[catchBuffer.length - 1] : null);
    if (root === null) { resetCatch(); return; }
    var scaleId = triad ? (triad.quality === "major" ? "major" : "aeolian") : null;
    resolveCatch(root, scaleId);
    catchBuffer = [];
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
          ev.notes.forEach(function (n) {
            var p = n % 12;
            if (pcsArr.indexOf(p) < 0) pcsArr.push(p);
          });
          var tri = triadFromPcs(pcsArr);
          if (tri) {
            if (catchTimer) { clearTimeout(catchTimer); catchTimer = null; }
            catchBuffer = [];
            catchLastAt = ev.time;
            var scId = tri.quality === "major" ? "major" : "aeolian";
            resolveCatch(tri.root, scId);
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

  function setInstrument(program, name) {
    var el = document.getElementById("instrument");
    if (el) el.textContent = "instrument: " + name + " (prog " + program + ")";
  }

  // Render the tempo control from backend state.
  // effective = the BPM quantization actually uses (user-fixed or detected);
  // detected  = the live estimate, shown as a guide when a user tempo is set;
  // user      = the user-fixed value (0 = auto).
  function renderTempo(effective, detected, user) {
    var el = document.getElementById("tempo");
    if (!el) return;
    var input = document.getElementById("tempo-input");
    var tag = document.getElementById("tempo-tag");
    var det = document.getElementById("tempo-detected");

    if (input) {
      // Don't clobber what the user is typing.
      if (document.activeElement !== input) {
        input.value = user > 0 ? String(Math.round(user)) : "";
      }
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

  (function () {
    var btn = document.getElementById("stave-clear");
    if (!btn) return;
    btn.addEventListener("click", function () {
      if (window.StavePanel) StavePanel.clear();
    });
  })();

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

  (function () {
    var btn = document.getElementById("feed-clear");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var feedList = document.getElementById("feed-list");
      if (feedList) feedList.innerHTML = "";
    });
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

  // initial state
  fetch("/api/state")
    .then(function (r) { return r.json(); })
    .then(function (s) {
      setStatus(s.online);
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
    
    var newEs = new EventSource("/events");
    
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

  buildPiano();
})();
