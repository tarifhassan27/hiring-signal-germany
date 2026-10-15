"""
Project 7 - Phase 2 data check
Question: does each company's public job feed work, and does it carry posting dates?

Input : company_list.csv
        required columns: company, careers_url
        optional columns: headcount_band, city, ats, slug, notes
        (ats + slug are worked out from careers_url; fill them only if detection fails)

Output: data_check.csv   one row per company
        data_check.md    PASS / FAIL summary (the Phase 2 artifact)
        raw/YYYY-MM-DD/  untouched feed responses = first snapshot for the weekly collector

Run   : python feed_check.py
Needs : pip install requests
"""
import csv
import re
import statistics
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
IN_FILE = HERE / "company_list.csv"
OUT_CSV = HERE / "data_check.csv"
OUT_MD = HERE / "data_check.md"
RAW_DIR = HERE / "raw" / date.today().isoformat()

# Pass rule, locked in Phase 0 - do not change after seeing results
MIN_COMPANIES = 10
MIN_ROLES = 200

DELAY_S = 1.0  # be polite: one request per second
TIMEOUT_S = 20
HEADERS = {"User-Agent": "job-feed-research (contact: tarifhassan27@gmail.com)"}

# Careers URL pattern -> (platform, slug)
URL_PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
    ("lever", r"jobs(?:\.eu)?\.lever\.co/([\w-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.%-]+)"),
    ("personio", r"([\w-]+)\.jobs\.personio\.(?:de|com)"),
    ("workable", r"apply\.workable\.com/([\w-]+)"),
    ("recruitee", r"([\w-]+)\.recruitee\.com"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)"),
]

