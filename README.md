# Patent Extractor Projects

Two complementary systems for extracting USPTO patent data from XML archives.

---

## 1. Patent Extractor (Publications) ✅ COMPLETE

**Purpose**: Extract application numbers from patent publications
**Status**: 100% coverage achieved (8,138,427 patents)
**File**: `patent_extractor_backfill.go`

### Key Features
- Processes both nested ZIP (2001-2010) and direct XML (2011+) formats
- Parallel processing with 8 concurrent workers
- Handles JSONB fields for inventors/assignees
- Advanced archive format handling (split ZIPs, I-prefix, TAR directories)
- Processes ~5-10M patents/hour

### Achievement
Backfilled 778,709 missing application numbers (90.4% → 100% coverage)

---

## 2. Grant Extractor ⚠️ IN PROGRESS

**Purpose**: Extract patent grant data to enable citation validation
**Status**: 81% success rate (blocked on design patent issue)
**File**: `grant_extractor.go`

### Current Results
Test on ipg251104.zip (Nov 4, 2024):
- ✅ Extracted: 6,565 grants
- ✅ Inserted: 5,307 grants (80.84%)
- ❌ Failed: 1,258 grants (19.16% - all design patents)

### Blocker
**JSON encoding failures on design patents**: Must achieve 100% success before processing historical data.

### Why This Matters
- Current database: 8.22M publications, **0 grants**
- Office Action citations: 44% are grants, 45% are publications
- **Impact**: Can only validate 45% of citations until grant data populated

**Target**: ~7.3M grants (2001-2025 when complete)

---

## Directory Structure
```
patent_extractor/
├── patent_extractor.go          # Original publication extractor
├── patent_extractor_backfill.go # Application number backfill
├── grant_extractor.go           # Grant data extractor
├── patent_extractor_backfill    # Backfill binary
├── grant_extractor              # Grant extractor binary
├── go.mod                        # Go dependencies
├── go.sum                        # Dependency checksums
├── logs/
│   ├── patent_extractor.log     # Publication extraction
│   ├── grant_extractor.log      # Grant extraction
│   └── grant_failures.log       # Detailed failure tracking (1,258 entries)
├── scripts/
│   ├── auto_batch.sh            # Batch processing automation
│   ├── auto_batch_downloads.sh  # Downloads staging
│   └── monitor_newfiles.sh      # File monitoring
├── temp/                         # Temporary work directory
├── processed_archives.txt        # Publications tracking
├── processed_grant_archives.txt  # Grants tracking
├── README.md                     # This file
├── CLAUDE.md                     # Complete documentation
└── GRANT_EXTRACTOR_STATUS.md     # Detailed grant status
```

## Data Structure
```
/mnt/patents/data/
├── grants/
│   └── xml/YYYY/                # IPG files (e.g., ipg251104.zip)
├── applications/
│   └── office_actions/YYYY/     # BDR files (e.g., bdr_oa_bulkdata_weekly_2025-11-16.zip)
└── historical/
    └── YYYY/                    # I-prefix TAR files (e.g., I20241121.tar)

/mnt/patents/staging/
└── queue/                       # Processing queue for auto_batch.sh
```

## Quick Start

### Start Web Services (Overmind)
```bash
cd /home/mark/projects/patent_extractor

# Start all web services
./scripts/start.sh

# Check status
./scripts/status.sh

# Stop services
./scripts/stop.sh
```

### Check Publication Coverage
```bash
cd /home/mark/projects/patent_extractor
./patent_extractor_backfill
```

### Run Grant Extractor (Test Mode)
```bash
cd /home/mark/projects/patent_extractor
./grant_extractor
```

### Monitor Progress
```bash
tail -f logs/grant_extractor.log
tail -f logs/grant_failures.log

# Or use Overmind
overmind connect web
overmind connect search_claims
```

## Database

### Publications Table: patent_data_unified
- **Records**: 8.22M patent publications (2001-2025)
- **Coverage**: 100% have application numbers ✅
- **Fields**: pub_number, title, abstract, application_number, inventors, assignees, etc.

### Grants Table: patent_grants
- **Records**: 5,307 grants (test data only)
- **Target**: ~7.3M grants (2001-2025)
- **Coverage**: 81% (blocked on design patent issue) ⚠️
- **Fields**: grant_number, title, abstract, claims (JSONB), citations, inventors, etc.

## Current Priority

**Fix design patent JSON encoding issue** to achieve 100% grant import success rate.

User requirement: "**focus on fixing json encoding, we need to be 100% coverage, no mistakes on import**"

Once resolved:
1. Process historical grant files (2001-2025, ~1,000 weekly files)
2. Populate ~7.3M grants into database
3. Enable grant citation validation for Office Action workflow (STEP 2.5)
4. Fill the 44% citation validation gap

## Documentation

### Detailed Docs
- **CLAUDE.md** - Complete project documentation (both extractors)
- **OVERMIND.md** - Process management with Overmind (start/stop/monitor services)
- **GRANT_EXTRACTOR_STATUS.md** - Detailed grant extractor status and issues
- **GRANT_DATA_DISCOVERY.md** - Research findings (in /mnt/patents/appdt/examiner_search/)

---

Last Updated: November 25, 2025