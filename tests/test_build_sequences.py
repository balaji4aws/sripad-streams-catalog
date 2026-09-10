"""Tests for build_sequences.py - splitting series by language and ordering them.

The point of this step is that a series taught more than once, in different
languages, is several independently numbered tracks rather than one list. These
tests pin down that split, the watch order inside each track, and the label
that avoids saying the language twice.
"""

import unittest
from typing import Any

from build_sequences import (
    ASSUMED_LANGUAGE,
    LANGUAGE_SPELLINGS,
    build_groups,
    category_names_language,
    detect_language,
    language_notes,
    normalize_words,
    order_videos,
    resolve_language,
    sequence_label,
    sequence_notes,
    session_number,
    session_part,
)


def row(position: int, category: str, title: str, date: str = "2024-01-01") -> dict[str, Any]:
    """A minimal master-table row, so each test only states what it cares about."""
    return {
        "list_position": position,
        "category": category,
        "title": title,
        "date": date,
        "video_id": f"vid{position}",
        "url": f"https://www.youtube.com/watch?v=vid{position}",
        "duration_min": 60.0,
        "view_count": 10,
    }


class DetectLanguageTests(unittest.TestCase):
    def test_language_named_in_the_title(self):
        self.assertEqual(detect_language("Manimanjari Kannada Day 14"), "kannada")

    def test_language_run_onto_an_adjacent_word(self):
        """Word-by-word matching would miss this, which is why substrings are used."""
        self.assertEqual(detect_language("Sandhyavandanakannada day2"), "kannada")

    def test_case_is_ignored(self):
        self.assertEqual(detect_language("NKHK MARATHI satsanga"), "marathi")

    def test_no_language_is_not_guessed(self):
        self.assertIsNone(detect_language("Pratah Sankalpa Gadya Day 3"))

    def test_real_misspellings_are_recognised(self):
        """Both of these occur on the channel and split a video from its series."""
        self.assertEqual(detect_language("NKHK marati Tulasi 22nd May"), "marathi")
        self.assertEqual(detect_language("Sumadhwavijaya Marath 7July 2026"), "marathi")

    def test_a_misspelling_maps_to_the_canonical_name(self):
        """The label must read "(Marathi)", never "(Marati)"."""
        language = detect_language("NKHK marati Tulasi")
        assert language is not None
        self.assertEqual(sequence_label("Tulasi Stotra", language), "Tulasi Stotra (Marathi)")

    def test_the_full_spelling_wins_over_its_own_truncation(self):
        """"marath" is a prefix of "marathi", so order of matching matters."""
        self.assertEqual(detect_language("NKHK Marathi Tulasi Stotra"), "marathi")

    def test_every_spelling_maps_to_a_known_language(self):
        for language, spellings in LANGUAGE_SPELLINGS.items():
            for spelling in spellings:
                with self.subTest(spelling=spelling):
                    self.assertEqual(detect_language(f"Something {spelling} here"), language)


class CategoryNamesLanguageTests(unittest.TestCase):
    def test_language_in_the_category_name_is_detected(self):
        self.assertEqual(category_names_language("Manimanjari (Kannada)"), "kannada")

    def test_language_mentioned_without_brackets_does_not_count(self):
        """Only a bracketed language means the category is single-language."""
        self.assertIsNone(category_names_language("Sumadhwavijaya Marathi series"))

    def test_category_with_no_language(self):
        self.assertIsNone(category_names_language("Pratah Sankalpa Gadya"))


class SequenceLabelTests(unittest.TestCase):
    def test_language_is_appended_when_the_category_omits_it(self):
        self.assertEqual(sequence_label("Satyatma Sandhya", "kannada"), "Satyatma Sandhya (Kannada)")

    def test_language_is_not_repeated(self):
        self.assertEqual(sequence_label("Manimanjari (Kannada)", "kannada"), "Manimanjari (Kannada)")

    def test_an_assumed_language_says_so(self):
        """A reader must be able to tell a guess from something the channel said."""
        self.assertEqual(
            sequence_label("Pratah Sankalpa Gadya", "kannada", assumed=True),
            "Pratah Sankalpa Gadya (Kannada, assumed)",
        )

    def test_a_stated_language_is_not_marked_as_assumed(self):
        self.assertEqual(
            sequence_label("Satyatma Sandhya", "kannada"),
            "Satyatma Sandhya (Kannada)",
        )

    def test_an_assumed_language_is_not_repeated_when_the_category_states_it(self):
        self.assertEqual(
            sequence_label("Manimanjari (Kannada)", "kannada", assumed=True),
            "Manimanjari (Kannada)",
        )


