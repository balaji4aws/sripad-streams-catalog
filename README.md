# Sripad K — Streams Catalog

A catalogue of the live-stream recordings on the [Sripad K](https://www.youtube.com/@sripadk8492/streams)
YouTube channel, so they can be watched **in order**.

The channel has 342 recorded streams — devotional classes, satsangs and readings in Kannada,
Marathi and English — and no playlists. They sit in one long list sorted by upload date, which
makes a series hard to follow: you can't tell which videos belong together, or which one comes
first. This project groups them into series and works out a watch order within each one.

**[Open the search page](search.html)** — type a few words and you get matching series as small
ordered lists ("video 1 of 12", "video 2 of 12"), rather than a flat pile of links. Or browse
[the full catalogue](output/CATALOG.md) as a single page.

Content and recordings belong to the channel. This is an independent, unofficial index built from
the channel's public listing, made with appreciation for the work that went into the streams.

## How it works

Four small steps, each writing a file the next one reads:

```
fetch.py  →  categorize.py  →  build_sequences.py  →  search.html
 get the      sort into         work out watch         search it
 video list   series + dates    order per series       in a browser
```

Grouping and ordering work from the video **titles**, because every description on the channel is
empty. Titles are informal and inconsistent, so most of the care in this project goes into reading
them reliably. [DESIGN.md](DESIGN.md) explains every decision and the reasoning behind it.

```
search.html / search.js       the search page
src/                          the four pipeline steps
data/raw_playlist.json        the saved video list, so steps 2-4 run offline
output/                       the catalogue: CSV, JSON, and CATALOG.md
tests/                        see REFRESH.md
```

## Running it

You need [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (`brew install yt-dlp`) and a Chrome logged
into YouTube — the fetch borrows your browser's own cookies locally so YouTube doesn't refuse the
request. Nothing is uploaded anywhere.

```bash
python3 src/fetch.py               # download the video list
python3 src/categorize.py          # sort into series, work out dates
python3 src/fill_unknown_dates.py  # fill any dates the titles didn't give
python3 src/categorize.py          # pick up those dates
python3 src/build_sequences.py     # work out watch order
make serve                         # then open http://localhost:8000/search.html
```

Steps 2 to 5 need no network — they read the saved `data/raw_playlist.json`. Every script takes
`--help`. To refresh the catalogue with newly uploaded videos, see **[REFRESH.md](REFRESH.md)**.

## Development

```bash
make check          # lint, type-check, both test suites, catalogue freshness
make test-browser   # load the page in a real browser, including contrast (needs Chrome)
```

`make help` lists the rest. The tests need nothing installed; `make lint` and `make typecheck`
need `pip install -r requirements-dev.txt`. Details of what's covered are in
[DESIGN.md section 7](DESIGN.md#7-testing).

## What it gets wrong

Worth knowing before trusting a date or a grouping:

- **Seven dates disagree with the channel's own ordering**, because those titles contain typos
  (`Sumadhwavijaya Marathi 4th June 2026` sits between videos dated 5 July and 2 July). Titles are
  reproduced as written rather than silently corrected. Watch order is unaffected — it comes from
  the channel's listing order, not the dates.
- **78 videos don't say which language they're in**, so they're grouped separately and labelled
  "Language not stated". The language is never guessed.
- **One video matched no series** and sits in a catch-all group.
- **Two videos are dated to the month only**, because their titles give no day.

Grouping is by title keyword, not by watching each video, so an unusually worded title could be
misfiled. [DESIGN.md section 6](DESIGN.md#6-limitations-and-possible-future-work) covers the
tradeoffs.

## Author and license

Built by **Balaji Venkatesh** (balaji4aws@gmail.com). Code is [MIT licensed](LICENSE).

That covers the code only. The recordings remain the channel's, and the catalogue metadata in
`data/` and `output/` is derived from the channel's public listing — it's committed so the pipeline
can be re-run and the search page used without re-scraping.
