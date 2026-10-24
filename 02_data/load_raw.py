"""
load_raw.py
Loads all weekly snapshot JSONs from 02_data/raw/ into raw.job_postings.
Run from the project root: python 02_data/load_raw.py
"""

import json
import os
import psycopg2
from pathlib import Path
from datetime import date

# --- CONFIG ---
DB = {
    "host":     os.environ.get("DB_HOST",     "localhost"),
    "port":     int(os.environ.get("DB_PORT", "5432")),
    "dbname":   os.environ.get("DB_NAME",     "hiring_signal"),
    "user":     os.environ.get("DB_USER",     "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}

RAW_DIR = Path(__file__).parent / "raw"


def parse_date(val):
    """Return a date string YYYY-MM-DD or None from various timestamp formats."""
    if not val:
        return None
    val = str(val).strip()
    # Unix ms timestamp (Greenhouse, Lever)
    if val.isdigit() and len(val) >= 10:
        ts = int(val)
        if len(val) == 13:
            ts = ts // 1000
        try:
            return date.fromtimestamp(ts).isoformat()
        except Exception:
            return None
    # ISO string (Ashby): "2024-03-15T10:22:00.000Z"
    if "T" in val or "-" in val:
        return val[:10]
    return None


def extract_jobs(platform, company, data):
    """
    Returns a list of dicts with keys: job_id, title, location, created_at.
    Handles Greenhouse, Ashby, and Lever JSON structures.
    """
    jobs = []

    if platform == "greenhouse":
        # Top-level list of job objects
        postings = data if isinstance(data, list) else data.get("jobs", [])
        for p in postings:
            jobs.append({
                "job_id":     str(p.get("id", "")),
                "title":      p.get("title", ""),
                "location":   p.get("location", {}).get("name", "") if isinstance(p.get("location"), dict) else str(p.get("location", "")),
                "created_at": parse_date(p.get("updated_at") or p.get("first_published") or p.get("created_at")),
            })

    elif platform == "ashby":
        # {"results": [...]} or {"jobPostings": [...]}
        postings = data.get("jobs", data.get("results", data.get("jobPostings", [])))
        for p in postings:
            loc = ""
            if isinstance(p.get("location"), dict):
                loc = p["location"].get("name", "")
            elif isinstance(p.get("locationName"), str):
                loc = p["locationName"]
            jobs.append({
                "job_id":     str(p.get("id", p.get("jobPostingId", ""))),
                "title":      p.get("title", ""),
                "location":   loc,
                "created_at": parse_date(p.get("publishedDate") or p.get("createdAt") or p.get("updatedAt")),
            })

    elif platform == "lever":
        # List of posting objects
        postings = data if isinstance(data, list) else data.get("data", [])
        for p in postings:
            loc = ""
            cats = p.get("categories", {})
            if isinstance(cats, dict):
                loc = cats.get("location", cats.get("city", ""))
            jobs.append({
                "job_id":     str(p.get("id", "")),
                "title":      p.get("text", p.get("title", "")),
                "location":   loc,
                "created_at": parse_date(p.get("createdAt") or p.get("created_at")),
            })

    return jobs


# --- CONNECT ---
conn = psycopg2.connect(**DB)
cur  = conn.cursor()

# --- FIND SNAPSHOT FOLDERS ---
snapshot_dirs = sorted([d for d in RAW_DIR.iterdir() if d.is_dir()])

if not snapshot_dirs:
    print("No snapshot folders found in 02_data/raw/")
    conn.close()
    exit()

loaded_total = 0
skipped_total = 0

for snap_dir in snapshot_dirs:
    snapshot_date = snap_dir.name

    try:
        date.fromisoformat(snapshot_date)
    except ValueError:
        print(f"  Skipping non-date folder: {snap_dir.name}")
        continue

    # Skip if already loaded
    cur.execute(
        "SELECT COUNT(*) FROM raw.job_postings WHERE snapshot_date = %s",
        (snapshot_date,)
    )
    already = cur.fetchone()[0]
    if already > 0:
        print(f"  {snapshot_date}: already loaded ({already} rows) — skipping")
        skipped_total += already
        continue

    json_files = list(snap_dir.glob("*.json"))
    if not json_files:
        print(f"  {snapshot_date}: no JSON files found — skipping")
        continue

    rows_loaded = 0

    for jf in sorted(json_files):
        # Filename pattern: platform__company.json
        stem = jf.stem  # e.g. "greenhouse__contentful"
        parts = stem.split("__", 1)
        if len(parts) != 2:
            print(f"    Skipping unrecognised filename: {jf.name}")
            continue

        platform, company = parts[0].lower(), parts[1]

        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"    Could not parse {jf.name}: {e}")
            continue

        jobs = extract_jobs(platform, company, data)

        for job in jobs:
            cur.execute(
                """
                INSERT INTO raw.job_postings
                    (snapshot_date, company, platform, job_id, title, location, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    snapshot_date,
                    company,
                    platform,
                    job["job_id"],
                    job["title"],
                    job["location"],
                    job["created_at"],
                )
            )
            rows_loaded += 1

    conn.commit()
    print(f"  {snapshot_date}: loaded {rows_loaded} rows from {len(json_files)} files")
    loaded_total += rows_loaded

cur.close()
conn.close()
print(f"\nDone. {loaded_total} rows loaded, {skipped_total} rows already existed.")
