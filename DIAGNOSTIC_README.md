# Patent Diagnostic Analyzer

## Purpose

Deeply analyze the remaining **53,977 patents** (0.66%) missing application numbers to identify:
- Why extraction failed
- What XML format issues exist
- Which files are corrupted or missing
- Patterns in failures by year/DTD version

## What It Does

The diagnostic analyzer performs a **7-step deep inspection** of each missing patent:

### Step-by-Step Analysis

1. **Extract Archive Date** from `raw_xml_path`
2. **Locate Archive File** (checks multiple directories)
3. **Load & Parse Archive** (outer ZIP)
4. **Find Nested ZIP** (2001-2004 format)
5. **Extract XML File** from nested ZIP
6. **Analyze XML Structure**:
   - DTD version
   - Has `<application-reference>` tag?
   - Has `<domestic-filing-data>` tag?
   - Has `<application-number>` tag?
   - Has `<doc-number>` tag?
   - Raw application number text
7. **Attempt Extraction** with both regex patterns

### Output Format

Results are logged in **JSONL** (JSON Lines) format for easy analysis:

```json
{
  "timestamp": "2025-11-22T20:45:00Z",
  "pub_number": "20030055038",
  "raw_xml_path": "US20030055038A1-20030320/US20030055038A1-20030320.XML",
  "year": 2003,
  "filing_date": "2002-05-22",
  "pub_date": "",
  "archive_name": "20030320.ZIP",
  "archive_found": true,
  "archive_location": "/mnt/patents/data/historical/2003/20030320.ZIP",
  "archive_size": 1234567890,
  "nested_zip_found": true,
  "nested_zip_name": "US20030055038A1-20030320.ZIP",
  "xml_file_found": true,
  "xml_file_name": "US20030055038A1-20030320.XML",
  "xml_size": 45678,
  "xml_readable": true,
  "dtd_version": "pap-v16-2002-01-01.dtd",
  "has_application_reference": false,
  "has_domestic_filing_data": true,
  "has_application_number": true,
  "has_doc_number": false,
  "raw_app_number_text": "...",
  "extracted_app_number": "",
  "failure_reason": "no_doc_number_tag",
  "xml_sample": "<?xml version...",
  "error_details": []
}
```

## Usage

### 1. Run Diagnostic Analysis

```bash
cd /home/mark/projects/patent_extractor
./run_diagnostic.sh
```

This will:
- Analyze up to **1,000 missing patents**
- Write detailed logs to `logs/diagnostic_analysis.jsonl`
- Show quick summary of failure reasons

### 2. Analyze Results

```bash
./analyze_diagnostics.sh
```

This provides:
- Count of each failure reason
- Year distribution
- DTD version breakdown
- XML structure statistics
- Sample cases for each failure type

### 3. Deep Dive Analysis

```bash
# View all cases of a specific failure
jq 'select(.failure_reason == "no_doc_number_tag")' logs/diagnostic_analysis.jsonl | less

# See XML samples for a failure type
jq -r 'select(.failure_reason == "no_application_section_in_xml") | .xml_sample' logs/diagnostic_analysis.jsonl | less

# Export to CSV for spreadsheet analysis
jq -r '[.pub_number, .year, .failure_reason, .dtd_version, .has_doc_number] | @csv' logs/diagnostic_analysis.jsonl > analysis.csv
```

## Failure Reason Categories

| Failure Reason | Description | Action Needed |
|----------------|-------------|---------------|
| `cannot_extract_date_from_path` | Path doesn't match expected format | Check path format |
| `archive_not_found` | Archive file missing from disk | Verify archive exists |
| `archive_read_error` | Can't read archive file | Check file permissions/corruption |
| `archive_parse_error` | ZIP file corrupted | Re-download archive |
| `nested_zip_not_found` | Expected nested ZIP missing | Check archive structure |
| `nested_zip_parse_error` | Nested ZIP corrupted | Re-download archive |
| `xml_file_not_found` | XML file missing from nested ZIP | Check archive contents |
| `xml_read_error` | Can't read XML file | Check XML file corruption |
| `no_application_section_in_xml` | No `<application-reference>` or `<domestic-filing-data>` | May need new regex pattern |
| `no_application_number_tag` | Has section but no `<application-number>` tag | Non-standard format |
| `no_doc_number_tag` | Has `<application-number>` but no `<doc-number>` | Non-standard format |
| `extraction_failed_unknown` | Has all tags but extraction failed | Debug regex pattern |
| `extracted_successfully_but_not_in_db` | Extraction works but not in DB | Check DB update logic |

## Files

| File | Purpose |
|------|---------|
| `patent_diagnostic_analyzer.go` | Main diagnostic program |
| `run_diagnostic.sh` | Run diagnostics and show summary |
| `analyze_diagnostics.sh` | Detailed analysis of results |
| `logs/diagnostic_analysis.jsonl` | Output log (JSONL format) |

## Expected Insights

After running diagnostics, you'll know:

1. **Most common failure reason** (e.g., 80% missing `<doc-number>` tag)
2. **Which DTD versions** have issues
3. **Which years** are problematic (2003, 2010)
4. **If archives are missing** vs. XML structure issues
5. **If we need new regex patterns** for edge cases

## Next Steps After Diagnosis

Based on results:

### If Most Failures Are Archive Issues:
- Check if archives need re-downloading
- Verify archive integrity

### If Most Failures Are XML Structure Issues:
- Examine XML samples
- Create additional regex patterns
- Update extraction logic

### If Most Failures Are Edge Cases:
- Document known limitations
- Accept 99.34% coverage as excellent

## Sample Workflow

```bash
# 1. Run diagnostic (analyzes 1000 patents)
./run_diagnostic.sh

# 2. See summary
./analyze_diagnostics.sh

# 3. If you see "no_doc_number_tag" is common, investigate:
jq 'select(.failure_reason == "no_doc_number_tag") | {pub_number, raw_app_number_text, xml_sample}' \
   logs/diagnostic_analysis.jsonl | less

# 4. Find patterns and create fix if possible
# 5. Re-run backfill with updated extraction logic
```

## Performance

- **Speed**: ~5-10 patents/second
- **Memory**: <500MB (processes one patent at a time)
- **Time**: ~2-3 minutes for 1,000 patents
- **Safety**: Read-only, won't modify database

## Limits

- Analyzes up to **1,000 patents** by default (configurable in code)
- Only checks years: 2001, 2002, 2003, 2004, 2010
- Doesn't attempt to fix issues (diagnostic only)

## Log Retention

Logs are **append-only** - each run adds to the JSONL file. To start fresh:

```bash
rm logs/diagnostic_analysis.jsonl
```

## Integration with jq

The JSONL format works perfectly with `jq`:

```bash
# Count by failure reason
jq -r '.failure_reason' logs/diagnostic_analysis.jsonl | sort | uniq -c

# Get all 2003 failures
jq 'select(.year == 2003)' logs/diagnostic_analysis.jsonl

# Find patents with specific DTD
jq 'select(.dtd_version | contains("2002"))' logs/diagnostic_analysis.jsonl

# Boolean field queries
jq 'select(.has_doc_number == false and .has_application_number == true)' logs/diagnostic_analysis.jsonl
```
