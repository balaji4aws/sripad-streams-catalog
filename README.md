# 🎥 Sripad K — Streams Catalog

A small scraper + organizer for the **[Sripad K YouTube channel's Streams tab](https://www.youtube.com/@sripadk8492/streams)**
(342 livestream recordings, mostly Madhwa/Vaishnava satsangs, classes, and stotra/stuti readings
in Kannada and Marathi). Pulls every stream's title and metadata, groups them into recurring
series/categories, and writes the result out as CSV, JSON, and a browsable Markdown catalog.

## Why this exists

The channel has 342 streams with no playlists to organize them — just one long reverse-chronological
list. This project turns that into **40 named series/categories** (e.g. "Sumadhwavijaya (Marathi)",
"Manimanjari (Kannada)", "Satyatma Sandhya", various "NKHK" satsang sub-series) so you can browse a
single series' history instead of scrolling the whole channel.

**Important finding:** every video's *description* field is empty (0 bytes) — confirmed by
checking descriptions across the channel, not assumed. So there's nothing to scrape or organize
from descriptions; **titles are the only usable metadata**, and that's what this project scrapes.

## What it does

1. **`src/fetch.py`** — calls `yt-dlp` to pull the full stream list (title, video ID, duration,
   view count) from the channel's Streams tab in one request.
2. **`src/categorize.py`** — reads that raw data and:
   - Assigns each stream to a category by matching recurring series-name keywords in its title
     (see "How categorization works" below).
   - Parses a date out of each title where possible (day/month, and year when present).
   - Writes out:
     - `output/streams_master.csv` / `.json` — every stream, one row each, newest-first
     - `output/streams_by_category.json` — the same data grouped by category
     - `output/by_category/*.csv` — one CSV per category
     - `output/CATALOG.md` — a single browsable Markdown file with a category index and a
       table per category (title, date, duration, views, link)

## Run it

Requires [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (`brew install yt-dlp`) and a Chrome
profile you're logged into on YouTube (used only to read cookies locally, needed because the
channel's Streams tab triggers YouTube's bot-check for anonymous requests — nothing is uploaded
or sent anywhere beyond the normal request to YouTube).

```bash
python3 src/fetch.py                          # -> data/raw_playlist.json
python3 src/categorize.py                      # -> output/*
```

Re-run `fetch.py` any time to refresh the raw data (e.g. after a new stream goes up), then
re-run `categorize.py` to regenerate the organized output.

## How categorization works

Titles on this channel are informal and inconsistently punctuated — typos, mixed date formats,
inconsistent spacing (`"9th July2026"` vs `"9th July 2026"`), occasional stray characters. There's
no structured tagging to rely on. What titles *do* have is a recognizable, recurring set of
series names. `categorize()` in `src/categorize.py` is an ordered list of substring-match rules
built by inspecting the actual titles — most specific series names checked first (e.g.
`"sumadhwavijaya"`), falling back to generic catch-alls (`"nkhk"`, `"satsanga"`) only if nothing
more specific matched, and finally to `"Uncategorized / Other"` if no rule matches at all (**1**
stream out of 342 landed there).

## How dates are resolved

`yt-dlp`'s fast `--flat-playlist` mode (what `fetch.py` uses) doesn't return a real per-video
upload date. There's a flag that claims to (`--extractor-args youtubetab:approximate_date`) — it
was tried and rejected: on this channel it returned a small number of distinct "bucket"
timestamps, each reused across dozens of unrelated videos (one single fake date was shared by 67
different streams). Fetching a genuine date per video means loading each video's own page
individually, which — with the cookie auth this channel requires — takes several seconds each;
for 342 videos that's 20–30+ minutes, which didn't seem worth it for a first pass.

Instead, dates are **parsed directly from the title text**:
1. Look for an explicit day + month (+ year if present) in the title, in either order
   (`"4th June 2026"` or `"Oct 2nd 2023"`).
2. If the year is missing, carry forward the most recently seen year — the channel lists streams
   newest-first, so walking down the list is walking backward in time — and step it back by one
   when the month sequence implies a year boundary was crossed (a `"21st Jan"` appearing after a
   run of Nov/Dec titles is the *preceding* January, not the same year).
3. If no date can be parsed from the title at all, it's marked **`Unknown`** rather than guessed.
   24 of 342 streams fall into this bucket — mostly early (2021–2023) titles that never included
   a date, or ambiguous fragments like "Day2" with no date text at all.

Every resolved/unresolved date was spot-checked against its neighbors in the list (see
`src/categorize.py`'s `resolve_dates()` docstring) to confirm no incorrect year rollovers.

## Project structure

```
sripad-streams-catalog/
├── src/
│   ├── fetch.py            # pulls the raw stream list via yt-dlp
│   └── categorize.py       # categorizes + resolves dates + writes all output formats
├── data/
│   └── raw_playlist.json   # raw yt-dlp output (committed, so output/ is reproducible without re-scraping)
└── output/
    ├── streams_master.csv/.json
    ├── streams_by_category.json
    ├── CATALOG.md
    └── by_category/*.csv
```

## Limitations

- **No descriptions** — as noted above, every video's description is empty. If Sripad K ever
  starts adding descriptions, `fetch.py`/`categorize.py` would need extending to pull and use them
  (currently out of scope, since there's nothing there today).
- **24 streams have an unresolved date** (marked `Unknown`) — see above. They're still included in
  every output, just without a specific date, in the channel's own newest-first order.
- **Categorization is keyword-based, not manually reviewed** — a title using unusual phrasing for
  a series could land in the wrong bucket or in "Uncategorized / Other". The single
  "Uncategorized / Other" entry (`"Marathi saturday 10th April"`) is a good example of a title too
  generic to confidently place.

## Author

Built by **Balaji Venkatesh** with [Kiro](https://kiro.dev), for organizing **Sripad K**'s stream
catalog. Not affiliated with or endorsed by the channel — this is a personal tool built from
publicly available YouTube data.
