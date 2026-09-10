"""Tests for categorize.py - series matching and title date parsing.

The date-parsing tests are built from the channel's real titles, including the
awkward ones. Every case in RegressionTests corresponds to a date that this
catalog once got wrong; those are the tests worth keeping if any others are
ever thrown away.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import categorize
from categorize import (
    UNCATEGORIZED,
    UNKNOWN_DATE,
    TitleDate,
    _carry_years_backward,
    _format_date,
    load_known_upload_dates,
    parse_title_date,
    resolve_dates,
)
from categorize import (
    categorize as categorize_title,
)


class RegressionTests(unittest.TestCase):
    """One test per date this catalog previously reported incorrectly."""

    def test_month_abbreviation_inside_a_word_is_not_a_month(self):
        """"Mar" inside "Marathi" once turned 16 May into 1 March.

        The digit came from the "Day1" session label and the month from the
        first three letters of "Marathi".
        """
        self.assertEqual(
            parse_title_date("NKHK Dhyana Day1 Marathi 16th May 2021"),
            TitleDate(16, 5, 2021),
        )

    def test_month_name_at_the_start_still_wins_over_a_trailing_word(self):
        """"Devapooja March 20th Marathi" must read the real "March", not "Mar" in "Marathi"."""
        self.assertEqual(parse_title_date("Devapooja March 20th Marathi"), TitleDate(20, 3, None))

    def test_session_number_is_not_read_as_a_calendar_day(self):
        """"Day 2 Feb 3rd" once resolved to 2 February instead of the 3rd."""
        self.assertEqual(
            parse_title_date("Sri Gopaladasara Charitre Day 2 Feb 3rd."),
            TitleDate(3, 2, None),
        )

    def test_four_digit_year_is_not_sliced_into_a_day(self):
        """"Oct 2024" once became day 20 of year 24 by splitting "2024"."""
        self.assertEqual(parse_title_date("Sandhyavandana Online Oct 2024"), TitleDate(None, 10, 2024))

    def test_impossible_day_falls_back_to_month_precision(self):
        """A day that cannot exist in its month must not be emitted as a date."""
        self.assertEqual(_format_date(TitleDate(29, 2, 2025)), "2025-02")
        self.assertEqual(_format_date(TitleDate(29, 2, 2024)), "2024-02-29")

    def test_a_letter_typed_into_a_day_is_not_silently_repaired(self):
        """"3oth Nov" uses a letter o. The month is known, the day is not."""
        self.assertEqual(
            parse_title_date("Day 63- Bhagavata Saroddhara -3oth Nov 2024 -"),
            TitleDate(None, 11, 2024),
        )


class SlashSeparatedDateTests(unittest.TestCase):
    """The /videos tab writes dates as DD/Mon/YYYY throughout."""

    def test_slash_separated_date(self):
        self.assertEqual(
            parse_title_date("Day 102 Bhagavata Saroddhara -25/Jul/2026 - 227-229"),
            TitleDate(25, 7, 2026),
        )

    def test_leading_zero_day(self):
        self.assertEqual(
            parse_title_date("Day 99 Bhagavata Saroddhara -04/Jul/2026 - 221"),
            TitleDate(4, 7, 2026),
        )

    def test_a_three_digit_session_number_is_never_read_as_a_day(self):
        """"Day 102" must not contribute a day; only the real date should."""
        self.assertEqual(
            parse_title_date("Day 102 Bhagavata Saroddhara -25/Jul/2026"),
            TitleDate(25, 7, 2026),
        )

    def test_slash_form_still_rejects_a_month_glued_to_a_word(self):
        self.assertEqual(
            parse_title_date("Day 5 Something Marathi -12/Aug/2025"),
            TitleDate(12, 8, 2025),
        )


class SessionLabelTests(unittest.TestCase):
    """The "Day N" rule must not overreach: sometimes that number IS the date."""

    def test_ordinal_after_a_day_label_is_a_date(self):
        self.assertEqual(
            parse_title_date("Satyatma Sandhya Kannada Final Day 24th June 2023"),
            TitleDate(24, 6, 2023),
        )

    def test_saturday_is_not_a_day_label(self):
        """"day" at the end of "Saturday" must not suppress the date after it."""
        self.assertEqual(
            parse_title_date("SatyatmaSandhya kannada Saturday 17th Sept 2022"),
            TitleDate(17, 9, 2022),
        )
        self.assertEqual(parse_title_date("Marathi saturday 10th April"), TitleDate(10, 4, None))

    def test_session_number_before_a_real_date_is_skipped_not_fatal(self):
        """Rejecting a candidate must continue the scan, not abandon the title."""
        self.assertEqual(
            parse_title_date("Manimanjari Kannada Day 14 6th May 2026"),
            TitleDate(6, 5, 2026),
        )
        self.assertEqual(parse_title_date("Manimanjari Day12 1st May 2026"), TitleDate(1, 5, 2026))

    def test_trailing_session_number_does_not_displace_the_date(self):
        self.assertEqual(
            parse_title_date("Sumadhwavijaya Marathi 19th June Day 57"),
            TitleDate(19, 6, None),
        )


class TitleDateFormatTests(unittest.TestCase):
    """The channel writes dates several different ways; all of them must parse."""

    def test_day_month_year_with_spaces(self):
        self.assertEqual(parse_title_date("Sumadhwavijaya Marathi 4th June 2026"), TitleDate(4, 6, 2026))

    def test_month_and_year_run_together(self):
        self.assertEqual(parse_title_date("Sumadhwavijaya Marathi - 3rd Sep2026"), TitleDate(3, 9, 2026))

    def test_two_digit_year_expands_to_four(self):
        self.assertEqual(parse_title_date("Sumadhwavijay-Marathi-Day4-15thJan26"), TitleDate(15, 1, 2026))
        self.assertEqual(parse_title_date("Sumadhawavijaya Marathi Day1-11th Jan26"), TitleDate(11, 1, 2026))

    def test_no_ordinal_suffix(self):
        self.assertEqual(parse_title_date("Sumadhwavijaya Marathi 14July 2026"), TitleDate(14, 7, 2026))

    def test_month_before_day(self):
        self.assertEqual(parse_title_date("Oct 2nd 2023 Satsanga"), TitleDate(2, 10, 2023))

    def test_longer_month_name_wins_over_its_own_abbreviation(self):
        """"june" must be preferred over "jun", so the year is not misread."""
        self.assertEqual(parse_title_date("Satsanga 13th June 2024"), TitleDate(13, 6, 2024))

    def test_month_and_year_with_no_day(self):
        self.assertEqual(parse_title_date("NKHK Marathi May 2021"), TitleDate(None, 5, 2021))

    def test_year_before_month_is_not_guessed(self):
        """Nothing in this channel writes dates this way, so it must not invent one."""
        self.assertEqual(parse_title_date("Some Title 2026 July"), TitleDate(None, None, None))

    def test_title_with_no_date_at_all(self):
        result = parse_title_date("-Artha-Marathi-Shloka2-SriJayateerthastuti")
        self.assertTrue(result.is_empty)


class CarryYearsBackwardTests(unittest.TestCase):
    """The listing is newest-first, so walking it walks backward through time."""

    def test_year_is_carried_to_later_entries_that_omit_it(self):
        filled = _carry_years_backward([
            TitleDate(6, 9, 2026),
            TitleDate(3, 9, None),
            TitleDate(28, 8, None),
        ])
        self.assertEqual([entry.year for entry in filled], [2026, 2026, 2026])

    def test_month_jumping_forward_steps_the_year_back(self):
        """A January below a run of December/November titles is the PRECEDING January."""
        filled = _carry_years_backward([
            TitleDate(5, 1, 2026),
            TitleDate(20, 12, None),
            TitleDate(21, 11, None),
        ])
        self.assertEqual([(entry.year, entry.month) for entry in filled],
                         [(2026, 1), (2025, 12), (2025, 11)])

    def test_repeated_month_does_not_step_the_year_back(self):
        filled = _carry_years_backward([
            TitleDate(20, 6, 2026),
            TitleDate(19, 6, None),
            TitleDate(18, 6, None),
        ])
        self.assertEqual([entry.year for entry in filled], [2026, 2026, 2026])

    def test_a_single_month_of_forward_jitter_is_tolerated(self):
        """One month forward is title-typo noise, not a year boundary."""
        filled = _carry_years_backward([TitleDate(2, 6, 2026), TitleDate(25, 7, None)])
        self.assertEqual(filled[1].year, 2026)

    def test_entries_before_any_known_year_are_left_alone(self):
        filled = _carry_years_backward([TitleDate(3, 5, None)])
        self.assertIsNone(filled[0].year)


class ResolveDatesTests(unittest.TestCase):
    def test_title_date_is_preferred_over_the_fetched_upload_date(self):
        """A real upload date can be a day off, so the title wins where it exists."""
        entries = [{"id": "abc", "title": "Satsanga 13th June 2024"}]
        resolved = resolve_dates(entries, {"abc": "2024-06-14"})
        self.assertEqual(resolved, ["2024-06-13"])

    def test_fetched_upload_date_fills_a_title_with_no_date(self):
        entries = [{"id": "abc", "title": "Artha-Marathi-Shloka2"}]
        self.assertEqual(resolve_dates(entries, {"abc": "2025-07-20"}), ["2025-07-20"])

    def test_no_title_date_and_no_fallback_stays_unknown(self):
        entries = [{"id": "abc", "title": "Artha-Marathi-Shloka2"}]
        self.assertEqual(resolve_dates(entries, {}), [UNKNOWN_DATE])

    def test_month_only_title_is_reported_to_the_month(self):
        entries = [{"id": "abc", "title": "Sandhyavandana Online Oct 2024"}]
        self.assertEqual(resolve_dates(entries, {}), ["2024-10"])

    def test_missing_title_key_is_tolerated(self):
        self.assertEqual(resolve_dates([{"id": "abc"}], {}), [UNKNOWN_DATE])


class CategorizeTests(unittest.TestCase):
    def test_misspellings_land_in_the_same_series(self):
        """These four titles are all the same series, spelled four ways."""
        for title in (
            "Sumadhwavijaya Marathi - 3rd Sep2026",
            "Sumadhwavijay-Marathi-Day4-15thJan26",
            "Sumadhawavijaya Marathi Day1-11th Jan26",
            "SuMadhwavijaya Day7-21st Jan 2026",
        ):
            with self.subTest(title=title):
                self.assertEqual(categorize_title(title), "Sumadhwavijaya (Marathi)")

    def test_a_run_together_series_name_still_matches(self):
        """"VighneshSandhi" fell through to the generic NKHK bucket, splitting
        one short series across two categories - day 3 in one, day 4 in another."""
        for title in ("NKHK Vighnesh Sandhi Day 3 14 June", "NKHK VighneshSandhi Day4 15 June"):
            with self.subTest(title=title):
                self.assertEqual(categorize_title(title), "Vighnesha Sandhi (NKHK)")

    def test_specific_rule_beats_the_general_one(self):
        """"Sandhya Shala" must not be swallowed by the broader "Sandhyavandana"."""
        self.assertEqual(
            categorize_title("Sandhya Shala Class3(slot2) 6th Sep2026"),
            "Sandhya Shala (Onboarding/Classes)",
        )
        self.assertEqual(categorize_title("Sandhyavandana something else"), "Sandhyavandana (Other)")

    def test_krishna_needs_a_recitation_word(self):
        """"Krishna" alone appears in unrelated titles, so it needs corroboration."""
        self.assertEqual(
            categorize_title("SriKrishnashtaka Stotra by Sri VadirajaTeertha - 3rd Sept"),
            "SriKrishna Stotra/Stuti",
        )
        self.assertNotEqual(categorize_title("NKHK Krishna satsanga"), "SriKrishna Stotra/Stuti")

    def test_combined_session_gets_its_own_series(self):
        self.assertEqual(
            categorize_title("NKHK Anusandhana+Dhyana 19th Dec"),
            "Anusandhana + Dhyana (NKHK)",
        )

    def test_jayateertha_stuti_is_distinct_from_teekacharya_charitra(self):
        self.assertEqual(categorize_title("Jayateertha Stuti Day2 16thJuly"), "SriJayateertha Stuti")
        self.assertEqual(
            categorize_title("Teekacharya's charitra in Marathi -Day2- 13th July 2025"),
            "SriJayateertha (Teekacharya) Charitra",
        )

    def test_unmatched_title_is_not_forced_into_a_series(self):
        self.assertEqual(categorize_title("something entirely unrelated"), UNCATEGORIZED)

    def test_categorization_is_case_insensitive(self):
        self.assertEqual(categorize_title("MANIMANJARI KANNADA"), "Manimanjari (Kannada)")


class LoadKnownUploadDatesTests(unittest.TestCase):
    """A broken lookup file must degrade to "no fallback available", not crash."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_known_upload_dates(self.tmp_path / "absent.json"), {})

    def test_valid_file_is_loaded(self):
        path = self.tmp_path / "dates.json"
        path.write_text(json.dumps({"abc": "2024-01-02"}), encoding="utf-8")
        self.assertEqual(load_known_upload_dates(path), {"abc": "2024-01-02"})

    def test_malformed_json_returns_empty_and_warns(self):
        path = self.tmp_path / "dates.json"
        path.write_text("{not json", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(load_known_upload_dates(path), {})
        self.assertIn("warning", stderr.getvalue())

    def test_wrong_json_shape_returns_empty_and_warns(self):
        path = self.tmp_path / "dates.json"
        path.write_text('["not", "an", "object"]', encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(load_known_upload_dates(path), {})
        self.assertIn("warning", stderr.getvalue())


class MonthPatternTests(unittest.TestCase):
    """Guard the regex building blocks that the parsing bugs came from."""

    def test_every_month_variant_maps_to_its_number(self):
        self.assertEqual(categorize.MONTHS["january"], 1)
        self.assertEqual(categorize.MONTHS["sept"], 9)
        self.assertEqual(categorize.MONTHS["dec"], 12)
        # No variant may be listed twice, or one spelling would shadow another.
        expected = sum(len(variants) for variants in categorize._MONTH_VARIANTS.values())
        self.assertEqual(len(categorize.MONTHS), expected)
        self.assertEqual(sorted(set(categorize._MONTH_VARIANTS)), list(range(1, 13)))

    def test_longer_variants_are_tried_first(self):
        """"june" must precede "jun" in the alternation, or it can never match."""
        alternatives = categorize.MONTH_RE.split("|")
        self.assertLess(alternatives.index("june"), alternatives.index("jun"))
        self.assertLess(alternatives.index("september"), alternatives.index("sep"))

    def test_all_twelve_months_round_trip_through_the_parser(self):
        for number, variants in categorize._MONTH_VARIANTS.items():
            for variant in variants:
                with self.subTest(month=variant):
                    self.assertEqual(
                        parse_title_date(f"Satsanga 5th {variant} 2024"),
                        TitleDate(5, number, 2024),
                    )


if __name__ == "__main__":
    unittest.main()
