# Sripad K — Video Catalogue

**A YouTube channel with 465 recorded classes and no playlists. This turns it into something you
can actually watch in order.**

### ▶ [Try it here](https://balaji4aws.github.io/sripad-streams-catalog/search.html)

---

## The problem

The [Sripad K](https://www.youtube.com/@sripadk8492) channel has 465 recordings going back to 2015 —
devotional classes and readings in Kannada, Marathi and English. They are taught as *series*: one
subject over dozens of weekly sessions.

YouTube shows them as one long list in upload order, with no playlists. So:

- The 108 sessions of one series are scattered among 465 videos.
- Nothing tells you which session comes first, or what to watch next.
- Some series were taught more than once in different languages, and the two runs are interleaved.
- Some series are split across the channel's two tabs, so part of the series is easy to miss.

Search doesn't help. Typing "sandhyavandana" into YouTube returns dozens of videos from unrelated
series, in three languages, in no useful order. If you want to *start at the beginning and work
through*, you can't.

## The solution

A search page. Type a topic, and you get the matching series as **numbered, ordered lists**:

```
Bhagavata Saroddhara (Kannada)          108 videos, watch in order below
   1/108   2023-04-08   Day 1 - Bhagavata Saroddhara - Shloka 1
   2/108   2023-04-15   Day 2 - Bhagavata Saroddhara - Shloka 2-3
   3/108   2023-04-22   Day 3 - Bhagavata Saroddhara - Shloka 4
   ...
```

You always know where to start and what comes next. Languages are kept apart, so the Kannada run of
a series doesn't get mixed into the English one. Where something needs explaining — a session the
channel never posted, or one uploaded twice — the page says so under that series.

Every link goes to the video on YouTube. Nothing is copied or re-hosted.

## How it works

Four small steps. Each writes a file the next one reads, so any step can be re-run on its own:

```
  fetch.py      →   categorize.py    →   build_sequences.py   →   search.html
  read both         sort into            work out the             search it in
  channel tabs      series + dates       order of each series     the browser
```

The interesting part is that **there is almost nothing to work with.** Every video description on
the channel is empty — so the only data is the title. And the titles are handwritten and
inconsistent:

```
Sumadhwavijaya Marathi - 3rd Sep2026        ← month and year run together
Sumadhwavijay-Marathi-Day4-15thJan26        ← missing letter, no spaces, 2-digit year
Sumadhawavijaya Marathi Day1-11th Jan26     ← extra letter
Day 102 Bhagavata Saroddhara -25/Jul/2026   ← a different date format entirely
Day 63- Bhagavata Saroddhara -3oth Nov      ← "3oth" is typed with the letter o
```

All the difficulty lives there. A few examples of what the code has to get right:

- **`Mar` hides inside `Marathi`.** A naive date parser reads "Day1 Marathi 16th May" as *1 March*.
- **`Day 24th June` is a date; `Day 2 Feb 3rd` is session 2.** The ordinal suffix tells them apart.
- **`Oct 2024` has no day in it.** So that video is dated to the month, not padded to a made-up day.
- **The channel's own ordering is sometimes wrong.** One series is listed in an order contradicting
  its own session numbers in ten places, so the session number is trusted instead.

## The one rule

**Never guess, and say so when you have to.**

Dates keep the precision the title actually gives. A typo is reproduced as written rather than
silently "corrected". A video matching no known series goes to a catch-all rather than the
nearest-looking guess. And where the language isn't stated anywhere, the catalogue assumes the
channel's main language but labels it **"Kannada, assumed"** — so you can always tell what was
written down from what was worked out.

## Running it

Needs [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (`brew install yt-dlp`) and a Chrome logged into
YouTube — the fetch borrows your browser's own cookies locally, so YouTube doesn't refuse the
request. Nothing is uploaded anywhere.

```bash
python3 src/fetch.py               # download the video list from both tabs
python3 src/categorize.py          # sort into series, work out dates
python3 src/fill_unknown_dates.py  # fill any dates the titles didn't give
python3 src/categorize.py          # pick those up
python3 src/build_sequences.py     # work out watch order
make serve                         # then open http://localhost:8000/search.html
```

Steps 2–5 need no network: they read the saved `data/raw_playlist.json`. To refresh the catalogue
with new videos, follow **[REFRESH.md](REFRESH.md)**.

## Development

```bash
make check          # lint, type-check, both test suites, catalogue freshness
make test-browser   # drives real Chrome, including WCAG contrast (needs Chrome)
```

**No dependencies.** The scripts use only the Python standard library; the page is plain HTML, CSS
and JavaScript with no framework and no build step. Even the tests need nothing installed — Python
uses `unittest`, JavaScript uses Node's built-in runner. `ruff` and `mypy --strict` are the only dev
tools.

**148 Python tests, 33 JavaScript, 34 in a real browser.** Worth knowing what they're for: four dates
in this catalogue were once wrong, and each has a named regression test that spells out the bug. The
browser check drives actual Chrome — searching, tabbing to a button and pressing Enter, checking for
overflow at phone width — and measures colour contrast from *computed* styles, so a colour change
that fails WCAG AA breaks the build.

CI also rebuilds the whole catalogue from the saved input and fails if the committed output differs,
which keeps the published data honest about the code that produced it.

**[DESIGN.md](DESIGN.md)** explains every decision and why, including the ones that turned out wrong
first. It's the interesting read if you want the reasoning rather than the summary.

## What it gets wrong

- **A few dates contradict the channel's own ordering**, because those titles have typos. Reproduced
  as written, not corrected. Watch order is unaffected — it comes from session numbers and listing
  position, not dates.
- **200 videos don't state a language**, so they're labelled "Kannada, assumed".
- **One video matches no series** and sits in a catch-all.
- **Three videos are dated to the month only**, because their titles give no usable day.

Grouping is by keyword on the title, not by watching each video, so an unusually worded title could
be misfiled.

## Author and licence

Built by **Balaji Venkatesh** (balaji4aws@gmail.com). Code is [MIT licensed](LICENSE).

That covers the code only. The recordings remain the channel's, and the catalogue data in `data/`
and `output/` is derived from the channel's public listing — committed so the pipeline can be re-run
and the page used without re-scraping. This is an independent, unofficial index, made with
appreciation for the teaching it points to.
