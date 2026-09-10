# Design Document: Sripad K — Streams Catalog

This document explains the problem this project solves, the approach taken, how the code is
organized, and the reasoning behind each design decision. It is written so that someone new to
the project — even a recent graduate with no prior context — can read it top to bottom and
understand the whole system.

---

## 1. Problem Statement

### 1.1 The situation

A YouTube channel has 342 recorded live streams. These are devotional lectures, classes, and
readings, delivered across several long-running series, in three languages (Kannada, Marathi,
and English). The channel has no playlists. Every video sits in one long list on the channel's
"Streams" tab, sorted only by upload date.

### 1.2 The problem

A viewer who wants to watch a specific series faces three separate problems:

1. **Finding the videos.** The videos for one series are scattered across the full list of 342,
   mixed in with videos from every other series.
2. **Not knowing the order.** Even after finding a handful of matching videos, nothing tells the
   viewer which one comes first, second, or last. Series were recorded over months or years, with
   gaps, so upload date alone is not a reliable guide, and some videos are numbered inconsistently
   in their own titles (for example, "Day 3" appearing twice, once as a typo re-upload).
3. **Language tracks getting mixed together.** Several series were taught more than once, in
   different languages, as fully separate video sequences (for example, the same lecture series
   taught as ten English sessions and, separately, as thirteen Kannada sessions). A plain
   keyword search returns both tracks mixed together, which makes the order meaningless — video 4
   of the English track has nothing to do with video 4 of the Kannada track.
4. **Search returning too much, without order.** A plain keyword search for something like
   "sandhyavandana" returns dozens of results with no structure. The viewer is left to sort
   through a wall of text with no sense of where to start or what to click next.

### 1.3 What "solved" looks like

A viewer should be able to type a short search term and see:

- The videos grouped into their correct series (and, where relevant, split by language).
- Each group shown as a clean, ordered list — "video 1 of 12," "video 2 of 12," and so on — so
  the viewer always knows what to watch first and what comes next.
- A way to browse by topic without needing to already know what to search for.

This project builds exactly that, as a small set of scripts plus one self-contained search page.

---

## 2. Approach

The problem breaks into four separate steps, and the project has one file for each step:

1. **Get the raw list of videos** from the channel (title, video ID, duration, view count).
2. **Sort each video into a named series** ("category"), and work out a date for it.
3. **Work out the watch order within each series** — and, importantly, keep different-language
   versions of the same series as separate ordered lists.
4. **Let a person search all of this** through a simple web page, with topic-browsing built in.

Each step reads the previous step's output and writes its own output file. Nothing is done in one
giant script — this makes each part easy to test, re-run, and understand on its own.

### 2.1 Why keyword matching on the video title, instead of something smarter

The channel's videos do not have descriptions (every single one is empty — this was checked, not
assumed). The video title is the only piece of text available to work with. Titles are informal,
inconsistently spelled, and inconsistently punctuated (see section 4 for real examples), but they
do reliably contain the name of the series and, often, the language and a date. So the approach
is: **read the title text carefully, and build rules from what is actually there**, rather than
guessing or using a heavier machine-learning approach that would be overkill for a few hundred
short strings with a fairly small, discoverable set of patterns.

### 2.2 Why the project is split into small files instead of one script

Each step in section 2 depends only on the file the previous step wrote, not on any of that
step's internal code. This means:

- Any one step can be re-run on its own without re-running the others (for example, if the
  category rules need a small tweak, only `categorize.py` needs to run again).
- Each step's logic is short enough to read and check by hand.
- If YouTube ever changes something and step 1 needs fixing, steps 2 through 4 are unaffected.

---

## 3. Tech Stack

This project deliberately uses the smallest possible set of tools:

