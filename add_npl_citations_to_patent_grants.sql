-- Add NPL (non-patent literature) citation columns to patent_grants table
-- Date: 2025-11-27
-- Purpose: Store non-patent literature citations (examiner and applicant) separately from patent citations
--
-- NPL citations include: scientific papers, technical publications, web URLs, foreign registrations, industry standards
-- These are referenced by examiners in USPTO office actions including Section 101 rejections

-- Add columns for NPL citations
ALTER TABLE patent_grants
ADD COLUMN IF NOT EXISTS npl_citations_examiner JSONB,
ADD COLUMN IF NOT EXISTS npl_citations_applicant JSONB;

-- Add comments to document the columns
COMMENT ON COLUMN patent_grants.npl_citations_examiner IS 'Non-patent literature citations cited by examiner - array of citation text strings';
COMMENT ON COLUMN patent_grants.npl_citations_applicant IS 'Non-patent literature citations cited by applicant - array of citation text strings';

-- Verify the columns were added
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'patent_grants'
  AND column_name IN ('npl_citations_examiner', 'npl_citations_applicant')
ORDER BY ordinal_position;
