# Grant Extractor Updates: NPL Citations + Raw XML Path

**Date**: November 27, 2025
**Status**: IMPLEMENTED - Ready for Migration + Testing

## Summary

Two critical improvements to grant_extractor.go:

1. **NPL Citations Support**: Added extraction and storage of non-patent literature citations
2. **Raw XML Path Format**: Updated to match patent_extractor.go pattern (includes XML filename)

## 1. NPL (Non-Patent Literature) Citations

### Why NPL Citations Matter

NPL citations are referenced by USPTO examiners in office actions, including Section 101 rejections. Examples include:
- Scientific papers
- Technical publications
- Web URLs (product pages, technical documentation)
- Foreign patent registrations
- Industry standards

### What Changed

**XML Structures Added** (grant_extractor.go:94-97):
```go
type GrantNPLCit struct {
    Num      string `xml:"num,attr"`
    Othercit string `xml:"othercit"`
}
```

**PatentGrant Struct Updated** (grant_extractor.go:127-128):
```go
NPLCitationsExaminer  json.RawMessage `json:"npl_citations_examiner"`
NPLCitationsApplicant json.RawMessage `json:"npl_citations_applicant"`
```

**Citation Extraction Logic** (grant_extractor.go:561-621):
- Separates patent citations (patcit) from NPL citations (nplcit)
- Patent citations: DocNumber-based identification
- NPL citations: Othercit text extraction
- Both categorized by examiner/applicant

**Database Columns** (migration file):
- `npl_citations_examiner` JSONB - Array of citation text strings
- `npl_citations_applicant` JSONB - Array of citation text strings

### Example NPL Citation

**XML**:
```xml
<nplcit num="00028">
<othercit>"GAW-566W Pants"; goldwin.co.jp; retrieved Jul. 28, 2008;
URL: <http://www.goldwin.co.jp/gw/training/warm-ups/566.html>.</othercit>
</nplcit>
<category>cited by applicant</category>
```

**Stored As**:
```json
{
  "npl_citations_applicant": [
    "\"GAW-566W Pants\"; goldwin.co.jp; retrieved Jul. 28, 2008; URL: <http://www.goldwin.co.jp/gw/training/warm-ups/566.html>."
  ]
}
```

## 2. Raw XML Path Format Update

### Why This Change

To match patent_extractor.go pattern for consistent on-demand XML retrieval across all patent types.

### What Changed

**Before**: `"ipg250415.zip"`
**After**: `"ipg250415.zip/ipg250415.xml"`

**Code Changes**:

grant_extractor.go:436-437:
```go
// Construct full XML path: "ipg250415.zip/ipg250415.xml"
xmlPath := archiveName + "/" + xmlFile.Name
```

grant_extractor.go:516:
```go
RawXMLPath:  archivePath, // Full path: "ipg251104.zip/ipg251104.xml"
```

**Database Evidence** (patent_data_unified already uses this pattern):
```
I20051020.ZIP/US20050230178A1-20051020/US20050230178A1-20051020.XML
I20121108.tar/US20120281410A1-20121108/US20120281410A1-20121108.XML
```

## Migration Steps

### 1. Run Database Migration

```bash
cd /home/mark/projects/patent_extractor
sudo -u postgres psql -h localhost -d companies_db -f add_npl_citations_to_patent_grants.sql
```

Or execute manually:
```sql
ALTER TABLE patent_grants
ADD COLUMN IF NOT EXISTS npl_citations_examiner JSONB,
ADD COLUMN IF NOT EXISTS npl_citations_applicant JSONB;
```

### 2. Verify Migration

```bash
PGPASSWORD=mark123 psql -h localhost -U mark -d companies_db -c "\d patent_grants"
```

Should show:
```
 npl_citations_examiner  | jsonb           |           |          |
 npl_citations_applicant | jsonb           |           |          |
```

### 3. Test with Single File

```bash
cd /home/mark/projects/patent_extractor
rm -f processed_grant_archives.txt
./grant_extractor -test 2>&1 | tee /tmp/grant_npl_test.log
```

### 4. Verify NPL Citations Extracted

```sql
-- Check for NPL citations
SELECT
    grant_number,
    title,
    jsonb_array_length(npl_citations_examiner) as examiner_npl_count,
    jsonb_array_length(npl_citations_applicant) as applicant_npl_count,
    raw_xml_source
FROM patent_grants
WHERE npl_citations_examiner IS NOT NULL
   OR npl_citations_applicant IS NOT NULL
LIMIT 5;

-- Example NPL citation content
SELECT
    grant_number,
    npl_citations_examiner->0 as first_examiner_npl
FROM patent_grants
WHERE npl_citations_examiner IS NOT NULL
LIMIT 1;
```

### 5. Verify Raw XML Path Format

```sql
SELECT grant_number, raw_xml_source
FROM patent_grants
WHERE grant_date >= '2025-04-01'
LIMIT 5;
```

Should show: `ipg250415.zip/ipg250415.xml` format

## Files Modified

1. **grant_extractor.go** (grant_extractor.go:1-800+)
   - Added GrantNPLCit struct
   - Updated PatentGrant struct with NPL fields
   - Separated patent/NPL citation extraction
   - Updated RawXMLPath construction
   - Updated INSERT statement with NPL columns

2. **add_npl_citations_to_patent_grants.sql** (NEW)
   - Database migration to add NPL citation columns
   - Includes verification queries

## Testing Checklist

- [ ] Migration SQL executed successfully
- [ ] Columns visible in `\d patent_grants`
- [ ] Test run achieves 100% success rate
- [ ] NPL citations extracted (check with SQL query)
- [ ] Raw XML paths include XML filename
- [ ] No regressions in patent citation extraction

## Success Criteria

1. **100% Success Rate**: All grants imported without failures
2. **NPL Citations Captured**: Non-zero NPL citations for patents that have them
3. **Path Format Correct**: All new grants use "archive.zip/file.xml" format
4. **Backward Compatible**: Existing grants unaffected

## Next Steps

After successful testing:
1. Clear processed_grant_archives.txt
2. Run full grant extraction on all archives
3. Monitor logs for 100% success rate
4. Verify NPL citation counts in database

---

**Files**:
- `/home/mark/projects/patent_extractor/grant_extractor.go`
- `/home/mark/projects/patent_extractor/add_npl_citations_to_patent_grants.sql`
- `/home/mark/projects/patent_extractor/grant_extractor` (compiled binary)
