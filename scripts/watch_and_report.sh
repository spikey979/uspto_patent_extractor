#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/home/mark/projects/patent_extractor/logs"
LOG_FILE="$LOG_DIR/extraction.log"
REPORT_FILE="$LOG_DIR/final_report_$(date +%Y%m%d_%H%M%S).txt"

# DB connection
export PGPASSWORD=${PGPASSWORD:-qwklmn711}
PSQL=(psql -h localhost -p 5555 -U postgres -d companies_db -t -A)

echo "[watch] Starting watcher at $(date -Is)" | tee -a "$REPORT_FILE"

# Baseline counts
baseline_abs="$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified WHERE abstract_text IS NULL OR btrim(abstract_text) = '';")"
baseline_claims="$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified WHERE claims_text IS NULL OR btrim(claims_text) = '';")"
baseline_total="$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified;")"
echo "[baseline] total=$baseline_total missing_abstracts=$baseline_abs missing_claims=$baseline_claims" | tee -a "$REPORT_FILE"

# Identify the latest run start
start_line=$(rg -n "^\d{4}/\d{2}/\d{2} .* metadata-fill-fs starting;" "$LOG_FILE" | tail -n1 | cut -d: -f1)
if [[ -z "${start_line:-}" ]]; then start_line=1; fi
echo "[watch] Monitoring log from line $start_line" | tee -a "$REPORT_FILE"

# Wait for completion marker after start_line
while :; do
  if sed -n "${start_line},\$p" "$LOG_FILE" | rg -q "^Extraction Complete!$"; then
    break
  fi
  sleep 30
done

# Gather final stats from the current run
run_slice=$(mktemp)
sed -n "${start_line},\$p" "$LOG_FILE" > "$run_slice"
archives=$(rg -n "^Archives processed: (\d+)" "$run_slice" | tail -n1 | awk '{print $3}')
extracted=$(rg -n "^Patents extracted: (\d+)" "$run_slice" | tail -n1 | awk '{print $3}')
inserted=$(rg -n "^Patents inserted: (\d+)" "$run_slice" | tail -n1 | awk '{print $3}')
errors=$(rg -n "^Errors: (\d+)" "$run_slice" | tail -n1 | awk '{print $2}')
rm -f "$run_slice"

# Post-run counts
final_abs="$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified WHERE abstract_text IS NULL OR btrim(abstract_text) = '';")"
final_claims="$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified WHERE claims_text IS NULL OR btrim(claims_text) = '';")"
final_total="$(${PSQL[@]} -c "SELECT count(*) FROM patent_data_unified;")"

delta_abs=$(( ${baseline_abs} - ${final_abs} ))
delta_claims=$(( ${baseline_claims} - ${final_claims} ))

{
  echo "[complete] $(date -Is)"
  echo "archives_processed=$archives patents_extracted=$extracted patents_upserted=$inserted errors=$errors"
  echo "final_total=$final_total"
  echo "abstracts_missing_before=$baseline_abs abstracts_missing_after=$final_abs delta=$delta_abs"
  echo "claims_missing_before=$baseline_claims claims_missing_after=$final_claims delta=$delta_claims"
} | tee -a "$REPORT_FILE"

echo "[watch] Report written to $REPORT_FILE"