class BuildGroupsTests(unittest.TestCase):
    def test_one_category_taught_in_three_languages_becomes_three_sequences(self):
        rows = [
            row(1, "Satyatma Sandhya", "Satyatma Sandhya English Day2"),
            row(2, "Satyatma Sandhya", "Satyatma Sandhya English Day1"),
            row(3, "Satyatma Sandhya", "Satyatma Sandhya Kannada Day2"),
            row(4, "Satyatma Sandhya", "Satyatma Sandhya Kannada Day1"),
            row(5, "Satyatma Sandhya", "Satyatma Sandhya Marathi Day1"),
        ]
        groups = build_groups(rows)
        self.assertEqual(
            sorted(group["label"] for group in groups),
            ["Satyatma Sandhya (English)", "Satyatma Sandhya (Kannada)", "Satyatma Sandhya (Marathi)"],
        )
        self.assertEqual(sorted(group["count"] for group in groups), [1, 2, 2])

    def test_single_language_category_is_not_split_by_its_own_titles(self):
        """A category naming its language must stay one sequence, not two identical labels."""
        rows = [
            row(1, "Manimanjari (Kannada)", "Manimanjari Kannada Day2"),
            row(2, "Manimanjari (Kannada)", "Manimanjari Day1"),
        ]
        groups = build_groups(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["label"], "Manimanjari (Kannada)")
        self.assertEqual(groups[0]["count"], 2)

    def test_videos_are_ordered_oldest_first(self):
        """list_position 1 is the newest video, so the sequence must run downward."""
        rows = [
            row(10, "Series", "Series Day1 first recorded"),
            row(2, "Series", "Series Day3 last recorded"),
            row(6, "Series", "Series Day2 middle"),
        ]
        videos = build_groups(rows)[0]["videos"]
        self.assertEqual([video["title"] for video in videos],
                         ["Series Day1 first recorded", "Series Day2 middle", "Series Day3 last recorded"])
        self.assertEqual([video["seq"] for video in videos], [1, 2, 3])
        self.assertTrue(all(video["total"] == 3 for video in videos))

    def test_a_partly_assumed_language_stays_one_sequence(self):
        """Splitting on it produced "Series (Kannada)" beside "Series (Kannada,
        assumed)", making one series look like two."""
        rows = [
            row(1, "Series", "Series Kannada Day1"),
            row(2, "Series", "Series Day2"),
        ]
        groups = build_groups(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["label"], "Series (Kannada)")
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(groups[0]["assumed_count"], 1)
        self.assertFalse(groups[0]["language_assumed"], "one video states it, so not wholly assumed")

    def test_a_partly_assumed_sequence_discloses_it_in_a_note(self):
        """The label reads plainly, so without a note the guess would be hidden."""
        rows = [
            row(1, "Series", "Series Kannada Day1"),
            row(2, "Series", "Series Day2"),
        ]
        notes = build_groups(rows)[0]["notes"]
        self.assertEqual(
            notes,
            ["1 of these 2 videos does not name a language; Kannada is assumed for it."],
        )

    def test_a_wholly_assumed_sequence_needs_no_note(self):
        """The label already says "assumed"; a note would just repeat it."""
        rows = [row(1, "Series", "Series Day1"), row(2, "Series", "Series Day2")]
        group = build_groups(rows)[0]
        self.assertEqual(group["label"], "Series (Kannada, assumed)")
        self.assertTrue(group["language_assumed"])
        self.assertEqual(group["notes"], [])

    def test_a_category_naming_no_language_anywhere_is_assumed_kannada(self):
        rows = [row(1, "Series", "Series Day1"), row(2, "Series", "Series Day2")]
        groups = build_groups(rows)
        self.assertEqual([group["label"] for group in groups], ["Series (Kannada, assumed)"])
        self.assertTrue(groups[0]["language_assumed"])

    def test_larger_sequences_come_first(self):
        rows = [
            row(1, "Small", "Small Day1"),
            row(2, "Big", "Big Day1"),
            row(3, "Big", "Big Day2"),
        ]
        self.assertEqual([group["category"] for group in build_groups(rows)], ["Big", "Small"])

    def test_ordering_is_stable_for_equal_counts(self):
        """Equal-sized sequences sort by label, so the output file does not churn."""
        rows = [row(1, "Zebra", "Zebra Day1"), row(2, "Alpha", "Alpha Day1")]
        self.assertEqual([group["category"] for group in build_groups(rows)], ["Alpha", "Zebra"])

    def test_search_words_cover_the_category_language_and_titles(self):
        rows = [row(1, "Satyatma Sandhya", "Satyatma Sandhya Kannada Day1 - 5th May 2024")]
        words = build_groups(rows)[0]["search_words"]
        for expected in ("satyatma", "sandhya", "kannada", "2024"):
            with self.subTest(word=expected):
                self.assertIn(expected, words)

    def test_search_words_are_sorted_and_deduplicated(self):
        rows = [
            row(1, "Series", "Series Kannada Day1"),
            row(2, "Series", "Series Kannada Day2"),
        ]
        words = build_groups(rows)[0]["search_words"]
        self.assertEqual(words, sorted(set(words)))

    def test_empty_input_produces_no_groups(self):
        self.assertEqual(build_groups([]), [])


