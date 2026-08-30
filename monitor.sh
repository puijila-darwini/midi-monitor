#!/usr/bin/env bash
# Keyboard Monitor helper: start / stop / restart / status / log
#
# Usage:
#   bash ~/ai/midi/monitor.sh start     start the server on :5050
#   bash ~/ai/midi/monitor.sh stop      stop it
#   bash ~/ai/midi/monitor.sh restart   restart it
#   bash ~/ai/midi/monitor.sh status    is it running / what's the url
#   bash ~/ai/midi/monitor.sh log       tail the server log
#
# (No need for the keyboard to be on -- the server handles that itself.)

DIR="$HOME/ai/midi"
PIDFILE="$HOME/ai/tmp/keymon/monitor.pid"
SUPPIDFILE="$HOME/ai/tmp/keymon/supervisor.pid"
LOG="$HOME/ai/tmp/keymon/monitor.log"
SUPLOG="$HOME/ai/tmp/keymon/supervisor.log"
PORT=5050

mkdir -p "$HOME/ai/tmp/keymon"

is_running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

sup_running() {
  [ -f "$SUPPIDFILE" ] && kill -0 "$(cat "$SUPPIDFILE")" 2>/dev/null
}

cmd_status() {
  if is_running; then
    echo "RUNNING  ->  http://127.0.0.1:$PORT"
    echo "pid: $(cat "$PIDFILE")"
    if sup_running; then
      echo "supervisor pid: $(cat "$SUPPIDFILE") (auto-restart on)"

    else
      echo "supervisor: not running"
    fi
  else
    echo "STOPPED  ->  start it with:  bash $DIR/monitor.sh start"
  fi
}

cmd_start() {
  if is_running; then
    echo "Already running -> http://127.0.0.1:$PORT"
    return 0
  fi
  rm -f "$PIDFILE"
  cd "$DIR" || exit 1
  nohup python3 -m monitor.app >> "$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  # Supervisor: health-checks /api/state and restarts the server if capture
  # dies or the server goes unreachable. Not started with the server so an
  # intentional 'stop' (below) kills it too -- otherwise it would immediately
  # try to restart a deliberately-stopped server.
  if ! sup_running; then
    rm -f "$SUPPIDFILE"
    nohup python3 -m monitor.supervisor "$DIR/monitor.sh" >> "$SUPLOG" 2>&1 &
    echo $! > "$SUPPIDFILE"
  fi
  sleep 2
  if is_running; then
    echo "Started -> http://127.0.0.1:$PORT  (log: $LOG)"
  else
    echo "Failed to start -- check the log:"
    tail -20 "$LOG"
  fi
}

cmd_stop() {
  if is_running; then
    kill "$(cat "$PIDFILE")"
    rm -f "$PIDFILE"
    echo "Stopped."
  else
    echo "Not running."
  fi
  if sup_running; then
    kill "$(cat "$SUPPIDFILE")"
    rm -f "$SUPPIDFILE"
  fi
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

case "${1:-}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_restart ;;
  status)  cmd_status ;;
  log)     tail -50 "$LOG" ;;
  *) echo "Usage: bash $0 {start|stop|restart|status|log}" ;;
esac
