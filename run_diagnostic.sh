#!/bin/bash
cd /home/mark/projects/patent_extractor

export DB_PORT=5432
export FILES_ROOT="/mnt/patents/originals"
export DB_PASSWORD="qwklmn711"
export LOG_FILE="/home/mark/projects/patent_extractor/logs/diagnostic_analysis.jsonl"

echo "Starting Patent Diagnostic Analyzer..."
echo ""
echo "This will analyze up to 1000 missing patents to identify why extraction failed."
echo ""
echo "Output: $LOG_FILE"
echo ""

# Create logs directory if it doesn't exist
mkdir -p /home/mark/projects/patent_extractor/logs

# Run diagnostic
go run patent_diagnostic_analyzer.go

echo ""
echo "=== Quick Analysis ==="
echo ""

if [ -f "$LOG_FILE" ]; then
    echo "Failure reasons (count):"
    jq -r '.failure_reason' "$LOG_FILE" 2>/dev/null | sort | uniq -c | sort -rn

    echo ""
    echo "DTD versions found:"
    jq -r '.dtd_version // "none"' "$LOG_FILE" 2>/dev/null | sort | uniq -c

    echo ""
    echo "Years analyzed:"
    jq -r '.year' "$LOG_FILE" 2>/dev/null | sort | uniq -c
fi

echo ""
echo "For detailed analysis, run:"
echo "  jq 'select(.failure_reason == \"REASON_HERE\")' $LOG_FILE | less"
echo "  jq '.xml_sample' $LOG_FILE | less"