class SessionNumberTests(unittest.TestCase):
    """"Day N" is a session number; a date that follows the word "Day" is not."""

    def test_plain_session_labels(self):
        self.assertEqual(session_number("Day 102 Bhagavata Saroddhara -25/Jul/2026"), 102)
        self.assertEqual(session_number("Day1- Bhagavata Saroddhara - 8th April 2023"), 1)
        self.assertEqual(session_number("Sumadhwavijay-Marathi-Day4-15thJan26"), 4)
        self.assertEqual(session_number("Sumadhwavijaya Marathi 19th June Day 57"), 57)

    def test_an_ordinal_after_day_is_a_date_not_a_session(self):
        """The regression this guards: backtracking used to yield session 2 here."""
        self.assertIsNone(session_number("Satyatma Sandhya Kannada Final Day 24th June 2023"))

    def test_day_at_the_end_of_another_word_is_not_a_label(self):
        self.assertIsNone(session_number("SatyatmaSandhya kannada Saturday 17th Sept 2022"))
        self.assertIsNone(session_number("Marathi saturday 10th April"))

    def test_no_session_label_at_all(self):
        self.assertIsNone(session_number("Sumadhwavijaya Marathi 16th March 2026"))


class OrderVideosTests(unittest.TestCase):
    def test_session_numbers_win_when_every_title_has_one(self):
        """Even when the channel listed them in a contradicting order."""
        items = [
            row(10, "S", "Day 3 S"),   # listed as the OLDEST
            row(20, "S", "Day 1 S"),
            row(30, "S", "Day 2 S"),   # listed as the NEWEST
        ]
        self.assertEqual([i["title"] for i in order_videos(items)], ["Day 1 S", "Day 2 S", "Day 3 S"])

    def test_channel_position_is_used_when_a_title_lacks_a_session_number(self):
        """Mixing numbered and unnumbered videos would compare incomparable keys."""
        items = [
            row(10, "S", "Day 3 S"),
            row(20, "S", "S with no number"),
            row(30, "S", "Day 1 S"),
        ]
        # Oldest first = highest list_position first.
        self.assertEqual([i["list_position"] for i in order_videos(items)], [30, 20, 10])

    def test_repeated_session_numbers_fall_back_to_channel_position(self):
        items = [row(10, "S", "Day 2 S second"), row(20, "S", "Day 2 S first"), row(30, "S", "Day 1 S")]
        self.assertEqual([i["title"] for i in order_videos(items)],
                         ["Day 1 S", "Day 2 S first", "Day 2 S second"])

    def test_a_split_session_runs_in_part_order(self):
        """One sitting uploaded as several videos: "Day 32(1)" .. "Day 32(5)"."""
        # Deliberately shuffled, and with channel positions that disagree.
        items = [
            row(10, "S", "Day 32(3) S"),
            row(40, "S", "Day 32(1) S"),
            row(20, "S", "Day 32(5) S"),
            row(50, "S", "Day 32(2) S"),
            row(30, "S", "Day 32(4) S"),
        ]
        self.assertEqual(
            [i["title"] for i in order_videos(items)],
            ["Day 32(1) S", "Day 32(2) S", "Day 32(3) S", "Day 32(4) S", "Day 32(5) S"],
        )

    def test_a_split_session_sorts_inside_its_own_session(self):
        items = [row(10, "S", "Day 33 S"), row(20, "S", "Day 32(2) S"), row(30, "S", "Day 32(1) S")]
        self.assertEqual([i["title"] for i in order_videos(items)],
                         ["Day 32(1) S", "Day 32(2) S", "Day 33 S"])


