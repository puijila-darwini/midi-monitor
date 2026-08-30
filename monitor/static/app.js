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

  function setTimesig(numer, denom) {
    timesig.numer = numer;
    timesig.denom = denom;
    window.timesig = timesig;
  }

  function isBlack(note) { return BLACK[note % 12] === 1; }
  function octLabel(note) {
    return "C" + (Math.floor(note / 12) - 1);
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
    var KW = 15, BW = 9;
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
        if (window.StavePanel && ev.notes) {
          StavePanel.push(ev.kind, ev.notes, ev.time, ev.label);
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
        if (window.StavePanel) StavePanel.push("note", [ev.note], ev.off_time, null, ev.duration);
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

  (function () {
    var btn = document.getElementById("feed-clear");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var feedList = document.getElementById("feed-list");
      if (feedList) feedList.innerHTML = "";
    });
  })();

  // Intended-key selector (manual key input)
  (function () {
    var sel = document.getElementById("intended-key");
    if (!sel) return;
    sel.addEventListener("change", function () {
      if (window.StavePanel) StavePanel.setKey(sel.value);
    });
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
