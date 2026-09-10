"""End-to-end tests over the committed catalog data.

These run the real steps against the real `data/raw_playlist.json`, writing into
a temporary directory so the committed output files are untouched. They check
the properties that matter to a reader of the catalog: every video is present,
nothing is dated by guesswork, watch order is intact, and the dates that were
once wrong are still right.
"""

import contextlib
import csv
import io
import json
import tempfile
import unittest
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import build_sequences
import catalog_paths
import categorize
from tests import REPO_ROOT

RAW_PLAYLIST = catalog_paths.RAW_PLAYLIST


@unittest.skipUnless(RAW_PLAYLIST.exists(), f"{RAW_PLAYLIST} not present")
class PipelineTests(unittest.TestCase):
    """Run categorize.py then build_sequences.py into a temp directory."""

    # Declared here rather than only assigned in setUpClass, so the shared
    # state this class builds once is visible to a reader and to a type checker.
    _tmp: ClassVar[tempfile.TemporaryDirectory[str]]
    outdir: ClassVar[Path]
    rows: ClassVar[list[dict[str, Any]]]
    groups: ClassVar[list[dict[str, Any]]]
    meta: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        outdir = Path(cls._tmp.name)

        # The scripts report progress on stdout; swallow it so the test output
        # stays readable.
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = categorize.main([
                "--in", str(RAW_PLAYLIST),
                "--outdir", str(outdir),
                "--known-dates", str(catalog_paths.KNOWN_UPLOAD_DATES),
            ])
            assert exit_code == 0, "categorize.py failed"

            sequences_path = outdir / "sequences.json"
            exit_code = build_sequences.main([
                "--in", str(outdir / "streams_master.json"),
                "--out", str(sequences_path),
                "--meta", str(outdir / "catalog_meta.json"),
            ])
            assert exit_code == 0, "build_sequences.py failed"

        cls.outdir = outdir
        cls.rows = json.loads((outdir / "streams_master.json").read_text(encoding="utf-8"))
        sequences = json.loads(sequences_path.read_text(encoding="utf-8"))
        cls.groups = sequences["groups"]
        cls.meta = sequences["meta"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def row_for(self, video_id: str) -> dict[str, Any]:
        return next(row for row in self.rows if row["video_id"] == video_id)

    def date_for_title(self, fragment: str) -> str:
        matches = [row for row in self.rows if fragment in row["title"]]
        self.assertEqual(len(matches), 1, f"expected exactly one title containing {fragment!r}")
        return str(matches[0]["date"])

    # --- the catalog as a whole ---------------------------------------------

    def test_every_raw_entry_becomes_exactly_one_row(self):
        raw = json.loads(RAW_PLAYLIST.read_text(encoding="utf-8"))
        self.assertEqual(len(self.rows), len(raw["entries"]))

    def test_list_positions_are_a_complete_sequence(self):
        self.assertEqual([row["list_position"] for row in self.rows], list(range(1, len(self.rows) + 1)))

    def test_video_ids_are_unique(self):
        ids = [row["video_id"] for row in self.rows]
        self.assertEqual(len(set(ids)), len(ids))

    def test_every_row_has_a_usable_date(self):
        unresolved = [row["title"] for row in self.rows if row["date"] == categorize.UNKNOWN_DATE]
        self.assertEqual(unresolved, [], "some videos have no date; re-run fill_unknown_dates.py")

    def test_dates_are_either_month_or_day_precision(self):
        for row in self.rows:
            with self.subTest(title=row["title"]):
                self.assertRegex(row["date"], r"^\d{4}-\d{2}(-\d{2})?$")

    def test_no_date_is_in_the_future_relative_to_the_newest_video(self):
        """The newest video is first, so nothing below it may be dated later."""
        newest = self.rows[0]["date"][:7]
        for row in self.rows:
            with self.subTest(title=row["title"]):
                self.assertLessEqual(row["date"][:7], newest)

    def test_at_most_one_video_is_uncategorized(self):
        """A rule change that starts dumping videos into the catch-all is a regression."""
        uncategorized = [row["title"] for row in self.rows if row["category"] == categorize.UNCATEGORIZED]
        self.assertLessEqual(len(uncategorized), 1, f"unexpectedly uncategorized: {uncategorized}")

    # --- the dates that were once wrong ------------------------------------

    def test_marathi_is_not_parsed_as_march(self):
        self.assertEqual(self.date_for_title("NKHK Dhyana Day1 Marathi 16th May 2021"), "2021-05-16")

    def test_day_label_is_not_parsed_as_the_calendar_day(self):
        self.assertEqual(self.date_for_title("Sri Gopaladasara Charitre Day 2 Feb 3rd."), "2021-02-03")

    def test_year_is_not_sliced_into_a_day(self):
        self.assertEqual(self.date_for_title("Sandhyavandana Online Oct 2024"), "2024-10")

    def test_month_only_dates_stay_rare_and_explicit(self):
        month_only = [row["title"] for row in self.rows if len(row["date"]) == len("2024-10")]
        self.assertEqual(len(month_only), 3, f"month-precision dates changed: {month_only}")

    # --- both channel tabs --------------------------------------------------

    def test_both_channel_tabs_are_present(self):
        sources = Counter(row["source"] for row in self.rows)
        self.assertEqual(dict(sources), {"streams": 342, "videos": 123})

    def test_positions_are_numbered_across_the_merged_catalog(self):
        """One continuous numbering over both tabs, not two overlapping ones."""
        self.assertEqual([row["list_position"] for row in self.rows], list(range(1, len(self.rows) + 1)))

    def test_each_tab_keeps_its_own_relative_order_after_merging(self):
        """The merge interleaves the tabs; it must not reshuffle within one."""
        for source in ("streams", "videos"):
            positions = [row["source_position"] for row in self.rows if row["source"] == source]
            with self.subTest(source=source):
                self.assertEqual(positions, sorted(positions),
                                 f"/{source} order was not preserved by the merge")

    def test_a_series_split_across_both_tabs_is_reassembled(self):
        """Pratah Sankalpa Gadya has sessions on both tabs; it must come out whole."""
        sequences = [g for g in self.groups if g["category"] == "Pratah Sankalpa Gadya"]
        self.assertEqual(len(sequences), 1, "the series should form one sequence, not one per tab")
        videos = sequences[0]["videos"]
        self.assertEqual(len(videos), 25)
        sources = {self.row_for(video["video_id"])["source"] for video in videos}
        self.assertEqual(sources, {"streams", "videos"}, "expected videos from both tabs")

    def test_numbered_series_run_in_session_order(self):
        """Where every title states a session number, that number sets the order."""
        for group in self.groups:
            numbers = [build_sequences.session_number(video["title"]) for video in group["videos"]]
            if len(numbers) > 1 and all(number is not None for number in numbers):
                with self.subTest(label=group["label"]):
                    self.assertEqual(numbers, sorted(numbers))

    def test_the_longest_series_is_complete_and_in_order(self):
        """Bhagavata Saroddhara: 108 videos, days 1 to 102, no gaps."""
        sequences = [g for g in self.groups if g["category"] == "Bhagavata Saroddhara"]
        self.assertEqual(len(sequences), 1)
        videos = sequences[0]["videos"]
        self.assertEqual(len(videos), 108)

        parsed = [build_sequences.session_number(video["title"]) for video in videos]
        self.assertNotIn(None, parsed, "every session in this series states its number")
        numbers = [number for number in parsed if number is not None]

        self.assertEqual(numbers, sorted(numbers), "sessions are not in order")
        self.assertEqual(sorted(set(numbers)), list(range(1, 103)), "a session number is missing")

    # --- output files -------------------------------------------------------

    def test_master_csv_matches_master_json(self):
        with (self.outdir / "streams_master.csv").open(encoding="utf-8") as handle:
            csv_rows = list(csv.DictReader(handle))
        self.assertEqual(len(csv_rows), len(self.rows))
        self.assertEqual([r["video_id"] for r in csv_rows], [r["video_id"] for r in self.rows])

    def test_a_csv_exists_for_every_category(self):
        grouped = json.loads((self.outdir / "streams_by_category.json").read_text(encoding="utf-8"))
        written = {path.name for path in (self.outdir / "by_category").glob("*.csv")}
        self.assertEqual(len(written), len(grouped))

    def test_catalog_markdown_lists_every_category(self):
        grouped = json.loads((self.outdir / "streams_by_category.json").read_text(encoding="utf-8"))
        catalog = (self.outdir / "CATALOG.md").read_text(encoding="utf-8")
        for category in grouped:
            with self.subTest(category=category):
                self.assertIn(f"## {category}", catalog)

    # --- sequences ----------------------------------------------------------

    def test_every_video_appears_in_exactly_one_sequence(self):
        seen = [video["video_id"] for group in self.groups for video in group["videos"]]
        self.assertEqual(len(seen), len(self.rows))
        self.assertEqual(set(seen), {row["video_id"] for row in self.rows})

    def test_sequence_numbering_is_contiguous_and_total_is_correct(self):
        for group in self.groups:
            with self.subTest(label=group["label"]):
                self.assertEqual([video["seq"] for video in group["videos"]],
                                 list(range(1, group["count"] + 1)))
                self.assertTrue(all(video["total"] == group["count"] for video in group["videos"]))

    def test_sequence_labels_are_unique(self):
        """Two sequences with the same label would be indistinguishable on the page."""
        labels = [group["label"] for group in self.groups]
        duplicates = {label for label in labels if labels.count(label) > 1}
        self.assertEqual(duplicates, set())

    def test_no_label_states_a_language_twice(self):
        for group in self.groups:
            lowered = group["label"].lower()
            for language in build_sequences.LANGUAGES:
                with self.subTest(label=group["label"], language=language):
                    self.assertLessEqual(lowered.count(language), 1)

    def test_a_search_for_a_language_only_returns_that_language(self):
        """The whole point of the language split: "kannada" must not return English tracks."""
        kannada = [group for group in self.groups if "kannada" in group["search_words"]]
        self.assertTrue(kannada)
        for group in kannada:
            with self.subTest(label=group["label"]):
                self.assertNotIn("(English)", group["label"])

    def test_an_unknown_language_sequence_is_labelled_where_it_could_be_mistaken(self):
        """Beside a language-specific sibling, an unlabelled sequence must say why."""
        by_category: dict[str, list[dict[str, Any]]] = {}
        for group in self.groups:
            by_category.setdefault(group["category"], []).append(group)

        for category, siblings in by_category.items():
            has_known = any(group["language"] for group in siblings)
            for group in siblings:
                if group["language"] is None and has_known:
                    with self.subTest(category=category):
                        self.assertIn(build_sequences.UNKNOWN_LANGUAGE_LABEL, group["label"])

    # --- catalog metadata ---------------------------------------------------

    def test_metadata_records_when_the_channel_was_scanned(self):
        self.assertRegex(self.meta["scanned_on"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(self.meta["next_scan_due"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertGreater(self.meta["next_scan_due"], self.meta["scanned_on"])

    def test_the_next_scan_is_one_interval_after_the_last(self):
        scanned = date.fromisoformat(self.meta["scanned_on"])
        due = date.fromisoformat(self.meta["next_scan_due"])
        self.assertEqual((due - scanned).days, self.meta["refresh_interval_days"])

    def test_the_scan_date_is_not_before_the_newest_video(self):
        """A scan cannot predate the newest thing it found."""
        self.assertGreaterEqual(self.meta["scanned_on"], self.meta["newest_video_date"])

    def test_metadata_counts_match_the_catalog(self):
        self.assertEqual(self.meta["video_count"], len(self.rows))
        self.assertEqual(self.meta["category_count"], len({row["category"] for row in self.rows}))

    def test_the_scan_date_comes_from_the_input_not_the_clock(self):
        """Output must stay a pure function of the input, or CI's freshness check breaks."""
        epoch = json.loads(RAW_PLAYLIST.read_text(encoding="utf-8"))["epoch"]
        expected = datetime.fromtimestamp(epoch, timezone.utc).date().isoformat()
        self.assertEqual(self.meta["scanned_on"], expected)


@unittest.skipUnless(RAW_PLAYLIST.exists(), f"{RAW_PLAYLIST} not present")
class CommittedOutputTests(unittest.TestCase):
    """The committed output files must match what the current code produces."""

    def test_committed_sequences_cover_the_committed_master_table(self):
        master = json.loads((REPO_ROOT / "output" / "streams_master.json").read_text(encoding="utf-8"))
        sequences = json.loads((REPO_ROOT / "output" / "sequences.json").read_text(encoding="utf-8"))
        in_sequences = {video["video_id"] for group in sequences["groups"] for video in group["videos"]}
        self.assertEqual(in_sequences, {row["video_id"] for row in master})

    def test_search_page_loads_the_committed_sequences_file(self):
        """A renamed output file would silently leave the page empty."""
        page = (REPO_ROOT / "search.html").read_text(encoding="utf-8")
        self.assertIn("output/sequences.json", page)
        self.assertTrue((REPO_ROOT / "output" / "sequences.json").exists())


if __name__ == "__main__":
    unittest.main()
