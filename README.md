# Sripad K — Streams Catalog

This project turns one YouTube channel's giant, unsorted list of live-stream recordings into
something a viewer can actually use: a small search page that returns videos **in the order you
should watch them**, not just a pile of loosely related links.

It scrapes the [Sripad K channel's Streams tab](https://www.youtube.com/@sripadk8492/streams)
(342 recordings as of this writing — devotional classes, satsangs, and readings in Kannada,
Marathi, and English), groups the videos into named series, works out a watch order for each
series, and serves all of that through one search page (`search.html`).

For the full problem statement, the approach, and how every part of the code works, see
**[DESIGN.md](DESIGN.md)**. This file is the quick-start.

## The problem, in one paragraph

YouTube's "Streams" tab is just one long list, sorted by upload date, with no concept of
"series" or "which video comes next." A channel that has been running lecture series for years
ends up with hundreds of videos where a viewer has no way to tell what a given video is part of,
or what to watch before or after it. Searching by keyword makes this worse, not better — a
keyword like "sandhyavandana" matches videos from several unrelated series, and YouTube search
returns them as a flat, unordered pile. This project fixes both problems: it groups videos into
series, and it works out an order within each series.

## What you get

- **A search page** (`search.html`) where typing a few words returns matching series as small,
  ordered lists (video 1 of 12, video 2 of 12, and so on) instead of a wall of unordered results.
- **Topic boxes** under the search bar showing every series and how many videos it has (for
  example, "Sumadhwavijaya (Marathi) (84)"). Click one to load that series name into the search
  box and see its videos — then edit the search text to narrow it down further (add a language
  name, for instance).
- **Plain data files** (CSV, JSON, and a Markdown catalog) if you'd rather browse or process the
  data yourself instead of using the search page.

## Project layout

```
sripad-streams-catalog/
├── search.html                  the search page — open this in a browser
├── src/
│   ├── fetch.py                  step 1: downloads the raw video list from YouTube
│   ├── categorize.py             step 2: sorts videos into series, works out dates
│   ├── fill_unknown_dates.py     step 2b: fetches a real date for videos with no date in the title
│   ├── build_sequences.py        step 3: works out watch order within each series
│   └── catalog_paths.py          shared default input/output locations
├── data/
│   ├── raw_playlist.json         the raw output of step 1 (saved so you don't have to re-download)
│   └── known_upload_dates.json   real per-video dates fetched by step 2b, for titles with no date
└── output/                        everything steps 2 and 3 produce
    ├── streams_master.csv/.json      every video, one row each
    ├── streams_by_category.json      videos grouped by series
    ├── by_category/*.csv             one file per series
    ├── sequences.json                 the file search.html actually reads
    └── CATALOG.md                     a browsable Markdown version of the whole catalog
```

Every file's exact job, and the logic behind it, is explained in **[DESIGN.md](DESIGN.md)**.

## How to run it

You need [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (a free command-line tool for reading
YouTube video lists — install with `brew install yt-dlp` on a Mac) and a Chrome browser that is
logged into YouTube (the scraper borrows your browser's login cookies locally, on your own
machine, so YouTube doesn't block the request as a bot — nothing is uploaded anywhere).

```bash
python3 src/fetch.py               # step 1:  download the video list
python3 src/categorize.py          # step 2:  sort into series, work out dates
python3 src/fill_unknown_dates.py  # step 2b: fill any remaining Unknown dates
python3 src/categorize.py          # step 2 again: pick up the filled-in dates
python3 src/build_sequences.py     # step 3:  work out watch order
```

Every script defaults its input and output locations relative to the repository root, so these
commands work from any directory. Pass `--help` to any of them to see the flags for overriding
those locations.

Step 2b only needs to run once for a given set of videos — it saves what it fetches to
`data/known_upload_dates.json`, and on future runs it skips any video already in that file.

Then open `search.html` in a browser (serving the folder with a simple local web server works
best, for example `python3 -m http.server 8000` from this folder, then visit
`http://localhost:8000/search.html`).

Re-run all three steps any time you want to refresh the catalog with newly uploaded videos.

## Known limitations

- **No video descriptions to work with.** Every video on this channel has an empty description
  field, so all the grouping and ordering logic works from the video *title* text alone.
- **A small number of videos have no date in their title at all.** For those, the catalog falls
  back to the video's real YouTube upload date instead (fetched individually, just for that
  handful of videos — see `src/fill_unknown_dates.py`). Every video in the catalog now has a
  date; none are left marked `Unknown` in the current run.
- **Two videos are dated to the month only.** Their titles name a month and year but no day
  (`Sandhyavandana Online Oct 2024`), so they show as `2024-10`. A day is never invented to fill
  the gap.
- **A title's stated date and its real YouTube upload date don't always match exactly.** In a
  spot-check, most were one calendar day apart (most likely late-night uploads rolling into the
  next day), so a small mismatch between the two is expected and not a bug.
- **Some titles contain their own typos, and the catalog repeats them faithfully.** A handful of
  videos state a date that contradicts their position in the channel's listing (for example
  `Sumadhwavijaya Marathi 4th June 2026`, sitting between videos dated the 5th and the 2nd of
  July). The stated date is kept as-is rather than being silently corrected. Watch order is
  unaffected, because sequences are ordered by channel listing position rather than by date.
- **Grouping is keyword-based, not manually checked video by video.** One video out of 342 didn't
  match any of the known series names and landed in a catch-all "Uncategorized" group.

See DESIGN.md for the reasoning behind each of these tradeoffs.

## Author

Built by **Balaji Venkatesh**, for organizing **Sripad K**'s stream catalog. This is an
independent personal tool built from publicly available YouTube data — it is not affiliated with
or endorsed by the channel.
