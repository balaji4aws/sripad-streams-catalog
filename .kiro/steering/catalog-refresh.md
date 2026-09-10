---
inclusion: always
---

# Working on this catalogue

This repository catalogues one YouTube channel's live streams so they can be watched in order. It
is refreshed roughly every two weeks, and the refresh has a runbook with specific checks that are
easy to skip and expensive to get wrong.

**Read the runbook before refreshing the catalogue or changing how titles are parsed:**

#[[file:REFRESH.md]]

## The rules that matter most

**Never guess.** This project reports only what the source actually says. Dates keep the precision
the title gives — a month with no day stays a month, and a title with no parseable date becomes
`Unknown` rather than an approximation. Languages are read from the title or labelled "Language not
stated". Unmatched titles go to a catch-all category rather than the nearest-looking series. Adding
a heuristic that fills a gap by inference changes what this project is; raise it explicitly rather
than treating it as a bug fix.

**Output must stay a pure function of the input.** Re-running the offline steps on the same
`data/raw_playlist.json` must produce byte-identical files in `output/`. CI verifies this. No
wall-clock timestamps, no unordered iteration reaching the output. The scan date is read from the
fetch timestamp recorded inside the playlist, never from the current time.

**Regressions get a named test first.** Four dates in this catalogue were once wrong; each has a
test in `RegressionTests` in `tests/test_categorize.py` naming the bug. Add the failing case before
fixing a new one.

**Titles are the only signal.** Every video description on this channel is empty — verified, not
assumed — so all grouping and dating works from title text. That is why the parsing rules look
fussy: each one handles a specific real title.

**Verify before claiming.** `make check` covers lint, types, both test suites and catalogue
freshness. `make test-browser` drives real Chrome and measures WCAG contrast from computed styles.
Run them rather than reasoning about whether a change was safe.

## Where things live

| | |
|---|---|
| Series rules (`RULES`) and all date parsing | `src/categorize.py` |
| Language split and watch order | `src/build_sequences.py` |
| Search matching rules | `search.js` |
| Page rendering only | `search.html` |
| Why any of it works this way | `DESIGN.md` |

`DESIGN.md` is the reasoning, not decoration. Read the relevant section before changing behaviour.
