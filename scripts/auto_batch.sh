#!/usr/bin/env bash
set -euo pipefail
PROJ=/home/mark/projects/patent_extractor
LOG=$PROJ/logs/extraction.log
PROC=$PROJ/processed_archives.txt
ST=/mnt/patents/staging/queue
ORIG=/mnt/patents/data/historical
BATCH_SIZE=${BATCH_SIZE:-100}
SLEEP=${SLEEP:-60}

echo "[auto-batch] starting with batch size $BATCH_SIZE, sleep $SLEEP s"

is_processed() {
  local base="$1"
  # Check basename only - path-agnostic matching
  grep -q "${base}$" "$PROC" 2>/dev/null && return 0
  return 1
}

stage_next() {
  local moved=0
  mkdir -p "$ST"
  for f in "$ORIG"/I*.tar; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    if is_processed "$base"; then continue; fi
    if [ -f "$ST/$base" ]; then continue; fi
    mv -f "$f" "$ST/$base" || true
    echo "[auto-batch] staged $base" >> "$PROJ/logs/auto_batch.log"
    moved=$((moved+1))
    if [ "$moved" -ge "$BATCH_SIZE" ]; then break; fi
  done
  echo "$moved"
}

while true; do
  if pgrep -f patent_extractor >/dev/null 2>&1; then
    sleep "$SLEEP"; continue
  fi
  qcnt=$(ls -1 "$ST"/I*.tar 2>/dev/null | wc -l | awk '{print $1}')
  if [ "$qcnt" -eq 0 ]; then
    moved=$(stage_next)
    echo "[auto-batch] staged_count=$moved" >> "$PROJ/logs/auto_batch.log"
    if [ "$moved" -eq 0 ]; then
      echo "[auto-batch] all archives completed. exiting." >> "$PROJ/logs/auto_batch.log"
      exit 0
    fi
  fi
  echo "[auto-batch] launching extractor; queue now $(ls -1 "$ST"/I*.tar 2>/dev/null | wc -l | awk '{print $1}')" >> "$PROJ/logs/auto_batch.log"
  (cd "$PROJ" && nohup ./patent_extractor >> "$LOG" 2>&1 & echo $!)
  sleep "$SLEEP"
done
