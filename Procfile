# Overmind Procfile for Patent Extractor Services
# Start all: overmind start
# Start specific: overmind start -l web,search
# Stop all: overmind quit or Ctrl+C

# Web Applications
web: cd patent_search && python3.11 patent_search_ai_fixed.py
search_claims: cd patent_search && python3.11 patent_search_ai_with_claims.py

# Data Sync (run manually)
sync: /mnt/patents/originals_ptgrmp2/sync.sh 2>&1 | tee logs/sync.log

# Data Extraction (run manually, not by default)
extract_historical: ./patent_extractor 2>&1 | tee logs/extractor_historical.log
extract_grants: ./grant_extractor 2>&1 | tee logs/extractor_grants.log

# File Monitoring/Watchers
# monitor: ./scripts/monitor_newfiles.sh

# Batch Processing (run manually)
# batch: ./scripts/auto_batch.sh
