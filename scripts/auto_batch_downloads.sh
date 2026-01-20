#!/usr/bin/env bash
set -euo pipefail

# Enhanced auto-batch script with Downloads monitoring
PROJ=/home/mark/projects/patent_extractor
DOWNLOAD_DIR=/home/mark/Downloads
NEWFILES=/mnt/patents/staging/queue
ORIG=/mnt/patents/data/historical
LOG=$PROJ/logs/auto_batch_downloads.log
PROC=$PROJ/processed_archives.txt
BATCH_SIZE=${BATCH_SIZE:-100}
SLEEP=${SLEEP:-60}

mkdir -p "$NEWFILES"
mkdir -p "$PROJ/logs"

echo "[$(date '+%F %T')] Auto-batch with Downloads monitoring starting" | tee -a "$LOG"
echo "[$(date '+%F %T')] Watch dir: $DOWNLOAD_DIR" | tee -a "$LOG"
echo "[$(date '+%F %T')] Stage dir: $NEWFILES" | tee -a "$LOG"
echo "[$(date '+%F %T')] Batch size: $BATCH_SIZE, Sleep: ${SLEEP}s" | tee -a "$LOG"
echo "" | tee -a "$LOG"

is_processed() {
  local base="$1"
  # Check basename only - path-agnostic matching
  grep -q "${base}$" "$PROC" 2>/dev/null && return 0
  return 1
}

