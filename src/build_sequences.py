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

#: Language name to the spellings that appear in titles, longest first so a full
#: spelling is preferred over a truncated one. The variants are not guesswork:
#: "marati" and "marath" are actual typos on this channel, and without them their
#: videos split away from their own series into a separate unknown-language
#: sequence - Tulasi Stotra came out as two sequences of one video each.
LANGUAGE_SPELLINGS: dict[str, list[str]] = {
    "kannada": ["kannada", "kannad"],
    "english": ["english"],
    "marathi": ["marathi", "marath", "marati"],
    "hindi": ["hindi"],
    "telugu": ["telugu"],
    "tamil": ["tamil"],
    "sanskrit": ["sanskrit"],
}

#: The canonical language names, used for labels and for reading a language out
#: of a category name.
LANGUAGES = list(LANGUAGE_SPELLINGS)

#: Every spelling paired with the language it means, longest first so that
#: "marathi" is matched before its truncation "marath".
_LANGUAGE_BY_SPELLING: list[tuple[str, str]] = sorted(
    ((spelling, language) for language, spellings in LANGUAGE_SPELLINGS.items() for spelling in spellings),
    key=lambda pair: -len(pair[0]),
)

#: Marathi grammatical forms that identify the language without naming it.
#: Deliberately tiny and evidence-based: "swamincha" is a Marathi possessive, and
#: it appears on two videos of one series where only the other one says
#: "Marathi", so without it that pair splits apart. Candidates like "ancha" were
#: rejected for matching "Panchanga" and "Panchami".
MARATHI_MARKERS = ["swamincha"]

#: Languages confirmed by the channel for a whole series, where no title says so.
#: These are told to us, not inferred, so they are not marked as assumed.
CONFIRMED_CATEGORY_LANGUAGES = {
    "Bhagavata Saroddhara": "kannada",
}

#: Where nothing identifies the language, the catalogue assumes this one - most
#: of the channel's teaching is in it. The assumption is always shown to the
#: reader rather than hidden (see sequence_label), because it IS an assumption.
ASSUMED_LANGUAGE = "kannada"

#: Suffix marking a language the catalogue worked out rather than read.
ASSUMED_SUFFIX = "assumed"

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
# A "Day N" session label.
#
# The label may run straight onto the preceding word - "manimanjariDay19" - so it
# cannot require a separator before it. Instead the weekday names are excluded
# explicitly, since those are the words that end in "day" and would otherwise
# make "Saturday 17th Sept" look like session 17.
#
# The `(?!\d)` matters too: without it the engine backtracks to a shorter digit
# run to satisfy the ordinal guard, so "Final Day 24th June" yields session 2 by
# matching just the "2" and finding "4th" acceptable after it.
_NOT_A_WEEKDAY = "".join(
    f"(?<!{stem})" for stem in ("mon", "tues", "wednes", "thurs", "fri", "satur", "sun", "birth")
)
_SESSION_RE = re.compile(
    rf"{_NOT_A_WEEKDAY}day[\s\-_:.]*(\d{{1,3}})(?!\d)(?!\s*(?:st|nd|rd|th)\b)", re.I
)

# A part number attached to a session label: "Day 32(4)". Anchored to the day
# label so a verse number elsewhere in the title ("Shloka 48(2)") is not read as
# a part.
_SESSION_PART_RE = re.compile(
    rf"{_NOT_A_WEEKDAY}day[\s\-_:.]*\d{{1,3}}\s*\((\d{{1,2}})\)", re.I
)


def detect_language(title: str) -> str | None:
    """Return the language named in `title`, or None if none is named.

    Recognises the misspellings that actually occur, so a typo does not exile a
    video from its own series. Spellings are tried longest first, so "marathi"
    wins over its truncation "marath".
    """
    lowered = title.lower()
    for spelling, language in _LANGUAGE_BY_SPELLING:
        if spelling in lowered:
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


def language_notes(language: str, *, assumed_count: int, total: int) -> list[str]:
    """Disclose an assumption that the label alone cannot express.

    When every video in a sequence needed the assumption, the label already says
    "(Kannada, assumed)" and no note is needed. The awkward case is a sequence
    where only SOME titles name the language: the label reads plainly, so without
    a note a reader would have no way to know part of it was inferred.
    """
    if assumed_count == 0 or assumed_count == total:
        return []
    one = assumed_count == 1
    return [
        f"{assumed_count} of these {total} videos {'does' if one else 'do'} not name a language; "
        f"{language.title()} is assumed for {'it' if one else 'them'}."
    ]


