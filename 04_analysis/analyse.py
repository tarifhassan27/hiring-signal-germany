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
print(f"Classified roles: {len(classified)}")

# --- COMPANY SUMMARY ---
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
company = company.sort_values("hard_to_fill_pct", ascending=False)

company_path = OUT_DIR / "company_summary.csv"
company.to_csv(company_path, index=False)
print(f"\nCompany summary ({len(company)} companies) -> {company_path}")
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

# --- BENCHMARK CALLOUT ---
BENCHMARK_DAYS = 168
print(f"\n--- Benchmark: {BENCHMARK_DAYS} days (Bundesagentur fur Arbeit, Dec 2024) ---")
for _, row in family.iterrows():
    diff = row["avg_days_open"] - BENCHMARK_DAYS
    direction = "above" if diff > 0 else "below"
    print(f"  {row['role_family']:12s}: avg {row['avg_days_open']} days "
          f"({abs(diff):.1f} days {direction} benchmark)")

print("\nDone.")
