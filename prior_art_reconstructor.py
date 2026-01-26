#!/usr/bin/env python3
"""
Prior Art Document Reconstructor
Reconstructs USPTO patent documents from bulk XML and TIF files.

Supports two modes:
1. Direct XML path: python prior_art_reconstructor.py /path/to/file.XML
2. Publication number lookup: python prior_art_reconstructor.py US20160148332A1
"""

import os
import sys
import re
import tarfile
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Tuple
from lxml import etree
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak, Table, TableStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
from io import BytesIO

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'companies_db',
    'user': 'mark',
    'password': 'mark123'
}

# Base path for patent archives
PATENT_ARCHIVE_BASE = '/mnt/patents/data/historical'


class PatentLookup:
    """Handles database lookup and file extraction for patents."""

    def __init__(self):
        self.conn = None

    def connect(self):
        """Connect to PostgreSQL database."""
        try:
            import psycopg2
            self.conn = psycopg2.connect(**DB_CONFIG)
            return True
        except ImportError:
            print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
            return False
        except Exception as e:
            print(f"Database connection error: {e}")
            return False

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def normalize_pub_number(self, pub_number: str) -> str:
        """Normalize publication number to database format (digits only)."""
        # Remove 'US' prefix if present
        pub_number = pub_number.upper().strip()
        if pub_number.startswith('US'):
            pub_number = pub_number[2:]

        # Remove kind code (A1, B1, etc.) if present
        pub_number = re.sub(r'[A-Z]\d*$', '', pub_number)

        return pub_number

    def lookup(self, pub_number: str) -> Optional[dict]:
        """Look up patent in database by publication number."""
        if not self.conn:
            if not self.connect():
                return None

        normalized = self.normalize_pub_number(pub_number)

        try:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT pub_number, pub_date, raw_xml_path, year, title
                FROM patent_data_unified
                WHERE pub_number = %s
            """, (normalized,))

            row = cur.fetchone()
            cur.close()

            if row:
                return {
                    'pub_number': row[0],
                    'pub_date': row[1],
                    'raw_xml_path': row[2],
                    'year': row[3],
                    'title': row[4]
                }
            return None
        except Exception as e:
            print(f"Database query error: {e}")
            return None

    def extract_patent_files(self, patent_info: dict, output_dir: str) -> Optional[str]:
        """Extract patent XML and TIF files from archive to output directory."""
        raw_xml_path = patent_info['raw_xml_path']
        year = patent_info['year']

        if not raw_xml_path:
            print("Error: No raw_xml_path in database")
            return None

        # Parse raw_xml_path: "I20160526.tar/US20160148332A1-20160526/US20160148332A1-20160526.XML"
        parts = raw_xml_path.split('/')
        if len(parts) < 2:
            print(f"Error: Invalid raw_xml_path format: {raw_xml_path}")
            return None

        tar_filename = parts[0]
        patent_dir = parts[1]  # e.g., "US20160148332A1-20160526"

        # Build full TAR path
        tar_path = Path(PATENT_ARCHIVE_BASE) / str(year) / tar_filename

        if not tar_path.exists():
            print(f"Error: TAR file not found: {tar_path}")
            return None

        print(f"Extracting from: {tar_path}")

        # Create output directory
        extract_dir = Path(output_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Open TAR and find the ZIP file
            with tarfile.open(tar_path, 'r') as tar:
                # Look for ZIP file containing our patent
                zip_pattern = f"{patent_dir}.ZIP"
                zip_member = None

                for member in tar.getmembers():
                    if member.name.endswith(zip_pattern):
                        zip_member = member
                        break

                if not zip_member:
                    print(f"Error: ZIP not found in TAR for pattern: {zip_pattern}")
                    # List some contents for debugging
                    print("Available files in TAR (first 10):")
                    for i, m in enumerate(tar.getmembers()[:10]):
                        print(f"  {m.name}")
                    return None

                print(f"Found ZIP: {zip_member.name}")

                # Extract ZIP to temp location
                zip_file = tar.extractfile(zip_member)
                if not zip_file:
                    print("Error: Could not extract ZIP from TAR")
                    return None

                # Read ZIP contents
                zip_data = BytesIO(zip_file.read())

                with zipfile.ZipFile(zip_data, 'r') as zf:
                    # Extract all files to output directory
                    for name in zf.namelist():
                        # Get just the filename
                        basename = Path(name).name
                        if basename:  # Skip directory entries
                            target_path = extract_dir / basename
                            with zf.open(name) as src, open(target_path, 'wb') as dst:
                                dst.write(src.read())
                            print(f"  Extracted: {basename}")

            # Find the XML file
            xml_files = list(extract_dir.glob('*.XML'))
            if xml_files:
                return str(xml_files[0])

            print("Error: No XML file found in extracted contents")
            return None

        except Exception as e:
            print(f"Extraction error: {e}")
            import traceback
            traceback.print_exc()
            return None


class PatentReconstructor:
    """Reconstructs a patent document from USPTO XML and TIF files."""

    def __init__(self, xml_path: str):
        self.xml_path = Path(xml_path)
        self.base_dir = self.xml_path.parent
        self.tree = etree.parse(str(self.xml_path))
        self.root = self.tree.getroot()
        self.ns = {}  # No namespace in USPTO XML

        # Setup styles
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles."""
        self.styles.add(ParagraphStyle(
            name='PatentTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            spaceAfter=12,
            alignment=TA_CENTER
        ))
        self.styles.add(ParagraphStyle(
            name='PatentHeading',
            parent=self.styles['Heading2'],
            fontSize=12,
            spaceBefore=12,
            spaceAfter=6,
            alignment=TA_CENTER
        ))
        self.styles.add(ParagraphStyle(
            name='PatentBody',
            parent=self.styles['Normal'],
            fontSize=10,
            leading=14,
            alignment=TA_JUSTIFY,
            firstLineIndent=20
        ))
        self.styles.add(ParagraphStyle(
            name='PatentClaim',
            parent=self.styles['Normal'],
            fontSize=10,
            leading=14,
            alignment=TA_JUSTIFY,
            leftIndent=20,
            firstLineIndent=-20
        ))
        self.styles.add(ParagraphStyle(
            name='PatentMeta',
            parent=self.styles['Normal'],
            fontSize=9,
            leading=11
        ))

    def _get_text(self, xpath: str, default: str = "") -> str:
        """Get text from xpath, return default if not found."""
        elements = self.root.xpath(xpath)
        if elements:
            if hasattr(elements[0], 'text') and elements[0].text:
                return elements[0].text.strip()
            elif isinstance(elements[0], str):
                return elements[0].strip()
        return default

    def _get_all_text(self, element) -> str:
        """Get all text content from element, including nested tags."""
        if element is None:
            return ""
        return ''.join(element.itertext()).strip()

    def extract_metadata(self) -> dict:
        """Extract bibliographic metadata from XML."""
        meta = {}

        # Publication info
        meta['pub_number'] = self._get_text('.//publication-reference//doc-number')
        meta['pub_kind'] = self._get_text('.//publication-reference//kind')
        meta['pub_date'] = self._get_text('.//publication-reference//date')

        # Format date
        if meta['pub_date'] and len(meta['pub_date']) == 8:
            d = meta['pub_date']
            meta['pub_date_fmt'] = f"{d[4:6]}/{d[6:8]}/{d[:4]}"
        else:
            meta['pub_date_fmt'] = meta['pub_date']

        # Application info
        meta['app_number'] = self._get_text('.//application-reference//doc-number')
        meta['app_date'] = self._get_text('.//application-reference//date')
        if meta['app_date'] and len(meta['app_date']) == 8:
            d = meta['app_date']
            meta['app_date_fmt'] = f"{d[4:6]}/{d[6:8]}/{d[:4]}"
        else:
            meta['app_date_fmt'] = meta['app_date']

        # Title
        meta['title'] = self._get_text('.//invention-title')

        # Applicant
        meta['applicant'] = self._get_text('.//us-applicants//orgname')
        if not meta['applicant']:
            # Try individual applicant
            first = self._get_text('.//us-applicants//first-name')
            last = self._get_text('.//us-applicants//last-name')
            meta['applicant'] = f"{first} {last}".strip()

        applicant_city = self._get_text('.//us-applicants//city')
        applicant_state = self._get_text('.//us-applicants//state')
        applicant_country = self._get_text('.//us-applicants//country')
        meta['applicant_location'] = f"{applicant_city}, {applicant_state} ({applicant_country})"

        # Inventors
        inventors = []
        for inv in self.root.xpath('.//inventors/inventor'):
            first = inv.xpath('.//first-name/text()')
            last = inv.xpath('.//last-name/text()')
            city = inv.xpath('.//city/text()')
            state = inv.xpath('.//state/text()')
            country = inv.xpath('.//country/text()')

            name = f"{first[0] if first else ''} {last[0] if last else ''}".strip()
            loc = f"{city[0] if city else ''}, {state[0] if state else ''} ({country[0] if country else ''})"
            inventors.append({'name': name, 'location': loc})
        meta['inventors'] = inventors

        # Related applications (provisional)
        provisionals = []
        for prov in self.root.xpath('.//us-provisional-application'):
            doc_num = prov.xpath('.//doc-number/text()')
            date = prov.xpath('.//date/text()')
            if doc_num:
                prov_date = date[0] if date else ''
                if len(prov_date) == 8:
                    prov_date = f"{prov_date[4:6]}/{prov_date[6:8]}/{prov_date[:4]}"
                provisionals.append({'number': doc_num[0], 'date': prov_date})
        meta['provisionals'] = provisionals

        # Classifications
        ipc_classes = []
        for ipc in self.root.xpath('.//classification-ipcr'):
            section = ipc.xpath('section/text()')
            cls = ipc.xpath('class/text()')
            subcls = ipc.xpath('subclass/text()')
            main_group = ipc.xpath('main-group/text()')
            subgroup = ipc.xpath('subgroup/text()')
            if section and cls and subcls:
                ipc_str = f"{section[0]}{cls[0]}{subcls[0]} {main_group[0] if main_group else ''}/{subgroup[0] if subgroup else ''}"
                ipc_classes.append(ipc_str.strip())
        meta['ipc_classes'] = ipc_classes

        cpc_classes = []
        for cpc in self.root.xpath('.//classification-cpc'):
            section = cpc.xpath('section/text()')
            cls = cpc.xpath('class/text()')
            subcls = cpc.xpath('subclass/text()')
            main_group = cpc.xpath('main-group/text()')
            subgroup = cpc.xpath('subgroup/text()')
            if section and cls and subcls:
                cpc_str = f"{section[0]}{cls[0]}{subcls[0]} {main_group[0] if main_group else ''}/{subgroup[0] if subgroup else ''}"
                cpc_classes.append(cpc_str.strip())
        meta['cpc_classes'] = cpc_classes

        return meta

    def extract_abstract(self) -> str:
        """Extract abstract text."""
        abstract_elem = self.root.xpath('.//abstract/p')
        if abstract_elem:
            return self._get_all_text(abstract_elem[0])
        return ""

    def extract_description(self) -> list:
        """Extract description paragraphs."""
        paragraphs = []
        desc = self.root.xpath('.//description')
        if not desc:
            return paragraphs

        for elem in desc[0]:
            if elem.tag == 'heading':
                paragraphs.append({'type': 'heading', 'text': self._get_all_text(elem)})
            elif elem.tag == 'p':
                num = elem.get('num', '')
                text = self._get_all_text(elem)
                if text:
                    paragraphs.append({'type': 'paragraph', 'num': num, 'text': text})

        return paragraphs

    def extract_claims(self) -> list:
        """Extract claims."""
        claims = []
        for claim in self.root.xpath('.//claims/claim'):
            claim_num = claim.get('num', '')
            claim_text = self._get_all_text(claim)
            # Clean up claim text
            claim_text = re.sub(r'\s+', ' ', claim_text).strip()
            claims.append({'num': claim_num, 'text': claim_text})
        return claims

    def get_drawing_files(self) -> list:
        """Get list of drawing TIF files in order."""
        drawings = []
        for fig in self.root.xpath('.//drawings/figure'):
            img = fig.xpath('.//img')
            if img:
                filename = img[0].get('file', '')
                if filename:
                    filepath = self.base_dir / filename
                    if filepath.exists():
                        drawings.append({
                            'file': str(filepath),
                            'num': fig.get('num', ''),
                            'id': fig.get('id', '')
                        })
        return drawings

    def convert_tif_to_png(self, tif_path: str) -> BytesIO:
        """Convert TIF image to PNG in memory for PDF embedding."""
        img = Image.open(tif_path)
        # Convert to RGB if necessary (TIF might be CMYK or other)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    def build_pdf(self, output_path: str):
        """Build the reconstructed PDF document."""
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )

        story = []

        # Extract all data
        meta = self.extract_metadata()
        abstract = self.extract_abstract()
        description = self.extract_description()
        claims = self.extract_claims()
        drawings = self.get_drawing_files()

        # === TITLE PAGE ===
        story.append(Paragraph("United States", self.styles['PatentHeading']))
        story.append(Paragraph("Patent Application Publication", self.styles['PatentTitle']))
        story.append(Spacer(1, 12))

        # Publication info
        pub_info = f"<b>Pub. No.:</b> US {meta['pub_number']} {meta['pub_kind']}"
        story.append(Paragraph(pub_info, self.styles['PatentMeta']))
        story.append(Paragraph(f"<b>Pub. Date:</b> {meta['pub_date_fmt']}", self.styles['PatentMeta']))
        story.append(Spacer(1, 20))

        # Title
        story.append(Paragraph(f"<b>(54) {meta['title'].upper()}</b>", self.styles['PatentHeading']))
        story.append(Spacer(1, 12))

        # Applicant
        story.append(Paragraph(f"<b>(71)</b> Applicant: {meta['applicant']}, {meta['applicant_location']}", self.styles['PatentMeta']))
        story.append(Spacer(1, 6))

        # Inventors
        inv_text = "<b>(72)</b> Inventors: "
        inv_parts = [f"{inv['name']}, {inv['location']}" for inv in meta['inventors']]
        inv_text += "; ".join(inv_parts)
        story.append(Paragraph(inv_text, self.styles['PatentMeta']))
        story.append(Spacer(1, 6))

        # Application info
        story.append(Paragraph(f"<b>(21)</b> Appl. No.: {meta['app_number']}", self.styles['PatentMeta']))
        story.append(Paragraph(f"<b>(22)</b> Filed: {meta['app_date_fmt']}", self.styles['PatentMeta']))
        story.append(Spacer(1, 6))

        # Related applications
        if meta['provisionals']:
            story.append(Paragraph("<b>Related U.S. Application Data</b>", self.styles['PatentMeta']))
            for prov in meta['provisionals']:
                story.append(Paragraph(
                    f"<b>(60)</b> Provisional application No. {prov['number']}, filed on {prov['date']}.",
                    self.styles['PatentMeta']
                ))
            story.append(Spacer(1, 6))

        # Classifications
        story.append(Paragraph("<b>Publication Classification</b>", self.styles['PatentMeta']))
        if meta['ipc_classes']:
            story.append(Paragraph(f"<b>(51)</b> Int. Cl.: {', '.join(meta['ipc_classes'])}", self.styles['PatentMeta']))
        if meta['cpc_classes']:
            story.append(Paragraph(f"<b>(52)</b> U.S. Cl. CPC: {', '.join(meta['cpc_classes'])}", self.styles['PatentMeta']))
        story.append(Spacer(1, 20))

        # Abstract
        story.append(Paragraph("<b>(57) ABSTRACT</b>", self.styles['PatentHeading']))
        story.append(Spacer(1, 6))
        story.append(Paragraph(abstract, self.styles['PatentBody']))

        # Add first drawing to title page if available (D00000)
        if drawings and drawings[0]['num'] == '00000':
            story.append(Spacer(1, 12))
            try:
                img_buffer = self.convert_tif_to_png(drawings[0]['file'])
                img = RLImage(img_buffer, width=4*inch, height=3*inch)
                story.append(img)
            except Exception as e:
                print(f"Warning: Could not add title drawing: {e}")

        story.append(PageBreak())

        # === DRAWINGS ===
        for i, drawing in enumerate(drawings):
            if drawing['num'] == '00000':
                continue  # Skip title page drawing, already added

            try:
                img_buffer = self.convert_tif_to_png(drawing['file'])
                # Calculate size to fit page
                img = RLImage(img_buffer, width=6.5*inch, height=8.5*inch)
                img.hAlign = 'CENTER'

                fig_num = int(drawing['num']) if drawing['num'].isdigit() else drawing['num']
                story.append(Paragraph(f"<b>FIG. {fig_num}</b>", self.styles['PatentHeading']))
                story.append(Spacer(1, 12))
                story.append(img)
                story.append(PageBreak())
            except Exception as e:
                print(f"Warning: Could not add drawing {drawing['file']}: {e}")

        # === DESCRIPTION ===
        story.append(Paragraph("<b>DETAILED DESCRIPTION</b>", self.styles['PatentHeading']))
        story.append(Spacer(1, 12))

        for para in description:
            if para['type'] == 'heading':
                story.append(Spacer(1, 12))
                story.append(Paragraph(f"<b>{para['text']}</b>", self.styles['PatentHeading']))
                story.append(Spacer(1, 6))
            else:
                num = para.get('num', '')
                text = para['text']
                if num:
                    # Format paragraph number
                    try:
                        num_int = int(num)
                        text = f"[{num_int:04d}] {text}"
                    except ValueError:
                        text = f"[{num}] {text}"
                story.append(Paragraph(text, self.styles['PatentBody']))
                story.append(Spacer(1, 6))

        story.append(PageBreak())

        # === CLAIMS ===
        story.append(Paragraph("<b>CLAIMS</b>", self.styles['PatentHeading']))
        story.append(Spacer(1, 12))
        story.append(Paragraph("What is claimed is:", self.styles['PatentBody']))
        story.append(Spacer(1, 12))

        for claim in claims:
            # Format claim number
            try:
                num = int(claim['num'])
            except (ValueError, TypeError):
                num = claim['num']

            text = claim['text']
            # Add claim number to beginning if not already there
            if not text.startswith(str(num)):
                text = f"<b>{num}.</b> {text}"

            story.append(Paragraph(text, self.styles['PatentClaim']))
            story.append(Spacer(1, 8))

        # Build PDF
        doc.build(story)
        print(f"PDF created: {output_path}")
        return output_path


