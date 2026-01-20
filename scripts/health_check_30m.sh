#!/usr/bin/env bash
set -euo pipefail

sleep 1800

DIR="/home/mark/projects/patent_extractor"
LOG="$DIR/logs/extraction.log"
PIDFILE="$DIR/patent_extractor.pid"
STATUS_LOG="$DIR/logs/health_checks.log"

ts() { date -Is; }

restart() {
  echo "[$(ts)] restarting extractor" | tee -a "$STATUS_LOG"
  cd "$DIR"
  if command -v go >/dev/null 2>&1; then
    go build -o patent_extractor patent_extractor.go
  else
    "$HOME"/go/bin/go build -o patent_extractor patent_extractor.go
  fi
  nohup env SCAN_NEW=0 REPROCESS_ALL=1 FORCE_OVERWRITE=1 FILES_ROOT=/mnt/patents/originals WORKERS=8 ./patent_extractor > "$LOG" 2>&1 &
  NEWPID=$!
  echo "$NEWPID" > "$PIDFILE"
  echo "[$(ts)] restarted PID=$NEWPID" | tee -a "$STATUS_LOG"
}

echo "[$(ts)] health check start" | tee -a "$STATUS_LOG"

PID=""; [ -f "$PIDFILE" ] && PID=$(cat "$PIDFILE" || true) || true
running=false
if [ -n "$PID" ] && ps -p "$PID" >/dev/null 2>&1; then running=true; fi

panic_recent=false
if [ -f "$LOG" ]; then
  if tail -n 500 "$LOG" | rg -qi "panic|index out of range|fatal"; then panic_recent=true; fi
fi

if ! $running || $panic_recent; then
  echo "[$(ts)] issue detected running=$running panic_recent=$panic_recent" | tee -a "$STATUS_LOG"
  restart
else
  cpu=$(ps -p "$PID" -o pcpu= 2>/dev/null | tr -d ' ' || echo "0")
  mem=$(ps -p "$PID" -o pmem= 2>/dev/null | tr -d ' ' || echo "0")
  echo "[$(ts)] healthy pid=$PID cpu=${cpu}% mem=${mem}%" | tee -a "$STATUS_LOG"
fi

# Lightweight DB ping
export PGPASSWORD=${PGPASSWORD:-qwklmn711}
psql -h localhost -p 5555 -U postgres -d companies_db -t -A -c "SELECT 'ok' AS db, NOW();" >> "$STATUS_LOG" 2>&1 || true

echo "[$(ts)] health check end" | tee -a "$STATUS_LOG"

