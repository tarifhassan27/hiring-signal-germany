"""
analyse.py
Pulls clean.job_postings from Postgres, computes company-level and
role-family-level summaries, saves two CSVs to 04_analysis/output/.
Run from the project root: python 04_analysis/analyse.py
"""

import os
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine

# --- CONFIG ---
DB = {
    "host":     os.environ.get("DB_HOST",     "localhost"),
    "port":     int(os.environ.get("DB_PORT", "5432")),
    "dbname":   os.environ.get("DB_NAME",     "hiring_signal"),
    "user":     os.environ.get("DB_USER",     "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

# --- LOAD ---
engine = create_engine(
    f"postgresql+psycopg2://{DB['user']}:{DB['password']}"
    f"@{DB['host']}:{DB['port']}/{DB['dbname']}"
)

df = pd.read_sql(
    """
    SELECT snapshot_date, company, platform, job_id, title,
           days_open, days_until_90, status, role_family
    FROM clean.job_postings
    """,
    engine
)

print(f"Loaded {len(df)} rows from clean.job_postings")

# Keep only classified roles for summary tables
classified = df[df["role_family"].notna()].copy()
print(f"In-scope roles (Eng/Product/Data/GTM): {len(classified)}")

# --- COMPANY SUMMARY ---
MIN_ROLES = 5  # minimum in-scope roles to appear in company-level results

company = (
    classified
    .groupby("company")
    .agg(
        total_roles        = ("job_id", "count"),
        hard_to_fill_count = ("status", lambda x: (x == "hard_to_fill").sum()),
        avg_days_open      = ("days_open", "mean"),
    )
    .reset_index()
)
company["hard_to_fill_pct"] = (
    company["hard_to_fill_count"] / company["total_roles"] * 100
).round(1)
company["avg_days_open"] = company["avg_days_open"].round(1)

# Enforce minimum role threshold before any output
company = company[company["total_roles"] >= MIN_ROLES].copy()
assert company["total_roles"].min() >= MIN_ROLES, "A company with fewer than 5 roles slipped through"

company = company.sort_values("hard_to_fill_pct", ascending=False)

print(f"Companies shown (>= {MIN_ROLES} in-scope roles): {len(company)} | Roles shown: {company['total_roles'].sum()}")

# Public CSV: anonymised (Company A, B, C ...) — safe to commit
company_public = company.copy().reset_index(drop=True)
company_public.insert(0, "company_label", [f"Company {chr(65 + i)}" for i in range(len(company_public))])
company_public_path = OUT_DIR / "company_summary_public.csv"
company_public.drop(columns=["company"]).to_csv(company_public_path, index=False)
print(f"Public company summary (anonymised) -> {company_public_path}")

# Private CSV: named — gitignored, never committed
private_dir = Path(__file__).parent.parent / "private"
private_dir.mkdir(exist_ok=True)
company_private_path = private_dir / "company_summary_named.csv"
company.to_csv(company_private_path, index=False)
print(f"Private company summary (named)     -> {company_private_path}")

print("\n--- Company results (named, private) ---")
print(company.to_string(index=False))

# --- ROLE FAMILY SUMMARY ---
active = classified[classified["status"] == "active"]

family = (
    classified
    .groupby("role_family")
    .agg(
        total_roles        = ("job_id", "count"),
        hard_to_fill_count = ("status", lambda x: (x == "hard_to_fill").sum()),
        avg_days_open      = ("days_open", "mean"),
    )
    .reset_index()
)
family["hard_to_fill_pct"] = (
    family["hard_to_fill_count"] / family["total_roles"] * 100
).round(1)
family["avg_days_open"] = family["avg_days_open"].round(1)

# For active roles only: avg days_until_90 (predictive signal)
avg_until_90 = (
    active
    .groupby("role_family")["days_until_90"]
    .mean()
    .round(1)
    .rename("avg_days_until_90_active")
)
family = family.merge(avg_until_90, on="role_family", how="left")
family = family.sort_values("avg_days_open", ascending=False)

family_path = OUT_DIR / "role_family_summary.csv"
family.to_csv(family_path, index=False)
print(f"\nRole family summary -> {family_path}")
print(family.to_string(index=False))

# Note on hard-to-fill counts: use raw counts (not percentages) for families
# with fewer than 5 hard-to-fill roles in the numerator — flag those here.
print("\n--- Hard-to-fill count check (use counts, not %, if < 5) ---")
for _, row in family.iterrows():
    flag = " ← use count, not %" if row["hard_to_fill_count"] < 5 else ""
    print(f"  {row['role_family']:12s}: {int(row['hard_to_fill_count'])} of {int(row['total_roles'])} "
          f"({row['hard_to_fill_pct']}%){flag}")

print("\nDone.")
