#!/usr/bin/env python3
"""
categorize.py - Turn the raw stream-list JSON (from fetch.py) into organized
lists: one master table plus a series/category breakdown, written out as
CSV, JSON, and a human-browsable Markdown catalog.

Usage:
    python3 categorize.py [--in data/raw_playlist.json] [--outdir output]

How categorization works:
    Titles on this channel are informal and inconsistently punctuated (typos,
    mixed date formats, mixed spacing) but they DO follow a recognizable set
    of recurring series/topic names (e.g. "Sumadhwavijaya", "Manimanjari",
    "Satyatma Sandhya", "NKHK ..."). categorize() below is a prioritized list
    of substring rules built by inspecting the actual titles - most specific
    checks first, falling back to "Uncategorized / Other" for anything that
    doesn't match. See README.md for the full category list and the rationale.

How dates are resolved:
    yt-dlp's --flat-playlist mode (used by fetch.py) doesn't return a real
    per-video upload date, and the one flag that claims to
    (youtubetab:approximate_date) turned out to return a handful of fake
    "bucket" dates reused across dozens of unrelated videos on this channel -
    not usable. Instead:
      1. Try to parse an explicit day+month(+year) out of the title text.
      2. If the year is missing, carry forward the most recently SEEN year
         (the channel list is newest-first, so this walks backward in time)
         - and step it back by one when the month sequence implies we've
         crossed a year boundary (e.g. titles go ...Dec, Nov... then a
         "21st Jan" turns up further down the list; that Jan must be the
         PRECEDING January, one year earlier than the Dec/Nov just above it).
      3. If no date can be parsed at all, the row is marked date="Unknown"
         rather than guessing - these are listed in the catalog by their
         original channel-list position instead (still newest-to-oldest,
         just without a specific date).
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

# Ordered rules: (category name, list of substrings to match against a
# lowercased title). First matching category wins - order matters, most
# specific series names come before generic catch-alls like "nkhk"/"satsanga".
RULES = [
    ("Sandhya Shala (Onboarding/Classes)", ["sandhya shala", "sandhyavandana shala"]),
    ("Sumadhwavijaya (Marathi)", ["sumadhwavijaya", "sumadhwavijay", "sumadhawavijaya", "sumdhwavijaya"]),
    ("Manimanjari (Kannada)", ["manimanjari"]),
    ("Satyatma Sandhya", ["satyatma sandhya", "satyatmasandhya", "satyatma batch"]),
    ("Sandhyavandana Online", ["sandhyaonline", "sandhya online", "sandhyavandana-online",
                                "sandhyavandana online", "sandhyavandana-onl"]),
    ("Pratah Sankalpa Gadya", ["sankalpa gadya"]),
    ("SriJayateertha (Teekacharya) Charitra", ["teekacharya", "teekachrayara", "teekachrya"]),
    ("SriJayateertha Swamiji (Charitra/Mahima)", ["jayateertha"]),
    ("SriRaghoottama Teertha", ["raghoottama", "raghottama"]),
    ("SriRaghavendra Swami", ["raghavendra"]),
    ("Vighnesha Sandhi (NKHK)", ["vighnesha sandhi", "vighnesh sandhi"]),
    ("Srinivasa Kalyana (NKHK)", ["srinivasa kalyana", "srinivasakalyana"]),
    ("Deva Pooja (NKHK)", ["devapooja", "deva pooja", "devara pooja"]),
    ("28 Moorthi Stuti (NKHK)", ["28moorthi", "28 moorthi", "28moorti"]),
    ("Navabrindavana Mahima (NKHK)", ["navabrindavana", "navavrindavana", "navabrindavan"]),
    ("Sri Gopaladasara Charitre", ["gopaladasara"]),
    ("Satyadhyana/Satyagnana Teertha Charitra", ["satyadhyana", "satyagnanateertha", "satyagnana"]),
    ("Sripadaraja/Satyabhinava Teertha", ["sripadarajateertha", "satyabhinva", "satyabhinava", "sripadaraja"]),
    ("Sandhyavandana Satsanga", ["sandhyavandana satsanga", "kondapur"]),
    ("Sandhyavandana (Other)", ["sandhyavandana"]),
    ("Dhyana (NKHK)", ["dhyana"]),
    ("Anusandhana", ["anusandhana"]),
    ("Narasimha Stuti/Stotra", ["narasimha"]),
    ("Purushottama Stotra", ["purushottama"]),
    ("Tulasi Stotra", ["tulasi"]),
    ("Taratamya (NKHK)", ["taratamya"]),
    ("Harikathamruta Sara", ["harikathamruta"]),
    ("Panchanga Shravana", ["panchanga"]),
    ("Paranjyothi Satsanga", ["paranjyothi"]),
    ("Pushpahasa Satsanga", ["pushpahasa"]),
    ("Adhika Masa Mahatmya", ["adhika masa", "adhikamasa"]),
    ("Ganesha Stotra", ["ganesha", "ganesh dwadash"]),
    ("Ekadashi Katha", ["ekadashi"]),
    ("NKHK Satsanga (Other)", ["satsanga", "satsang"]),
    ("Naham Karta Hari Karta (Meeting Room)", ["naham karta"]),
    ("NKHK (Other)", ["nkhk"]),
]

# Each key maps to its month number; listed variants are matched longest-first
# so e.g. "june" is tried before the ambiguous 3-letter "jun" abbreviation
# (this also avoids "mar" wrongly matching inside words like "Marathi", since
# the alternation is anchored where it's used and doesn't rely on \b alone -
# a plain \b doesn't sit between "jun" and the following "e" in "june").
_MONTH_VARIANTS = {
    1: ["january", "jan"], 2: ["february", "feb"], 3: ["march", "mar"],
    4: ["april", "apr"], 5: ["may"], 6: ["june", "jun"],
    7: ["july", "jul"], 8: ["august", "aug"], 9: ["september", "sept", "sep"],
    10: ["october", "oct"], 11: ["november", "nov"], 12: ["december", "dec"],
}
MONTHS = {}
_alts = []
for _num, _variants in _MONTH_VARIANTS.items():
    for _v in _variants:
        MONTHS[_v] = _num
        _alts.append(_v)
_alts.sort(key=len, reverse=True)  # longest alternative first, so "june" wins over "jun"
MONTH_RE = "|".join(_alts)

# "4th June 2026" / "3rd Sep2026" / "5th July2026" (day, then month name, then
# optional year with or without a space before it)
DAY_FIRST_RE = re.compile(rf"(\d{{1,2}})\s*(?:st|nd|rd|th)?\.?\s*({MONTH_RE})\.?\s*(\d{{4}}|\d{{2}})?", re.I)
# "Oct 2nd 2023" / "May 8th 2026" (month name first, then day, then optional year)
MONTH_FIRST_RE = re.compile(rf"({MONTH_RE})\.?\s*(\d{{1,2}})\s*(?:st|nd|rd|th)?\.?\s*[,]?\s*(\d{{4}}|\d{{2}})?", re.I)
MONTH_YEAR_RE = re.compile(rf"({MONTH_RE})\.?\s+(\d{{4}})", re.I)


def categorize(title: str) -> str:
    t = title.lower()
    if "jayateertha" in t and ("stuti" in t or "stotra" in t) and not any(
        k in t for k in ["teekacharya", "teekachrayara", "teekachrya"]
    ):
        return "SriJayateertha Stuti"
    if "krishna" in t and any(k in t for k in ["stotra", "stuti", "ashtottara", "ashtaka"]):
        return "SriKrishna Stotra/Stuti"
    if "dhyana" in t and "anusandhana" in t:
        return "Anusandhana + Dhyana (NKHK)"
    for category, needles in RULES:
        if any(n in t for n in needles):
            return category
    return "Uncategorized / Other"


def _norm_year(year_str):
    if not year_str:
        return None
    yr = int(year_str)
    return yr + 2000 if yr < 100 else yr


def parse_title_date(title: str):
    """Return (day_or_None, month_num_or_None, year_or_None) parsed from the title.
    Tries day-before-month ("4th June 2026") first, then month-before-day
    ("Oct 2nd 2023"), then a bare "month year" with no day at all."""
    m = DAY_FIRST_RE.search(title)
    if m:
        day, mon, year = m.groups()
        return int(day), MONTHS[mon.lower()], _norm_year(year)
    m2 = MONTH_FIRST_RE.search(title)
    if m2:
        mon, day, year = m2.groups()
        return int(day), MONTHS[mon.lower()], _norm_year(year)
    m3 = MONTH_YEAR_RE.search(title)
    if m3:
        mon, year = m3.groups()
        return None, MONTHS[mon.lower()], int(year)
    return None, None, None


def resolve_dates(entries):
    """Walk the channel's own newest-first order and fill in missing years by
    carrying the most recently seen year forward, decrementing it when the
    month sequence implies a year boundary was crossed. Returns a list of
    dicts aligned with `entries`, each with day/month/year (any may be None)
    and a formatted `date` string ("YYYY-MM-DD", "YYYY-MM", or "Unknown")."""
    parsed = []
    for e in entries:
        day, mon, year = parse_title_date(e["title"])
        parsed.append({"id": e["id"], "day": day, "mon": mon, "year": year})

    current_year = None
    last_month_with_year = None
    for i, p in enumerate(parsed):
        if p["year"] is not None:
            current_year = p["year"]
            if p["mon"] is not None:
                last_month_with_year = p["mon"]
        elif p["mon"] is not None and current_year is not None:
            if last_month_with_year is not None and p["mon"] > last_month_with_year + 1:
                current_year -= 1
            p["year"] = current_year
            last_month_with_year = p["mon"]

    out = []
    for p in parsed:
        if p["day"] and p["mon"] and p["year"]:
            date_str = f"{p['year']:04d}-{p['mon']:02d}-{p['day']:02d}"
        elif p["mon"] and p["year"]:
            date_str = f"{p['year']:04d}-{p['mon']:02d}"
        else:
            date_str = "Unknown"
        out.append(date_str)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="infile", default="data/raw_playlist.json")
    ap.add_argument("--outdir", default="output")
    args = ap.parse_args()

    raw = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    entries = raw.get("entries", [])
    dates = resolve_dates(entries)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows = []
    for pos, (e, date_str) in enumerate(zip(entries, dates)):
        rows.append({
            "list_position": pos + 1,  # 1 = most recent, per the channel's own newest-first order
            "date": date_str,
            "category": categorize(e.get("title", "")),
            "title": e.get("title", ""),
            "video_id": e.get("id", ""),
            "url": f"https://www.youtube.com/watch?v={e.get('id', '')}",
            "duration_min": round((e.get("duration") or 0) / 60, 1),
            "view_count": e.get("view_count") or 0,
        })

    # ---- Master CSV / JSON: every stream, newest-first (the channel's own order) ----
    master_csv = outdir / "streams_master.csv"
    with master_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (outdir / "streams_master.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- Grouped by category (each category's own list kept newest-first) ----
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    grouped = dict(sorted(by_cat.items(), key=lambda x: -len(x[1])))
    (outdir / "streams_by_category.json").write_text(
        json.dumps(grouped, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    cat_dir = outdir / "by_category"
    cat_dir.mkdir(exist_ok=True)
    for cat, items in grouped.items():
        safe = re.sub(r"[^A-Za-z0-9]+", "_", cat).strip("_")
        with (cat_dir / f"{safe}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(items[0].keys()))
            w.writeheader()
            w.writerows(items)

    unknown_dates = sum(1 for r in rows if r["date"] == "Unknown")

    # ---- Markdown catalog (human-browsable) ----
    lines = [
        "# Sripad K — Streams Catalog",
        "",
        f"Auto-generated from the channel's Streams tab "
        f"(**{raw.get('channel')}**, {raw.get('channel_follower_count')} subscribers).",
        f"Total streams: **{len(rows)}** across **{len(grouped)}** categories.",
        "",
        "Categorization is by title-keyword matching (see `src/categorize.py`) — it groups",
        "recurring series by name rather than by manually reviewing each stream. A",
        "description-based grouping wasn't possible: every video on this channel currently",
        "has an empty description.",
        "",
        f"Dates are parsed from the title text where possible; {unknown_dates} stream(s) had no",
        "parseable date and are marked **Unknown** rather than guessed — see `src/categorize.py`",
        "for exactly how dates are resolved, including the year-carry-forward logic.",
        "",
        "## Category index",
        "",
        "| Category | Count |",
        "|---|---|",
    ]
    for cat, items in grouped.items():
        anchor = re.sub(r"[^a-z0-9]+", "-", cat.lower()).strip("-")
        lines.append(f"| [{cat}](#{anchor}) | {len(items)} |")
    lines.append("")

    for cat, items in grouped.items():
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Date | Title | Duration | Views | Link |")
        lines.append("|---|---|---|---|---|")
        for r in items:
            lines.append(
                f"| {r['date']} | {r['title']} | {r['duration_min']}m | "
                f"{r['view_count']} | [watch]({r['url']}) |"
            )
        lines.append("")

    (outdir / "CATALOG.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"{len(rows)} streams -> {len(grouped)} categories ({unknown_dates} with unresolved dates)")
    print(f"Wrote: {master_csv}, streams_master.json, streams_by_category.json, CATALOG.md, by_category/*.csv")


if __name__ == "__main__":
    main()