def sequence_notes(videos: list[dict[str, Any]]) -> list[str]:
    """Things a reader should know about a sequence before working through it.

    Derived from the data, not written by hand, so they stay true as the channel
    grows. Two things get flagged, both of which are otherwise puzzling:

    - A session number missing from an otherwise continuous run. The video is
      not on the channel; nothing is being hidden.
    - A session number used twice. Two identical uploads and two different
      recordings sharing a number are different problems, so they are worded
      differently, distinguished by whether date and length match.

    Sequences whose titles are not numbered produce no notes: there is nothing
    to check a run against.
    """
    by_number: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for video in videos:
        number = session_number(video["title"])
        if number is not None:
            by_number[number].append(video)

    # Below this, the numbered videos are too small a share of the sequence for a
    # "run" to mean anything, and a gap would more likely be an unnumbered title
    # than a missing video.
    if len(by_number) < 4 or len(by_number) < 0.6 * len(videos):
        return []

    notes: list[str] = []
    present = sorted(by_number)

    missing = [number for number in range(min(present), max(present) + 1) if number not in by_number]
    if missing:
        listed = ", ".join(str(number) for number in missing)
        singular = len(missing) == 1
        notes.append(
            f"{'Session' if singular else 'Sessions'} {listed} "
            f"{'is' if singular else 'are'} not on the channel, so the numbering skips "
            f"{'it' if singular else 'them'}."
        )

    for number in present:
        copies = by_number[number]
        if len(copies) < 2:
            continue

        # One class uploaded as several videos - "Day 32(1)" .. "Day 32(5)" - is
        # not a duplicate. It is worth explaining, since those parts are much
        # shorter than a normal session.
        parts = {session_part(video["title"]) for video in copies}
        if len(parts) == len(copies) and 0 not in parts:
            notes.append(f"Session {number} was uploaded in {len(copies)} parts, listed here in order.")
            continue

        if len({(video["date"], video["duration_min"]) for video in copies}) == 1:
            notes.append(
                f"Session {number} appears {len(copies)} times because the same recording was "
                f"uploaded more than once. Either copy will do."
            )
        else:
            dates = ", ".join(sorted(video["date"] for video in copies))
            notes.append(
                f"Session {number} appears {len(copies)} times as different recordings ({dates}). "
                f"Both are kept here; one of them may be numbered wrongly."
            )
    return notes


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


def resolve_language(category: str, title: str) -> tuple[str, bool]:
    """Work out a sequence's language. Returns (language, was_it_assumed).

    In order of how much the source actually tells us:

    1. The category name states it, e.g. "Manimanjari (Kannada)".
    2. The title states it, including known misspellings.
    3. The channel has confirmed it for the whole series.
    4. The title carries Marathi grammar without naming the language.
    5. Nothing identifies it, so Kannada is assumed.

    Only the first three are read from the source. Cases 4 and 5 are inferences,
    and are reported as such so the label can say so - a reader should be able to
    tell what was written down from what was worked out.
    """
    stated = category_names_language(category) or detect_language(title)
    if stated:
        return stated, False
    confirmed = CONFIRMED_CATEGORY_LANGUAGES.get(category)
    if confirmed:
        return confirmed, False
    lowered = title.lower()
    if any(marker in lowered for marker in MARATHI_MARKERS):
        return "marathi", True
    return ASSUMED_LANGUAGE, True


def sequence_label(category: str, language: str, *, assumed: bool = False) -> str:
    """Build the display label for a sequence.

    Avoids a redundant "(Kannada) (Kannada)" when the category name already
    states the language, and marks an assumed language so a reader is never
    misled into thinking the channel said it.
    """
    if f"({language})" in category.lower():
        return category
    suffix = f"{language.title()}, {ASSUMED_SUFFIX}" if assumed else language.title()
    return f"{category} ({suffix})"


def build_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group rows into (category, language) sequences, ordered oldest-first."""
    # Keyed on category and language only. Whether the language was stated or
    # assumed is recorded per video, NOT used to split the group: doing that put
    # "Deva Pooja (Kannada)" beside "Deva Pooja (Kannada, assumed)" and made one
    # series look like two, in thirteen categories. Where only some videos needed
    # the assumption, the sequence says so in a note instead.
    groups_map: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    assumed_ids: set[str] = set()
    for row in rows:
        category = row["category"]
        language, assumed = resolve_language(category, row["title"])
        if assumed:
            assumed_ids.add(row["video_id"])
        groups_map[(category, language)].append(row)

    groups: list[dict[str, Any]] = []
    for (category, language), items in groups_map.items():
        assumed_here = sum(1 for item in items if item["video_id"] in assumed_ids)
        # Only call the whole sequence's language assumed when nothing in it
        # states one. If even one video names the language, the sequence is
        # labelled plainly and the note carries the detail.
        assumed = assumed_here == len(items)
        ordered = order_videos(items)

        # Only the word list is published. The joined text it is built from was
        # also written out originally, but nothing ever read it - it was 26 KB of
        # the file the page downloads on every visit.
        searchable = " ".join([
            category.lower(),
            language,
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
            "language_assumed": assumed,
            "label": sequence_label(category, language, assumed=assumed),
            "count": len(videos),
            "assumed_count": assumed_here,
            "notes": sequence_notes(videos) + language_notes(
                language, assumed_count=assumed_here, total=len(videos),
            ),
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
