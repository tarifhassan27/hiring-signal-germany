# Analysis Definitions

## Role families
Roles are grouped into four families based on job title keywords:

| Family | Keywords (title must contain one) |
|---|---|
| Engineering | Engineer, Developer, Architect, Backend, Frontend, Fullstack, DevOps, Platform, SRE |
| Product | Product Manager, PM, Product Owner |
| Data | Data Scientist, Data Analyst, Data Engineer, Analytics, ML, Machine Learning |
| GTM | Sales, Account Executive, AE, Account Manager, Marketing, Growth, Partnerships |

Roles that match none of the above are excluded from analysis.

## Posting age threshold
A role is flagged as hard-to-fill if it has been open for **90 days or more** from the
posting creation date to the snapshot date.

## Snapshot date
First snapshot: 2026-10-15. Single-snapshot analysis.

## Company weighting
No weighting applied. Each open role counts as one unit regardless of company size.

## Exclusion rules
- Roles with no detectable creation date are excluded
- Roles with a creation date in the future are excluded
- Duplicate postings (same title, same company, within 7 days of each other) — keep the oldest

## Cohort threshold
The 90-day hard-to-fill threshold is calibrated against this cohort: p90 posting age across
all 252 in-scope roles is 51 days. A role at 90 days is already past the 90th percentile
of the distribution — a meaningful outlier, not an arbitrary cutoff.
