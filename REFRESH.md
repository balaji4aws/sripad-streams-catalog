# Refreshing the catalogue

The channel keeps streaming, so this catalogue goes stale. It is refreshed roughly **every two
weeks**. The search page shows the last scan date and when the next one is due, and says so plainly
once a refresh is overdue.

This file is the runbook. Work through it in order.

---

## Before you start

- [ ] `yt-dlp` on PATH (`brew install yt-dlp`, or `pip install -U yt-dlp`). It breaks whenever
      YouTube changes something, so **update it first** — a stale `yt-dlp` is the most common cause
      of a failed fetch.
- [ ] Chrome installed and logged into YouTube. The fetch borrows its cookies locally; without
      them YouTube refuses the request as bot traffic.
- [ ] Working tree clean (`git status`), so the refresh shows up as its own reviewable diff.
- [ ] `pip install -r requirements-dev.txt` if you want `make lint` and `make typecheck`.

## 1. Fetch

```bash
python3 src/fetch.py
```

Prints the number of streams found. **Sanity-check it** against the previous run: it should have
grown by roughly the number of streams since the last scan, and never shrunk. A sharp drop means
the fetch was throttled or partially blocked — investigate rather than committing it, because a
short list silently deletes videos from the catalogue.

If it fails, in this order: update `yt-dlp`; confirm Chrome is logged in; try
`--browser firefox`; raise `--timeout`.

## 2. Build the catalogue

```bash
python3 src/categorize.py          # sort into series, work out dates
python3 src/fill_unknown_dates.py  # only if the step above reports unresolved dates
python3 src/categorize.py          # re-run so those dates flow through
python3 src/build_sequences.py     # watch order
```

`fill_unknown_dates.py` only fetches videos it hasn't already resolved, so it is cheap to re-run
and skippable when `categorize.py` reports `0 with unresolved dates`.

## 3. Check the new videos specifically

This is the part that needs a person. Everything else is automated.

```bash
make check          # lint, types, both test suites, catalogue freshness
make test-browser   # real browser: search, keyboard, layout, WCAG contrast
git --no-pager diff --stat -- output/
```

Then look at what actually changed, and check these five things:

- [ ] **Did any new video land in `Uncategorized / Other`?**
      ```bash
      grep -c 'Uncategorized' output/streams_master.csv
      ```
      One known video sits there (`Marathi saturday 10th April`, which names no series at all). A
      count above that means a new title didn't match any rule — add or widen a spelling in `RULES`
      in `src/categorize.py`. It's one line, and there's a test pattern to copy.

- [ ] **Did any new video come out with a wrong date?** Titles carry typos, and a new *kind* of
      typo can defeat the parser. This lists every place a date disagrees with the channel's own
      ordering:
      ```bash
      python3 - <<'PY'
      import json
      rows = json.loads(open('output/streams_master.json').read())
      prev = None
      for r in rows:
          if prev and r['date'] > prev:
              print(f"pos {r['list_position']:>3}  listed after {prev} but dated {r['date']}  {r['title']!r}")
          prev = r['date']
      PY
      ```
      **Seven results are expected** and are typos in the source titles (see README). More than
      seven means a new title needs looking at. If the parser mis-read it — rather than the title
      being wrong — add a case to `RegressionTests` in `tests/test_categorize.py` first, then fix
      it.

- [ ] **Did the scan date update?** `output/catalog_meta.json` should show today-ish in
      `scanned_on`, and `next_scan_due` two weeks out. If `scanned_on` didn't move, step 1 didn't
      actually re-fetch.

- [ ] **Did any sequence lose its order?** Watch order comes from position in the channel listing,
      not from dates, so it is normally robust. Spot-check one series you know in the browser and
      confirm video 1 really is the first session.

- [ ] **Did the counts move sensibly?** `git diff --stat -- output/` should show a handful of new
      rows, not a rewrite. A large diff on old rows means a rule change altered history — deliberate
      or not, understand it before committing.

## 4. Commit and publish

```bash
git add data/ output/ && git commit
git push
```

Commit the data and the generated output together, in one commit, with the new stream count in the
message. CI rebuilds `output/` from `data/raw_playlist.json` and fails if the committed files don't
match, so they must be regenerated and committed together or the build breaks.

The live page is served by GitHub Pages from `main`, so pushing publishes it. Give Pages a minute,
then run the same browser checks against the deployed copy — this catches a path that works locally
but breaks under the Pages URL prefix:

```bash
node tests/browser_check.mjs https://balaji4aws.github.io/sripad-streams-catalog/search.html
```

Confirm the scan date shown on the live page is the new one. If it still shows the old date, the
browser is serving a cached copy — hard-reload before concluding anything is wrong.

---

## Notes for whoever (or whatever) does this next

**Never guess.** Every rule in this project prefers "unknown" over a plausible-looking invention.
Dates are only reported to the precision the title actually gives (a month with no day stays a
month). Languages are read from the title or left unstated. Series come from keyword rules, and an
unmatched title goes to a catch-all rather than the nearest guess. If you find yourself adding a
heuristic that fills a gap by inference, that is a change in the project's character, not a bug fix
— say so out loud rather than sliding it in.

**Titles are the only signal.** Every description on the channel is empty (checked, not assumed).
If that ever changes, descriptions become a much better source for both grouping and dates, and a
good chunk of the parsing cleverness in `categorize.py` could retire.

**Output must stay a pure function of the input.** Re-running steps 2 to 5 on the same
`raw_playlist.json` must produce byte-identical files — that is what CI's freshness check verifies.
So no wall-clock timestamps, no random ordering, no set iteration leaking into output. The scan date
comes from the fetch timestamp recorded *inside* the playlist, not from `datetime.now()`.

**Regressions get a named test.** Four dates in this catalogue were once wrong. Each has a test in
`RegressionTests` in `tests/test_categorize.py` that names the bug and asserts the right answer. If
a new parsing bug turns up, add the case there before fixing it.

**Where things live.** `src/categorize.py` holds the series rules (`RULES`) and all date parsing.
`src/build_sequences.py` holds the language split and watch order. `search.js` holds the matching
rules; `search.html` holds only rendering. `DESIGN.md` explains why each of them works the way it
does — read the relevant section before changing behaviour, because most of the odd-looking rules
exist to handle a specific real title.

**Known-good numbers**, as of the 2026-09-10 scan of both tabs. The same counts are
asserted by `BASELINE` at the top of `tests/test_pipeline.py` — when the channel gains
videos those tests will fail on purpose, and both places should be updated together — useful as a baseline for "did this change more
than I expected":

| | |
|---|---|
| Videos | 465 (342 from /streams, 123 from /videos) |
| Categories | 40 |
| Sequences | 55 (41 with 2+ videos) |
| Date range | 2015-03-30 to 2026-09-06 |
| Unresolved dates | 0 |
| Month-precision dates | 3 |
| Uncategorized | 1 |
| Videos with an assumed language | 92, labelled "Kannada, assumed" |
| Largest series | Bhagavata Saroddhara, 108 videos, sessions 1-102 |
| Sequences ordered by session number | 5 |
| Sequences carrying a note | 16 |
