-- Fix raw_xml_path for Sept-Nov 2025 patents
-- These patents are missing the archive filename prefix
--
-- Current format: US20250275964A1-20250904/US20250275964A1-20250904-S00001.XML
-- Correct format: I20250904.tar/US20250275964A1-20250904/US20250275964A1-20250904-S00001.XML

-- First, let's verify the issue
SELECT
    to_char(pub_date, 'YYYY-MM') as month,
    COUNT(*) as total_patents,
    COUNT(*) FILTER (WHERE raw_xml_path NOT LIKE 'I%.tar/%') as missing_prefix
FROM patent_data_unified
WHERE pub_date >= '2025-09-01' AND pub_date < '2025-12-01'
GROUP BY to_char(pub_date, 'YYYY-MM')
ORDER BY month;

-- Sample of affected patents
SELECT pub_number, pub_date, raw_xml_path
FROM patent_data_unified
WHERE pub_date >= '2025-09-01' AND pub_date < '2025-12-01'
  AND raw_xml_path NOT LIKE 'I%.tar/%'
LIMIT 10;

-- Fix the paths by prepending the archive name based on pub_date
-- Format: I + YYYYMMDD (Wednesday of that week) + .tar/
UPDATE patent_data_unified
SET raw_xml_path =
    'I' || to_char(pub_date, 'YYYYMMDD') || '.tar/' || raw_xml_path
WHERE pub_date >= '2025-09-01' AND pub_date < '2025-12-01'
  AND raw_xml_path NOT LIKE 'I%.tar/%';

-- Verify the fix
SELECT
    to_char(pub_date, 'YYYY-MM') as month,
    COUNT(*) as total_patents,
    COUNT(*) FILTER (WHERE raw_xml_path LIKE 'I%.tar/%') as with_prefix,
    COUNT(*) FILTER (WHERE raw_xml_path NOT LIKE 'I%.tar/%') as missing_prefix
FROM patent_data_unified
WHERE pub_date >= '2025-09-01' AND pub_date < '2025-12-01'
GROUP BY to_char(pub_date, 'YYYY-MM')
ORDER BY month;

-- Show sample of fixed patents
SELECT pub_number, pub_date, raw_xml_path
FROM patent_data_unified
WHERE pub_date >= '2025-09-01' AND pub_date < '2025-12-01'
ORDER BY pub_date
LIMIT 20;
