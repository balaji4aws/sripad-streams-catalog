#!/usr/bin/env python3
"""
categorize.py - Turn the raw stream-list JSON (from fetch.py) into organized
lists: one master table plus a series/category breakdown, written out as
CSV, JSON, and a human-browsable Markdown catalog.

Usage:
    python3 src/categorize.py [--in data/raw_playlist.json] [--outdir output]
                              [--known-dates data/known_upload_dates.json]

How categorization works:
    Titles on this channel are informal and inconsistently punctuated (typos,
    mixed date formats, mixed spacing) but they DO follow a recognizable set
    of recurring series/topic names (e.g. "Sumadhwavijaya", "Manimanjari",
    "Satyatma Sandhya", "NKHK ..."). categorize() below applies a prioritized
    list of substring rules built by inspecting the actual titles - most
    specific checks first, falling back to "Uncategorized / Other" for
    anything that doesn't match. See DESIGN.md for the full rationale.

How dates are resolved:
    yt-dlp's --flat-playlist mode (used by fetch.py) doesn't return a real
    per-video upload date, and the one flag that claims to
    (youtubetab:approximate_date) turned out to return a handful of fake
    "bucket" dates reused across dozens of unrelated videos on this channel -
    not usable. Instead:
      1. Try to parse an explicit day+month(+year) out of the title text.
      2. If the year is missing, carry forward the most recently SEEN year
         (the channel list is newest-first, so this walks backward in time)
         - and step it back by one when the month sequence implies a year
         boundary was crossed (e.g. titles go ...Dec, Nov... then a
         "21st Jan" turns up further down the list; that Jan must be the
         PRECEDING January, one year earlier than the Dec/Nov just above it).
      3. If no date can be parsed at all, fall back to a real, individually-
         fetched YouTube upload date from data/known_upload_dates.json, if
         one is available there (see src/fill_unknown_dates.py, which fetches
         that lookup for just the handful of videos that need it rather than
         for all 342 videos up front). A title-parsed date is always
         preferred over this fallback when the title actually gives one,
         since a real upload date and a title's stated date can differ by
         roughly a day (late-night uploads rolling into the next calendar
         day) - the title is kept as the source of truth wherever it exists.
      4. If neither a title date nor a known upload date exists, the row is
         marked date="Unknown" rather than guessing - these are listed in
         the catalog by their original channel-list position instead (still
         newest-to-oldest, just without a specific date).
"""

import argparse
import calendar
import csv
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple

import catalog_paths

UNCATEGORIZED = "Uncategorized / Other"
UNKNOWN_DATE = "Unknown"

#: Used when a raw entry carries no source tab, which happens only for a
#: playlist file saved before fetch.py started recording one.
DEFAULT_SOURCE = "streams"

#: How often the channel is expected to be re-scanned. Used only to work out the
#: date the next scan is due, which the search page shows so a reader can see how
#: current the catalog is.
REFRESH_INTERVAL_DAYS = 14

