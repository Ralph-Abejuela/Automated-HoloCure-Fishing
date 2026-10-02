"""Tests for the note search window's offset, and the latency behind it.

Run with: python -m unittest discover -s tests -t .

Nothing here needs HoloCure, a capture or a note: presses are handed in as a
number of pixels and a speed, which is all the module ever gets.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from note_offset import (
    MAX_LATENCY,
    MAX_STEP_LATENCY,
    MIN_FLUSH_PRESSES,
    MIN_LATENCY,
    MIN_TRACKABLE_SPEED,
    WINDOW_PRESSES,
    OffsetLearner,
    effective_level,
    seed_offset,
)

#: A plausible note speed for a slow fish and for one at the top of the game.
SLOW_PX_S = 150.0
FAST_PX_S = 600.0


def anchored(learner, speed=SLOW_PX_S, level=4):
    """A learner that has seen one velocity, so a latency exists."""
    learner.offset_for(level, speed_px_s=speed)
    return learner


class TestSeedOffset(unittest.TestCase):
    def test_the_table_still_ramps_down_from_level_one_to_seven(self):
        self.assertEqual(seed_offset(1), 0)
        self.assertEqual(seed_offset(4), -2)
        self.assertEqual(seed_offset(7), -4)

    def test_a_level_outside_the_table_is_held_at_its_end(self):
        self.assertEqual(seed_offset(0), seed_offset(1))
        self.assertEqual(seed_offset(-4), seed_offset(1))
        self.assertEqual(seed_offset(99), seed_offset(7))

    def test_an_unread_level_falls_back_to_the_chain(self):
        self.assertEqual(seed_offset(None, 0), 0)
        self.assertEqual(seed_offset(None, 35), seed_offset(4))
        self.assertEqual(seed_offset(None, 70), seed_offset(7))

    def test_a_chain_past_the_top_of_the_table_holds_at_the_top(self):
        self.assertEqual(seed_offset(None, 10000), seed_offset(7))


class TestEffectiveLevel(unittest.TestCase):
    def test_the_panel_is_the_level_when_it_has_been_read(self):
        self.assertEqual(effective_level(3, 0), 3)
        self.assertEqual(effective_level(7, 0), 7)

    def test_a_level_outside_one_to_seven_is_clamped_into_it(self):
        self.assertEqual(effective_level(0, 0), 1)
        self.assertEqual(effective_level(-2, 0), 1)
        self.assertEqual(effective_level(12, 0), 7)

    def test_the_chain_stands_in_for_the_panel_until_it_is_read(self):
        self.assertEqual(effective_level(None, 0), 1)
        self.assertEqual(effective_level(None, 9), 1)
        self.assertEqual(effective_level(None, 25), 2)
        self.assertEqual(effective_level(None, 999), 7)


class TestColdStart(unittest.TestCase):
    def test_without_a_velocity_the_offset_is_the_seed(self):
        learner = OffsetLearner()
        self.assertEqual(learner.offset_for(1), seed_offset(1))
        self.assertEqual(learner.offset_for(5, 12), seed_offset(5))
        self.assertEqual(learner.offset_for(None, 40), seed_offset(None, 40))

    def test_nothing_is_learned_before_a_velocity_arrives(self):
        learner = OffsetLearner()
        for _ in range(WINDOW_PRESSES * 3):
            learner.observe(-3.0, 4)
        self.assertIsNone(learner.cell.latency)
        self.assertEqual(learner.cell.count, 0)
        self.assertEqual(learner.offset_for(4), seed_offset(4))


class TestAnchoring(unittest.TestCase):
    def test_the_first_velocity_gives_the_same_offset_the_table_would_have(self):
        # The whole point of the changeover: nothing about the window moves on
        # the first note that the model sees.
        for level in range(1, 8):
            for speed in (SLOW_PX_S, FAST_PX_S):
                learner = OffsetLearner()
                self.assertEqual(
                    learner.offset_for(level, speed_px_s=speed),
                    seed_offset(level),
                    f"level {level} at {speed}px/s",
                )

    def test_anchoring_does_not_move_again_once_it_has_happened(self):
        learner = OffsetLearner()
        learner.offset_for(7, speed_px_s=FAST_PX_S)
        first = learner.cell.latency
        learner.offset_for(1, speed_px_s=SLOW_PX_S)
        self.assertEqual(learner.cell.latency, first)
        self.assertTrue(learner.cell.anchored)


class TestTheVelocityModel(unittest.TestCase):
    def test_a_faster_note_gets_a_larger_offset_of_the_same_sign(self):
        learner = OffsetLearner()
        learner.offset_for(4, speed_px_s=SLOW_PX_S)
        slow = learner.offset_for(4, speed_px_s=SLOW_PX_S)
        fast = learner.offset_for(4, speed_px_s=FAST_PX_S)
        self.assertLess(slow, 0)
        self.assertLess(fast, slow)
        self.assertAlmostEqual(fast / slow, FAST_PX_S / SLOW_PX_S, places=6)

    def test_the_offset_is_the_latency_scaled_by_the_speed(self):
        learner = OffsetLearner()
        learner.offset_for(4, speed_px_s=SLOW_PX_S)
        learner.cell.latency = 0.02
        self.assertEqual(learner.offset_for(4, speed_px_s=250.0), -5)

    def test_presses_landing_early_pull_an_over_compensated_window_back(self):
        # Anchored at the deepest table offset, the window is four pixels left
        # of the circle. A press that lands a pixel early is saying the
        # presses are a pixel less late than the window allows, and the
        # window comes back towards zero, one step cap at a time.
        learner = OffsetLearner()
        self.assertEqual(learner.offset_for(7, speed_px_s=SLOW_PX_S), -4)
        for _ in range(WINDOW_PRESSES * 6):
            learner.observe(-1.0, 7, speed_px_s=SLOW_PX_S)
        after = learner.offset_for(7, speed_px_s=SLOW_PX_S)
        self.assertGreater(after, -4)
        self.assertEqual(after, -1)
        self.assertLess(learner.cell.latency, 0.0267)

    def test_presses_landing_late_push_the_window_further_the_other_way(self):
        # The same window, with the presses landing the other way: the bot is
        # pressing later than the window says, and the sign of the correction
        # follows the presses rather than the level.
        learner = OffsetLearner()
        self.assertEqual(learner.offset_for(7, speed_px_s=SLOW_PX_S), -4)
        for _ in range(WINDOW_PRESSES * 20):
            learner.observe(1.0, 7, speed_px_s=SLOW_PX_S)
        after = learner.offset_for(7, speed_px_s=SLOW_PX_S)
        self.assertGreater(after, -4)
        self.assertEqual(after, 1)
        self.assertLess(learner.cell.latency, 0.0)


class TestConvergence(unittest.TestCase):
    def teach(self, learner, true_latency, speed=SLOW_PX_S, level=4, count=400):
        """Feed presses made by a machine with a known delay."""
        for _ in range(count):
            learner.observe(-true_latency * speed, level, speed_px_s=speed)
        return learner

    def test_early_presses_teach_the_latency_that_would_have_landed_them(self):
        learner = self.teach(anchored(OffsetLearner()), 0.02)
        self.assertAlmostEqual(learner.cell.latency, 0.02, places=4)

    def test_the_latency_settles_rather_than_oscillating(self):
        learner = self.teach(anchored(OffsetLearner()), 0.02, count=300)
        self.assertAlmostEqual(learner.cell.latency, 0.02, places=6)
        settled = learner.cell.latency
        for _ in range(300):
            learner.observe(-0.02 * SLOW_PX_S, 4, speed_px_s=SLOW_PX_S)
        self.assertAlmostEqual(learner.cell.latency, settled, places=7)
        self.assertEqual(learner.offset_for(4, speed_px_s=SLOW_PX_S), -3)

    def test_the_same_latency_is_learned_from_notes_at_different_speeds(self):
        learner = anchored(OffsetLearner())
        for speed in (SLOW_PX_S, FAST_PX_S):
            for _ in range(WINDOW_PRESSES * 4):
                learner.observe(-0.015 * speed, 4, speed_px_s=speed)
        self.assertAlmostEqual(learner.cell.latency, 0.015, places=4)

    def test_the_errors_taught_at_one_speed_stay_right_at_another(self):
        learner = self.teach(anchored(OffsetLearner()), 0.01, count=400)
        learner.cell.recent.clear()
        for _ in range(WINDOW_PRESSES):
            learner.observe(0.0, 4, speed_px_s=FAST_PX_S)
        self.assertAlmostEqual(learner.cell.mean, 0.0, places=9)


class TestUnusableSpeeds(unittest.TestCase):
    def discard(self, speed):
        learner = anchored(OffsetLearner())
        before = learner.cell.latency
        for _ in range(WINDOW_PRESSES * 2):
            learner.observe(-5.0, 4, speed_px_s=speed)
        self.assertEqual(learner.cell.latency, before)
        self.assertEqual(learner.cell.count, 0)
        self.assertEqual(learner.cell.pending, [])

    def test_a_press_with_no_speed_at_all_is_not_evidence(self):
        self.discard(None)

    def test_a_press_at_a_speed_that_is_not_a_number_is_not_evidence(self):
        self.discard(float("nan"))
        self.discard(float("inf"))
        self.discard("fast")

    def test_a_press_at_a_speed_below_the_floor_is_not_evidence(self):
        self.discard(MIN_TRACKABLE_SPEED / 2.0)
        self.discard(0.0)
        self.discard(-300.0)

    def test_a_press_at_exactly_the_floor_is_kept(self):
        learner = anchored(OffsetLearner())
        learner.observe(-5.0, 4, speed_px_s=MIN_TRACKABLE_SPEED)
        self.assertEqual(learner.cell.count, 1)

    def test_a_press_before_the_panel_has_been_read_is_not_learned_from(self):
        learner = anchored(OffsetLearner())
        before = learner.cell.latency
        for _ in range(WINDOW_PRESSES * 2):
            learner.observe(-5.0, None, 40, speed_px_s=SLOW_PX_S)
        self.assertEqual(learner.cell.latency, before)
        self.assertEqual(learner.cell.count, 0)


class TestFlush(unittest.TestCase):
    def test_a_part_filled_window_is_spent_when_the_run_moves_on(self):
        learner = anchored(OffsetLearner())
        before = learner.cell.latency
        for _ in range(MIN_FLUSH_PRESSES):
            learner.observe(-6.0, 4, speed_px_s=SLOW_PX_S)
        self.assertTrue(learner.cell.flush())
        self.assertEqual(learner.cell.pending, [])
        self.assertNotEqual(learner.cell.latency, before)

    def test_too_few_presses_to_mean_anything_are_thrown_away(self):
        learner = anchored(OffsetLearner())
        before = learner.cell.latency
        for _ in range(MIN_FLUSH_PRESSES - 1):
            learner.observe(-6.0, 4, speed_px_s=SLOW_PX_S)
        self.assertFalse(learner.cell.flush())
        self.assertEqual(learner.cell.latency, before)
        self.assertEqual(learner.cell.pending, [])

    def test_the_presses_are_still_counted_after_a_flush(self):
        learner = anchored(OffsetLearner())
        for _ in range(MIN_FLUSH_PRESSES):
            learner.observe(-6.0, 4, speed_px_s=SLOW_PX_S)
        learner.flush()
        self.assertEqual(learner.cell.count, MIN_FLUSH_PRESSES)


class TestBounds(unittest.TestCase):
    def test_one_enormous_error_cannot_move_the_latency_far(self):
        learner = anchored(OffsetLearner())
        before = learner.cell.latency
        for _ in range(WINDOW_PRESSES):
            learner.observe(-200.0, 4, speed_px_s=SLOW_PX_S)
        self.assertLessEqual(
            abs(learner.cell.latency - before), MAX_STEP_LATENCY + 1e-12
        )

    def test_a_long_run_of_impossible_latencies_is_capped_at_the_top(self):
        # Far enough windows to walk the step cap all the way to the clamp.
        learner = anchored(OffsetLearner())
        for _ in range(WINDOW_PRESSES * 120):
            learner.observe(-100.0, 4, speed_px_s=SLOW_PX_S)
        self.assertEqual(learner.cell.latency, MAX_LATENCY)

    def test_a_long_run_of_impossible_latencies_is_capped_at_the_bottom(self):
        learner = anchored(OffsetLearner())
        for _ in range(WINDOW_PRESSES * 120):
            learner.observe(100.0, 4, speed_px_s=SLOW_PX_S)
        self.assertEqual(learner.cell.latency, MIN_LATENCY)

    def test_the_offset_never_leaves_the_strip_the_search_covers(self):
        learner = OffsetLearner()
        learner.cell.latency = 1.0
        self.assertEqual(learner.offset_for(4, speed_px_s=900.0), -30)
        learner.cell.latency = -1.0
        self.assertEqual(learner.offset_for(4, speed_px_s=900.0), 5)


class TestReport(unittest.TestCase):
    KEYS = (
        "level",
        "offset",
        "seed",
        "learned",
        "presses",
        "mean_error",
        "settling",
        "latency_ms",
        "speed_px_s",
        "modelled",
    )

    def test_every_documented_key_is_there_before_anything_is_measured(self):
        report = OffsetLearner().report(3, 12)
        for key in self.KEYS:
            self.assertIn(key, report)
        self.assertEqual(report["level"], 3)
        self.assertEqual(report["offset"], seed_offset(3))
        self.assertEqual(report["seed"], seed_offset(3))
        self.assertFalse(report["learned"])
        self.assertEqual(report["presses"], 0)
        self.assertEqual(report["mean_error"], 0.0)
        self.assertEqual(report["settling"], 0)
        self.assertIsNone(report["latency_ms"])
        self.assertIsNone(report["speed_px_s"])
        self.assertFalse(report["modelled"])

    def test_the_model_keys_turn_on_with_the_first_velocity(self):
        learner = OffsetLearner()
        for _ in range(WINDOW_PRESSES):
            learner.observe(-6.0, 3, 12, speed_px_s=SLOW_PX_S)
        report = learner.report(3, 12, speed_px_s=SLOW_PX_S)
        self.assertTrue(report["modelled"])
        self.assertEqual(report["speed_px_s"], SLOW_PX_S)
        self.assertIsNotNone(report["latency_ms"])
        self.assertAlmostEqual(report["latency_ms"], learner.cell.latency * 1000.0)
        self.assertTrue(report["learned"])
        self.assertEqual(report["presses"], WINDOW_PRESSES)

    def test_a_report_without_a_velocity_does_not_claim_the_model_is_running(self):
        learner = OffsetLearner()
        for _ in range(WINDOW_PRESSES):
            learner.observe(-6.0, 3, 12, speed_px_s=SLOW_PX_S)
        report = learner.report(3, 12)
        self.assertFalse(report["modelled"])
        self.assertIsNone(report["speed_px_s"])
        self.assertEqual(report["offset"], seed_offset(3))

    def test_the_mean_error_is_reported_in_pixels(self):
        learner = OffsetLearner()
        for _ in range(WINDOW_PRESSES):
            learner.observe(-4.0, 3, 12, speed_px_s=SLOW_PX_S)
        report = learner.report(3, 12, speed_px_s=SLOW_PX_S)
        self.assertEqual(report["mean_error"], -4.0)

    def test_the_level_is_named_from_the_chain_when_the_panel_is_unread(self):
        report = OffsetLearner().report(None, 45)
        self.assertEqual(report["level"], 4)
        self.assertEqual(report["offset"], seed_offset(None, 45))


if __name__ == "__main__":
    unittest.main()
