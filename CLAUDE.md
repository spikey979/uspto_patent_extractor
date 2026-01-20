# Patent Extractor Projects

## Project Overview
System for extracting patent data from USPTO XML files:
1. **Patent Extractor** - Application number backfill (COMPLETE - 100% coverage)
2. **Grant Extractor** - Patent grant data extraction (IN PROGRESS)

---

## ⚠️ CRITICAL: Data Architecture Principle

### DO NOT store bulk data in PostgreSQL - store REFERENCES only!

**The Rule**: Database contains **metadata and file references**. Bulk data (citations, claims, full text, NPL) stays in XML files and is fetched **on-demand** via `raw_xml_path`.

**What TO store in database:**
- `grant_number`, `pub_number` (identifiers)
- `title`, `abstract_text` (searchable text)
- `grant_date`, `filing_date`, `pub_date` (dates)
- `application_number`, `kind`, `year` (metadata)
- `raw_xml_path` or `raw_xml_source` (file reference for on-demand retrieval)
- Simple JSONB for names only: `inventors`, `assignees` (e.g., `[{"name": "John Doe"}]`)

**What NOT to store in database:**
- ❌ `citations_examiner` JSONB arrays
- ❌ `citations_applicant` JSONB arrays
- ❌ `claims` JSONB arrays
- ❌ NPL (non-patent literature) citations
- ❌ Full description text (use truncated or omit)
- ❌ Any complex nested JSON structures

**Why this matters:**
1. **Avoids JSON encoding failures** - PostgreSQL JSONB is stricter than Go's json.Marshal
2. **Keeps database size manageable** - 8M+ patents × citations = explosion
3. **On-demand retrieval works** - Use `raw_xml_path` to fetch what you need when you need it
4. **100% import success** - Simple metadata never fails

**How to retrieve bulk data on-demand:**
```go
// Example: Get citations from raw XML
func getCitations(rawXMLPath string) ([]Citation, error) {
    // Parse path: "ipg250107.zip/ipg250107.xml"
    // Open archive, find patent by grant_number, extract citations
}
```

**Reference implementation**: See `patent_data_unified` table - stores `raw_xml_path` and simple metadata only.

---

## Database Configuration
- **Host**: localhost (100.76.27.122 external)
- **Port**: 5432 (PostgreSQL)
- **Database**: companies_db
- **User**: mark
- **Password**: mark123
- **Table**: patent_data_unified (8,138,427 patents)

## Status
- **Total Patents**: 8,138,427
- **With Application Numbers**: 8,138,427 (100%)
- **Missing**: 0
- **Backfilled**: 778,709 patents from initial 90.4% coverage

## Key Technical Solutions

### 1. Multi-Format Archive Handling

#### Standard ZIP Archives (2001-2004)
- Format: `20020725.ZIP` containing nested `US[number]-[date].ZIP` files
- Location: `/mnt/patents/data/historical/YYYY/`

#### Split Archives (2003)
- Format: `20030313A.ZIP`, `20030313B.ZIP`
- **Critical**: Load ALL variants (A, B) for each date - patents can be in any variant
- Code: Modified `processPatentBatch()` to load all available archives per date

#### I-Prefix Archives (2010)
- Format: `I20100107.ZIP` (note the "I" prefix)
- Code: `buildArchiveName()` checks for 2010 dates and prepends "I"

#### Extracted TAR Directories (Late 2010)
- Format: `xml_extracted/I20101021/US[patent]/tmp*_[patent]/[patent].XML`
- Code: `extractFromDirectory()` walks directory structure to find XML

### 2. Dual XML Schema Support

#### Old Format (2001-2004)
```xml
<domestic-filing-data>
    <application-number>
        <doc-number>09876543</doc-number>
    </application-number>
</domestic-filing-data>
```

#### New Format (2005+)
```xml
<application-reference>
    <doc-number>12345678</doc-number>
</application-reference>
```

**Code**: `extractAppNumber()` tries both patterns with regex

### 3. PG-PUB-2 Legacy Format (One-Off Anomaly)

**Discovery**: Patent US20020099721A1 (out of 8.1M patents) used legacy USPTO packaging

**Original USPTO Archive Structure**:
```
20020725.ZIP
  └─ 20020725/UTIL0099/US20020099721A1-20020725.ZIP
       └─ PG-PUB-2/Files/us20020099721072502/US20020099721A1-20020725/
            └─ US20020099721A1-20020725.XML
```

**Database Expected Path**:
```
US20020099721A1-20020725/US20020099721A1-20020725.XML
```

