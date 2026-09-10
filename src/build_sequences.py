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
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import catalog_paths

LANGUAGES = ["kannada", "english", "marathi", "hindi", "telugu", "tamil", "sanskrit"]

#: Shown in place of a language when a title names none. The language is never
#: inferred from anything other than the title text.
UNKNOWN_LANGUAGE_LABEL = "Language not stated"

REQUIRED_FIELDS = ("category", "title", "list_position", "date", "video_id", "url")

#: Unicode categories for combining marks - the matras and the virama that
#: Devanagari uses to build a syllable. They are not alphanumeric, so a word
#: like "अध्यात्मप्रकरण" splits into fragments without them. Python's `re` has no
#: \p{M}, hence the explicit check in normalize_words().
_COMBINING_CATEGORIES = frozenset({"Mn", "Mc"})

# A "Day N" session label. The number must NOT carry an ordinal suffix: "Day 6"
# is session six, but "Final Day 24th June" is a date that happens to sit after
# the word "Day". This is the same distinction categorize.py draws when parsing
# dates, for the same reason.
# The `(?!\d)` matters: without it the engine backtracks to a shorter digit run
# to satisfy the ordinal guard, so "Final Day 24th June" yields session 2 by
# matching just the "2" and finding "4th" acceptable after it.
_SESSION_RE = re.compile(r"(?:^|[^a-z])day[\s\-_:.]*(\d{1,3})(?!\d)(?!\s*(?:st|nd|rd|th)\b)", re.I)

# A part number attached to a session label: "Day 32(4)". Anchored to the day
# label so a verse number elsewhere in the title ("Shloka 48(2)") is not read as
# a part.
_SESSION_PART_RE = re.compile(r"(?:^|[^a-z])day[\s\-_:.]*\d{1,3}\s*\((\d{1,2})\)", re.I)


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


def _is_word_character(char: str) -> bool:
    """True for a letter or digit in any script, or a combining mark."""
    return char.isalnum() or unicodedata.category(char) in _COMBINING_CATEGORIES


def normalize_words(text: str) -> list[str]:
    """Split text into lowercase words for the search index.

    Words in any script, not just Latin: the /videos titles carry Devanagari
    section names ("अध्यात्मप्रकरण") which an ASCII-only tokenizer dropped
    entirely, leaving those terms unsearchable. Combining marks count as part of
    a word, or a Devanagari syllable would break apart at every matra and fill
    the index with fragments.

    Must stay in step with tokenize() in search.js, which does the same job on
    the query side with \\p{L}, \\p{N} and \\p{M}.
    """
    words: list[str] = []
    current: list[str] = []
    for char in text.lower():
        if _is_word_character(char):
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def session_number(title: str) -> int | None:
    """Return the "Day N" session number stated in a title, or None."""
    match = _SESSION_RE.search(title)
    return int(match.group(1)) if match else None


def session_part(title: str) -> int:
    """Return the part number from a split session, or 0 when there is none.

    One session can be uploaded as several videos: "Day 32(1)" through
    "Day 32(5)", five short videos covering consecutive verses of the same
    sitting. Without reading that bracketed number they all share session 32
    and fall back to channel position, which puts them in the order the channel
    happened to list them - shlokas 71, 73, 75, 74, 72 in the case above.

    The bracket must directly follow the day label. Verse numbers elsewhere in a
    title, like "Shloka 48(2)", are not part numbers and must not be read as one.
    """
    match = _SESSION_PART_RE.search(title)
    return int(match.group(1)) if match else 0


