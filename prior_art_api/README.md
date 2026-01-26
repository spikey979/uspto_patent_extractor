# Prior Art API

Go-based API service for retrieving USPTO patent documents as structured JSON.

## Quick Start

```bash
# Build and run
./run.sh

# Or manually
go build -o prior_art_api .
./prior_art_api
```

## API Endpoints

### GET /
Service info and available endpoints.

### GET /health
Health check endpoint.

### GET /api/patent/{pub_number}
Retrieve full patent document as JSON.

**Supported input formats:**
- `US20160148332A1` - Full format with country and kind code
- `20160148332` - Just the number

**Example:**
```bash
curl http://localhost:8095/api/patent/US20160148332A1 | jq .
```

## Response Format

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
      "name": "BLUE SUN TECHNOLOGIES, INC.",
      "location": "Malibu, CA (US)"
    },
    "inventors": [
      {"name": "Jeffrey M. Stibel", "location": "Malibu, CA (US)"}
    ],
    "classifications": {
      "ipc": ["G06Q 20/40"],
      "cpc": ["G06Q 20/401"]
    },
    "abstract": "Some embodiments provide...",
    "drawings": [
      {
        "num": 1,
        "id": "Fig-EMI-D00001",
        "file": "US20160148332A1-20160526-D00001.TIF",
        "path": "/mnt/patents/.../I20160526.tar:US20160148332A1-20160526/...D00001.TIF"
      }
    ],
    "description": [
      {"type": "heading", "text": "BACKGROUND"},
      {"type": "paragraph", "num": 1, "text": "..."}
    ],
    "claims": [
      {"num": 1, "text": "A method of identity protection..."}
    ],
    "source": {
      "archive": "I20160526.tar",
      "xml_path": "I20160526.tar/US20160148332A1-20160526/US20160148332A1-20160526.XML"
    }
  }
}
```

## Configuration

Environment variables:
- `DB_HOST` - PostgreSQL host (default: localhost)
- `DB_PORT` - PostgreSQL port (default: 5432)
- `DB_NAME` - Database name (default: companies_db)
- `DB_USER` - Database user (default: mark)
- `DB_PASSWORD` - Database password (default: mark123)
- `SERVER_PORT` - API server port (default: 8095)
- `ARCHIVE_BASE` - Path to patent archives (default: /mnt/patents/data/historical)

## How It Works

1. **Database Lookup**: Queries `patent_data_unified` table for `raw_xml_path`
2. **Archive Extraction**: Opens TAR file, finds ZIP, extracts XML and TIF references
3. **XML Parsing**: Parses USPTO XML schema for all patent sections
4. **JSON Response**: Returns structured document with image paths

## Dependencies

- Go 1.21+
- PostgreSQL with `patent_data_unified` table
- Access to `/mnt/patents/data/historical/` archives

## Files

```
prior_art_api/
├── main.go       # Main application
├── go.mod        # Go module
├── go.sum        # Dependencies
├── run.sh        # Run script
└── README.md     # This file
```
