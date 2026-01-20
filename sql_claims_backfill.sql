-- Add separate claims_text column and (optional) description_body column
ALTER TABLE patent_data_unified
    ADD COLUMN IF NOT EXISTS claims_text TEXT;

-- Optional: store description without the leading CLAIMS block
ALTER TABLE patent_data_unified
    ADD COLUMN IF NOT EXISTS description_body TEXT;

-- Backfill claims_text from embedded CLAIMS: ... DESCRIPTION: structure
-- Assumes description_text begins with 'CLAIMS:' when claims are embedded
UPDATE patent_data_unified
SET claims_text = CASE
    WHEN description_text LIKE 'CLAIMS:%' THEN
        CASE
            WHEN position(E'\n\nDESCRIPTION:' in description_text) > 0 THEN
                substring(description_text from 8 for position(E'\n\nDESCRIPTION:' in description_text) - 8)
            ELSE
                substring(description_text from 8)
        END
    ELSE claims_text
END
WHERE claims_text IS NULL AND description_text LIKE 'CLAIMS:%';

-- Backfill description_body (content after DESCRIPTION:), keep original description_text intact
UPDATE patent_data_unified
SET description_body = CASE
    WHEN description_text LIKE 'CLAIMS:%' AND position(E'\n\nDESCRIPTION:' in description_text) > 0 THEN
        substring(description_text from position(E'\n\nDESCRIPTION:' in description_text) + length(E'\n\nDESCRIPTION:'))
    ELSE COALESCE(description_body, description_text)
END
WHERE description_text IS NOT NULL;

-- Optional: mark empty claims_text explicitly as NULL if it's just whitespace
UPDATE patent_data_unified SET claims_text = NULL WHERE claims_text IS NOT NULL AND btrim(claims_text) = '';

-- Suggested index for faster filtering by presence of claims
CREATE INDEX IF NOT EXISTS patent_data_unified_claims_present_idx
    ON patent_data_unified ((claims_text IS NOT NULL));

