# Prior Art Document Reconstruction Guide

This guide explains how to reconstruct USPTO patent documents (prior art) from the bulk data downloaded by the auto-file-download system.

---

## Overview

The `appdt` dataset contains complete patent application publications that can serve as prior art. Each publication includes:
- Full XML with all bibliographic data, abstract, claims, and description
- TIF images of all drawings/figures

**Example**: Document `US20160148332A1` (Identity Protection by Stibel et al.)

---

## Data Location

### Directory Structure
```
/mnt/patents/data/historical/
├── 2001/
├── 2002/
│   ...
├── 2016/
│   ├── I20160107.tar
│   ├── I20160114.tar
│   │   ...
│   └── I20160526.tar    ← Contains US20160148332A1
└── 2025/
```

### File Naming Convention
- **TAR files**: `I{YYYYMMDD}.tar` - Weekly publication date
- **ZIP files**: `US{pub_number}{kind}-{date}.ZIP`
- **XML files**: `US{pub_number}{kind}-{date}.XML`
- **Images**: `US{pub_number}{kind}-{date}-D{NNNNN}.TIF`

### Kind Codes
| Code | Meaning |
|------|---------|
| A1 | Patent Application Publication |
| A2 | Patent Application Publication (2nd publication) |
| A9 | Corrected Patent Application Publication |
| B1 | Patent Grant (no prior publication) |
| B2 | Patent Grant (with prior publication) |

---

## Locating a Specific Document

### Step 1: Identify Publication Date

From the document number `US 2016/0148332 A1`:
- Publication date: May 26, 2016 (found on document or via USPTO search)
- TAR file: `I20160526.tar`

### Step 2: Find in TAR Archive

```bash
# List contents and search for document
tar -tvf /mnt/patents/data/historical/2016/I20160526.tar | grep "148332"

# Output:
# I20160526/UTIL0148/US20160148332A1-20160526.ZIP
```

### Step 3: Extract Document

```bash
# Extract specific file
tar -xvf /mnt/patents/data/historical/2016/I20160526.tar \
    "I20160526/UTIL0148/US20160148332A1-20160526.ZIP" \
    -C /tmp/

# Unzip contents
unzip /tmp/I20160526/UTIL0148/US20160148332A1-20160526.ZIP -d /tmp/patent/
```

### Extracted Contents
```
/tmp/patent/US20160148332A1-20160526/
├── US20160148332A1-20160526.XML        (112 KB - all data)
├── US20160148332A1-20160526-D00000.TIF (title page drawing)
├── US20160148332A1-20160526-D00001.TIF (Figure 1)
├── US20160148332A1-20160526-D00002.TIF (Figure 2)
│   ...
└── US20160148332A1-20160526-D00011.TIF (Figure 11)
```

---

## XML Structure

The XML file follows the `us-patent-application-v44-2014-04-03.dtd` schema.

### Key Elements

