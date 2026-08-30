#!/usr/bin/env python3
"""Supervisor: health-check the monitor server and restart it if it dies.

This is the second line of defense behind the in-process capture watchdog
(see app.py `_run_capture_supervised`). It polls /api/state; if the server is
unreachable, or the capture loop reports dead, it restarts the whole server
via monitor.sh so a wedged/hung process is replaced rather than left silently
serving a dead keyboard.

Stdlib-only (urllib/json/subprocess) so it needs no pip installs.
"""
import json
import subprocess
import sys
import time
import urllib.request

PORT = 5050
BASE = f"http://127.0.0.1:{PORT}"
POLL_INTERVAL = 5.0
# Restart only once the fault persists across this many consecutive polls,
# giving the in-process watchdog time to recover first.
RESTART_AFTER_POLLS = 3

MONITOR_SH = None


def fetch_state():
    try:
        with urllib.request.urlopen(BASE + "/api/state", timeout=4) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def log(msg):
    print(f"[supervisor] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def restart_server():
    log(f"restarting monitor ({MONITOR_SH})")
    if MONITOR_SH:
        try:
            subprocess.run(["bash", MONITOR_SH, "restart"], timeout=20)
        except Exception as e:  # noqa: BLE001
            log(f"restart failed: {e}")


def main():
    global MONITOR_SH
    MONITOR_SH = sys.argv[1] if len(sys.argv) > 1 else None
    dead_polls = 0
    log(f"supervisor started (poll {POLL_INTERVAL}s, restart after "
        f"{RESTART_AFTER_POLLS} bad polls)")
    while True:
        time.sleep(POLL_INTERVAL)
        s = fetch_state()
        if s is None:
            dead_polls += 1
            log(f"server unreachable (poll {dead_polls})")
            if dead_polls >= RESTART_AFTER_POLLS:
                restart_server()
                dead_polls = 0
            continue
        cap = s.get("capture") or {}
        if cap.get("alive") is False and cap.get("error"):
            dead_polls += 1
            log(f"capture dead ({cap.get('error')}) (poll {dead_polls})")
            if dead_polls >= RESTART_AFTER_POLLS:
                restart_server()
                dead_polls = 0
        else:
            dead_polls = 0


if __name__ == "__main__":
    main()