# Public feed endpoints. Where a platform has EU and non-EU hosts, both are tried in order.
FEEDS = {
    "greenhouse": ["https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                   "https://boards-api.eu.greenhouse.io/v1/boards/{slug}/jobs"],
    "lever": ["https://api.lever.co/v0/postings/{slug}?mode=json",
              "https://api.eu.lever.co/v0/postings/{slug}?mode=json"],
    "ashby": ["https://api.ashbyhq.com/posting-api/job-board/{slug}"],
    "personio": ["https://{slug}.jobs.personio.de/xml",
                 "https://{slug}.jobs.personio.com/xml"],
    "workable": ["https://apply.workable.com/api/v1/widget/accounts/{slug}"],
    "recruitee": ["https://{slug}.recruitee.com/api/offers/"],
    "smartrecruiters": ["https://api.smartrecruiters.com/v1/companies/{slug}/postings"],
}

# Field names differ by platform, so dates are found by name, best first.
# "updated" is a weak signal: it is not the date the role was first posted.
STRONG_DATE_HINTS = ["first_published", "firstpublished", "published", "created", "posted", "released"]
WEAK_DATE_HINTS = ["updated"]
TITLE_KEYS = ["title", "text", "name"]
LIST_KEYS = ["jobs", "offers", "content", "postings", "results"]

# Crude German-title flag: sanity indicator only, not a language detector
GERMAN_WORDS = re.compile(
    r"\b(mitarbeiter|leiter|leitung|werkstudent|entwickler|berater|sachbearbeiter|"
    r"ausbildung|praktik|referent|vertrieb|kauf(mann|frau)|ingenieur|buchhalt|personal)",
    re.IGNORECASE,
)


def detect_platform(row):
    if row.get("ats") and row.get("slug"):
        return row["ats"].strip().lower(), row["slug"].strip()
    url = (row.get("careers_url") or "").strip()
    for platform, pattern in URL_PATTERNS:
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            return platform, m.group(1)
    return None, None


def parse_jobs(platform, text):
    """Return a list of flat dicts, one per open role."""
    if platform == "personio":
        root = ET.fromstring(text)
        return [{child.tag: (child.text or "").strip() for child in pos} for pos in root.iter("position")]
    import json
    data = json.loads(text)
    if isinstance(data, list):
        return [j for j in data if isinstance(j, dict)]
    if isinstance(data, dict):
        for key in LIST_KEYS:
            if isinstance(data.get(key), list):
                return [j for j in data[key] if isinstance(j, dict)]
    return []


def to_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000 if value > 1e11 else value  # epoch ms vs epoch s
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_date_field(jobs):
    """Pick the best date field that parses for at least half the roles."""
    if not jobs:
        return None, None
    keys = {k for j in jobs for k in j}
    for strength, hints in (("strong", STRONG_DATE_HINTS), ("weak", WEAK_DATE_HINTS)):
        for hint in hints:
            for key in sorted(k for k in keys if hint in k.lower().replace("_", "")
                              or hint in k.lower()):
                parsed = sum(1 for j in jobs if to_datetime(j.get(key)) is not None)
                if parsed >= len(jobs) / 2:
                    return key, strength
    return None, None


def check_company(row):
    result = {
        "company": row.get("company", "").strip(),
        "headcount_band": row.get("headcount_band", ""),
        "city": row.get("city", ""),
        "platform": "", "slug": "", "feed_ok": False, "http_status": "", "feed_url": "",
        "n_roles": 0, "date_field": "", "date_strength": "",
        "median_age_days": "", "max_age_days": "", "german_title_share": "",
        "company_pass": False, "note": "",
    }
    platform, slug = detect_platform(row)
    if not platform:
        result["note"] = "platform not detected - check the careers_url or fill ats + slug"
        return result
    if platform not in FEEDS:
        result["note"] = f"no feed defined for platform '{platform}'"
        return result
    result["platform"], result["slug"] = platform, slug

    text = None
    for template in FEEDS[platform]:
        url = template.format(slug=slug)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            result["http_status"], result["note"] = "error", str(e)[:120]
            time.sleep(DELAY_S)
            continue
        result["http_status"], result["feed_url"] = resp.status_code, url
        time.sleep(DELAY_S)
        if resp.ok:
            text = resp.text
            break
    if text is None:
        result["note"] = result["note"] or "feed did not respond with 200"
        return result

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ext = "xml" if platform == "personio" else "json"
    (RAW_DIR / f"{platform}__{slug}.{ext}").write_text(text, encoding="utf-8")

    try:
        jobs = parse_jobs(platform, text)
    except Exception as e:  # malformed feed
        result["note"] = f"could not parse feed: {str(e)[:100]}"
        return result

    result["feed_ok"] = True
    result["n_roles"] = len(jobs)
    if not jobs:
        result["note"] = "feed works but has 0 open roles"
        return result

    titles = [next((str(j[k]) for k in TITLE_KEYS if j.get(k)), "") for j in jobs]
    result["german_title_share"] = round(sum(bool(GERMAN_WORDS.search(t)) for t in titles) / len(titles), 2)

    key, strength = find_date_field(jobs)
    if key:
        now = datetime.now(timezone.utc)
        ages = [(now - d).days for d in (to_datetime(j.get(key)) for j in jobs) if d]
        result["date_field"], result["date_strength"] = key, strength
        result["median_age_days"] = round(statistics.median(ages), 1)
        result["max_age_days"] = max(ages)
    else:
        result["note"] = "no posting-date field found"

    result["company_pass"] = result["feed_ok"] and strength == "strong" and result["n_roles"] > 0
    if strength == "weak":
        result["note"] = "only an 'updated' date - not a posting date, does not count"
    return result


def write_outputs(results):
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    passing = [r for r in results if r["company_pass"]]
    n_companies = len(passing)
    n_roles = sum(r["n_roles"] for r in passing)
    verdict = "PASS" if n_companies >= MIN_COMPANIES and n_roles >= MIN_ROLES else "FAIL"

    lines = [
        "# Phase 2 data check",
        "",
        f"Run date: {date.today().isoformat()}",
        "",
        f"## Verdict: {verdict}",
        "",
        f"- Companies with a working feed AND a posting date: **{n_companies}** (need {MIN_COMPANIES})",
        f"- Open roles at those companies: **{n_roles}** (need {MIN_ROLES})",
        f"- Companies checked: {len(results)}",
        "",
        "## Per company",
        "",
        "| Company | Platform | Feed | Roles | Date field | Median age (days) | German titles | Pass | Note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['company']} | {r['platform'] or '-'} | {'yes' if r['feed_ok'] else 'no'} | "
            f"{r['n_roles']} | {r['date_field'] or '-'} | {r['median_age_days'] or '-'} | "
            f"{r['german_title_share'] if r['german_title_share'] != '' else '-'} | "
            f"{'yes' if r['company_pass'] else 'no'} | {r['note']} |"
        )
    lines += ["", "If FAIL: change the sector or country, not the idea. Do not lower the pass rule."]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return verdict, n_companies, n_roles


def main():
    with IN_FILE.open(newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("company") or "").strip()]
    if not rows:
        raise SystemExit("company_list.csv has no companies yet")

    results = []
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row['company']}")
        results.append(check_company(row))

    verdict, n_companies, n_roles = write_outputs(results)
    print(f"\n{verdict}: {n_companies} companies pass, {n_roles} open roles")
    print(f"Written: {OUT_MD.name}, {OUT_CSV.name}, {RAW_DIR}")


if __name__ == "__main__":
    main()
