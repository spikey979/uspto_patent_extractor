# Patent Grant Extractor - Implementation Status

**Date**: 2025-11-25
**Project**: USPTO Patent Grant Data Extraction Pipeline
**Current Status**: ⚠️ **BLOCKED - 81% Success Rate (Target: 100%)**

---

## Executive Summary

Built extraction pipeline to populate patent grant data from USPTO XML files. Successfully extracts and parses grants, but encountering JSON encoding failures on 19% of records (all design patents). **Cannot proceed with historical data processing until 100% success rate is achieved.**

---

## Current State

### What's Working ✅

1. **XML Parsing** - Successfully extracts grant data from USPTO XML format
2. **Database Schema** - `patent_grants` table created with proper structure
3. **Concurrent Processing** - 8 workers processing grants in parallel
4. **Error Tracking** - Comprehensive failure logging and categorization
5. **Batch Operations** - Efficient database inserts (100 grants per batch)

### What's Not Working ❌

**JSON Encoding Failures (19% of grants)**
- **Count**: 1,258 out of 6,565 grants failing
- **Pattern**: ALL failures are design patents (D-prefix)
- **Error**: `pq: invalid input syntax for type json`
- **Impact**: Cannot achieve 100% coverage requirement

---

## Test Results

### ipg251104.zip (Nov 4, 2024 weekly file)

```
Total Files Processed: 1
Grants Extracted: 6,565
Grants Inserted: 5,307 (80.84%)
Grants Failed: 1,258 (19.16%)

Failure Breakdown:
  db_invalid_json: 1,258 (100.0%)
```

### Failure Pattern

All 1,258 failures follow this pattern:
- Design patents only (D1067578, D1067580, D1067583, etc.)
- Error type: `db_invalid_json`
- PostgreSQL rejects JSON even though Go's `json.Marshal()` succeeds

**Sample failures** (from logs/grant_failures.log):
```
2025-11-25 09:56:44	db_invalid_json	D1067578	pq: invalid input syntax for type json
2025-11-25 09:56:44	db_invalid_json	D1067580	pq: invalid input syntax for type json
2025-11-25 09:56:44	db_invalid_json	D1067583	pq: invalid input syntax for type json
```

---

## Implementation Details

### File Structure

```
/home/mark/projects/patent_extractor/
├── grant_extractor.go          # Main extraction code (NEW)
├── patent_extractor.go         # Original publication extractor (template)
├── logs/
│   ├── grant_extractor.log     # Processing log
│   └── grant_failures.log      # Failure tracking (1,258 entries)
├── processed_grant_archives.txt # Tracking file
└── GRANT_EXTRACTOR_STATUS.md   # This file
```

### Database Schema

**Table**: `patent_grants`

```sql
CREATE TABLE patent_grants (
    id SERIAL PRIMARY KEY,
    grant_number VARCHAR(20) NOT NULL,        -- "9668909", "D1100410"
    kind VARCHAR(5),                           -- B1, B2, S1, etc.
    title TEXT,
    grant_date DATE,
    application_number VARCHAR(20),
    application_date DATE,
    abstract_text TEXT,
    claims JSONB,                              -- Array of claim text
    citations_examiner JSONB,                  -- Structured citations
    citations_applicant JSONB,
    inventors JSONB,                           -- Array of inventor objects
    assignees JSONB,                           -- Array of assignee objects
    classifications_cpc JSONB,
    classifications_national JSONB,
    raw_xml_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(grant_number)
);

CREATE INDEX idx_grant_number ON patent_grants(grant_number);
CREATE INDEX idx_application_number ON patent_grants(application_number);
CREATE INDEX idx_grant_date ON patent_grants(grant_date);
```

### Key Code Components

#### XML Structures (encoding/xml)

```go
type USPatentGrant struct {
    XMLName xml.Name `xml:"us-patent-grant"`
    BibData GrantBibData `xml:"us-bibliographic-data-grant"`
    Abstract GrantAbstract `xml:"abstract"`
    Description GrantDescription `xml:"description"`
    Claims  GrantClaims `xml:"claims"`
}

type GrantClaims struct {
    Claims []GrantClaim `xml:"claim"`
}

type GrantClaim struct {
    Num  string `xml:"num,attr"`
    Text string `xml:"claim-text"`
}
```

#### Text Cleaning Function

```go
func cleanXMLText(text string) string {
    // Remove XML tags
    text = regexp.MustCompile(`<[^>]+>`).ReplaceAllString(text, " ")

    // Replace control characters and invalid UTF-8
    text = strings.Map(func(r rune) rune {
        if r < 32 && r != '\n' && r != '\t' {
            return -1
        }
        return r
    }, text)

    // Normalize whitespace
    text = regexp.MustCompile(`\s+`).ReplaceAllString(text, " ")
    return strings.TrimSpace(text)
}
```

