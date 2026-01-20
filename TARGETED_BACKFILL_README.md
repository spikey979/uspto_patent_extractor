# Targeted Backfill for Missing Application Numbers

## Problem Summary

The original backfill script processed **all 3,590 archives** but only extracted application numbers for patents using the 2005+ XML schema. This left **778,709 patents** (9.6%) from years 2001-2004 without application numbers.

### Root Cause
- **2001-2004 patents** use `<domestic-filing-data><application-number>` XML structure
- **2005+ patents** use `<application-reference>` XML structure
- Original regex only matched the newer format

## Optimization Strategy

Instead of reprocessing ALL archives (expensive), the new targeted backfill:

### 1. **Database-Driven Approach**
```sql
SELECT pub_number, raw_xml_path
FROM patent_data_unified
WHERE (application_number IS NULL OR application_number = '')
  AND year IN (2001, 2002, 2003, 2004, 2010)
```
- Only loads **778,709 patents** that need fixing
- Reduces I/O by **90%+** compared to full scan

### 2. **Smart Archive Lookup**
- Extracts publication date from `raw_xml_path`: `US20030058959A1-20030327` → `20030327`
- Builds archive filename: `20030327.ZIP`
- Checks multiple locations:
  - `/mnt/patents/originals/20030327.ZIP`
  - `/mnt/patents/originals/NewFiles/20030327.ZIP`

### 3. **Archive Caching**
- Caches loaded archives in memory
- Multiple patents from same archive reuse cached data
- Eliminates redundant disk reads

### 4. **Batched Processing**
- Groups patents by archive for efficiency
- Batch size: 2000 patents per worker
- 16 parallel workers

### 5. **Dual-Format XML Parser**
```go
// Try new format first (2005+)
<application-reference>
  <document-id>
    <doc-number>12/345,678</doc-number>
  </document-id>
</application-reference>

// Fall back to old format (2001-2004)
<domestic-filing-data>
  <application-number>
    <doc-number>09964200</doc-number>
  </application-number>
</domestic-filing-data>
```

## Performance Comparison

| Metric | Original Backfill | Targeted Backfill |
|--------|------------------|-------------------|
| Archives Scanned | ~3,590 | 0 (DB-driven) |
| Files Processed | ~8.1M patents | 778K patents |
| Efficiency | 100% | ~9.5% of work |
| Speed Estimate | Hours | Minutes |

## Usage

### Run Targeted Backfill
```bash
cd /home/mark/projects/patent_extractor
./run_targeted_backfill.sh
```

### Monitor Progress
```bash
# Check how many still missing
psql -h localhost -U postgres -d companies_db -c \
  "SELECT COUNT(*) FROM patent_data_unified \
   WHERE application_number IS NULL OR application_number = '';"
```

### Verify Results
```bash
# Check coverage by year
psql -h localhost -U postgres -d companies_db -c \
  "SELECT year,
          COUNT(*) as total,
          COUNT(application_number) as with_app_num,
          ROUND(100.0 * COUNT(application_number) / COUNT(*), 2) as pct
   FROM patent_data_unified
   WHERE year IN (2001, 2002, 2003, 2004, 2010)
   GROUP BY year
   ORDER BY year;"
```

## Technical Details

### File Structure (2001-2004)
```
20030327.ZIP/
├── 20030327/
│   ├── UTIL0056/
│   │   └── US20030056271A1-20030327.ZIP
│   │       └── US20030056271A1-20030327/
│   │           └── US20030056271A1-20030327.XML  ← Extract from here
│   └── UTIL0058/
│       └── US20030058959A1-20030327.ZIP
│           └── US20030058959A1-20030327/
│               └── US20030058959A1-20030327.XML
```

Database stores: `US20030058959A1-20030327/US20030058959A1-20030327.XML`
Script finds: `20030327.ZIP` → nested ZIP → XML file

### Environment Variables
- `DB_HOST`: localhost (default)
- `DB_PORT`: 5432 (default)
- `DB_USER`: postgres (default)
- `DB_PASSWORD`: qwklmn711
- `FILES_ROOT`: /mnt/patents/originals
- `WORKERS`: 16 (default)
- `BATCH_SIZE`: 2000 (default)

## Expected Results

After completion, you should see:
- **~778K patents updated** with application numbers
- Coverage for 2001-2004 should jump from **0%** to **~95%+**
- Overall coverage should increase from **90.4%** to **~99%+**

Some patents may still be missing application numbers if:
- Archive file is corrupted/missing
- XML doesn't contain the field (rare)
- Format is non-standard (edge cases)

## Files

| File | Purpose |
|------|---------|
| `patent_extractor_targeted_backfill.go` | Optimized Go program |
| `run_targeted_backfill.sh` | Execution script |
| `patent_extractor_backfill.go` | Original (processes all archives) |
| `run_backfill.sh` | Original execution script |

## Key Improvements

1. ✅ **90%+ fewer files processed** - Only targets missing data
2. ✅ **Database-driven workflow** - No filesystem scanning
3. ✅ **Archive caching** - Eliminates redundant reads
4. ✅ **Dual-format XML parser** - Handles both old and new schemas
5. ✅ **Batched updates** - Efficient database transactions
6. ✅ **Progress logging** - Real-time status updates

## Notes

- This script is **idempotent** - safe to run multiple times
- Archive cache grows with unique archives (cleared on completion)
- Some archives may be in `NewFiles/` subdirectory
- Process can be interrupted and resumed safely
