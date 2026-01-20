#!/usr/bin/env bash
set -euo pipefail
STAGE_DIR="/mnt/patents/staging/queue"
LOG_FILE="/home/mark/projects/patent_extractor/logs/newfiles_monitor.log"
INTERVAL="10"
MAX_LOOPS="0"   # 0 = infinite

printf "[%s] Monitor starting. Watching %s\n" "$(date '+%F %T')" "$STAGE_DIR" | tee -a "$LOG_FILE"
loops=0
prev_count=0
while true; do
  count=$(find "$STAGE_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l | awk '{print $1}')
  if [[ "$count" -gt 0 ]]; then
    printf "[%s] DETECTED %s file(s):\n" "$(date '+%F %T')" "$count" | tee -a "$LOG_FILE"
    ls -lt "$STAGE_DIR" 2>/dev/null | head -n 20 | tee -a "$LOG_FILE" || true
    exit 0
  fi
  if [[ "$prev_count" != "$count" ]]; then
    printf "[%s] Still empty (count=%s).\n" "$(date '+%F %T')" "$count" | tee -a "$LOG_FILE"
    prev_count="$count"
  fi
  sleep "$INTERVAL"
  if [[ "$MAX_LOOPS" -gt 0 ]]; then
    loops=$((loops+1))
    [[ "$loops" -ge "$MAX_LOOPS" ]] && exit 0
  fi
done
