#!/bin/bash
# Helper script to analyze diagnostic results

LOG_FILE="/home/mark/projects/patent_extractor/logs/diagnostic_analysis.jsonl"

if [ ! -f "$LOG_FILE" ]; then
    echo "Error: Log file not found: $LOG_FILE"
    echo "Run ./run_diagnostic.sh first"
    exit 1
fi

echo "=== Diagnostic Analysis Report ==="
echo ""

echo "Total patents analyzed:"
wc -l < "$LOG_FILE"
echo ""

echo "Failure Reasons (sorted by frequency):"
jq -r '.failure_reason' "$LOG_FILE" | sort | uniq -c | sort -rn
echo ""

echo "Years with issues:"
jq -r '.year' "$LOG_FILE" | sort | uniq -c
echo ""

echo "DTD Versions:"
jq -r '.dtd_version // "none"' "$LOG_FILE" | sort | uniq -c
echo ""

echo "Archive success rates:"
echo -n "  Archives found: "
jq -r 'select(.archive_found == true)' "$LOG_FILE" | wc -l
echo -n "  Archives NOT found: "
jq -r 'select(.archive_found == false)' "$LOG_FILE" | wc -l
echo ""

echo "XML structure analysis:"
echo -n "  Has application-reference: "
jq -r 'select(.has_application_reference == true)' "$LOG_FILE" | wc -l
echo -n "  Has domestic-filing-data: "
jq -r 'select(.has_domestic_filing_data == true)' "$LOG_FILE" | wc -l
echo -n "  Has application-number tag: "
jq -r 'select(.has_application_number == true)' "$LOG_FILE" | wc -l
echo -n "  Has doc-number tag: "
jq -r 'select(.has_doc_number == true)' "$LOG_FILE" | wc -l
echo ""

echo "=== Sample Cases by Failure Type ==="
echo ""

# Get unique failure reasons
REASONS=$(jq -r '.failure_reason' "$LOG_FILE" | sort -u)

for REASON in $REASONS; do
    COUNT=$(jq -r "select(.failure_reason == \"$REASON\")" "$LOG_FILE" | wc -l)
    echo "[$COUNT cases] $REASON"
    echo "  Sample patent:"
    jq -r "select(.failure_reason == \"$REASON\") | .pub_number + \" (\" + (.year | tostring) + \")\"" "$LOG_FILE" | head -1
    echo ""
done

echo "=== Detailed Analysis Commands ==="
echo ""
echo "View all cases of a specific failure:"
echo "  jq 'select(.failure_reason == \"REASON\")' $LOG_FILE | less"
echo ""
echo "View XML samples for specific failure:"
echo "  jq -r 'select(.failure_reason == \"REASON\") | .xml_sample' $LOG_FILE | less"
echo ""
echo "Get raw application number text for specific failure:"
echo "  jq -r 'select(.failure_reason == \"REASON\") | .raw_app_number_text' $LOG_FILE | grep ."
echo ""
echo "Export to CSV for spreadsheet analysis:"
echo "  jq -r '[.pub_number, .year, .failure_reason, .dtd_version] | @csv' $LOG_FILE > analysis.csv"