**Actual Extracted Location**:
```
/mnt/patents/data/historical/xml_extracted/20020725/tmpcbrirhwb_PG-PUB-2/Files/us20020099721072502/US20020099721A1-20020725/US20020099721A1-20020725.XML
```

**Three-Part Solution Implemented**:

1. **Filesystem Normalization** (Immediate fix)
   ```bash
   mkdir -p /mnt/patents/data/historical/xml_extracted/20020725/US20020099721A1-20020725/tmp_normalized
   cp [original-path] [normalized-path]
   ```

2. **Code Enhancement** (Future-proofing)
   - Added `recursiveSearchForXML()` function
   - Falls back to recursive directory walk if standard structure not found
   - Handles ANY non-standard directory structure automatically

3. **Documentation** (Knowledge preservation)
   - Documented in BACKFILL_STATUS.md
   - Documented in this CLAUDE.md
   - Added inline code comments

**Why This Happened**:
- USPTO used "PG-PUB-2" (Publication version 2) format in early 2002
- Out of 1,000 patents in same UTIL0099 batch, only this ONE had the structure
- Likely a re-submission or correction using older packaging format
- True one-off anomaly, not a pattern

**Investigation Performed**:
- Checked all 2002 archives: No other PG-PUB structures found
- Checked all extracted directories: Only 1 PG-PUB directory exists
- Verified: 999 other patents in same batch processed normally

## Main Scripts

### Backfill System
- **File**: `patent_extractor_backfill.go`
- **Purpose**: Extract application numbers for patents missing them
- **Features**:
  - Memory-optimized (handles millions of patents)
  - Concurrent processing (8 workers)
  - Batch updates (500 patents per batch)
  - Progress checkpoints every 10,000 patents
  - Archive caching with automatic cleanup

### Diagnostic Tool
- **File**: `patent_diagnostic_analyzer.go`
- **Purpose**: Analyze missing application numbers and identify patterns

## Key Code Functions

### `extractFromDirectory(pubDate, xmlFilename)`
Handles pre-extracted TAR directories:
1. Tries I-prefix path first (2010)
2. Falls back to non-prefixed path (2002)
3. Looks for expected patent directory structure
4. If not found, calls `recursiveSearchForXML()` (handles PG-PUB edge case)
5. Walks tmp* subdirectories to find XML file

### `recursiveSearchForXML(rootDir, targetFilename)`
**NEW** - Added to handle non-standard structures:
- Recursively walks entire directory tree
- Searches for exact filename match
- Returns extracted application number
- Used as fallback for PG-PUB-2 and any future anomalies

### `processPatentBatch(patents)`
Core processing logic:
1. Groups patents by archive date
2. Loads ALL archive variants (A, B, etc.) for each date
3. For each patent:
   - Tries extraction from all available archives
   - Falls back to xml_extracted directory if not found
4. Returns batch of updates for database

### `extractAppNumber(xmlData)`
XML parsing with dual schema support:
1. Tries new format regex: `<application-reference>...<doc-number>`
2. Falls back to old format: `<domestic-filing-data>...<doc-number>`
3. Returns application number or empty string

## Performance Characteristics

- **Processing Speed**: ~500 patents per batch
- **Memory Usage**: ~30GB peak (optimized with archive cleanup)
- **Concurrency**: 8 workers
- **Database Batch Size**: 500 patents per UPDATE
- **Archive Loading**: On-demand, with automatic cleanup
- **Typical Runtime**:
  - 16,237 patents (2003): 3 minutes
  - 17,781 patents (2010): ~10 minutes

## Common Issues and Solutions

### Issue: "No patents to process but coverage < 100%"
**Cause**: Duplicate entries, bad paths, or junk data
**Solution**: Manual SQL cleanup (see fix_remaining_*.sql files)

### Issue: "Archive not found"
**Cause**: Missing I-prefix for 2010 or missing A/B suffix for 2003
**Solution**: Code now handles both automatically

### Issue: "Patent directory not found in xml_extracted"
**Cause**: Non-standard structure (like PG-PUB-2)
**Solution**: Recursive search fallback now handles this

## File Locations

### Archives
- **Location**: `/mnt/patents/data/historical/YYYY/`
- **Format**: `I[date].tar` (e.g., I20241121.tar)
- **Organization**: Year-based subdirectories (2024/, 2025/, etc.)

