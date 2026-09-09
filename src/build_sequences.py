#!/usr/bin/env python3
"""
build_sequences.py - Turn the flat, categorized stream list into WATCH-ORDER
SEQUENCES, grouped by (category, language), and write the single JSON file the
search page reads.

Usage:
    python3 src/build_sequences.py [--in output/streams_master.json]
                                   [--out output/sequences.json]

The problem this solves (beyond categorization): within one category, videos
in different languages are separate, independently-numbered tracks. For
example "Satyatma Sandhya" interleaves an English Day1..Day10+ run, a Kannada
Day1..Final Day run, and a Marathi Day1..Day4 run - three unrelated sequences
that happen to share a category. Flattening them into one date-sorted list
misorders every one of them, so the unit of "a sequence" here is
(category, language), not category alone.

Ordering within a sequence:
    The OLDEST video comes first (seq 1) and the newest last, because that is
    watch order for a lecture series. The sort key is `list_position` - the
    video's index in the channel's own newest-first listing, where 1 is the
    newest video on the channel - rather than the resolved date, because
    `list_position` is present and unambiguous for every video while a date
    can be missing or only month-precise. A higher `list_position` means an
    older video, so sorting by it descending gives oldest-first.

Language detection:
    A plain substring search for a known language name anywhere in the
    lowercased title, deliberately NOT word-tokenized, because several titles
    push the language name straight onto an adjacent word with no separator
    (e.g. "Sandhyavandanakannada"). A video with no recognizable language name
    joins an unlabelled group for its category; it is never guessed into a
    specific language.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import catalog_paths

LANGUAGES = ["kannada", "english", "marathi", "hindi", "telugu", "tamil", "sanskrit"]

REQUIRED_FIELDS = ("category", "title", "list_position", "date", "video_id", "url")

_WORD_RE = re.compile(r"[a-z0-9]+")


def detect_language(title: str) -> str | None:
    """Return the first known language named in `title`, or None."""
    lowered = title.lower()
    for language in LANGUAGES:
        if language in lowered:
            return language
    return None


def category_names_language(category: str) -> str | None:
    """Return the language a category name already states, e.g. "Manimanjari (Kannada)".

    When a category names its own language, the language dimension is folded
    into the category instead of being split on. Otherwise a video in that
    category whose *title* also happens to say "Kannada" would break off into
    a second group with an identical label, splitting one single-language
    series into two.
    """
    lowered = category.lower()
    for language in LANGUAGES:
        if f"({language})" in lowered:
            return language
    return None


def normalize_words(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens for the search index."""
    return _WORD_RE.findall(text.lower())


def sequence_label(category: str, language: str | None) -> str:
    """Build the display label, avoiding a redundant "(Kannada) (Kannada)"."""
    if language and f"({language})" not in category.lower():
        return f"{category} ({language.title()})"
    return category


def build_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group rows into (category, language) sequences, ordered oldest-first."""
    groups_map: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        category = row["category"]
        language = category_names_language(category) or detect_language(row["title"])
        groups_map[(category, language)].append(row)

    groups = []
    for (category, language), items in groups_map.items():
        # list_position 1 is the newest video, so descending gives oldest-first.
        ordered = sorted(items, key=lambda row: row["list_position"], reverse=True)

        search_text = " ".join([
            category.lower(),
            language or "",
            *(item["title"].lower() for item in ordered),
        ])

        videos = [
            {
                "seq": index,
                "total": len(ordered),
                "date": row["date"],
                "title": row["title"],
                "video_id": row["video_id"],
                "url": row["url"],
                "duration_min": row.get("duration_min", 0),
                "view_count": row.get("view_count", 0),
            }
            for index, row in enumerate(ordered, start=1)
        ]

        groups.append({
            "category": category,
            "language": language,
            "label": sequence_label(category, language),
            "count": len(videos),
            "search_text": search_text,
            "search_words": sorted(set(normalize_words(search_text))),
            "videos": videos,
        })

    # Largest sequences first, so the output file is easy to skim by eye. The
    # secondary key on the label keeps the order stable across runs.
    groups.sort(key=lambda group: (-group["count"], group["label"]))
    return groups


def _validate(rows: object) -> list[dict[str, Any]]:
    """Check the master-table shape before relying on it, with a clear error."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("expected a non-empty JSON array of stream rows")
    missing = [field for field in REQUIRED_FIELDS if field not in rows[0]]
    if missing:
        raise ValueError(f"stream rows are missing required field(s): {', '.join(missing)}")
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="infile", default=str(catalog_paths.STREAMS_MASTER_JSON),
                        help="Master stream table written by categorize.py")
    parser.add_argument("--out", dest="outfile", default=str(catalog_paths.SEQUENCES_JSON),
                        help="Sequence JSON file the search page loads")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    infile = catalog_paths.resolve(args.infile)
    if not infile.exists():
        print(f"error: {infile} not found - run categorize.py first.", file=sys.stderr)
        return 1
    try:
        rows = _validate(json.loads(infile.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError) as err:
        print(f"error: cannot use {infile}: {err}", file=sys.stderr)
        return 1

    groups = build_groups(rows)

    out_path: Path = catalog_paths.resolve(args.outfile)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"groups": groups}, indent=2, ensure_ascii=False), encoding="utf-8")

    multi = sum(1 for group in groups if group["count"] > 1)
    print(f"{len(rows)} videos -> {len(groups)} sequences "
          f"({multi} with 2+ videos, {len(groups) - multi} single-video)")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
