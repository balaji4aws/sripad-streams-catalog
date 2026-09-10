#!/usr/bin/env python3
"""
fetch.py - Pull the channel's full video list (title, video id, duration, view
count) from every tab that holds recordings, via yt-dlp, and save it as raw
JSON for categorize.py to process.

Usage:
    python3 src/fetch.py [--channel URL] [--tabs streams,videos]
                         [--out data/raw_playlist.json]
                         [--browser chrome] [--timeout 300]

Why two tabs: YouTube splits this channel's recordings across /streams (live
sessions) and /videos (regular uploads), and a series can appear on BOTH - the
Pratah Sankalpa Gadya sessions are split across the two, so reading only one
tab shows a viewer an incomplete sequence with no sign that anything is
missing. Each tab is fetched separately, because that is how YouTube exposes
them, and every entry is tagged with the tab it came from plus its position
within that tab. categorize.py needs both facts to merge the two lists into a
single ordering (see its `_merge_sources`).

Notes:
- Uses yt-dlp's --flat-playlist mode: one request per tab, fast, and it returns
  every video's title/id/duration/view_count without visiting each video page
  individually. Each tab lists newest-first; that ordering is preserved and
  used later to resolve dates that can't be fully parsed from the title text
  alone (see categorize.py).
- Deliberately does NOT pass --extractor-args "youtubetab:approximate_date".
  That flag sounds like exactly what's needed (it asks for a per-entry upload
  timestamp) but on this channel it returned a small number of distinct
  "bucket" timestamps reused across dozens of unrelated videos - one single
  fake date was shared by 67 different streams - not real per-video dates.
  Real per-video dates require opening every video page individually (~4-5s
  each with cookie auth), which would take well over half an hour for a
  465-video channel. --flat-playlist plus title parsing is the practical
  tradeoff. Where a title carries no parseable date at all, the catalog either
  falls back to a real fetched upload date (see fill_unknown_dates.py) or marks
  the video "Unknown" rather than guessing.
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
from typing import Any

import catalog_paths

DEFAULT_CHANNEL = "https://www.youtube.com/@sripadk8492"
#: Tabs that hold recordings, in the order they are stored. /shorts is skipped:
#: it was checked and is empty on this channel.
DEFAULT_TABS = ("streams", "videos")
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


def fetch_tab(channel: str, tab: str, browser: str, timeout: int) -> dict[str, Any]:
    """Fetch one channel tab. Raises RuntimeError with a readable message on failure."""
    url = f"{channel.rstrip('/')}/{tab}"
    command = build_command(url, browser)
    print(f"Fetching /{tab}: {' '.join(command)}", file=sys.stderr)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as err:
        raise RuntimeError(
            "yt-dlp not found on PATH. Install it with 'brew install yt-dlp' or 'pip install yt-dlp'."
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"yt-dlp did not finish /{tab} within {timeout}s. Re-run with a longer --timeout.") from err

    if result.returncode != 0:
        raise RuntimeError(f"{result.stderr.strip()}\nyt-dlp exited with status {result.returncode} for /{tab}.")
    try:
        parsed: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"yt-dlp returned output for /{tab} that is not valid JSON: {err}") from err
    return parsed


def merge_tabs(tabs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Combine per-tab results into one payload.

    Every entry gains two fields the downstream steps rely on:

      _source           the tab it came from ("streams" or "videos")
      _source_position  its 1-based place in that tab's own newest-first list

    Both are needed because the tabs are separate lists: position 1 of /streams
    and position 1 of /videos are unrelated, so a single position number across
    the whole channel would be meaningless. categorize.py resolves dates within
    each tab and then merges the two into one ordering.
    """
    merged_entries = []
    counts = {}
    first = next(iter(tabs.values()))

    for tab_name, payload in tabs.items():
        entries = payload.get("entries") or []
        counts[tab_name] = len(entries)
        for position, entry in enumerate(entries, start=1):
            merged_entries.append({**entry, "_source": tab_name, "_source_position": position})

    return {
        "channel": first.get("channel"),
        "channel_id": first.get("channel_id"),
        "channel_url": first.get("channel_url"),
        "channel_follower_count": first.get("channel_follower_count"),
        # The tab each fetch actually came from, and how many it held. Recorded so
        # a later reader can see the split without recounting.
        "tabs": counts,
        "webpage_url": first.get("webpage_url"),
        "epoch": first.get("epoch"),
        "entries": merged_entries,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help="Channel URL, without a tab suffix")
    parser.add_argument("--tabs", default=",".join(DEFAULT_TABS),
                        help="Comma-separated channel tabs to fetch")
    parser.add_argument("--out", default=str(catalog_paths.RAW_PLAYLIST), help="Output JSON path")
    parser.add_argument("--browser", default="chrome",
                        help="Browser to read cookies from (chrome/firefox/safari/edge)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                        help="Seconds to wait per tab for yt-dlp before giving up")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tab_names = [tab.strip() for tab in args.tabs.split(",") if tab.strip()]
    if not tab_names:
        print("error: --tabs listed no tabs to fetch.", file=sys.stderr)
        return 1

    out_path: Path = catalog_paths.resolve(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, Any]] = {}
    for tab in tab_names:
        try:
            results[tab] = fetch_tab(args.channel, tab, args.browser, args.timeout)
        except RuntimeError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        found = len(results[tab].get("entries") or [])
        print(f"  /{tab}: {found} videos", file=sys.stderr)

    data = merge_tabs(results)
    total = len(data["entries"])
    if total == 0:
        print("error: no videos found on any tab. Check --channel, and that the browser given by "
              "--browser is logged into YouTube.", file=sys.stderr)
        return 1

    breakdown = ", ".join(f"{count} from /{tab}" for tab, count in data["tabs"].items())
    print(f"Fetched {total} videos from '{data.get('channel', 'unknown channel')}' ({breakdown}).",
          file=sys.stderr)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved raw playlist JSON -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
