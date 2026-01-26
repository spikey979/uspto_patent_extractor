# Prior Art Document API - Analysis Report

**Date**: January 26, 2026
**Project**: USPTO Patent Extractor
**Request**: API service for reconstructing prior art documents as text

---

## 1. Requirements Summary

| Requirement | Description |
|-------------|-------------|
| **Input** | Publication number (e.g., `US20160148332A1`) |
| **Output** | Full document as TEXT (not PDF) |
| **Images** | Return image paths/names instead of actual images |
| **Integration** | Consider existing API at port 8093 |

---

## 2. Existing API Analysis (Port 8093)

### Current System: Patent Search AI
- **Location**: `/home/mark/projects/uspto_patent_extractor/patent_search/patent_search_ai_fixed.py`
- **Framework**: Flask (Python)
- **Purpose**: Patent SEARCH with AI relevance scoring
- **Dependencies**: Ollama LLM (gpt-oss:20b), PostgreSQL

### Current API Endpoints
```
POST /api/professional-search  → Search patents by description
GET  /api/search-progress/{id} → Check search progress
GET  /                         → Web UI
```

### Architecture
```
User Query → Keyword Extraction → DB Search → AI Scoring → Results
                                     ↓
                              Ollama (20B model)
```

---

## 3. Comparison: Extend Existing vs New Service

### Option A: Extend Existing API (Port 8093)

| Pros | Cons |
|------|------|
| Single codebase | Mixing concerns (search vs reconstruction) |
| Shared DB config | Python ecosystem (slower for archive I/O) |
| Already running | Adds complexity to existing service |
| Quick to implement | Resource contention with AI scoring |

**Effort**: ~2 hours

### Option B: New Dedicated Service (Recommended)

| Pros | Cons |
|------|------|
| Single responsibility | Another service to maintain |
| Can use Go (faster I/O) | Separate port/deployment |
| No AI dependencies | Initial setup time |
| Independent scaling | |
| Matches patent_extractor patterns | |

**Effort**: ~4-6 hours

### Recommendation: **Option B - New Service**

**Reasons**:
1. **Separation of concerns**: Search ≠ Document retrieval
2. **Performance**: Archive extraction is I/O intensive, Go excels here
3. **Consistency**: Matches existing Go codebase patterns (`patent_extractor.go`)
4. **Independence**: No risk of impacting AI scoring workloads
5. **Future-proof**: Easier to scale independently

---

## 4. Python vs Go Analysis

### Current Python Implementation
```python
# prior_art_reconstructor.py
- lxml for XML parsing
- tarfile, zipfile for archive handling
- psycopg2 for PostgreSQL
- reportlab/PIL for PDF (not needed for text)
```

### Go Implementation Benefits

| Aspect | Python | Go |
|--------|--------|-----|
| Archive I/O | Slower | **Native, fast** |
| Concurrency | GIL limitations | **Goroutines** |
| Deployment | venv + deps | **Single binary** |
| Memory | Higher | **Lower** |
| Existing code | New | **Matches project** |
| Build | Interpreted | **Compiled, checked** |

### Go Libraries Available
```go
import (
    "archive/tar"      // TAR extraction (stdlib)
    "archive/zip"      // ZIP extraction (stdlib)
    "encoding/xml"     // XML parsing (stdlib)
    "database/sql"     // PostgreSQL (with lib/pq)
    "net/http"         // HTTP server (stdlib)
    "encoding/json"    // JSON response (stdlib)
)
```

### Recommendation: **Go**

All required functionality is available in Go's standard library. The existing `patent_extractor.go` already demonstrates:
- TAR/ZIP archive handling
- XML parsing
- PostgreSQL integration
- Concurrent processing

---

## 5. Proposed Architecture

### New Service: `prior-art-api`

```
┌─────────────────────────────────────────────────────────┐
│                    prior-art-api                        │
│                    (Port 8094)                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   GET /api/patent/{pub_number}                         │
│        │                                                │
│        ▼                                                │
│   ┌─────────────┐    ┌──────────────────┐              │
│   │  DB Lookup  │───▶│  patent_data_    │              │
│   │             │    │  unified         │              │
│   └─────────────┘    └──────────────────┘              │
│        │                                                │
│        ▼ raw_xml_path                                   │
│   ┌─────────────┐    ┌──────────────────┐              │
│   │  Archive    │───▶│  /mnt/patents/   │              │
│   │  Extractor  │    │  data/historical │              │
│   └─────────────┘    └──────────────────┘              │
│        │                                                │
│        ▼ XML + TIF paths                               │
│   ┌─────────────┐                                       │
│   │  Document   │                                       │
│   │  Builder    │                                       │
│   └─────────────┘                                       │
│        │                                                │
│        ▼ JSON Response                                  │
│   ┌─────────────────────────────────────────────────┐  │
│   │ {                                               │  │
│   │   "pub_number": "20160148332",                  │  │
│   │   "title": "Identity Protection",              │  │
│   │   "metadata": {...},                           │  │
│   │   "abstract": "...",                           │  │
│   │   "drawings": [                                │  │
│   │     {"num": 1, "path": "/mnt/.../D00001.TIF"} │  │
│   │   ],                                           │  │
│   │   "description": [...],                        │  │
│   │   "claims": [...]                              │  │
│   │ }                                               │  │
│   └─────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 6. Proposed API Response Format

### Endpoint
```
GET /api/patent/{pub_number}

