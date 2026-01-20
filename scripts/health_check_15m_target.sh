#!/usr/bin/env bash
set -euo pipefail
sleep 900
DIR=/home/mark/projects/patent_extractor
LOG="$DIR/logs/extraction.log"
PIDFILE="$DIR/patent_extractor.pid"
OUT="$DIR/logs/health_2010_2015.log"
TS() { date -Is; }

PID=""; [ -f "$PIDFILE" ] && PID=$(cat "$PIDFILE" || true) || true
running=false
if [ -n "$PID" ] && ps -p "$PID" >/dev/null 2>&1; then running=true; fi
panic_recent=false
if [ -f "$LOG" ]; then tail -n 500 "$LOG" | rg -qi "panic|fatal|index out of range" && panic_recent=true || true; fi

if ! $running || $panic_recent; then
  echo "[$(TS)] UNHEALTHY running=$running panic_recent=$panic_recent" | tee -a "$OUT"
  cd "$DIR"
  if command -v go >/dev/null 2>&1; then go build -o patent_extractor patent_extractor.go; else "$HOME"/go/bin/go build -o patent_extractor patent_extractor.go; fi
  nohup env SCAN_NEW=1 REPROCESS_ALL=1 FORCE_OVERWRITE=1 FILES_ROOT="/mnt/patents/originals/Target2010_2015" WORKERS=8 ./patent_extractor > "$LOG" 2>&1 &
  NEWPID=$!
  echo "$NEWPID" > "$PIDFILE"
  echo "[$(TS)] restarted PID=$NEWPID" | tee -a "$OUT"
else
  echo "[$(TS)] HEALTHY pid=$PID" | tee -a "$OUT"
fi

# DB verification for 2010–2015 window
export PGPASSWORD=${PGPASSWORD:-qwklmn711}
PSQL=(psql -h localhost -p 5555 -U postgres -d companies_db -t -A)
claims_marker=$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified WHERE pub_date BETWEEN '2010-01-01' AND '2015-12-31' AND description_text ILIKE 'CLAIMS:%';")
brackets=$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified WHERE pub_date BETWEEN '2010-01-01' AND '2015-12-31' AND (description_text ~ '\\[[0-9]{4}\\]' OR description_body ~ '\\[[0-9]{4}\\]');")
claims_nonempty=$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified WHERE pub_date BETWEEN '2010-01-01' AND '2015-12-31' AND btrim(COALESCE(claims_text,'')) <> '';")

echo "[$(TS)] verify: claims_marker=$claims_marker brackets=$brackets claims_nonempty=$claims_nonempty" | tee -a "$OUT"
