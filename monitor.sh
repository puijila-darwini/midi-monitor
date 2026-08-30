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
LOG="$HOME/ai/tmp/keymon/monitor.log"
PORT=5050

mkdir -p "$HOME/ai/tmp/keymon"

is_running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

cmd_status() {
  if is_running; then
    echo "RUNNING  ->  http://127.0.0.1:$PORT"
    echo "pid: $(cat "$PIDFILE")"
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