Examples:
  GET /api/patent/US20160148332A1
  GET /api/patent/20160148332
```

### Response Structure
```json
{
  "success": true,
  "patent": {
    "pub_number": "20160148332",
    "kind": "A1",
    "title": "Identity Protection",

    "publication": {
      "date": "2016-05-26",
      "date_formatted": "05/26/2016"
    },

    "application": {
      "number": "14947996",
      "date": "2015-11-20",
      "date_formatted": "11/20/2015"
    },

    "applicant": {
      "name": "Blue Sun Technologies, Inc.",
      "location": "Naples, FL (US)"
    },

    "inventors": [
      {
        "name": "Jeffrey M. Stibel",
        "location": "Weston, MA (US)"
      }
    ],

    "classifications": {
      "ipc": ["G06Q 20/40"],
      "cpc": ["G06Q 20/401", "G06F 21/31"]
    },

    "related_applications": [
      {
        "type": "provisional",
        "number": "62082377",
        "date": "2014-11-20"
      }
    ],

    "abstract": "Some embodiments provide holistic and comprehensive identity protection solutions...",

    "drawings": [
      {
        "num": 0,
        "id": "D00000",
        "path": "/mnt/patents/data/historical/2016/I20160526.tar:US20160148332A1-20160526/US20160148332A1-20160526-D00000.TIF"
      },
      {
        "num": 1,
        "id": "D00001",
        "path": "/mnt/patents/data/historical/2016/I20160526.tar:US20160148332A1-20160526/US20160148332A1-20160526-D00001.TIF"
      }
    ],

    "description": [
      {
        "type": "heading",
        "text": "CROSS-REFERENCE TO RELATED APPLICATIONS"
      },
      {
        "type": "paragraph",
        "num": 1,
        "text": "This application claims the benefit of..."
      },
      {
        "type": "heading",
        "text": "BACKGROUND"
      },
      {
        "type": "paragraph",
        "num": 2,
        "text": "Identity theft is a growing problem..."
      }
    ],

    "claims": [
      {
        "num": 1,
        "type": "independent",
        "text": "A method of identity protection, the method comprising..."
      },
      {
        "num": 2,
        "type": "dependent",
        "depends_on": 1,
        "text": "The method of claim 1, wherein..."
      }
    ],

    "source": {
      "archive": "I20160526.tar",
      "xml_path": "US20160148332A1-20160526/US20160148332A1-20160526.XML"
    }
  }
}
```

### Error Response
```json
{
  "success": false,
  "error": "Patent not found: US99999999A1"
}
```

---

## 7. Implementation Plan

### Phase 1: Core Go Service (~3 hours)
1. Create `prior_art_api.go`
2. Implement DB lookup (reuse patterns from `patent_extractor.go`)
3. Implement archive extraction
4. Implement XML parsing
5. Build JSON response

### Phase 2: HTTP API (~1 hour)
1. Setup HTTP server (net/http)
2. Implement `/api/patent/{pub_number}` endpoint
3. Add error handling
4. Add request logging

### Phase 3: Testing & Deployment (~1 hour)
1. Test with sample patents
2. Create systemd service file
3. Add to CLAUDE.md documentation

### File Structure
```
/home/mark/projects/uspto_patent_extractor/
├── prior_art_api.go          # New API service
├── prior_art_reconstructor.py # Existing Python (keep for reference)
├── patent_extractor.go        # Existing extractor
└── ...
```

---

## 8. Port Allocation

| Service | Port | Status |
|---------|------|--------|
| Patent Search AI | 8093 | Running |
| **Prior Art API** | **8094** | **Proposed** |
| Bookmark Pipeline | 8095 | Planned |

---

## 9. Summary & Recommendation

| Decision | Recommendation |
|----------|----------------|
| Extend existing vs New service | **New service** (separation of concerns) |
| Python vs Go | **Go** (performance, consistency) |
| Port | **8094** |
| Response format | **JSON** with structured sections |
| Image handling | **Return paths** (archive:path format) |

### Next Steps
1. ✅ Report created
2. ⏳ Implement `prior_art_api.go`
3. ⏳ Test with sample patents
4. ⏳ Deploy and document

---

*Report generated: January 26, 2026*