def order_videos(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put a sequence's videos into watch order, oldest first.

    Two signals, and the choice between them matters.

    Where EVERY video in the sequence states a session number - "Day 1",
    "Day 2", and so on - that number is used. It is the teacher's own statement
    of the order, which beats anything this project could infer. It matters in
    practice: the 108-session Bhagavata Saroddhara series is listed by the
    channel in an order that contradicts its own day numbers in ten places, and
    several of its dates carry typos ("3oth Nov", and a "2024" that plainly
    means 2025). The day numbers run 1 to 102 with no gaps.

    Otherwise the merged channel position is used, highest first, since
    position 1 is the newest video. Most series on this channel do not number
    their sessions, so this remains the common path - and it is deliberately
    preferred over sorting by date, because a handful of titles state a date
    that contradicts where the channel itself placed the video.

    Requiring the number on EVERY video, rather than most, is the safe choice: a
    sequence where only some titles are numbered would interleave numbered and
    unnumbered videos on incomparable keys.
    """
    numbers = [session_number(item["title"]) for item in items]
    if len(items) > 1 and all(number is not None for number in numbers):
        # Sort by session, then by part within a split session, then by channel
        # position (oldest first) so a genuinely duplicated upload is still
        # ordered deterministically.
        decorated = [
            (number, session_part(item["title"]), -item["list_position"], index)
            for index, (number, item) in enumerate(zip(numbers, items, strict=True))
        ]
        return [items[key[-1]] for key in sorted(decorated)]
    return sorted(items, key=lambda item: item["list_position"], reverse=True)


def sequence_label(category: str, language: str | None, *, has_language_siblings: bool = False) -> str:
    """Build the display label for a sequence.

    Avoids a redundant "(Kannada) (Kannada)" when the category name already
    states the language.

    When a video's title names no language, the language is left unknown rather
    than guessed. That is only worth saying out loud when the same category ALSO
    produced language-specific sequences: there, a bare "Satyatma Sandhya"
    sitting beside "Satyatma Sandhya (Kannada)" reads as if the language were
    missing from the tool rather than from the source titles, so it is labelled
    explicitly. Where a whole category names no language anywhere, the marker
    would be noise on every one of its sequences, so it is omitted.
    """
    if language:
        return category if f"({language})" in category.lower() else f"{category} ({language.title()})"
    return f"{category} ({UNKNOWN_LANGUAGE_LABEL})" if has_language_siblings else category


def build_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group rows into (category, language) sequences, ordered oldest-first."""
    groups_map: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        category = row["category"]
        language = category_names_language(category) or detect_language(row["title"])
        groups_map[(category, language)].append(row)

    # Categories that produced at least one language-specific sequence. Used to
    # decide whether an unknown-language sequence needs to say so - see
    # sequence_label().
    categories_with_a_language = {
        category for (category, language) in groups_map if language is not None
    }

    groups: list[dict[str, Any]] = []
    for (category, language), items in groups_map.items():
        ordered = order_videos(items)

        # Only the word list is published. The joined text it is built from was
        # also written out originally, but nothing ever read it - it was 26 KB of
        # the file the page downloads on every visit.
        searchable = " ".join([
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
            "label": sequence_label(
                category, language,
                has_language_siblings=category in categories_with_a_language,
            ),
            "count": len(videos),
            "search_words": sorted(set(normalize_words(searchable))),
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


def load_meta(path: Path) -> dict[str, Any]:
    """Load the catalog summary categorize.py wrote, if it is there.

    It is folded into sequences.json so the search page can show how current the
    catalog is without a second request. Missing or unreadable metadata is not
    fatal: the sequences are still perfectly usable without it.
    """
    if not path.exists():
        print(f"warning: {path} not found; the page will not show a scan date.", file=sys.stderr)
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        print(f"warning: ignoring unreadable {path}: {err}", file=sys.stderr)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="infile", default=str(catalog_paths.STREAMS_MASTER_JSON),
                        help="Master stream table written by categorize.py")
    parser.add_argument("--out", dest="outfile", default=str(catalog_paths.SEQUENCES_JSON),
                        help="Sequence JSON file the search page loads")
    parser.add_argument("--meta", dest="metafile", default=str(catalog_paths.CATALOG_META_JSON),
                        help="Catalog summary written by categorize.py")
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
    meta = load_meta(catalog_paths.resolve(args.metafile))

    out_path: Path = catalog_paths.resolve(args.outfile)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"meta": meta, "groups": groups}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    multi = sum(1 for group in groups if group["count"] > 1)
    print(f"{len(rows)} videos -> {len(groups)} sequences "
          f"({multi} with 2+ videos, {len(groups) - multi} single-video)")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
