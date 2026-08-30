# Live Keyboard Monitor

Turns your MIDI keyboard into a live, on-screen grand piano. As you play,
keys light up, a note stream scrolls by, and the app names the chords,
arpeggios and intervals you're playing — in real time.

Visit it in your browser at: **http://127.0.0.1:5050**

---

## Starting and stopping it (the easy way)

Open a terminal and run:

```
bash ~/ai/midi/monitor.sh start
```

That's it. Then open http://127.0.0.1:5050 in your browser.

| What you want | Command |
|---|---|
| Start | `bash ~/ai/midi/monitor.sh start` |
| Stop | `bash ~/ai/midi/monitor.sh stop` |
| Restart | `bash ~/ai/midi/monitor.sh restart` |
| Is it running? | `bash ~/ai/midi/monitor.sh status` |
| See recent log | `bash ~/ai/midi/monitor.sh log` |

### How to know it worked
- `start` prints `Started -> http://127.0.0.1:5050`.
- `status` prints `RUNNING` (or `STOPPED` with a hint).

### Notes
- You don't need to worry about the keyboard being on first — the app
  watches for it and reconnects on its own. It shows **keyboard offline**
  until the keyboard is on.
- If you move/copy this project folder, update the path in the commands
  above to match.

---

## What you'll see on screen

- **The big piano** – all 88 keys (A0 to C8). Keys light up as you hold them.
- **The flash banner** – names what you just played. Colour tells you what
  kind of musical object it was:
  - 🔵 **blue** – a **chord** (e.g. `C4 maj`, `G4 min`)
  - 🩵 **light blue** – an **arpeggio** (a chord you rolled/played note-by-note)
  - 🩷 **pink** – an **interval** (just two notes, e.g. `perf 5th`)
- **The note stream** – every note on/off scrolling in real time.
- **Status** – keyboard on/off.

### Playing tips
- Hold a few notes together → you'll see a **blue chord**.
- Roll a chord quickly (one note after the other) → **light blue arpeggio**.
- Hold just two notes → **pink interval**.
- Staccato and fast repeated chords are picked up too.

---

## Under the hood (for the curious / future-you)

This is a small Python web app. Everything lives in `~/ai/midi/monitor/`:

- `capture.py` – reads MIDI from the keyboard (via `aseqdump`), reconnects
  automatically.
- `analysis.py` – the brain: decides chord vs arpeggio vs interval, with
  de-duplication so repeated chords still flash.
- `chords.py` – chord/interval naming engine.
- `state.py` – current held notes + recent history.
- `app.py` – the web server (Flask, port 5050) streaming to the browser.
- `templates/` + `static/` – the on-screen piano and note stream.

The old one-off CLI scripts (`fast.py`, `listen.py`, `arpeggio.py`,
`melody.py`) were folded into this app and are no longer the product.