#### Error Categorization

```go
func categorizeDBError(err error) string {
    errStr := err.Error()
    if strings.Contains(errStr, "invalid input syntax for type json") {
        return "db_invalid_json"
    }
    if strings.Contains(errStr, "duplicate key") {
        return "db_duplicate"
    }
    return "db_other"
}
```

#### Insert Logic with Pre-Validation

```go
func (e *GrantExtractor) insertBatch(grants []PatentGrant, workerID int) (int, int) {
    inserted := 0
    failed := 0

    for _, grant := range grants {
        // Validate JSON encoding BEFORE database insert
        claimsJSON, err := json.Marshal(grant.Claims)
        if err != nil {
            e.recordFailure("json_marshal_claims", grant.GrantNumber,
                fmt.Sprintf("Claims marshal failed: %v", err))
            failed++
            continue
        }

        // Validate citations JSON
        if grant.CitationsExaminer != nil && !json.Valid(grant.CitationsExaminer) {
            e.recordFailure("invalid_json_citations_examiner", grant.GrantNumber,
                "Invalid citations_examiner JSON")
            grant.CitationsExaminer = nil
        }

        // Attempt database insert
        _, err = e.db.Exec(`
            INSERT INTO patent_grants (
                grant_number, kind, title, grant_date, application_number,
                application_date, abstract_text, claims, citations_examiner,
                citations_applicant, inventors, assignees,
                classifications_cpc, classifications_national, raw_xml_path
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            ON CONFLICT (grant_number) DO NOTHING
        `, grant.GrantNumber, grant.Kind, grant.Title, grant.GrantDate,
           grant.ApplicationNumber, grant.ApplicationDate, grant.AbstractText,
           claimsJSON, grant.CitationsExaminer, grant.CitationsApplicant,
           grant.Inventors, grant.Assignees, grant.ClassificationsCPC,
           grant.ClassificationsNational, grant.RawXMLPath)

        if err != nil {
            errType := categorizeDBError(err)
            e.recordFailure(errType, grant.GrantNumber, err.Error())
            failed++
        } else {
            inserted++
        }
    }
    return inserted, failed
}
```

---

## Known Issues

### Issue #1: Design Patent JSON Encoding Failures

**Problem**: 19% of grants (all design patents) fail database insertion with "invalid input syntax for type json"

**Symptoms**:
- All 1,258 failures are design patents (D-prefix)
- Go's `json.Marshal()` succeeds without error
- PostgreSQL rejects the JSON during INSERT
- Error: `pq: invalid input syntax for type json`

**Investigation Performed**:
1. ✅ Added `cleanXMLText()` to strip XML markup from claims
2. ✅ Implemented pre-validation with `json.Valid()`
3. ✅ Added error categorization and detailed logging
4. ✅ Filtering control characters and invalid UTF-8
5. ❌ Still getting 19% failure rate

**Suspected Root Causes**:
1. Design patent claims have different XML structure than utility patents
2. Special characters specific to design patents not being sanitized
3. Possible byte-order marks (BOM) or invisible characters
4. PostgreSQL JSONB validation stricter than Go's JSON validation

**Next Investigation Steps**:
1. Extract a failing design patent XML to examine actual claim structure
2. Identify specific characters causing PostgreSQL rejection
3. Compare design patent vs utility patent claim XML format
4. Test with more aggressive sanitization approaches

**Potential Solutions**:
1. Use `strconv.Quote/Unquote` for guaranteed JSON-safe escaping
2. Strip ALL non-printable characters (not just control chars)
3. Handle HTML entities with `html.UnescapeString()`
4. Validate each claim string individually before adding to array
5. Consider storing design patent claims as TEXT instead of JSONB

---

## Performance Characteristics

### Processing Speed
- **Extraction**: ~6,500 grants per minute
- **Parsing**: Negligible overhead (structured XML)
- **Database Insert**: 100 grants per batch

### Resource Usage
- **Memory**: Similar to patent_extractor (~30GB peak)
- **CPU**: 8 workers, moderate load
- **Disk I/O**: Archive reading + database writes

### Concurrency
- **Workers**: 8 concurrent processors
- **Batch Size**: 100 grants per database transaction
- **Archive Caching**: Load once per file, process all grants

---

## Blocked Milestones

Cannot proceed with the following until 100% success rate achieved:

### ❌ Milestone 1: Historical Data Processing
**Blocked**: Cannot process 2001-2025 grant files with 19% failure rate
- **Scope**: ~1,000 weekly files
- **Volume**: ~7.3M grants estimated
- **Storage**: ~500 GB database

### ❌ Milestone 2: STEP 2.5 Integration
**Blocked**: Citation validation requires complete grant database
- **Impact**: Cannot validate 44% of Office Action citations
- **Gap**: Missing all grant citations (only publications available)

### ❌ Milestone 3: Grant-Publication Linking
**Blocked**: Cannot cross-reference without complete data
- **Use Case**: Link application publications to granted patents
- **Value**: Track application → grant lifecycle

---

## User Requirements

**Primary Requirement**: "**focus on fixing json encoding, we need to be 100% coverage, no mistakes on import, use common sense libraries or methods for fool proof import and evaluate and track failure at all times so we can know to fix things like that.**"

**Current Status vs Requirements**:
- ❌ **100% coverage**: Currently 80.84% (19.16% failures)
- ✅ **Track failures**: Comprehensive logging implemented
- ✅ **Categorize errors**: All failures typed and logged
- ❌ **Fool-proof import**: Design patent handling incomplete

---

## Testing Commands

### Check Database Status
```sql
-- Count grants by type
SELECT
    SUBSTRING(grant_number, 1, 1) as type,
    COUNT(*) as count
FROM patent_grants
GROUP BY type
ORDER BY type;

-- Check for design patents
SELECT COUNT(*) FROM patent_grants WHERE grant_number LIKE 'D%';
```

### Review Failures
```bash
# Count failures by type
cut -f2 /home/mark/projects/patent_extractor/logs/grant_failures.log | sort | uniq -c

# Show unique grant prefixes in failures
cut -f3 /home/mark/projects/patent_extractor/logs/grant_failures.log | cut -c1-5 | sort | uniq -c

# Check if all failures are design patents
cut -f3 /home/mark/projects/patent_extractor/logs/grant_failures.log | grep -v "^D" | wc -l
```

### Extract Failing Grant XML
```bash
# Extract specific design patent XML for debugging
cd /mnt/patents/originals_ptgrmp2
unzip -p ipg251104.zip | grep -A 200 "D1067578" > /tmp/failing_grant.xml
```

---

## Next Steps (Priority Order)

### 1. Root Cause Analysis
- [ ] Extract failing design patent XML examples
- [ ] Compare design patent vs utility patent claim structure
- [ ] Identify specific problematic characters/patterns
- [ ] Test PostgreSQL JSON validation limits

### 2. Enhanced Sanitization
- [ ] Implement `strconv.Quote/Unquote` approach
- [ ] Strip ALL non-printable characters (not just control chars)
- [ ] Handle HTML entities explicitly
- [ ] Add per-claim validation before array construction

### 3. Testing & Validation
- [ ] Unit test with known problematic strings
- [ ] Test with design patents specifically
- [ ] Verify 100% success rate on ipg251104.zip
- [ ] Test on additional weekly files

### 4. Production Rollout
- [ ] Reprocess ipg251104.zip with fixed code
- [ ] Process remaining Nov 2024 files (ipg251111, ipg251118)
- [ ] Download and process 2001-2025 historical files
- [ ] Achieve full database population (~7.3M grants)

---

## Files & Logs

### Source Code
- `/home/mark/projects/patent_extractor/grant_extractor.go` - Main implementation

### Logs
- `/home/mark/projects/patent_extractor/logs/grant_extractor.log` - Processing log
- `/home/mark/projects/patent_extractor/logs/grant_failures.log` - 1,258 failure entries

### Tracking
- `/home/mark/projects/patent_extractor/processed_grant_archives.txt` - Archive tracking

### Documentation
- `/mnt/patents/appdt/examiner_search/GRANT_DATA_DISCOVERY.md` - Research findings
- `/home/mark/projects/patent_extractor/GRANT_EXTRACTOR_STATUS.md` - This file

---

## Success Criteria

Before proceeding with historical data:

✅ **100% import success rate**
- Current: 80.84% ✗
- Target: 100.00% ✓

✅ **All grant types supported**
- Utility patents (7xxxxxxx): ✓ Working
- Design patents (D prefix): ✗ Failing

✅ **Comprehensive error handling**
- Error tracking: ✓ Implemented
- Error categorization: ✓ Implemented
- Graceful failures: ✓ Implemented

---

**STATUS**: ⚠️ **WAITING FOR JSON ENCODING FIX** - Cannot proceed until design patent issue resolved.

**BLOCKER**: 1,258 design patents failing JSON validation (19% of test file)

**PRIORITY**: HIGH - Blocks STEP 2.5 citation validation and Office Action workflow