# Ordered rules: (category name, substrings to match against a lowercased
# title). The FIRST matching category wins, so order matters: specific series
# names must come before generic catch-alls like "nkhk"/"satsanga".
RULES: list[tuple[str, list[str]]] = [
    # The channel's longest series, 100+ numbered sessions on the /videos tab.
    # "saroddhara" is unique to it across the whole channel, so the shorter
    # spelling is safe to match on as well.
    ("Bhagavata Saroddhara", ["bhagavata saroddhara", "bhagavatha saroddhara", "saroddhara"]),
    # Videos of Sri Satyatma Teertha himself, distinct from the "Satyatma
    # Sandhya" classes below - checked first so the shared "satyatma" prefix
    # cannot pull these into that series.
    ("SriSatyatma Teertha (Darshana/Mangalarati)", ["satyatmatheertharu", "satyatma teertharu"]),
    ("Rushi Panchami", ["rushi panchami", "rishi panchami"]),
    ("Mutt Utsava / Puja", ["uttaradi mutt", "vedavyasa puja"]),
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

_TEEKACHARYA_SPELLINGS = ("teekacharya", "teekachrayara", "teekachrya")
_RECITATION_WORDS = ("stotra", "stuti", "ashtottara", "ashtaka")

# Month name variants, longest first, so that "june" is preferred over the
# shorter "jun" and "september" over "sept"/"sep".
_MONTH_VARIANTS: dict[int, list[str]] = {
    1: ["january", "jan"], 2: ["february", "feb"], 3: ["march", "mar"],
    4: ["april", "apr"], 5: ["may"], 6: ["june", "jun"],
    7: ["july", "jul"], 8: ["august", "aug"], 9: ["september", "sept", "sep"],
    10: ["october", "oct"], 11: ["november", "nov"], 12: ["december", "dec"],
}
MONTHS: dict[str, int] = {
    variant: number for number, variants in _MONTH_VARIANTS.items() for variant in variants
}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

# A standalone 1-2 digit number. The lookarounds stop a longer run of digits
# from being sliced into a bogus day: without them, "May 2021" would parse as
# day 20 of May in the year 21, and "2026 July" as day 26 of July.
_SMALL_NUMBER = r"(?<!\d)(\d{1,2})(?!\d)"
_YEAR = r"(?<!\d)(\d{4}|\d{2})(?!\d)"
# Separator between the parts of a date. Whitespace covers "4th June 2026" and
# the run-together "3rd Sep2026"; the slash covers "25/Jul/2026", the format the
# /videos tab uses throughout.
_SEP = r"[\s/]*"
# Wrapped in a non-capturing group so that making the year optional makes the
# whole year (digits and lookarounds) optional, not just its trailing lookahead.
_OPTIONAL_YEAR = rf"(?:{_YEAR})?"
_OPTIONAL_ORDINAL = r"(st|nd|rd|th)?"
# A month name must not be followed by another letter. Without this, "Mar"
# matches inside "Marathi" - which appears in a large share of these titles -
# and silently produces a March date for a video streamed in some other month.
_MONTH_TOKEN = rf"({MONTH_RE})(?![A-Za-z])"

# "4th June 2026" / "3rd Sep2026" / "14July 2026": day, then month name, then
# an optional year with or without a space in front of it.
# Groups: 1=day, 2=ordinal suffix (may be absent), 3=month, 4=year (optional).
DAY_FIRST_RE = re.compile(
    rf"{_SMALL_NUMBER}{_SEP}{_OPTIONAL_ORDINAL}\.?{_SEP}{_MONTH_TOKEN}\.?{_SEP}{_OPTIONAL_YEAR}", re.I
)
# "Oct 2nd 2023" / "May 8th 2026": month name first, then day, then an
# optional year. Groups: 1=month, 2=day, 3=ordinal suffix, 4=year (optional).
MONTH_FIRST_RE = re.compile(
    rf"{_MONTH_TOKEN}\.?{_SEP}{_SMALL_NUMBER}{_SEP}{_OPTIONAL_ORDINAL}\.?\s*,?{_SEP}{_OPTIONAL_YEAR}", re.I
)
# "May 2021" / "Sep2026": a month and a year with no day at all.
MONTH_YEAR_RE = re.compile(rf"{_MONTH_TOKEN}\.?\s*(?<!\d)(\d{{4}})(?!\d)", re.I)

# Matches a trailing "Day"/"Day-"/"Day:" session label. Titles number their
# sessions two ways, and the two collide: "Day 24th June" means the 24th of
# June, but "Day 2 Feb 3rd" means session 2, streamed on February 3rd. The
# ordinal suffix is what tells them apart, so a bare number sitting directly
# after a "Day" label is read as a session number, not a calendar day.
# "day" must not be the tail of a longer word, so this never fires on
# "Saturday 17th Sept", where 17 really is the calendar day.
_SESSION_LABEL_RE = re.compile(r"(?:^|[^a-z])day[\s\-_:.]*$", re.I)

# The month sequence is allowed to step forward by this many months without
# being read as a year rollover. Some titles carry a typo'd day or month, and
# a few videos sit slightly out of order in the channel listing, so a small
# amount of forward movement is normal noise rather than a new year.
MONTH_JITTER_TOLERANCE = 1

# Highest day number each month can hold. February is given 29 so that a leap
# day survives title parsing; the exact year is checked later, once known.
_MAX_DAY_IN_MONTH = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
                     7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


class TitleDate(NamedTuple):
    """A date parsed out of a title. Any field may be None."""

    day: int | None
    month: int | None
    year: int | None

    @property
    def is_empty(self) -> bool:
        return self.day is None and self.month is None and self.year is None


NO_DATE = TitleDate(None, None, None)


def categorize(title: str) -> str:
    """Return the series/category name for a video title."""
    text = title.lower()
    if (
        "jayateertha" in text
        and any(word in text for word in ("stuti", "stotra"))
        and not any(spelling in text for spelling in _TEEKACHARYA_SPELLINGS)
    ):
        return "SriJayateertha Stuti"
    # "Krishna" on its own shows up in many unrelated titles, so it only counts
    # as this series when the title also names a kind of recitation.
    if "krishna" in text and any(word in text for word in _RECITATION_WORDS):
        return "SriKrishna Stotra/Stuti"
    # A combined session gets its own name rather than being forced into
    # either "Dhyana" or "Anusandhana" alone.
    if "dhyana" in text and "anusandhana" in text:
        return "Anusandhana + Dhyana (NKHK)"
    for category, needles in RULES:
        if any(needle in text for needle in needles):
            return category
    return UNCATEGORIZED


def _normalize_year(year_text: str | None) -> int | None:
    """Expand a 2-digit year ("26") to 4 digits (2026); pass 4-digit years through."""
    if not year_text:
        return None
    year = int(year_text)
    return year + 2000 if year < 100 else year


def _is_session_number(title: str, match: re.Match[str]) -> bool:
    """True when the digits DAY_FIRST_RE matched as a day are a session number.

    A number carrying an ordinal suffix ("Day 24th June") is a date. A bare
    number directly after a "Day" label ("Day 2 Feb 3rd") is a session number.
    """
    has_ordinal_suffix = bool(match.group(2))
    if has_ordinal_suffix:
        return False
    return bool(_SESSION_LABEL_RE.search(title[: match.start(1)]))


def _plausible_day(day: int, month: int) -> bool:
    """True when `day` can exist in `month`, ignoring the year."""
    return 1 <= day <= _MAX_DAY_IN_MONTH[month]


def parse_title_date(title: str) -> TitleDate:
    """Parse a date out of a video title.

    Tries day-before-month ("4th June 2026") first, then month-before-day
    ("Oct 2nd 2023"), then a bare month and year with no day ("May 2021").
    Candidate matches that are really session numbers, or that name an
    impossible day for their month, are skipped rather than accepted, so the
    scan continues to the next candidate in the same title.
    """
    for match in DAY_FIRST_RE.finditer(title):
        if _is_session_number(title, match):
            continue
        day, month = int(match.group(1)), MONTHS[match.group(3).lower()]
        if not _plausible_day(day, month):
            continue
        return TitleDate(day, month, _normalize_year(match.group(4)))

    for match in MONTH_FIRST_RE.finditer(title):
        month, day = MONTHS[match.group(1).lower()], int(match.group(2))
        if not _plausible_day(day, month):
            continue
        return TitleDate(day, month, _normalize_year(match.group(4)))

    # A separate name: the loops above bind `match` to a guaranteed Match,
    # whereas search() can return None.
    month_year = MONTH_YEAR_RE.search(title)
    if month_year:
        return TitleDate(None, MONTHS[month_year.group(1).lower()], int(month_year.group(2)))

    return NO_DATE


def load_known_upload_dates(path: Path) -> dict[str, str]:
    """Load the ``{video_id: 'YYYY-MM-DD'}`` fallback lookup, if it exists.

    These are REAL YouTube upload dates, fetched one video at a time by
    src/fill_unknown_dates.py - not parsed from titles. They are used only as
    a fallback for videos that would otherwise be "Unknown", because a real
    upload date and the date a title states can differ by about a day
    (a late-night stream rolls over into the next calendar day), and the
    title is kept as the source of truth wherever it gives one.
    """
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        print(f"warning: ignoring unreadable {path}: {err}", file=sys.stderr)
        return {}
    if not isinstance(loaded, dict):
        print(f"warning: ignoring {path}: expected a JSON object", file=sys.stderr)
        return {}
    return {str(k): str(v) for k, v in loaded.items()}


def _carry_years_backward(parsed: list[TitleDate]) -> list[TitleDate]:
    """Fill in missing years by walking the channel's own newest-first order.

    Many titles give a day and month but no year. Because the listing is
    newest-first, walking down it walks backward through time, so the most
    recently seen year can be carried forward - stepping back one year when
    the month sequence jumps forward far enough to imply a year boundary was
    crossed (a "21st Jan" appearing below a run of Dec/Nov titles belongs to
    the January *before* that December).
    """
    filled: list[TitleDate] = []
    current_year: int | None = None
    last_month: int | None = None

    for entry in parsed:
        if entry.year is not None:
            current_year = entry.year
            if entry.month is not None:
                last_month = entry.month
        elif entry.month is not None and current_year is not None:
            if last_month is not None and entry.month > last_month + MONTH_JITTER_TOLERANCE:
                current_year -= 1
            entry = entry._replace(year=current_year)
            last_month = entry.month
        filled.append(entry)

    return filled


def _format_date(entry: TitleDate) -> str | None:
    """Render a parsed date as YYYY-MM-DD, or YYYY-MM when the day is unusable.

    Returns None when there isn't enough information to name even a month, so
    the caller knows to reach for the upload-date fallback.
    """
    if entry.year is None or entry.month is None:
        return None
    month_only = f"{entry.year:04d}-{entry.month:02d}"
    if entry.day is None:
        return month_only
    # Catches a day that only becomes impossible once the year is known,
    # e.g. February 29th in a non-leap year.
    days_in_month = calendar.monthrange(entry.year, entry.month)[1]
    if entry.day > days_in_month:
        return month_only
    return f"{month_only}-{entry.day:02d}"


def resolve_dates(entries: list[dict[str, Any]], known_upload_dates: dict[str, str] | None = None) -> list[str]:
    """Return one date string per entry, aligned with `entries`.

    Each string is "YYYY-MM-DD", "YYYY-MM" when only a month is known, or
    "Unknown". Videos whose title has no parseable date fall back to
    `known_upload_dates` (a ``{video_id: 'YYYY-MM-DD'}`` map of real fetched
    upload dates) when an entry is present there. Videos with neither a title
    date nor an entry in that map stay "Unknown" rather than being guessed.

    The year-carry-backward pass runs SEPARATELY per source tab. Each tab is its
    own newest-first list, so carrying a year from the end of one tab into the
    start of another would compare unrelated positions and shift years wrongly.
    """
    known_upload_dates = known_upload_dates or {}

    resolved: list[str | None] = [None] * len(entries)
    for indices in _group_indices_by_source(entries).values():
        parsed = _carry_years_backward([parse_title_date(entries[i].get("title", "")) for i in indices])
        for index, entry in zip(indices, parsed, strict=True):
            resolved[index] = _format_date(entry)

    return [
        formatted if formatted is not None else known_upload_dates.get(raw.get("id", ""), UNKNOWN_DATE)
        for formatted, raw in zip(resolved, entries, strict=True)
    ]


def _group_indices_by_source(entries: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Indices of `entries`, grouped by the tab each came from, order preserved."""
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, entry in enumerate(entries):
        grouped[str(entry.get("_source", DEFAULT_SOURCE))].append(index)
    return dict(grouped)


def merge_sources(entries: list[dict[str, Any]], dates: list[str]) -> list[int]:
    """Interleave the source tabs into one newest-first ordering.

    Returns the indices of `entries` in that order.

    The problem: /streams and /videos are separate lists. Each is newest-first
    within itself, but position 5 of one has no relationship to position 5 of the
    other, so there is no single "channel position" to sort by - and one series
    (Pratah Sankalpa Gadya) has sessions on both tabs, so its videos genuinely
    need ordering against each other.

    The fix is a stable merge on date, newest first, of two already-sorted lists.
    Two properties follow, and both matter:

    - Within a tab, relative order is exactly what the channel itself listed.
      That is deliberately kept, because a handful of titles state a date that
      contradicts their position, and the position is the more trustworthy of the
      two. Sorting everything by date outright would reorder those wrongly.
    - Across tabs, the date decides. It is the only signal the two lists share.

    A video with no usable date keeps its place relative to its own tab, and
    sorts as though it were as old as the last dated video above it - it is never
    moved to an arbitrary end of the catalog.
    """
    grouped = _group_indices_by_source(entries)

    # Give every entry a comparable date by carrying the last known one down its
    # own tab, so an undated video stays beside its neighbours instead of
    # collapsing to the top or bottom of the merged list.
    merge_date: dict[int, str] = {}
    for indices in grouped.values():
        carried = ""
        for index in indices:
            if dates[index] != UNKNOWN_DATE:
                carried = dates[index]
            merge_date[index] = carried

    # Stable merge: repeatedly take whichever tab's next video is newest. On a
    # tie max() returns the first candidate, which is the earliest tab in
    # insertion order, so the result is deterministic.
    queues = {name: list(indices) for name, indices in grouped.items()}
    order: list[int] = []
    while any(queues.values()):
        candidates = [(name, queue[0]) for name, queue in queues.items() if queue]
        chosen_name, chosen_index = max(candidates, key=lambda pair: merge_date[pair[1]])
        order.append(chosen_index)
        queues[chosen_name].pop(0)
    return order


def build_rows(entries: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    """Flatten raw yt-dlp entries plus resolved dates into the master table.

    Rows come out in merged newest-first order across every source tab (see
    merge_sources), and `list_position` numbers them in that order. Downstream,
    build_sequences.py sorts by `list_position` descending to get watch order,
    so that single number carries the whole ordering decision.
    """
    rows = []
    for position, index in enumerate(merge_sources(entries, dates), start=1):
        entry = entries[index]
        video_id = entry.get("id", "")
        rows.append({
            # 1 = most recent across the whole channel, after merging the tabs.
            "list_position": position,
            "date": dates[index],
            "category": categorize(entry.get("title", "")),
            "title": entry.get("title", ""),
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "duration_min": round((entry.get("duration") or 0) / 60, 1),
            "view_count": entry.get("view_count") or 0,
            # Which channel tab this came from, and where it sat in that tab's
            # own list. Kept so the merge above can be checked by hand.
            "source": str(entry.get("_source", DEFAULT_SOURCE)),
            "source_position": entry.get("_source_position") or position,
        })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _slugify(text: str, separator: str = "_") -> str:
    """Reduce a category name to a filename-safe / anchor-safe slug."""
    pattern = r"[^A-Za-z0-9]+" if separator == "_" else r"[^a-z0-9]+"
    source = text if separator == "_" else text.lower()
    return re.sub(pattern, separator, source).strip(separator)


def build_catalog_markdown(
    rows: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    channel: str,
    subscribers: int | None,
    meta: dict[str, Any] | None = None,
) -> str:
    """Render the whole catalog as a single browsable Markdown document."""
    unknown_dates = sum(1 for row in rows if row["date"] == UNKNOWN_DATE)
    subscriber_note = f", {subscribers} subscribers" if subscribers else ""
    meta = meta or {}
    scanned_note = (
        f"Channel last scanned **{meta['scanned_on']}**; next scan due {meta.get('next_scan_due')}."
        if meta.get("scanned_on")
        else "Scan date unknown."
    )

    lines = [
        "# Sripad K — Video Catalogue",
        "",
        f"Auto-generated from the channel's /streams and /videos tabs "
        f"(**{channel}**{subscriber_note}).",
        f"Total videos: **{len(rows)}** across **{len(grouped)}** categories.",
        scanned_note,
        "",
        "Categorization is by title-keyword matching (see `src/categorize.py`) — it groups",
        "recurring series by name rather than by manually reviewing each video. A",
        "description-based grouping wasn't possible: every video on this channel currently",
        "has an empty description.",
        "",
        f"Dates are parsed from the title text where possible; {unknown_dates} video(s) had no",
        "parseable date and are marked **Unknown** rather than guessed — see `src/categorize.py`",
        "for exactly how dates are resolved, including the year-carry-backward logic.",
        "",
        "## Category index",
        "",
        "| Category | Count |",
        "|---|---|",
    ]
    for category, items in grouped.items():
        lines.append(f"| [{category}](#{_slugify(category, '-')}) | {len(items)} |")
    lines.append("")

    for category, items in grouped.items():
        lines += [
            f"## {category}",
            "",
            "| Date | Title | Duration | Views | Link |",
            "|---|---|---|---|---|",
        ]
        for row in items:
            lines.append(
                f"| {row['date']} | {row['title']} | {row['duration_min']}m | "
                f"{row['view_count']} | [watch]({row['url']}) |"
            )
        lines.append("")

    return "\n".join(lines)


def build_catalog_meta(raw: dict[str, Any], rows: list[dict[str, Any]], category_count: int) -> dict[str, Any]:
    """Summarise the catalog, including when the channel was last scanned.

    The scan date comes from the timestamp yt-dlp records in the raw playlist at
    fetch time, NOT from the clock when this script runs. That keeps the output
    a pure function of the input: re-running the offline steps on the same saved
    playlist produces byte-identical files, which is what lets CI check that the
    committed catalog still matches the code that made it.
    """
    epoch = raw.get("epoch")
    scanned_on = (
        dt.datetime.fromtimestamp(epoch, dt.timezone.utc).date().isoformat()
        if isinstance(epoch, (int, float))
        else None
    )
    next_due = (
        (dt.date.fromisoformat(scanned_on) + dt.timedelta(days=REFRESH_INTERVAL_DAYS)).isoformat()
        if scanned_on
        else None
    )
    return {
        "channel": raw.get("channel"),
        "channel_url": raw.get("webpage_url"),
        "scanned_on": scanned_on,
        "refresh_interval_days": REFRESH_INTERVAL_DAYS,
        "next_scan_due": next_due,
        "video_count": len(rows),
        "category_count": category_count,
        "newest_video_date": rows[0]["date"] if rows else None,
        "oldest_video_date": rows[-1]["date"] if rows else None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="infile", default=str(catalog_paths.RAW_PLAYLIST),
                        help="Raw playlist JSON written by fetch.py")
    parser.add_argument("--outdir", default=str(catalog_paths.OUTPUT_DIR),
                        help="Directory to write the catalog files into")
    parser.add_argument("--known-dates", dest="known_dates", default=str(catalog_paths.KNOWN_UPLOAD_DATES),
                        help="Fallback {video_id: date} lookup from fill_unknown_dates.py")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    infile = catalog_paths.resolve(args.infile)
    if not infile.exists():
        print(f"error: {infile} not found - run fetch.py first.", file=sys.stderr)
        return 1
    try:
        raw = json.loads(infile.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        print(f"error: {infile} is not valid JSON: {err}", file=sys.stderr)
        return 1

    entries = raw.get("entries") or []
    if not entries:
        print(f"error: {infile} contains no playlist entries - nothing to categorize.", file=sys.stderr)
        return 1

    dates = resolve_dates(entries, load_known_upload_dates(catalog_paths.resolve(args.known_dates)))
    rows = build_rows(entries, dates)

    outdir = catalog_paths.resolve(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())

    # Master CSV / JSON: every stream, newest-first (the channel's own order).
    _write_csv(outdir / "streams_master.csv", rows, fieldnames)
    _write_json(outdir / "streams_master.json", rows)

    # Grouped by category, largest category first; each list stays newest-first.
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    grouped = dict(sorted(by_category.items(), key=lambda item: -len(item[1])))
    _write_json(outdir / "streams_by_category.json", grouped)

    category_dir = outdir / "by_category"
    category_dir.mkdir(exist_ok=True)
    for category, items in grouped.items():
        _write_csv(category_dir / f"{_slugify(category)}.csv", items, fieldnames)

    meta = build_catalog_meta(raw, rows, len(grouped))
    _write_json(outdir / "catalog_meta.json", meta)

    (outdir / "CATALOG.md").write_text(
        build_catalog_markdown(rows, grouped, raw.get("channel", "unknown channel"),
                               raw.get("channel_follower_count"), meta),
        encoding="utf-8",
    )

    unknown_dates = sum(1 for row in rows if row["date"] == UNKNOWN_DATE)
    print(f"{len(rows)} videos -> {len(grouped)} categories ({unknown_dates} with unresolved dates)")
    print(f"Channel last scanned {meta['scanned_on'] or 'unknown'}; "
          f"next scan due {meta['next_scan_due'] or 'unknown'}")
    print(f"Wrote {outdir}/: streams_master.csv/.json, streams_by_category.json, "
          f"catalog_meta.json, CATALOG.md, by_category/*.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
