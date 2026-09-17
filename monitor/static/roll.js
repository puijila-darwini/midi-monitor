// Piano roll renderer (pure SVG, no dependencies).
//
// Consumes the SAME event list the notation card renders (/api/notation), so
// the roll always shows whatever the notation shows. Time is fit to the card
// width ("fill it up"); pitch auto-fits the notes present.
//
// Built with editing in mind: render() is a pure function of `model` (note
// blocks with stable indices) and every block is a hit-testable <rect>, so a
// future add/delete/drag is a model mutation + re-render.
(function () {
  "use strict";

  var mount = document.getElementById("roll");
  if (!mount) return;
  var metaEl = document.getElementById("roll-meta");

  var LOW = 21;              // A0
  var HIGH = 108;            // C8
  var BLACK = [1, 3, 6, 8, 10];
  var NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

  var GUTTER = 36;           // mini-piano gutter width (px)
  var RULER = 18;            // time ruler height (px)
  var PAD_BOTTOM = 8;
  var TARGET_H = 300;        // preferred plot height; row height derives from it
  var ROW_MIN = 7, ROW_MAX = 18;
  var MIN_SPAN = 12;         // semitones
  var MIN_SPAN_SEC = 1.0;    // minimum timeline so short takes don't stretch
  var RIGHT_PAD = 10;

  var model = [];            // [{note,on,off,velocity,idx}] in onset order
  var blockEls = [];         // <rect> per model entry (same order)
  var layout = null;         // {gutter,pps,ruler,h}
  var opts = {};
  var playCursor = 0;
  var tinted = [];
  var playheadEl = null;

  function pc(n) { return ((n % 12) + 12) % 12; }
  function isBlack(n) { return BLACK.indexOf(pc(n)) >= 0; }
  function noteName(n) { return NAMES[pc(n)] + (Math.floor(n / 12) - 1); }
  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // Brighter = harder. Hue fixed to the house mint.
  function velFill(v) {
    var l = 32 + (clamp(v, 1, 127) / 127) * 34; // 32%..66%
    return "hsl(158 42% " + l.toFixed(0) + "%)";
  }

  function clear() {
    model = [];
    blockEls = [];
    layout = null;
    opts = {};
    playCursor = 0;
    tinted = [];
    playheadEl = null;
    mount.innerHTML = '<div class="roll-empty">no notes yet \u2014 play something</div>';
    if (metaEl) metaEl.textContent = "";
  }

  function render(events, options) {
    opts = options || {};
    model = [];
    (events || []).forEach(function (ev, idx) {
      if (!ev || ev.kind === "rest" || !ev.notes || !ev.notes.length) return;
      var on = Number(ev.on_time);
      if (!isFinite(on)) return;
      var off = Number(ev.off_time);
      if (!isFinite(off) || off <= on) off = on + Number(ev.duration || 0.25);
      var vel = Number(ev.velocity);
      if (!isFinite(vel) || vel <= 0) vel = 100;
      ev.notes.forEach(function (n) {
        n = Number(n);
        if (isFinite(n) && n >= LOW && n <= HIGH) {
          model.push({ note: n, on: on, off: off, velocity: vel, idx: idx });
        }
      });
    });
    playCursor = 0;
    tinted = [];
    playheadEl = null;
    draw();
  }

  function timeSig() {
    var parts = String(opts.time_signature || "4/4").split("/");
    var numer = Number(parts[0]);
    var denom = Number(parts[1]);
    if (!(numer > 0)) numer = 4;
    if (!(denom > 0)) denom = 4;
    return { numer: numer, denom: denom };
  }

  function draw() {
    if (!model.length) { clear(); return; }

    var lo = Infinity, hi = -Infinity, t0 = Infinity, t1 = -Infinity;
    model.forEach(function (b) {
      if (b.note < lo) lo = b.note;
      if (b.note > hi) hi = b.note;
      if (b.on < t0) t0 = b.on;
      if (b.off > t1) t1 = b.off;
    });
    lo = clamp(lo - 2, LOW, HIGH);
    hi = clamp(hi + 2, LOW, HIGH);
    if (hi - lo + 1 < MIN_SPAN) {
      var c = Math.round((lo + hi) / 2);
      lo = clamp(c - Math.floor(MIN_SPAN / 2), LOW, HIGH - MIN_SPAN + 1);
      hi = Math.min(HIGH, lo + MIN_SPAN - 1);
    }
    var rows = hi - lo + 1;
    var span = Math.max(MIN_SPAN_SEC, t1 - t0);

    var rowH = clamp(Math.round(TARGET_H / rows), ROW_MIN, ROW_MAX);
    var plotH = rows * rowH;
    var ruler = RULER;
    var h = ruler + plotH + PAD_BOTTOM;

    var width = Math.max(240, mount.clientWidth || 800);
    var plotW = Math.max(120, width - GUTTER - RIGHT_PAD);
    var pps = plotW / span;

    layout = { gutter: GUTTER, ruler: ruler, pps: pps, h: h, origin: t0 };

    function y(n) { return ruler + (hi - n) * rowH; }

    var s = [];
    s.push('<svg class="roll-svg" width="' + width + '" height="' + h +
           '" viewBox="0 0 ' + width + ' ' + h + '" role="img" aria-label="piano roll">');

    // Row backgrounds (one per semitone in range).
    s.push('<g class="roll-rows">');
    for (var n = lo; n <= hi; n++) {
      s.push('<rect class="roll-row ' + (isBlack(n) ? "black" : "white") +
             '" x="0" y="' + y(n) + '" width="' + width + '" height="' + rowH + '"/>');
    }
    s.push("</g>");

    // Time grid + ruler. Bars are the strong lines, beats lighter, and the
    // quantize subdivision faintest (only when it won't turn to mush).
    var tempo = Number(opts.tempo) > 0 ? Number(opts.tempo) : 120;
    var ts = timeSig();
    var beatSec = (60 / tempo) * (4 / ts.denom);
    var barSec = beatSec * ts.numer;
    var divisions = Number(opts.divisions) > 0 ? Number(opts.divisions) : 4;

    s.push('<rect class="roll-ruler" x="0" y="0" width="' + width + '" height="' + ruler + '"/>');
    s.push('<g class="roll-grid">');
    if (opts.enabled && (beatSec / divisions) * pps >= 6) {
      var sub = beatSec / divisions;
      for (var t = sub; t < span; t += sub) {
        var x = (GUTTER + t * pps).toFixed(1);
        s.push('<line class="roll-gridline" x1="' + x + '" y1="' + ruler +
               '" x2="' + x + '" y2="' + h + '"/>');
      }
    }
    if (beatSec * pps >= 34) {
      for (var tb = beatSec; tb < span; tb += beatSec) {
        var xb = (GUTTER + tb * pps).toFixed(1);
        s.push('<line class="roll-beatline" x1="' + xb + '" y1="' + ruler +
               '" x2="' + xb + '" y2="' + h + '"/>');
      }
    }
    for (var bi = 0; bi * barSec < span; bi++) {
      var xbar = GUTTER + bi * barSec * pps;
      s.push('<line class="roll-barline" x1="' + xbar.toFixed(1) + '" y1="0" x2="' +
             xbar.toFixed(1) + '" y2="' + h + '"/>');
      s.push('<text class="roll-barlabel" x="' + (xbar + 3).toFixed(1) + '" y="' +
             (ruler - 5) + '">' + (bi + 1) + "</text>");
    }
    s.push("</g>");

    // Gutter (after the grid so it masks the grid's left ends).
    s.push('<g class="roll-gutter">');
    s.push('<rect class="roll-gutter-bg" x="0" y="0" width="' + GUTTER +
           '" height="' + h + '"/>');
    for (var m = lo; m <= hi; m++) {
      var black = isBlack(m);
      var kw = black ? GUTTER * 0.6 : GUTTER;
      s.push('<rect class="roll-key ' + (black ? "black" : "white") +
             '" x="0" y="' + y(m) + '" width="' + kw.toFixed(1) + '" height="' +
             rowH + '"/>');
      if (!black && m % 12 === 0) {
        s.push('<text class="roll-keylabel" x="' + (GUTTER - 3) + '" y="' +
               (y(m) + rowH - 1) + '">' + noteName(m) + "</text>");
      }
    }
    s.push('<line class="roll-edge" x1="' + GUTTER + '" y1="0" x2="' + GUTTER +
           '" y2="' + h + '"/>');
    s.push("</g>");

    // Note blocks.
    s.push('<g class="roll-blocks">');
    model.forEach(function (b, i) {
      var x = GUTTER + (b.on - t0) * pps;
      var w = Math.max(2, (b.off - b.on) * pps);
      var bh = Math.max(3, rowH - 2);
      var yy = y(b.note) + (rowH - bh) / 2;
      var tip = noteName(b.note) + "  " + (b.on - t0).toFixed(2) + "s  " +
                (b.off - b.on).toFixed(2) + "s  v" + b.velocity;
      s.push('<rect class="roll-block" data-idx="' + i + '" data-note="' + b.note +
             '" x="' + x.toFixed(1) + '" y="' + yy.toFixed(1) + '" width="' +
             w.toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="1.5" fill="' +
             velFill(b.velocity) + '"><title>' + esc(tip) + "</title></rect>");
    });
    s.push("</g>");

    // Playhead (hidden until replay; moved by showPlayhead).
    s.push('<line class="roll-playhead hidden" x1="' + GUTTER + '" y1="0" x2="' +
           GUTTER + '" y2="' + h + '"/>');

    s.push("</svg>");
    mount.innerHTML = s.join("");

    var svg = mount.querySelector(".roll-svg");
    blockEls = svg ? Array.prototype.slice.call(svg.querySelectorAll(".roll-block")) : [];
    playheadEl = svg ? svg.querySelector(".roll-playhead") : null;

    if (metaEl) {
      metaEl.textContent = model.length + (model.length === 1 ? " note" : " notes") +
        " \u00b7 " + span.toFixed(1) + "s \u00b7 " + tempo.toFixed(0) + " bpm";
    }
  }

  // ---- replay playhead + sounding-block highlight ----
  function showPlayhead(tSec) {
    if (!playheadEl || !layout) return;
    var t = Number(tSec);
    if (!isFinite(t)) return;
    var x = (layout.gutter + Math.max(0, t) * layout.pps).toFixed(1);
    playheadEl.setAttribute("x1", x);
    playheadEl.setAttribute("x2", x);
    playheadEl.classList.remove("hidden");
  }
  function hidePlayhead() {
    if (playheadEl) playheadEl.classList.add("hidden");
  }
  function untint() {
    tinted.forEach(function (el) { el.classList.remove("playing"); });
    tinted = [];
  }
  function resetPlayback() {
    playCursor = 0;
    untint();
    hidePlayhead();
  }
  function markPlaying(notes) {
    if (!notes || !notes.length || !model.length) return;
    var pick = null, pickIdx = -1;
    for (var i = playCursor; i < model.length; i++) {
      if (notes.indexOf(model[i].note) >= 0) { pick = model[i]; pickIdx = i; break; }
    }
    if (!pick) return;
    untint();
    for (var k = 0; k < model.length; k++) {
      if (Math.abs(model[k].on - pick.on) < 1e-6 && blockEls[k]) {
        blockEls[k].classList.add("playing");
        tinted.push(blockEls[k]);
      }
    }
    playCursor = pickIdx + 1;
  }

  window.PianoRoll = {
    render: render,
    clear: clear,
    resetPlayback: resetPlayback,
    showPlayhead: showPlayhead,
    hidePlayhead: hidePlayhead,
    markPlaying: markPlaying,
  };

  clear();

  // Refit time + pitch on resize (debounced).
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (model.length) draw(); }, 150);
  });
})();
