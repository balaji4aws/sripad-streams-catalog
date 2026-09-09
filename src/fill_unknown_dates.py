#!/usr/bin/env python3
"""
fill_unknown_dates.py - For videos whose title carries no parseable date (see
categorize.py's resolve_dates()), fetch each video's REAL YouTube publish date
individually and save it to a small lookup file. categorize.py reads that
lookup and uses it as a fallback wherever the title alone leaves a video's
date "Unknown".

Why this is a separate, small step instead of just fetching every video's real
date in fetch.py: fetch.py deliberately avoids opening all 342 video pages
individually, because each one takes several seconds with the login this
channel needs, so all 342 would take 25+ minutes (see fetch.py's docstring).
Only a SMALL number of videos actually need the per-video fetch - the ones
whose title gave nothing to work with. Doing it just for those keeps the
one-time cost to well under a minute while still recovering a real date.

Usage:
    python3 src/fill_unknown_dates.py [--in output/streams_master.json]
                                      [--out data/known_upload_dates.json]
                                      [--browser chrome] [--timeout 60]

Run this AFTER categorize.py (it reads streams_master.json to learn which
video IDs currently have an Unknown date), then re-run categorize.py so the
newly filled dates flow into all of its output files.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import catalog_paths

UNKNOWN_DATE = "Unknown"
DEFAULT_TIMEOUT_SECONDS = 60
_YT_DLP_DATE_LENGTH = 8  # yt-dlp's %(upload_date)s is YYYYMMDD


def load_existing(path: Path) -> dict[str, str]:
    """Load the already-fetched lookup, tolerating a missing or unreadable file."""
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        print(f"warning: {path} is not valid JSON ({err}); starting a fresh lookup.", file=sys.stderr)
        return {}
    if not isinstance(loaded, dict):
        print(f"warning: {path} is not a JSON object; starting a fresh lookup.", file=sys.stderr)
        return {}
    return {str(key): str(value) for key, value in loaded.items()}


def format_upload_date(raw: str) -> str | None:
    """Convert yt-dlp's YYYYMMDD upload date to the YYYY-MM-DD used elsewhere."""
    raw = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if len(raw) != _YT_DLP_DATE_LENGTH or not raw.isdigit():
        return None
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def fetch_upload_date(video_id: str, browser: str, timeout: int) -> str | None:
    """Fetch one video's real upload date, or None if it can't be determined."""
    command = [
        "yt-dlp", "--cookies-from-browser", browser,
        "--skip-download", "--print", "%(upload_date)s",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return format_upload_date(result.stdout)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="infile", default=str(catalog_paths.STREAMS_MASTER_JSON),
                        help="Master stream table written by categorize.py")
    parser.add_argument("--out", dest="outfile", default=str(catalog_paths.KNOWN_UPLOAD_DATES),
                        help="Lookup file to create or extend")
    parser.add_argument("--browser", default="chrome", help="Browser to read cookies from")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                        help="Seconds to wait per video before skipping it")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    infile = catalog_paths.resolve(args.infile)
    if not infile.exists():
        print(f"error: {infile} not found - run categorize.py first.", file=sys.stderr)
        return 1
    try:
        rows: Any = json.loads(infile.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        print(f"error: {infile} is not valid JSON: {err}", file=sys.stderr)
        return 1
    if not isinstance(rows, list):
        print(f"error: {infile} should contain a JSON array of stream rows.", file=sys.stderr)
        return 1

    out_path: Path = catalog_paths.resolve(args.outfile)
    known = load_existing(out_path)

    unknown = [row for row in rows if row.get("date") == UNKNOWN_DATE]
    to_fetch = [row for row in unknown if row.get("video_id") and row["video_id"] not in known]
    print(f"{len(unknown)} video(s) currently marked {UNKNOWN_DATE}; "
          f"{len(to_fetch)} not yet in {out_path} - fetching those now.", file=sys.stderr)

    if not to_fetch:
        print("Nothing to fetch.", file=sys.stderr)
        return 0

    fetched = 0
    for row in to_fetch:
        video_id = row["video_id"]
        try:
            upload_date = fetch_upload_date(video_id, args.browser, args.timeout)
        except FileNotFoundError:
            print("error: yt-dlp not found on PATH. Install it with 'brew install yt-dlp' "
                  "or 'pip install yt-dlp'.", file=sys.stderr)
            return 1
        if upload_date is None:
            print(f"  [skip] {video_id}: could not fetch a real upload date ({row.get('title', '')!r})",
                  file=sys.stderr)
            continue
        known[video_id] = upload_date
        fetched += 1
        print(f"  [ok] {video_id}: {upload_date}  ({row.get('title', '')!r})", file=sys.stderr)

    if fetched:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(known, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nWrote {len(known)} known upload date(s) -> {out_path}", file=sys.stderr)
        print("Re-run categorize.py now so these flow into the catalog.", file=sys.stderr)
    else:
        print(f"\nNo new dates fetched; {out_path} left unchanged.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
