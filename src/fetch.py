#!/usr/bin/env python3
"""
fetch.py - Pull the full stream list (title, video id, duration, view count)
from a YouTube channel's Streams tab via yt-dlp, and save it as raw JSON for
categorize.py to process.

Usage:
    python3 src/fetch.py [--url URL] [--out data/raw_playlist.json]
                         [--browser chrome] [--timeout 300]

Notes:
- Uses yt-dlp's --flat-playlist mode: one request, fast, and it returns every
  video's title/id/duration/view_count without visiting each video page
  individually. The channel lists streams newest-first; that ordering is
  preserved and used later to resolve dates that can't be fully parsed from
  the title text alone (see categorize.py).
- Deliberately does NOT pass --extractor-args "youtubetab:approximate_date".
  That flag sounds like exactly what's needed (it asks for a per-entry upload
  timestamp) but on this channel it returned a small number of distinct
  "bucket" timestamps reused across dozens of unrelated videos - one single
  fake date was shared by 67 different streams - not real per-video dates.
  Real per-video dates require opening every video page individually (~4-5s
  each with cookie auth), which would take 25+ minutes for a 342-video
  channel. --flat-playlist plus title parsing is the practical tradeoff.
  Where a title carries no parseable date at all, the catalog either falls
  back to a real fetched upload date (see fill_unknown_dates.py) or marks the
  video "Unknown" rather than guessing.
- Descriptions are NOT fetched: a spot-check across a sample of this channel's
  videos found every description empty (0 bytes), so there is nothing to
  organize from them. Titles carry all the retrievable metadata here.
- --cookies-from-browser reads cookies locally from your own browser profile
  to satisfy YouTube's bot check. Nothing is uploaded or sent anywhere beyond
  the normal request to YouTube.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import catalog_paths

DEFAULT_URL = "https://www.youtube.com/@sripadk8492/streams"
DEFAULT_TIMEOUT_SECONDS = 300


def build_command(url: str, browser: str) -> list[str]:
    """Assemble the yt-dlp invocation for a one-shot flat playlist dump."""
    return [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "--flat-playlist",
        "--dump-single-json",
        url,
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL, help="Channel streams URL")
    parser.add_argument("--out", default=str(catalog_paths.RAW_PLAYLIST), help="Output JSON path")
    parser.add_argument("--browser", default="chrome",
                        help="Browser to read cookies from (chrome/firefox/safari/edge)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                        help="Seconds to wait for yt-dlp before giving up")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    out_path: Path = catalog_paths.resolve(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    command = build_command(args.url, args.browser)
    print("Running:", " ".join(command), file=sys.stderr)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout, check=False)
    except FileNotFoundError:
        print("error: yt-dlp not found on PATH. Install it with 'brew install yt-dlp' "
              "or 'pip install yt-dlp'.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(f"error: yt-dlp did not finish within {args.timeout}s. "
              f"Re-run with a longer --timeout.", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        print(f"error: yt-dlp exited with status {result.returncode}.", file=sys.stderr)
        return 1

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as err:
        print(f"error: yt-dlp returned output that is not valid JSON: {err}", file=sys.stderr)
        return 1

    entries = data.get("entries") or []
    if not entries:
        print("error: yt-dlp returned no videos. Check the --url, and that the browser "
              "given by --browser is logged into YouTube.", file=sys.stderr)
        return 1

    print(f"Fetched {len(entries)} streams from '{data.get('channel', 'unknown channel')}'.", file=sys.stderr)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved raw playlist JSON -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
