#!/bin/bash
cd /home/mark/projects/patent_extractor
export DB_PORT=5432
export FILES_ROOT="/mnt/patents/originals"
export WORKERS=8
export BATCH_SIZE=500
export DB_PASSWORD="qwklmn711"

echo "Starting Patent Application Number Backfill..."
echo "Processing patents with missing application numbers"
echo ""
./patent_extractor_backfill
