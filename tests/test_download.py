from __future__ import annotations

import unittest

from pipeline import download as dl


class FormatSelectorTests(unittest.TestCase):
    def test_selector_prefers_480p(self) -> None:
        self.assertEqual(
            dl.FORMAT_SELECTOR, "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b"
        )
        self.assertIn("height<=480", dl.FORMAT_SELECTOR)
        self.assertLessEqual(dl.MAX_HEIGHT, 480)

    def test_extract_frame_never_upscales(self) -> None:
        import inspect

        src = inspect.getsource(dl.extract_frame)
        self.assertIn("min(", src)
        self.assertIn("ih", src)


class AdaptiveCountTests(unittest.TestCase):
    def test_frame_count_follows_duration(self) -> None:
        # clamp(ceil(seconds / 10), 4, 12)
        self.assertEqual(dl.frame_count_for(13), 4)
        self.assertEqual(dl.frame_count_for(60), 6)
        self.assertEqual(dl.frame_count_for(120), 12)
        self.assertEqual(dl.frame_count_for(212), 12)
        self.assertEqual(dl.frame_count_for(1800), 12)
        self.assertEqual(dl.frame_count_for(0), 4)
        self.assertEqual(dl.frame_count_for(1800, cap=6), 6)

    def test_chapter_count_follows_duration(self) -> None:
        # clamp(round(seconds / 90) + 1, 2, 5)
        self.assertEqual(dl.chapter_count_for(13), 2)
        self.assertEqual(dl.chapter_count_for(90), 2)
        self.assertEqual(dl.chapter_count_for(180), 3)
        self.assertEqual(dl.chapter_count_for(360), 5)
        self.assertEqual(dl.chapter_count_for(1800), 5)
        self.assertEqual(dl.chapter_count_for(0), 2)


class FrameTimestampTests(unittest.TestCase):
    def test_evenly_spread_inside_the_video(self) -> None:
        ts = dl.frame_timestamps(120, 12)
        self.assertEqual(len(ts), 12)
        self.assertEqual(ts, sorted(ts))
        self.assertGreater(ts[0], 0)
        self.assertLess(ts[-1], 120)
        gaps = [round(b - a, 2) for a, b in zip(ts, ts[1:])]
        self.assertAlmostEqual(min(gaps), max(gaps), places=2)

    def test_count_and_short_video(self) -> None:
        self.assertEqual(len(dl.frame_timestamps(5, 10)), 10)
        self.assertEqual(len(dl.frame_timestamps(0, 12)), 12)

    def test_midpoint_sampling(self) -> None:
        self.assertEqual(dl.frame_timestamps(120, 3), [20.0, 60.0, 100.0])


if __name__ == "__main__":
    unittest.main()