def reconstruct_from_pub_number(pub_number: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Reconstruct a patent PDF from just the publication number.

    Args:
        pub_number: Publication number (e.g., "US20160148332A1" or "20160148332")
        output_path: Optional output PDF path. If not provided, uses pub_number.pdf

    Returns:
        Path to generated PDF, or None on failure
    """
    lookup = PatentLookup()

    # Look up patent in database
    print(f"Looking up patent: {pub_number}")
    patent_info = lookup.lookup(pub_number)

    if not patent_info:
        print(f"Error: Patent not found in database: {pub_number}")
        lookup.close()
        return None

    print(f"Found: {patent_info['title']}")
    print(f"Publication date: {patent_info['pub_date']}")
    print(f"Raw XML path: {patent_info['raw_xml_path']}")

    # Create temp directory for extraction
    temp_dir = tempfile.mkdtemp(prefix='patent_reconstruct_')

    try:
        # Extract files from archive
        xml_path = lookup.extract_patent_files(patent_info, temp_dir)

        if not xml_path:
            print("Error: Failed to extract patent files")
            return None

        print(f"Extracted XML: {xml_path}")

        # Determine output path
        if not output_path:
            normalized = lookup.normalize_pub_number(pub_number)
            output_path = f"US{normalized}_reconstructed.pdf"

        # Reconstruct PDF
        reconstructor = PatentReconstructor(xml_path)
        result = reconstructor.build_pdf(output_path)

        return result

    finally:
        # Cleanup temp directory
        lookup.close()
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"Cleaned up temp directory: {temp_dir}")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python prior_art_reconstructor.py <pub_number> [output.pdf]")
        print("  python prior_art_reconstructor.py <xml_file> [output.pdf]")
        print("\nExamples:")
        print("  python prior_art_reconstructor.py US20160148332A1")
        print("  python prior_art_reconstructor.py 20160148332 output.pdf")
        print("  python prior_art_reconstructor.py /path/to/file.XML")
        sys.exit(1)

    input_arg = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) >= 3 else None

    # Check if input is an existing XML file or a publication number
    if os.path.exists(input_arg) and input_arg.upper().endswith('.XML'):
        # Direct XML file mode
        print(f"Reconstructing patent from XML: {input_arg}")

        if not output_path:
            xml_name = Path(input_arg).stem
            output_path = f"{xml_name}_reconstructed.pdf"

        reconstructor = PatentReconstructor(input_arg)
        reconstructor.build_pdf(output_path)
    else:
        # Publication number lookup mode
        result = reconstruct_from_pub_number(input_arg, output_path)
        if not result:
            sys.exit(1)


if __name__ == "__main__":
    main()