### Extracted Files
- **Path**: `/mnt/patents/data/historical/xml_extracted/[date]/`
- **Structure**: `[date]/US[patent]-[date]/tmp*_US[patent]-[date]/[patent].XML`
- **Special**: I-prefix for 2010: `I[date]/...`

## Testing Commands

### Check Coverage
```sql
SELECT COUNT(*) as total,
       COUNT(application_number) as with_app_num,
       ROUND(100.0 * COUNT(application_number) / COUNT(*), 6) as coverage_pct
FROM patent_data_unified;
```

### Find Missing by Year
```sql
SELECT year, COUNT(*)
FROM patent_data_unified
WHERE application_number IS NULL OR application_number = ''
GROUP BY year ORDER BY year;
```

### Verify Specific Patent
```sql
SELECT pub_number, application_number, raw_xml_path, title
FROM patent_data_unified
WHERE pub_number = '20020099721';
```

## Implementation Notes

1. **Always load ALL archive variants** - Don't break after finding first match
2. **Implement fallback strategies** - Recursive search handles non-standard structures
3. **Investigate thoroughly** - Anomalies require root cause analysis
4. **Document edge cases** - Important for future maintenance

## Timeline

- **Starting Point**: 90.4% coverage (778,709 missing)
- **After 2003 A/B Fix**: 99.98% coverage
- **After 2010 I-prefix Fix**: 99.99% coverage
- **After 2010 extracted dirs**: 99.9999% coverage
- **After path corrections**: 99.99999% coverage
- **After PG-PUB-2 fix**: 100% coverage

Total backfilled: 778,709 patents

## Maintenance

For new patents added to the database:

1. Run backfill: `cd /home/mark/projects/patent_extractor && ./patent_extractor_backfill`
2. Check coverage using SQL commands documented above
3. Investigate failures using `patent_diagnostic_analyzer.go`
4. Recursive search fallback handles most edge cases automatically

Last Updated: November 25, 2025

---

# Grant Extractor - Patent Grant Data Extraction

## Status: IN PROGRESS

### Current State
Extracting USPTO patent grants from weekly XML files. Following the data architecture principle above - storing **metadata only**, not citations or claims.

### Files
- **Main Code**: `/home/mark/projects/patent_extractor/grant_extractor.go`
- **Data Source**: `/mnt/patents/data/grants/xml/YYYY/ipgYYMMDD.zip`

### Database Table: patent_grants (SIMPLIFIED)

```sql
CREATE TABLE patent_grants (
    id SERIAL PRIMARY KEY,
    grant_number VARCHAR(20) NOT NULL UNIQUE,  -- "12345678", "D1100410"
    kind VARCHAR(5),                            -- B1, B2, S1, etc.
    title TEXT,
    grant_date DATE,
    application_number VARCHAR(20),
    application_date DATE,
    abstract_text TEXT,
    year INTEGER,
    raw_xml_source VARCHAR(255),               -- "ipg250107.zip/ipg250107.xml"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Note**: NO citations, NO claims, NO complex JSONB - fetch on-demand from `raw_xml_source`.

### Data Sources
- **Location**: `/mnt/patents/data/grants/xml/YYYY/`
- **Format**: `ipgYYMMDD.zip` (weekly USPTO grant files)
- **2025 Files**: 48 IPG files available

### Why This Matters

From Office Action citation analysis:
- **Grant citations**: 44% of all citations
- **Publication citations**: 45% of all citations

We need grant data to validate citations in office actions.

---

### Data Acquisition

Patent bulk data files are downloaded using the **auto-file-download** system:
- **Location**: `/home/mark/projects/auto-file-download/`
- **Documentation**: See `CLAUDE.md` and `PLAN.md` in that directory

**Data Sources Being Downloaded**:
| Dataset | API ID | URL | Destination |
|---------|--------|-----|-------------|
| Patent Grants XML | `PTGRXML` | data.uspto.gov/bulkdata/datasets/PTGRXML | `/mnt/patents/data/grants/xml/YYYY/` |
| Patent Grants APS | `ptgraps` | data.uspto.gov/bulkdata/datasets/ptgraps | `/mnt/patents/data/grants/aps/YYYY/` |
| Application Data | `appdt` | data.uspto.gov/bulkdata/datasets/appdt | `/mnt/patents/data/applications/appdt/YYYY/` |

**Current Data Status** (run `./scripts/patent_data_status.sh`):
- Grants XML: 48 files (2025 only) - needs 2002-2024 historical
- Grants APS: 0 files - needs 1976-2001 data
- Historical: 50 files (2024)
- Office Actions: 46 files (2025)

Last Updated: December 1, 2025
