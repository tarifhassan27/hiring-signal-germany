-- clean_load.sql
-- Rebuilds clean.job_postings from raw.job_postings.
-- Applies: 365-day posting cap, role family classification, days_open, days_until_90, status.
-- Run from DBeaver against the hiring_signal database.

TRUNCATE clean.job_postings;

INSERT INTO clean.job_postings (
    snapshot_date, company, platform, job_id, title, location,
    created_at, days_open, days_until_90, status, role_family
)
SELECT
    snapshot_date,
    company,
    platform,
    job_id,
    title,
    location,
    created_at,
    (snapshot_date - created_at)                        AS days_open,
    90 - (snapshot_date - created_at)                   AS days_until_90,
    CASE
        WHEN (snapshot_date - created_at) >= 90 THEN 'hard_to_fill'
        ELSE 'active'
    END                                                  AS status,
    CASE
        WHEN title ILIKE ANY(ARRAY[
            '%Engineer%','%Developer%','%Architect%',
            '%Backend%','%Frontend%','%Fullstack%',
            '%DevOps%','%Platform%','%SRE%'
        ]) THEN 'Engineering'
        WHEN title ILIKE ANY(ARRAY[
            '%Product Manager%','% PM %','%Product Owner%'
        ]) THEN 'Product'
        WHEN title ILIKE ANY(ARRAY[
            '%Data Scientist%','%Data Science%','%Data Analyst%',
            '%Data Engineer%','%Analytics%','% ML %','%Machine Learning%'
        ]) THEN 'Data'
        WHEN title ILIKE ANY(ARRAY[
            '%Sales%','%Account Executive%','% AE %',
            '%Account Manager%','%Marketing%','%Growth%',
            '%Partnerships%','%Partnership%','%Customer Success%'
        ]) THEN 'GTM'
        ELSE NULL
    END                                                  AS role_family
FROM raw.job_postings
WHERE created_at IS NOT NULL
  AND created_at <= snapshot_date
  AND created_at >= snapshot_date - INTERVAL '365 days';