```xml
<?xml version="1.0" encoding="UTF-8"?>
<us-patent-application>

  <!-- Bibliographic Data -->
  <us-bibliographic-data-application>

    <!-- Publication Info -->
    <publication-reference>
      <document-id>
        <country>US</country>
        <doc-number>20160148332</doc-number>
        <kind>A1</kind>
        <date>20160526</date>
      </document-id>
    </publication-reference>

    <!-- Application Info -->
    <application-reference appl-type="utility">
      <document-id>
        <country>US</country>
        <doc-number>14947996</doc-number>
        <date>20151120</date>
      </document-id>
    </application-reference>

    <!-- Classifications -->
    <classifications-ipcr>...</classifications-ipcr>
    <classifications-cpc>...</classifications-cpc>

    <!-- Title -->
    <invention-title>Identity Protection</invention-title>

    <!-- Related Applications (Provisional, Continuations, etc.) -->
    <us-related-documents>
      <us-provisional-application>
        <document-id>
          <doc-number>62082377</doc-number>
          <date>20141120</date>
        </document-id>
      </us-provisional-application>
    </us-related-documents>

    <!-- Applicants & Inventors -->
    <us-parties>
      <us-applicants>...</us-applicants>
      <inventors>...</inventors>
    </us-parties>

  </us-bibliographic-data-application>

  <!-- Abstract -->
  <abstract>
    <p>Some embodiments provide holistic and comprehensive
       identity protection solutions...</p>
  </abstract>

  <!-- Drawings (references to TIF files) -->
  <drawings>
    <figure id="Fig-EMI-D00001" num="00001">
      <img file="US20160148332A1-20160526-D00001.TIF"
           img-format="tif"
           he="254.17mm" wi="180.68mm"/>
    </figure>
    ...
  </drawings>

  <!-- Full Description -->
  <description>
    <heading>CROSS-REFERENCE TO RELATED APPLICATIONS</heading>
    <p>...</p>
    <heading>BACKGROUND</heading>
    <p>...</p>
    <heading>DETAILED DESCRIPTION</heading>
    <p>...</p>
  </description>

  <!-- Claims -->
  <claims>
    <claim id="CLM-00001" num="00001">
      <claim-text>
        <b>1</b>. A method of identity protection, the method comprising:
        <claim-text>providing an identity protection front-end...</claim-text>
      </claim-text>
    </claim>
    ...
  </claims>

</us-patent-application>
```

---

## Reconstruction Methods

### Method 1: XML to HTML (Simple)

Convert XML to readable HTML using XSLT transformation.

```python
from lxml import etree

# Load XML
xml_doc = etree.parse('US20160148332A1-20160526.XML')

# Create simple HTML output
def xml_to_html(xml_path, output_path):
    tree = etree.parse(xml_path)
    root = tree.getroot()

    # Extract key fields
    title = root.find('.//invention-title').text
    abstract = root.find('.//abstract/p').text

    # Build HTML
    html = f"""
    <html>
    <head><title>{title}</title></head>
    <body>
        <h1>{title}</h1>
        <h2>Abstract</h2>
        <p>{abstract}</p>
        <!-- Add more sections -->
    </body>
    </html>
    """

    with open(output_path, 'w') as f:
        f.write(html)
```

### Method 2: XML + TIF to PDF (Full Reconstruction)

For complete PDF reconstruction matching USPTO format:

```python
from lxml import etree
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

def reconstruct_patent_pdf(xml_path, images_dir, output_pdf):
    # Parse XML
    tree = etree.parse(xml_path)
    root = tree.getroot()

    # Extract metadata
    pub_number = root.find('.//publication-reference//doc-number').text
    kind = root.find('.//publication-reference//kind').text
    pub_date = root.find('.//publication-reference//date').text
    title = root.find('.//invention-title').text
    abstract = root.find('.//abstract/p').text

    # Extract inventors
    inventors = []
    for inv in root.findall('.//inventor'):
        last = inv.find('.//last-name').text
        first = inv.find('.//first-name').text
        inventors.append(f"{first} {last}")

    # Extract claims
    claims = []
    for claim in root.findall('.//claim'):
        claim_text = etree.tostring(claim, method='text', encoding='unicode')
        claims.append(claim_text.strip())

    # Create PDF
    c = canvas.Canvas(output_pdf, pagesize=letter)
    width, height = letter

    # Title page
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1*inch, height - 1*inch, f"US {pub_number} {kind}")
    c.setFont("Helvetica", 12)
    c.drawString(1*inch, height - 1.5*inch, title)
    c.drawString(1*inch, height - 2*inch, f"Inventors: {', '.join(inventors)}")

    # Abstract
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1*inch, height - 3*inch, "ABSTRACT")
    c.setFont("Helvetica", 10)
    # Text wrapping needed here...

    # Add drawings
    for img_file in sorted(os.listdir(images_dir)):
        if img_file.endswith('.TIF'):
            c.showPage()
            img_path = os.path.join(images_dir, img_file)
            # Convert TIF to format reportlab can use
            img = Image.open(img_path)
            img_rgb = img.convert('RGB')
            temp_jpg = '/tmp/temp_drawing.jpg'
            img_rgb.save(temp_jpg)
            c.drawImage(temp_jpg, 0.5*inch, 0.5*inch,
                       width=7*inch, height=9*inch,
                       preserveAspectRatio=True)

    c.save()
```

