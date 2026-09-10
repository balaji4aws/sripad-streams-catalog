"""Tests for build_sequences.py - splitting series by language and ordering them.

The point of this step is that a series taught more than once, in different
languages, is several independently numbered tracks rather than one list. These
tests pin down that split, the watch order inside each track, and the label
that avoids saying the language twice.
"""

import unittest

from build_sequences import (
    build_groups,
    category_names_language,
    detect_language,
    normalize_words,
    sequence_label,
)


def row(position, category, title, date="2024-01-01"):
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

    def test_no_language_leaves_the_category_alone(self):
        self.assertEqual(sequence_label("Pratah Sankalpa Gadya", None), "Pratah Sankalpa Gadya")


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

    def test_videos_with_no_language_form_their_own_sequence(self):
        rows = [
            row(1, "Series", "Series Kannada Day1"),
            row(2, "Series", "Series Day1"),
        ]
        groups = build_groups(rows)
        self.assertEqual({group["language"] for group in groups}, {"kannada", None})

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


class NormalizeWordsTests(unittest.TestCase):
    def test_punctuation_and_case_are_stripped(self):
        self.assertEqual(normalize_words("Day-2, Shloka10/11!"), ["day", "2", "shloka10", "11"])

    def test_empty_text(self):
        self.assertEqual(normalize_words(""), [])


if __name__ == "__main__":
    unittest.main()
