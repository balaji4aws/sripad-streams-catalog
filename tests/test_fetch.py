"""Tests for fetch.py's tab merging.

The network call itself is not tested - it needs YouTube and browser cookies -
but merge_tabs() is pure, and it is where a mistake would quietly corrupt the
whole catalogue by losing or double-counting videos.
"""

import unittest
from typing import Any

from fetch import merge_tabs


def tab(*titles: str, epoch: int = 1000, channel: str = "Sripad K") -> dict[str, Any]:
    """A minimal yt-dlp payload for one channel tab."""
    return {
        "channel": channel,
        "channel_url": "https://www.youtube.com/@example",
        "webpage_url": "https://www.youtube.com/@example/streams",
        "epoch": epoch,
        "entries": [{"id": title.replace(" ", ""), "title": title} for title in titles],
    }


class MergeTabsTests(unittest.TestCase):
    def test_entries_are_tagged_with_their_tab_and_position(self):
        merged = merge_tabs({"streams": tab("a", "b"), "videos": tab("c")})
        self.assertEqual(
            [(e["title"], e["_source"], e["_source_position"]) for e in merged["entries"]],
            [("a", "streams", 1), ("b", "streams", 2), ("c", "videos", 1)],
        )

    def test_per_tab_counts_are_recorded(self):
        merged = merge_tabs({"streams": tab("a", "b"), "videos": tab("c")})
        self.assertEqual(merged["tabs"], {"streams": 2, "videos": 1})

    def test_tab_order_is_preserved(self):
        merged = merge_tabs({"streams": tab("a"), "videos": tab("b")})
        self.assertEqual([e["_source"] for e in merged["entries"]], ["streams", "videos"])

    def test_a_video_listed_on_two_tabs_is_kept_once(self):
        """A duplicate would be counted twice and appear twice in its series."""
        shared = tab("a", "shared")
        other = tab("shared", "b")
        merged = merge_tabs({"streams": shared, "videos": other})
        titles = [e["title"] for e in merged["entries"]]
        self.assertEqual(titles, ["a", "shared", "b"])
        self.assertEqual(merged["tabs"], {"streams": 2, "videos": 1},
                         "the counts must reflect what was kept, not what was fetched")

    def test_positions_stay_contiguous_after_a_duplicate_is_dropped(self):
        """Otherwise a gap in source_position would look like a lost video."""
        merged = merge_tabs({"streams": tab("dup"), "videos": tab("dup", "x", "y")})
        videos = [e for e in merged["entries"] if e["_source"] == "videos"]
        self.assertEqual([e["_source_position"] for e in videos], [1, 2])

    def test_scan_time_is_the_latest_across_the_tabs(self):
        """The scan finishes when its last request does, not its first."""
        merged = merge_tabs({"streams": tab("a", epoch=1000), "videos": tab("b", epoch=2000)})
        self.assertEqual(merged["epoch"], 2000)

    def test_an_empty_tab_is_harmless(self):
        merged = merge_tabs({"streams": tab("a"), "videos": tab()})
        self.assertEqual(merged["tabs"], {"streams": 1, "videos": 0})
        self.assertEqual(len(merged["entries"]), 1)

    def test_channel_metadata_is_carried_over(self):
        merged = merge_tabs({"streams": tab("a"), "videos": tab("b")})
        self.assertEqual(merged["channel"], "Sripad K")
        self.assertIn("channel_url", merged)


if __name__ == "__main__":
    unittest.main()