| Layer | Tool | Why |
|---|---|---|
| Getting data from YouTube | [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (a free command-line tool) | Standard, well-maintained tool for reading YouTube video lists without needing an official API key. |
| Processing the data | Python 3.10 or newer, standard library only (no third-party packages) | The processing here is straightforward text and list handling — no need for extra libraries. Keeping the dependency list at zero means anyone can run this without a package install step. |
| The search page | Plain HTML, CSS, and JavaScript — no framework, no build step | The page does one job (search a small list and show it back nicely). A framework would add complexity without adding capability here. |
| Tests | `unittest` (Python standard library) and `node --test` (built into Node) | Both ship with their runtime, so the tests run with nothing installed — which keeps the promise that a reader can clone this and run it immediately. |
| Linting | [`ruff`](https://docs.astral.sh/ruff/), configured in `pyproject.toml` | The one development dependency. Config lives in the repository so a local run and CI flag the same things. |
| Data storage between steps | Plain JSON and CSV files | No database needed for 342 rows of data. Files are easy to inspect, easy to version, and easy to hand to someone else. |

There is no server, no database, and no build pipeline. Every part of this project can be run and
understood by reading it directly.

---

## 4. Repository Structure — what each file does

```
sripad-streams-catalog/
├── README.md                  quick-start guide (short version of this document)
├── DESIGN.md                  this file
├── LICENSE                     MIT, covering the code
├── Makefile                    the development commands, and what CI runs
├── pyproject.toml              lint configuration (this is not an installable package)
├── requirements.txt            notes that no Python packages are needed; yt-dlp is required
├── requirements-dev.txt        the one development dependency (ruff), pinned
├── .github/workflows/ci.yml    lint, both test suites, and a catalog-freshness check
├── .gitignore
├── search.html                 the search page — this is what a person actually opens
├── search.js                   the page's matching logic, separated so it can be tested
├── tests/                      the test suite (see section 7)
├── src/
│   ├── fetch.py                 STEP 1 — downloads the raw video list
│   ├── categorize.py            STEP 2 — sorts videos into series, works out dates
│   ├── fill_unknown_dates.py    STEP 2b — fetches a real date for videos with no date in the title
│   ├── build_sequences.py       STEP 3 — works out watch order, writes the file search.html reads
│   └── catalog_paths.py         shared default file locations, resolved from the repository root
│                                 so every script runs the same from any directory
├── data/
│   ├── raw_playlist.json       the exact output of Step 1 (kept so Steps 2–4 can be re-run without
│   │                            re-downloading from YouTube every time)
│   └── known_upload_dates.json real per-video dates fetched by Step 2b, for titles with no date
└── output/                      everything Steps 2 and 3 produce
    ├── streams_master.csv        every video, one row each, with its series and date
    ├── streams_master.json       the same data as JSON
    ├── streams_by_category.json  the same videos, grouped by series
    ├── by_category/*.csv          one small CSV file per series (40 files)
    ├── sequences.json             the final file — series split by language, with watch order.
    │                              This is the ONE file search.html actually loads.
    └── CATALOG.md                 a single, browsable Markdown version of the whole catalog
```

### 4.1 `src/fetch.py` — Step 1: getting the raw list

**What it does:** Calls `yt-dlp` once, asking for every video's title, video ID, duration, and
view count from the channel's Streams tab. Saves the result to `data/raw_playlist.json`.

**Key decisions and why:**

- **It does not fetch video descriptions.** A spot-check across a sample of videos on this
  channel found every description empty. There is nothing to gain from fetching them, so the
  fetch step skips it entirely — this keeps the download fast (one request, not 342).
- **It does not use `yt-dlp`'s "approximate date" feature**, even though that feature sounds like
  exactly what is needed. It was tried and rejected: on this channel, it returned a small number
  of made-up placeholder dates, each one reused across dozens of unrelated videos (one single
  fake date was attached to 67 different videos). A genuine upload date for every video would
  require opening each video's page individually, which takes several seconds per video with the
  login step this channel requires — for 342 videos that is 25 minutes or more. Given titles
  already carry real, useful date information most of the time (see Step 2), that trade-off was
  not worth it for this project's goal.
- **It reads login cookies from a local Chrome browser.** YouTube blocks plain, un-authenticated
  requests to this channel's page as suspected bot traffic. Borrowing the browser's existing
  YouTube login, entirely on the local machine, avoids that block. Nothing is uploaded or sent
  anywhere beyond the normal request to YouTube itself.

### 4.2 `src/categorize.py` — Step 2: sorting videos into series, working out dates

This is the largest and most important file, because it does the two hardest jobs: figuring out
**what series each video belongs to**, and **what date it was recorded**.

#### 4.2.1 Sorting into series (the `categorize()` function)

**The challenge:** Video titles are informal and inconsistent. Real examples from this channel:

- `"Sumadhwavijaya Marathi - 3rd Sep2026"`
- `"Sumadhwavijay-Marathi-Day4-15thJan26"` (missing a letter, no spaces)
- `"Sumadhawavijaya Marathi Day1-11th Jan26"` (extra letter)
- `"SuMadhwavijaya Day7-21st Jan 2026"` (unusual capitalization, no language stated)

All four of these belong to the same series. There is no structured tag anywhere that says so —
the only signal is that they all contain some close spelling of the word "Sumadhwavijaya."

**The approach:** A single function, `categorize()`, checks a video's title (converted to
lowercase) against an ordered list of rules. Each rule is a series name paired with a list of
possible spellings/fragments to look for. The list is ordered from *most specific* to *most
general*, and the **first matching rule wins**. For example:

- `"sandhya shala"` is checked before the more general `"sandhyavandana"` — otherwise, every
  "Sandhya Shala" class (a specific onboarding series) would get lumped into the much bigger,
  more general "Sandhyavandana" bucket.
- A generic fallback like `"nkhk"` (an abbreviation this channel reuses across many unrelated
  one-off talks) is checked only after every more specific series name has already been ruled
  out, so it only catches videos that truly don't belong to a bigger, named series.
- If nothing matches at all, the video is placed in `"Uncategorized / Other"` rather than being
  forced into the wrong bucket. Out of 342 videos, exactly one landed here.

This produces **40 series** in total.

Two small extra rules handle cases where a single keyword is ambiguous by itself:

- The word "Krishna" alone appears in many unrelated titles. It's only treated as the
  "SriKrishna Stotra/Stuti" series if the title *also* contains a word like "stotra" or "stuti"
  (a type of devotional recitation).
- The word "dhyana" (meditation) and "anusandhana" (reflection) sometimes appear together in one
  title, describing a combined session — that combination gets its own series name rather than
  being forced into either the "Dhyana" or "Anusandhana" series alone.

#### 4.2.2 Working out a date for each video (`resolve_dates()` and `parse_title_date()`)

Since Step 1 deliberately does not fetch a real upload date (see 4.1), this step has to work out
a date from the title text itself.

**The approach, in four passes:**

1. **Look for an explicit date in the title.** Titles write dates in two different orders —
   "4th June 2026" (day, then month) or "Oct 2nd 2023" (month, then day) — and sometimes squash
   the month and year together with no space at all ("3rd Sep2026"). Two separate patterns are
   checked, one for each order, so both styles are caught.

   Three things make this harder than a single pattern match, and each one caused a genuine
   wrong date before it was handled:

   - **A month abbreviation can hide inside an ordinary word.** "Mar" sits inside "Marathi,"
     which appears in a large share of these titles. `"NKHK Dhyana Day1 Marathi 16th May 2021"`
     was read as *1 March* — it matched the "1" of "Day1" against the "Mar" of "Marathi" — rather
     than 16 May. A month name is therefore only accepted when it is not followed by another
     letter.
   - **A session number looks exactly like a calendar day.** Titles number sessions as "Day N,"
     and that number sits right next to the month often enough to be mistaken for the date.
     `"Sri Gopaladasara Charitre Day 2 Feb 3rd."` was read as *2 February* instead of the 3rd.
     The ordinal suffix is what separates the two cases: "Day 24th June" means the 24th of June,
     while "Day 2 Feb 3rd" means session 2, streamed on February 3rd. So a bare number directly
     after a "Day" label is treated as a session number, and the scan moves on to the next
     candidate in the same title. (The check is careful not to fire on "Saturday 17th Sept,"
     where the 17 really is the date.)
   - **A four-digit year can be sliced into a false day.** `"Sandhyavandana Online Oct 2024"`
     names no day at all, but a pattern that accepts any one-or-two-digit number read "2024" as
     *day 20 of the year 24*. Day and year numbers are now required to stand alone, so this title
     resolves to the month only — see pass 4.

   When a candidate is rejected for any of these reasons, the scan continues through the rest of
   the title rather than giving up, so a title carrying both a decoy and a real date still
   resolves correctly.
2. **If the year is missing, work it out from neighboring videos.** Many older titles give a day
   and month but no year (for example, "Dec 24th - Day13"). Because the channel lists videos
   *newest first*, walking down that list is the same as walking backward through time. The code
   remembers the most recently seen year and carries it forward — until it notices the month
   sequence has wrapped around (for example, a title says "21st Jan" right after several titles
   said "Dec" and "Nov" — that January must be *before* that December, so it belongs to the
   previous year, not the same one). This one small rule correctly handles every year boundary in
   the whole channel history (checked by hand for all six year transitions from 2021 to 2026).

   The month sequence is allowed to step forward by one month without being read as a year
   rollover. A few titles carry a typo'd date, and a few videos sit slightly out of order in the
   channel's own listing, so a single month of forward movement is ordinary noise rather than
   evidence of a new year. On the current catalog this tolerance changes no dates either way; it
   is there to keep one stray typo in a future refresh from shifting a whole run of videos back
   by a year.
3. **If no date can be worked out from the title at all, fall back to the video's real YouTube
   upload date** — but only for the small number of videos that need it (see section 4.2.4
   below for why this is kept as a separate, later step rather than something Step 1 does for
   every video up front).
4. **Report only what is actually known — never invent a missing piece.** A title that names a
   month and year but no day is recorded to the month (`2024-10`), not padded out to a
   made-up day; two videos in the current catalog fall into this category. A day that cannot
   exist in its month (a 30th of February, or a February 29th in a non-leap year) is dropped back
   to month precision in the same way. And if neither the title nor the fallback lookup yields
   anything at all, the video is marked `"Unknown"`. In the current run every video ended up with
   a date from one source or the other, so nothing is marked `"Unknown"` — but the rule stays in
   place for any future video that genuinely has neither.

#### 4.2.4 `src/fill_unknown_dates.py` — filling in the gaps the title can't answer

A small, separate script exists just for the handful of videos that pass 4.2.2 with no date at
all. Rather than teach `categorize.py` to fetch real dates from YouTube itself, this is a
one-purpose script that:

1. Reads `streams_master.json` and finds every video currently marked `"Unknown"`.
2. Fetches that video's own page individually and reads its real, YouTube-recorded upload date.
3. Saves the result to `data/known_upload_dates.json`, a simple `{video_id: date}` lookup.

`categorize.py` then reads that lookup file as a fallback source — used only when the title
itself has nothing (see pass 3 above). A title-parsed date is always trusted over this fallback
when the title does state one, because the two can differ by roughly a day: this project checked
a real sample and found that in most cases, a video's actual YouTube upload date landed one
calendar day *after* the date its own title stated, most likely because the stream ran late at
night and technically crossed over into the next day by the time YouTube recorded it — a
mismatch between "the date someone wrote down" and "the exact timestamp a system recorded," not
an error in either one. Because of that, the title's stated date is kept as the primary source
of truth everywhere it exists; the real upload date is used only to fill a genuine gap, not to
"correct" a title that already gives an answer.

**Why this is its own separate script, run only for a handful of videos, instead of just having
`fetch.py` grab every video's real date up front:** opening one video's page individually — the
only way to get its real upload date — takes several seconds with the login this channel
requires. Doing that for all 342 videos would take 25 minutes or more, which is not worth it when
the vast majority of titles already state a usable date on their own (see 4.2.2). Doing it only
for the small remainder that truly need it keeps this extra step fast, while still giving every
video in the catalog a real date.

#### 4.2.5 What this step writes out

- `streams_master.csv` / `.json` — the full list of 342 videos, each with its series, resolved
  date, video link, duration, and view count.
- `streams_by_category.json` — the same videos, grouped by series.
- `by_category/*.csv` — one small file per series (useful if someone wants just one series'
  video list without opening the full catalog).
- `CATALOG.md` — a single Markdown document listing every series and its videos, viewable
  directly on any site that renders Markdown, with no extra tooling needed.

### 4.3 `src/build_sequences.py` — Step 3: working out watch order

This step solves the "language tracks getting mixed together" problem described in section
1.2.3. It reads `streams_master.json` (from Step 2) and produces `output/sequences.json` — the
one file the search page actually uses.

**The core idea:** the right *unit* for a watch-in-order sequence is not "series" — it is
**"series plus language."** A series like "Satyatma Sandhya" was taught three separate times, in
English, Kannada, and Marathi, each as its own independently numbered set of sessions. Grouping
by series alone would interleave English session 3 with Kannada session 7 with no relationship
between them. Splitting further by language keeps each taught sequence intact.

**How the language is detected:** a simple check for whether a known language name (Kannada,
English, Marathi, and a few others in case the channel ever uses them) appears anywhere in the
video's title text. This deliberately does not require the language name to stand alone as a
separate word — some titles jam it directly onto the next word with no space at all (for
example, "Sandhyavandanakannada"), and a plain word-by-word check would miss those.

One extra rule avoids a subtle duplicate: some series names *already* state their language in
the series name itself (for example, "Manimanjari (Kannada)"). For those, the language check is
skipped, and the whole series is treated as one sequence — otherwise, a video in that series
whose *title* also happened to say "Kannada" would incorrectly split off into a second,
identically-named group.

**How the order is worked out:** every video keeps track of its original position in the
channel's own newest-first list (position 1 = the newest video on the whole channel). Within a
sequence, sorting by that position — from *largest* number to *smallest* — puts the oldest video
in that sequence first, which is watch order for a lecture series. Each video in a sequence is
then labeled "video X of Y" using that order.

**What this step writes out:** one JSON file, `sequences.json`, containing every sequence. Each
sequence carries its display label (for example, "Satyatma Sandhya (Kannada)"), its ordered list
of videos, and a pre-built list of searchable words drawn from its own title text and series
name — this pre-built word list is what makes the search page's search instant, with no work
needed at search time beyond comparing words that are already sitting in the file.

### 4.4 `search.html` and `search.js` — Step 4: the search page

Two plain static files — no server, no build step, no framework. The page loads
`sequences.json` once when it opens, then does all searching and filtering directly in the browser
as the person types.

**Why two files rather than one.** The page was originally a single self-contained HTML file, which
read well but left the matching rules untestable: they were closure-local functions inside an
inline `<script>`, unreachable from anything outside the browser. `search.js` now holds the pure
matching logic and nothing else — it has no state and never touches the DOM — while `search.html`
holds all the rendering. That keeps the "no build step, no framework" property intact (it's still
just a `<script src>` tag) and makes both halves testable: the matching rules directly, and the
rendering against a small stub DOM. See section 7.

**How searching works:** the search box is split into individual words as the person types (for
example, "sandhyavandana kannada" becomes two words: "sandhyavandana" and "kannada"). A sequence
is shown as a result only if it matches **every** word typed — this is why searching
"sandhyavandana kannada" returns only Kannada-language sandhyavandana sequences, not every
Kannada video on the channel and not every sandhyavandana video in every language.

Matching a single word against a sequence uses a flexible check in both directions — the typed
word can be a piece of a word in the sequence's title, or a word in the sequence's title can be a
piece of the typed word. This is what lets a search for the full word "sandhyavandana" find
sequences whose titles only ever wrote the shorter "sandhya," and what lets "kannada" match a
title that squashed it directly onto another word with no space.

Two kinds of word fall back to an exact match instead:

- **Numbers.** A plain number (like "28," from the series "28 Moorthi Stuti") must match a number
  in the sequence's title *exactly*, not as a partial piece. Without this, a search containing the
  number "2" would match "2026," which appears somewhere in nearly every title on the channel
  (it's the current year).
- **Words of one or two letters,** which are too short to narrow anything down as a partial
  match. They still match a word of the same length exactly, so a genuinely short search term
  finds its sequence rather than silently returning nothing.

**Accessibility.** The topic boxes are real buttons rather than clickable boxes, so they can be
reached and activated from the keyboard and are announced as controls by a screen reader. The
search field has a visible label, the result count is announced as it changes, each result table
carries a description naming its sequence, and the greys used throughout are dark enough to meet
the WCAG AA contrast ratio for small text. Full WCAG conformance would still need hands-on testing
with assistive technology and an accessibility review — this covers the issues that can be
verified from the markup alone.

**The topic boxes:** below the search bar, one small box is shown per series, labeled with its
name and its total video count across all of that series' languages (for example, "Sumadhwavijaya
(Marathi) (84)"). Boxes are sorted largest-first. Clicking a box fills the search bar with that
series' name and runs the search immediately — the searcher can then type more into the box (for
example, adding "kannada") to narrow the results further, without starting from scratch.

---

## 5. Architecture — how the pieces fit together

```
                     ┌─────────────────────────┐
  YouTube's channel  │                         │
  "Streams" page  →  │      src/fetch.py       │  → data/raw_playlist.json
                     │  (asks yt-dlp for the   │      (title, video ID,
                     │   video list, once)     │       duration, views)
                     └─────────────────────────┘
                                  │
                                  ▼
                     ┌─────────────────────────┐
                     │    src/categorize.py    │  → output/streams_master.csv / .json
                     │  (sorts each video into │  → output/streams_by_category.json
                     │   a series; works out   │  → output/by_category/*.csv
                     │   a date from the title)│  → output/CATALOG.md
                     └─────────────────────────┘
                                  │
                                  ▼ (for any video still missing a date)
                     ┌─────────────────────────┐
                     │ src/fill_unknown_       │  → data/known_upload_dates.json
                     │        dates.py         │      (fed back into categorize.py
                     │ (fetches a REAL date    │       on its next run)
                     │  for just those videos) │
                     └─────────────────────────┘
                                  │
                                  ▼
                     ┌─────────────────────────┐
                     │ src/build_sequences.py  │  → output/sequences.json
                     │ (splits each series by  │      (the file search.html
                     │  language; works out    │       actually reads)
                     │  watch order)           │
                     └─────────────────────────┘
                                  │
                                  ▼
                     ┌─────────────────────────┐
                     │      search.html        │  → what a person opens in a
                     │ (loads sequences.json,  │     browser and interacts with
                     │  searches + displays    │
                     │  it live in the browser)│
                     └─────────────────────────┘
```

Everything runs on the local machine. There is no server component and no external service
involved beyond the one-time download from YouTube in Step 1. Steps 2 through 4 can be re-run
entirely offline, as many times as needed, using the saved `raw_playlist.json` from Step 1.

---

## 6. Limitations and Possible Future Work

These are documented honestly rather than glossed over, since knowing a limitation exists is
often as useful as fixing it:

- **No video descriptions to draw on.** If the channel ever starts writing descriptions, this
  project's series-matching and date-parsing logic could be extended to use them as an extra,
  more reliable signal — today there is nothing there to use.
- **A title's stated date and a video's real YouTube upload date are not always identical.** A
  spot-check across a sample of videos found most of them one calendar day apart, almost
  certainly because a late-night stream can technically finish after midnight even though the
  title still names the day it started. The title is kept as the source of truth wherever it
  states a date; the real upload date is used only as a fallback when the title has nothing.
- **Some titles contain their own typos, and the catalog repeats them faithfully.** There are
  eight points in the catalog where a stated date disagrees with where its video sits in the
  channel's own listing. Seven of them trace to a mistyped title: `Sumadhwavijaya Marathi 4th
  June 2026` sits between videos dated the 5th and the 2nd of July, and `Manimanjari kannada
  Day24 !9th June 2026` writes "!9th" where it plainly means "19th". (The eighth is a video with
  no date in its title at all, using its real fetched upload date, which can legitimately differ
  by a day — see the point above.) These are mistakes in the source titles, not in the parsing,
  and they are left as written rather than silently rewritten: a rule that "corrected" a stated date based on
  neighboring videos would be guessing, and would quietly overwrite correct dates whenever the
  channel's listing order and the recording order genuinely differ. The watch order is unaffected,
  since sequences are ordered by listing position rather than by date (see section 4.3).
- **New videos with no date in their title will show as `"Unknown"` until `fill_unknown_dates.py`
  is re-run.** That script only fetches real dates for videos it hasn't already resolved, so it
  needs to be run again any time the catalog is refreshed with newly uploaded videos, to pick up
  any brand-new video that also happens to have no date in its title.
- **Series-matching is rule-based, not manually checked video by video.** It was validated by
  checking that only one video (out of 342) failed to match any rule, but an unusually worded
  title for an existing series could theoretically still be missed or mis-matched. Adding a new
  series, or fixing a mismatch, means adding or adjusting one line in the rule list in
  `categorize.py`.
- **The search page has no ranking beyond "matches every word."** All matching sequences are
  shown; there's no attempt to guess which one the searcher most likely wants first. Given the
  intentionally small number of matches per search this produces in practice, this has not been
  a problem, but a future version could sort sequences by some notion of relevance if the
  catalog grows large enough for that to matter.

---

## 7. Testing

### 7.1 What is tested, and why it is tested that way

The tests are shaped by where this project actually got things wrong. Four videos in an earlier
version of this catalog carried dates that were simply incorrect — not missing, not approximate,
but wrong — and all four came from the same file: the title-parsing rules in `categorize.py`. So
that is where the tests are densest.

`tests/test_categorize.py` opens with a class called `RegressionTests` holding one named test per
date this catalog once reported incorrectly, each asserting the correct value and explaining in its
docstring what went wrong. If any other test in this project were ever deleted, these are the ones
to keep. The rest of the file covers the parsing rules more broadly: every way the channel writes a
date, every month name and abbreviation, the "Day N" session-label rule and the cases it must *not*
fire on, the year-carry-backward walk including its year-boundary and jitter behavior, and the
series-matching rules where one keyword has to beat another.

`tests/test_build_sequences.py` covers the language split — the thing that makes a sequence a
sequence. Its central case is a single category taught in three languages, which must come out as
three separately numbered tracks, plus the inverse: a category that already names its own language
must *not* be split into two identically labelled groups.

`tests/test_pipeline.py` runs the real `categorize` and `build_sequences` steps over the real saved
`data/raw_playlist.json`, writing into a temporary directory so nothing committed is disturbed. It
asserts the properties a reader of the catalog would care about rather than exact contents: every
raw entry becomes exactly one row, video IDs are unique, no date is left as a guess, no date sits
in the future relative to the newest video, every video appears in exactly one sequence, sequence
numbering is contiguous, and no two sequences share a label. It also pins the four corrected dates
a second time, this time end to end.

`tests/search_logic.test.mjs` tests `search.js` directly, including the cases that motivated its
odd-looking rules: a bare `"2"` must not match `"2026"`, and a one or two letter word must not
match by substring. The second half of the file runs real searches against the committed
`sequences.json`, so a change to the catalog that breaks a search a person would actually type is
caught.

`tests/page_render.test.mjs` covers the part that nothing checked before: the page's own script. It
runs the real inline script against a small stub DOM implementing only the handful of methods that
script uses, then asserts on the structure produced — that topic controls are real `<button>`
elements with accessible labels and click handlers, that result rows come out in watch order, that
links carry `rel="noopener noreferrer"`, that each table has a screen-reader description and
`scope="col"` headers, that a hostile title is written as text rather than markup, and that a
failed load explains how to fix it. The stub is deliberately dumb: if the page starts using a DOM
method it does not implement, the test fails loudly rather than passing on a silent no-op.

### 7.2 Choices worth explaining

**No test framework.** The Python tests use the standard library's `unittest` and the JavaScript
tests use Node's built-in `node --test`. Both ship with their runtime, so the whole suite runs on a
fresh clone with nothing installed. That is a deliberate match to this project's zero-dependency
stance (section 3) — adding `pytest` would be more idiomatic in isolation, but it would make the
README's "no package install step" claim untrue for a small gain.

**No browser or DOM library.** Testing the page against a real DOM would mean pulling in a headless
browser or a library like `jsdom` — by a wide margin the heaviest dependency in the project, for one
file. The stub DOM in `tests/page_render.test.mjs` is around 120 lines and covers what this page
actually does. The tradeoff is honest: it verifies the page builds the right structure, not that a
real browser paints it correctly, and it cannot substitute for opening the page and using it.

**A freshness check instead of golden files.** Rather than committing expected output files and
diffing against them, CI regenerates `output/` from the saved playlist and fails if the result
differs from what is committed. This catches the two failure modes that matter — a code change that
silently alters the published catalog, and committed output that has drifted from the code that
produced it — without a second copy of the data to keep in sync.

### 7.3 Running them

```bash
make check     # lint, both test suites, and the catalog freshness check — what CI runs
make test      # both test suites
make lint      # ruff (the one development dependency)
```

### 7.4 What is still not covered

- **The page in a real browser.** See above: structure is tested, rendering is not.
- **`fetch.py` and `fill_unknown_dates.py` against YouTube.** Both shell out to `yt-dlp` and need
  network access and browser cookies, so neither is exercised by the suite or by CI. Their argument
  handling and error paths are simple and readable; their happy paths are verified by the fact that
  `data/raw_playlist.json` and `data/known_upload_dates.json` exist and are consumed by everything
  downstream.
- **The CSS.** Contrast ratios were computed by hand against the WCAG AA threshold for small text;
  nothing checks them automatically, so a future colour change could regress them unnoticed.