class ResolveLanguageTests(unittest.TestCase):
    """The ladder from "the source says so" down to "we assumed"."""

    def test_the_category_naming_it_wins(self):
        self.assertEqual(resolve_language("Manimanjari (Kannada)", "Manimanjari Day 5"),
                         ("kannada", False))

    def test_the_title_naming_it_is_not_an_assumption(self):
        self.assertEqual(resolve_language("Satyatma Sandhya", "Satyatma Sandhya English Day1"),
                         ("english", False))

    def test_a_channel_confirmed_series_is_not_an_assumption(self):
        """Told to us for the whole series, so it is not marked assumed."""
        self.assertEqual(resolve_language("Bhagavata Saroddhara", "Day 5 Bhagavata Saroddhara"),
                         ("kannada", False))

    def test_marathi_grammar_without_the_language_name_is_an_assumption(self):
        self.assertEqual(resolve_language("SriRaghavendra Swami",
                                          "SriRaghavendra swamincha Charitra ,mahima"),
                         ("marathi", True))

    def test_nothing_at_all_falls_back_to_assumed_kannada(self):
        self.assertEqual(resolve_language("Pratah Sankalpa Gadya", "Day 6 - Pratah Sankalpa Gadya"),
                         (ASSUMED_LANGUAGE, True))

    def test_a_stated_language_beats_a_marathi_marker(self):
        self.assertEqual(
            resolve_language("SriRaghavendra Swami", "SriRaghavendra Swamincha Charitra Marathi"),
            ("marathi", False),
        )


class SequenceNotesTests(unittest.TestCase):
    def video(self, title: str, date: str = "2024-01-01", minutes: float = 50.0) -> dict[str, Any]:
        return {"title": title, "date": date, "duration_min": minutes}

    def numbered(self, *numbers: int) -> list[dict[str, Any]]:
        return [self.video(f"Day {n} S") for n in numbers]

    def test_a_missing_session_is_explained(self):
        notes = sequence_notes(self.numbered(1, 2, 3, 5, 6))
        self.assertEqual(len(notes), 1)
        self.assertIn("Session 4 is not on the channel", notes[0])

    def test_several_missing_sessions_read_naturally(self):
        notes = sequence_notes(self.numbered(1, 2, 5, 6, 7))
        self.assertIn("Sessions 3, 4 are not on the channel", notes[0])

    def test_a_complete_run_says_nothing(self):
        self.assertEqual(sequence_notes(self.numbered(1, 2, 3, 4, 5)), [])

    def test_the_same_recording_uploaded_twice(self):
        """Same session number, same date, same length: one upload done twice."""
        videos = self.numbered(1, 2, 3, 4)
        videos.append(self.video("Day 4 S  again", date="2024-01-01", minutes=50.0))
        notes = sequence_notes(videos)
        self.assertTrue(any("uploaded more than once" in note for note in notes), notes)

    def test_two_different_recordings_sharing_a_number(self):
        videos = self.numbered(1, 2, 3, 4)
        videos.append(self.video("Day 3 S other", date="2024-03-03", minutes=61.0))
        notes = sequence_notes(videos)
        self.assertTrue(any("may be numbered wrongly" in note for note in notes), notes)
        self.assertTrue(any("2024-01-01, 2024-03-03" in note for note in notes), notes)

    def test_a_session_split_into_parts_is_not_called_a_duplicate(self):
        videos = self.numbered(1, 2, 3)
        videos += [self.video(f"Day 4({p}) S", minutes=9.0) for p in (1, 2, 3)]
        notes = sequence_notes(videos)
        self.assertEqual(notes, ["Session 4 was uploaded in 3 parts, listed here in order."])

    def test_a_barely_numbered_sequence_produces_no_notes(self):
        """With most titles unnumbered, a gap says nothing about missing videos."""
        videos = [self.video("Day 1 S"), self.video("S no number"), self.video("S none either"),
                  self.video("S nor this"), self.video("Day 9 S")]
        self.assertEqual(sequence_notes(videos), [])

    def test_an_unnumbered_sequence_produces_no_notes(self):
        self.assertEqual(sequence_notes([self.video("S one"), self.video("S two")]), [])


