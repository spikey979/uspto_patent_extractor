-- Fix raw_xml_path for ALL patents missing archive prefixes
-- Total affected: ~859,508 patents from years 2001-2004 and 2010
--
-- Pattern extraction: The date is embedded in the path as US[number]A1-YYYYMMDD/
-- We extract YYYYMMDD and prepend it as an archive name

-- =====================================================================
-- ANALYSIS: Check current state
-- =====================================================================

-- Check breakdown by year
SELECT
    year,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE raw_xml_path LIKE '%.ZIP/%' OR raw_xml_path LIKE '%.tar/%') as with_prefix,
    COUNT(*) FILTER (WHERE raw_xml_path NOT LIKE '%.ZIP/%' AND raw_xml_path NOT LIKE '%.tar/%' AND raw_xml_path IS NOT NULL) as missing_prefix
FROM patent_data_unified
WHERE year IN (2001, 2002, 2003, 2004, 2010)
GROUP BY year
ORDER BY year;

-- Show sample of affected patents
SELECT pub_number, year, raw_xml_path
FROM patent_data_unified
WHERE year IN (2001, 2002, 2003, 2004, 2010)
  AND raw_xml_path NOT LIKE '%.ZIP/%'
  AND raw_xml_path NOT LIKE '%.tar/%'
  AND raw_xml_path IS NOT NULL
LIMIT 20;

-- =====================================================================
-- FIX: Years 2001-2004 (ZIP archives)
-- =====================================================================

-- Extract date from path pattern: US[number]A1-YYYYMMDD/
-- Prepend as: YYYYMMDD.ZIP/[original_path]

UPDATE patent_data_unified
SET raw_xml_path =
    SUBSTRING(raw_xml_path FROM 'US[0-9]+[A-Z][0-9]+-([0-9]{8})') || '.ZIP/' || raw_xml_path
WHERE year IN (2001, 2002, 2003, 2004)
  AND raw_xml_path NOT LIKE '%.ZIP/%'
  AND raw_xml_path NOT LIKE '%.tar/%'
  AND raw_xml_path ~ 'US[0-9]+[A-Z][0-9]+-[0-9]{8}/';

-- =====================================================================
-- FIX: Year 2010 (TAR archives - I-prefix)
-- =====================================================================

-- Extract date from path pattern: US[number]A1-YYYYMMDD/
-- Prepend as: I + YYYYMMDD.tar/[original_path]
-- Note: 2010 uses I-prefix

UPDATE patent_data_unified
SET raw_xml_path =
    'I' || SUBSTRING(raw_xml_path FROM 'US[0-9]+[A-Z][0-9]+-([0-9]{8})') || '.tar/' || raw_xml_path
WHERE year = 2010
  AND raw_xml_path NOT LIKE '%.ZIP/%'
  AND raw_xml_path NOT LIKE '%.tar/%'
  AND raw_xml_path ~ 'US[0-9]+[A-Z][0-9]+-[0-9]{8}/';

-- =====================================================================
-- VERIFICATION
-- =====================================================================

-- Check results by year
SELECT
    year,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE raw_xml_path LIKE '%.ZIP/%' OR raw_xml_path LIKE '%.tar/%') as with_prefix,
    COUNT(*) FILTER (WHERE raw_xml_path NOT LIKE '%.ZIP/%' AND raw_xml_path NOT LIKE '%.tar/%' AND raw_xml_path IS NOT NULL) as still_missing
FROM patent_data_unified
WHERE year IN (2001, 2002, 2003, 2004, 2010)
GROUP BY year
ORDER BY year;

-- Show samples of fixed patents
SELECT pub_number, year, raw_xml_path
FROM patent_data_unified
WHERE year IN (2001, 2002, 2003, 2004)
  AND raw_xml_path LIKE '%.ZIP/%'
ORDER BY year, pub_number
LIMIT 20;

SELECT pub_number, year, raw_xml_path
FROM patent_data_unified
WHERE year = 2010
  AND raw_xml_path LIKE 'I%.tar/%'
ORDER BY pub_number
LIMIT 10;

-- Overall database statistics
SELECT
    COUNT(*) as total_patents,
    COUNT(*) FILTER (WHERE raw_xml_path LIKE '%.ZIP/%' OR raw_xml_path LIKE '%.tar/%') as with_archive_prefix,
    COUNT(*) FILTER (WHERE raw_xml_path NOT LIKE '%.ZIP/%' AND raw_xml_path NOT LIKE '%.tar/%' AND raw_xml_path IS NOT NULL) as without_archive_prefix,
    ROUND(100.0 * COUNT(*) FILTER (WHERE raw_xml_path LIKE '%.ZIP/%' OR raw_xml_path LIKE '%.tar/%') /
          NULLIF(COUNT(*) FILTER (WHERE raw_xml_path IS NOT NULL), 0), 2) as coverage_pct
FROM patent_data_unified;
