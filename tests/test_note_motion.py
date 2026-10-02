"""Tests for measuring how fast the notes move.

Run with: python -m unittest discover -s tests -t .
"""

import dataclasses
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from note_motion import (
    MAX_SPEED_PX_S,
    MIN_SPEED_PX_S,
    Motion,
    NoteTracker,
    implied_latency,
)


class TestNoteTracker(unittest.TestCase):
    def test_the_first_sample_of_a_note_reports_no_speed(self):
        tracker = NoteTracker()
        self.assertIsNone(tracker.update("left", 100.0, 1.0))
        self.assertIsNone(tracker.last)
        self.assertIsNone(tracker.last_speed)

    def test_two_samples_of_one_note_give_the_exact_speed(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        motion = tracker.update("left", 102.0, 1.01)
        self.assertIsNotNone(motion)
        self.assertAlmostEqual(motion.px_per_second, 200.0, places=6)
        self.assertEqual(motion.samples, 1)
        self.assertEqual(motion.key, "left")

    def test_the_reported_speed_is_the_mean_of_several_samples(self):
        tracker = NoteTracker()
        tracker.update("up", 100.0, 1.00)
        speeds = []
        # 100, 200 and 300 pixels a second, over the three intervals after.
        centres = (101.0, 103.0, 106.0)
        for centre, now in zip(centres, (1.01, 1.02, 1.03)):
            speeds.append(tracker.update("up", centre, now).px_per_second)
        self.assertAlmostEqual(speeds[0], 100.0, places=6)
        self.assertAlmostEqual(speeds[1], 150.0, places=6)
        self.assertAlmostEqual(speeds[2], 200.0, places=6)
        self.assertEqual(tracker.last.samples, 3)

    def test_the_sample_count_says_how_full_the_window_is(self):
        tracker = NoteTracker(smoothing=2)
        tracker.update("down", 100.0, 1.00)
        self.assertEqual(tracker.update("down", 102.0, 1.01).samples, 1)
        self.assertEqual(tracker.update("down", 104.0, 1.02).samples, 2)
        # The window is two long, so the third reading replaces the first.
        self.assertEqual(tracker.update("down", 106.0, 1.03).samples, 2)

    def test_a_different_key_starts_tracking_again(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        speed_before = tracker.update("left", 102.0, 1.01).px_per_second
        self.assertIsNone(tracker.update("up", 140.0, 1.02))
        self.assertAlmostEqual(tracker.last_speed, speed_before, places=6)

    def test_a_gap_longer_than_allowed_starts_tracking_again(self):
        tracker = NoteTracker(max_gap=0.25)
        tracker.update("left", 100.0, 1.00)
        self.assertIsNone(tracker.update("left", 102.0, 1.30))
        # The refused gap is not simply resumed from, so the two pixels that
        # moved during it are not measured against a stale baseline.
        resumed = tracker.update("left", 104.0, 1.31)
        self.assertAlmostEqual(resumed.px_per_second, 200.0, places=6)
        self.assertEqual(resumed.samples, 1)

    def test_a_note_that_did_not_move_right_starts_tracking_again(self):
        tracker = NoteTracker()
        tracker.update("right", 100.0, 1.00)
        # Same place as last time is not a new note, it is not travelling.
        self.assertIsNone(tracker.update("right", 100.0, 1.01))
        # Backwards is not a very slow note either, it is a different one.
        self.assertIsNone(tracker.update("right", 80.0, 1.02))
        # Tracking resumed from that sighting, so the jump is measured from it.
        self.assertAlmostEqual(
            tracker.update("right", 81.0, 1.03).px_per_second, 100.0, places=6
        )

    def test_a_clock_that_did_not_move_starts_tracking_again(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        self.assertIsNone(tracker.update("left", 110.0, 1.00))

    def test_an_implausibly_fast_note_is_refused(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        good = tracker.update("left", 102.0, 1.01)
        # Far quicker than any note travels: a tenth of a pixel of clock.
        self.assertIsNone(tracker.update("left", 200.0, 1.011))
        self.assertIs(
            tracker.last, good, "the last good reading must survive a bad frame"
        )

    def test_an_implausibly_slow_note_is_refused(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        good = tracker.update("left", 102.0, 1.01)
        self.assertIsNone(tracker.update("left", 205.0, 1.011))
        self.assertIs(tracker.last, good)

    def test_the_speed_limits_are_inclusive_at_both_ends(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        at_ceiling = tracker.update("left", 101.0, 1.00 + 1 / MAX_SPEED_PX_S)
        self.assertAlmostEqual(at_ceiling.px_per_second, MAX_SPEED_PX_S, places=6)
        # Twice the ceiling is past it, and is refused.
        self.assertIsNone(tracker.update("left", 102.0, 1.00 + 2 / MAX_SPEED_PX_S))
        tracker.reset()
        tracker.update("left", 100.0, 1.00)
        # The floor itself is a wash in binary floating point, so a note
        # clearly and legitimately above it stands in for it.
        above_floor = tracker.update("left", 101.0, 1.05)
        self.assertAlmostEqual(above_floor.px_per_second, 20.0, places=6)

    def test_recovery_after_a_refused_reading_comes_from_the_new_baseline(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        tracker.update("left", 102.0, 1.01)
        tracker.update("left", 202.0, 1.011)  # refused, baseline moves to 202
        motion = tracker.update("left", 204.0, 1.021)
        self.assertAlmostEqual(motion.px_per_second, 200.0, places=6)
        self.assertEqual(motion.samples, 2)

    def test_a_refused_reading_does_not_join_the_smoothing_window(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        tracker.update("left", 102.0, 1.01)  # 200 px/s
        tracker.update("left", 202.0, 1.011)  # refused
        motion = tracker.update("left", 203.0, 1.021)  # 100 px/s
        self.assertAlmostEqual(motion.px_per_second, 150.0, places=6)
        self.assertEqual(motion.samples, 2)

    def test_reset_clears_the_last_reading(self):
        tracker = NoteTracker()
        tracker.update("left", 100.0, 1.00)
        tracker.update("left", 102.0, 1.01)
        tracker.reset()
        self.assertIsNone(tracker.last)
        self.assertIsNone(tracker.last_speed)
        self.assertIsNone(tracker.update("left", 104.0, 1.02))

    def test_a_note_measured_over_many_iterations_keeps_its_speed(self):
        tracker = NoteTracker()
        tracker.update("space", 60.0, 10.00)
        speeds = {
            round(tracker.update("space", 60.0 + 2.0 * i, 10.0 + 0.01 * i)
                  .px_per_second, 6)
            for i in range(1, 6)
        }
        self.assertEqual(speeds, {200.0})


class TestImpliedLatency(unittest.TestCase):
    def test_an_early_press_works_out_as_a_negative_latency(self):
        self.assertAlmostEqual(implied_latency(-4.0, 200.0), 0.02, places=6)

    def test_a_late_press_works_out_as_a_positive_latency(self):
        self.assertAlmostEqual(implied_latency(3.0, 300.0), -0.01, places=6)

    def test_no_error_means_no_latency(self):
        self.assertAlmostEqual(implied_latency(0.0, 250.0), 0.0, places=6)

    def test_a_speed_too_slow_to_measure_gives_no_latency(self):
        self.assertIsNone(implied_latency(-4.0, MIN_SPEED_PX_S / 2))

    def test_a_speed_that_is_not_a_number_gives_no_latency(self):
        self.assertIsNone(implied_latency(-4.0, float("nan")))
        self.assertIsNone(implied_latency(-4.0, float("inf")))

    def test_a_speed_at_the_floor_is_still_usable(self):
        self.assertAlmostEqual(
            implied_latency(-1.0, MIN_SPEED_PX_S), 1.0 / MIN_SPEED_PX_S, places=6
        )


class TestMotion(unittest.TestCase):
    def test_a_motion_cannot_be_changed_after_it_is_made(self):
        motion = Motion(key="up", px_per_second=200.0, samples=1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            motion.px_per_second = 900.0

    def test_the_fields_are_named_as_the_caller_expects(self):
        names = [field.name for field in dataclasses.fields(Motion)]
        self.assertEqual(names, ["key", "px_per_second", "samples"])

    def test_the_fields_hold_what_was_given(self):
        motion = Motion(key="down", px_per_second=123.5, samples=4)
        self.assertEqual(motion.key, "down")
        self.assertTrue(math.isclose(motion.px_per_second, 123.5))


if __name__ == "__main__":
    unittest.main()