class SessionPartTests(unittest.TestCase):
    def test_part_number_after_a_day_label(self):
        self.assertEqual(session_part("Day 32(4) - Bhagavata Saroddhara"), 4)
        self.assertEqual(session_part("Day 32 (1) - Bhagavata Saroddhara"), 1)

    def test_no_part_number(self):
        self.assertEqual(session_part("Day 33- Bhagavata Saroddhara"), 0)

    def test_a_verse_number_elsewhere_is_not_a_part(self):
        """"Shloka 48(2)" is a verse reference, not a session part."""
        self.assertEqual(session_part("Day 22 - Bhagavata Saroddhara - Shloka 48(2)"), 0)

    def test_a_single_video_needs_no_ordering(self):
        self.assertEqual(len(order_videos([row(1, "S", "Day 1 S")])), 1)


class NormalizeWordsTests(unittest.TestCase):
    def test_punctuation_and_case_are_stripped(self):
        self.assertEqual(normalize_words("Day-2, Shloka10/11!"), ["day", "2", "shloka10", "11"])

    def test_empty_text(self):
        self.assertEqual(normalize_words(""), [])

    def test_devanagari_words_are_indexed(self):
        """An ASCII-only tokenizer dropped these, leaving the terms unsearchable."""
        self.assertEqual(
            normalize_words("Bhagavata Saroddhara अध्यात्मप्रकरण 227"),
            ["bhagavata", "saroddhara", "अध्यात्मप्रकरण", "227"],
        )

    def test_a_devanagari_syllable_is_not_split_at_its_matras(self):
        """Combining marks belong to the word; without them it breaks into pieces."""
        word = "ब्रह्मोपदेशप्रकरण"
        self.assertEqual(normalize_words(word), [word])
        self.assertEqual(len(normalize_words(f"x {word} y")), 3)

    def test_scripts_are_separated_from_each_other_by_punctuation_only(self):
        self.assertEqual(normalize_words("अध्यात्मप्रकरण-227"), ["अध्यात्मप्रकरण", "227"])

    def test_underscore_is_not_part_of_a_word(self):
        self.assertEqual(normalize_words("day_2"), ["day", "2"])


if __name__ == "__main__":
    unittest.main()


class LanguageNotesTests(unittest.TestCase):
    def test_nothing_assumed_needs_no_note(self):
        self.assertEqual(language_notes("kannada", assumed_count=0, total=5), [])

    def test_everything_assumed_needs_no_note(self):
        """The label already carries it."""
        self.assertEqual(language_notes("kannada", assumed_count=5, total=5), [])

    def test_one_assumed_video_reads_correctly(self):
        self.assertEqual(
            language_notes("marathi", assumed_count=1, total=2),
            ["1 of these 2 videos does not name a language; Marathi is assumed for it."],
        )

    def test_several_assumed_videos_read_correctly(self):
        self.assertEqual(
            language_notes("kannada", assumed_count=5, total=18),
            ["5 of these 18 videos do not name a language; Kannada is assumed for them."],
        )