# Check Downloads folder for completed files
check_downloads() {
    local moved=0

    # Process TAR files
    shopt -s nullglob
    for file in "$DOWNLOAD_DIR"/*.tar; do
        # Skip incomplete downloads
        [[ "$file" == *".crdownload"* ]] && continue
        [[ "$file" == *"Unconfirmed"* ]] && continue

        base=$(basename "$file")

        # Skip if already processed
        if is_processed "$base"; then
            echo "[$(date '+%F %T')] Skipping already processed: $base" >> "$LOG"
            rm -f "$file"
            continue
        fi

        # Skip if already in staging
        if [ -f "$NEWFILES/$base" ]; then
            echo "[$(date '+%F %T')] Already in staging: $base" >> "$LOG"
            rm -f "$file"
            continue
        fi

        echo "[$(date '+%F %T')] New download detected: $base" >> "$LOG"
        mv "$file" "$NEWFILES/" && moved=$((moved+1))
    done

    # Process ZIP files
    for file in "$DOWNLOAD_DIR"/*.ZIP "$DOWNLOAD_DIR"/*.zip; do
        # Skip incomplete downloads
        [[ "$file" == *".crdownload"* ]] && continue
        [[ "$file" == *"Unconfirmed"* ]] && continue

        base=$(basename "$file")

        # Skip if already processed
        if is_processed "$base"; then
            echo "[$(date '+%F %T')] Skipping already processed: $base" >> "$LOG"
            rm -f "$file"
            continue
        fi

        # Skip if already in staging
        if [ -f "$NEWFILES/$base" ]; then
            echo "[$(date '+%F %T')] Already in staging: $base" >> "$LOG"
            rm -f "$file"
            continue
        fi

        echo "[$(date '+%F %T')] New download detected: $base" >> "$LOG"
        mv "$file" "$NEWFILES/" && moved=$((moved+1))
    done

    # Process TAR.GZ files
    for file in "$DOWNLOAD_DIR"/*.tar.gz; do
        # Skip incomplete downloads
        [[ "$file" == *".crdownload"* ]] && continue
        [[ "$file" == *"Unconfirmed"* ]] && continue

        base=$(basename "$file")

        # Skip if already processed
        if is_processed "$base"; then
            echo "[$(date '+%F %T')] Skipping already processed: $base" >> "$LOG"
            rm -f "$file"
            continue
        fi

        # Skip if already in staging
        if [ -f "$NEWFILES/$base" ]; then
            echo "[$(date '+%F %T')] Already in staging: $base" >> "$LOG"
            rm -f "$file"
            continue
        fi

        echo "[$(date '+%F %T')] New download detected: $base" >> "$LOG"
        mv "$file" "$NEWFILES/" && moved=$((moved+1))
    done
    shopt -u nullglob

    echo "$moved"
}

# Stage next batch from originals
stage_next_from_originals() {
  local moved=0

  # Stage I-prefix TAR files first (newer patents)
  for f in "$ORIG"/I*.tar; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    if is_processed "$base"; then continue; fi
    if [ -f "$NEWFILES/$base" ]; then continue; fi
    mv -f "$f" "$NEWFILES/$base" || true
    echo "[$(date '+%F %T')] Staged from originals: $base" >> "$LOG"
    moved=$((moved+1))
    if [ "$moved" -ge "$BATCH_SIZE" ]; then break; fi
  done

  # If batch not full, add regular archives
  if [ "$moved" -lt "$BATCH_SIZE" ]; then
    for f in "$ORIG"/*.ZIP "$ORIG"/*.zip "$ORIG"/*.tar; do
      [ -e "$f" ] || continue
      base=$(basename "$f")
      # Skip I-prefix (already processed above)
      [[ "$base" == I*.tar ]] && continue
      if is_processed "$base"; then continue; fi
      if [ -f "$NEWFILES/$base" ]; then continue; fi
      mv -f "$f" "$NEWFILES/$base" || true
      echo "[$(date '+%F %T')] Staged from originals: $base" >> "$LOG"
      moved=$((moved+1))
      if [ "$moved" -ge "$BATCH_SIZE" ]; then break; fi
    done
  fi

  echo "$moved"
}

# Main monitoring loop
while true; do
    # Step 1: Check for new downloads
    dl_moved=$(check_downloads)
    if [ "$dl_moved" -gt 0 ]; then
        echo "[$(date '+%F %T')] Moved $dl_moved files from Downloads to staging" | tee -a "$LOG"
    fi

    # Step 2: Check if extractor is running
    if pgrep -f "patent_extractor" >/dev/null 2>&1; then
        echo "[$(date '+%F %T')] Extractor running, waiting..." >> "$LOG"
        sleep "$SLEEP"
        continue
    fi

    # Step 3: Check staging queue
    qcnt=$(find "$NEWFILES" -maxdepth 1 -type f \( -name "*.tar" -o -name "*.ZIP" -o -name "*.zip" -o -name "*.tar.gz" \) 2>/dev/null | wc -l)

    # Step 4: If queue empty, stage next batch from originals
    if [ "$qcnt" -eq 0 ]; then
        echo "[$(date '+%F %T')] Queue empty, staging next batch..." | tee -a "$LOG"
        staged=$(stage_next_from_originals)
        echo "[$(date '+%F %T')] Staged $staged archives from originals" | tee -a "$LOG"

        if [ "$staged" -eq 0 ]; then
            # Recheck downloads one more time before exiting
            dl_check=$(check_downloads)
            if [ "$dl_check" -eq 0 ]; then
                echo "[$(date '+%F %T')] All archives completed and no pending downloads. Exiting." | tee -a "$LOG"
                exit 0
            fi
        fi

        # Recalculate queue count
        qcnt=$(find "$NEWFILES" -maxdepth 1 -type f \( -name "*.tar" -o -name "*.ZIP" -o -name "*.zip" -o -name "*.tar.gz" \) 2>/dev/null | wc -l)
    fi

    # Step 5: Launch extractor if queue has files
    if [ "$qcnt" -gt 0 ]; then
        echo "[$(date '+%F %T')] Launching extractor for $qcnt files in queue" | tee -a "$LOG"
        cd "$PROJ"
        WORKERS=8 DB_PASSWORD=qwklmn711 \
            ./patent_extractor -scan-new >> "$PROJ/logs/extraction.log" 2>&1 &
        extractor_pid=$!
        echo "[$(date '+%F %T')] Started extractor (PID: $extractor_pid)" | tee -a "$LOG"
    fi

    sleep "$SLEEP"
done