### Method 3: Using Existing Tools

The `patent_extractor` project already has XML parsing logic:

```go
// From /home/mark/projects/patent_extractor/patent_extractor.go
// Adapt existing parsers for reconstruction
```

---

## Batch Processing

### Find All Patents by Applicant

```bash
# Search all 2016 archives for "Blue Sun Technologies"
for tar in /mnt/patents/data/historical/2016/I*.tar; do
    tar -xOf "$tar" --wildcards "*.XML" 2>/dev/null | \
    grep -l "Blue Sun Technologies" | head -5
done
```

### Extract All Patents from a Date Range

```bash
#!/bin/bash
# extract_patents.sh - Extract patents from date range

START_DATE="20160501"
END_DATE="20160531"
OUTPUT_DIR="/tmp/patents_may_2016"

mkdir -p "$OUTPUT_DIR"

for tar in /mnt/patents/data/historical/2016/I*.tar; do
    date=$(basename "$tar" | sed 's/I\(.*\)\.tar/\1/')
    if [[ "$date" >= "$START_DATE" && "$date" <= "$END_DATE" ]]; then
        echo "Processing $tar..."
        tar -xf "$tar" -C "$OUTPUT_DIR"
    fi
done
```

---

## Database Integration

For searchable prior art, load key fields into PostgreSQL:

```sql
CREATE TABLE prior_art_documents (
    id SERIAL PRIMARY KEY,
    publication_number VARCHAR(20) UNIQUE,
    kind_code VARCHAR(5),
    publication_date DATE,
    application_number VARCHAR(20),
    filing_date DATE,
    title TEXT,
    abstract TEXT,
    applicant_name TEXT,
    inventors TEXT[],
    ipc_classifications TEXT[],
    cpc_classifications TEXT[],
    source_file TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for full-text search
CREATE INDEX idx_prior_art_abstract_fts
ON prior_art_documents
USING GIN (to_tsvector('english', abstract));

CREATE INDEX idx_prior_art_title_fts
ON prior_art_documents
USING GIN (to_tsvector('english', title));
```

---

## Quick Reference

### Locate Document by Publication Number

```bash
# Format: US YYYY NNNNNNN KIND
# Example: US 2016 0148332 A1

PUB_NUM="20160148332"
YEAR="${PUB_NUM:0:4}"  # 2016

# Search all TAR files for that year
for tar in /mnt/patents/data/historical/$YEAR/I*.tar; do
    if tar -tvf "$tar" 2>/dev/null | grep -q "$PUB_NUM"; then
        echo "Found in: $tar"
        tar -tvf "$tar" | grep "$PUB_NUM"
        break
    fi
done
```

### Convert TIF to PNG (for web display)

```bash
# Single file
convert US20160148332A1-20160526-D00001.TIF output.png

# Batch convert
for tif in *.TIF; do
    convert "$tif" "${tif%.TIF}.png"
done
```

---

## Dependencies

For full reconstruction:

```bash
# Python packages
pip install lxml pillow reportlab

# System tools
sudo apt install imagemagick  # for TIF conversion
```

---

## Related Files

- **Data source**: `/mnt/patents/data/historical/{YYYY}/`
- **Patent extractor**: `/home/mark/projects/patent_extractor/`
- **Download system**: `/home/mark/projects/auto-file-download/`
- **Patent search**: `/home/mark/projects/patent_extractor/patent_search/`

---

Last Updated: January 20, 2026
