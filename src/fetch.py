#!/usr/bin/env python3
"""
fetch.py - Pull the full stream list (title, video id, date, duration, view
count) from a YouTube channel's Streams tab, via yt-dlp, and save it as raw
JSON for categorize.py to process.

Usage:
    python3 fetch.py [--url URL] [--out data/raw_playlist.json]

Notes:
- Uses yt-dlp's --flat-playlist mode: fast (a single request), gives every
  video's title/id/duration/view_count without visiting each video page
  individually. The channel lists streams newest-first; that ordering is
  preserved and used later to resolve dates that can't be fully parsed
  from the title text alone (see categorize.py).
- Deliberately does NOT pass --extractor-args "youtubetab:approximate_date".
  That flag sounds like it would help (it asks for a per-entry upload
  timestamp) but on this channel it returned a small number of distinct
  "bucket" timestamps reused across dozens of unrelated videos (e.g. one
  single fake date shared by 67 different streams) - not real per-video
  dates. Real per-video dates require opening every video page individually
  (~4-5s each with cookie auth), which would take ~25+ minutes for a
  342-video channel; --flat-playlist + title-parsing is the practical
  tradeoff. Where a title has no parseable date at all, the catalog marks
  it "Unknown" rather than guessing.
- Descriptions are NOT fetched: a spot-check across a sample of this
  channel's videos found every description empty (0 bytes), so there is
  nothing to organize from them. Only titles carry the retrievable
  metadata here - see the README for detail.
- --cookies-from-browser reads cookies locally from your own Chrome
  profile to satisfy YouTube's bot-check; nothing is uploaded or sent
  anywhere beyond the normal request to YouTube.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_URL = "https://www.youtube.com/@sripadk8492/streams"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL, help="Channel streams URL")
    ap.add_argument("--out", default="data/raw_playlist.json", help="Output JSON path")
    ap.add_argument("--browser", default="chrome", help="Browser to read cookies from (chrome/firefox/safari/edge)")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        "--cookies-from-browser", args.browser,
        "--flat-playlist",
        "--dump-single-json",
        args.url,
    ]
    print("Running:", " ".join(cmd), file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    data = json.loads(result.stdout)
    entries = data.get("entries", [])
    print(f"Fetched {len(entries)} streams from '{data.get('channel')}'.", file=sys.stderr)

    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved raw playlist JSON -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
