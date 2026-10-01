"""Tests for the reporting sink the game loops write into.

Run with: python -m unittest discover -s tests -t .
"""

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telemetry import (
    STATE_ERROR,
    STATE_RUNNING,
    STATE_STOPPED,
    Dot,
    Match,
    Rect,
    Telemetry,
)


class TestTelemetry(unittest.TestCase):
    def test_a_new_telemetry_is_idle_and_never_stops(self):
        telemetry = Telemetry()
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["frame"].state, "idle")
        self.assertEqual(snapshot["frame"].loop, 0)
        self.assertFalse(telemetry.should_stop())

    def test_update_replaces_the_fields_it_is_given(self):
        telemetry = Telemetry()
        telemetry.update(loop_ms=12.5, scale=2)
        frame = telemetry.snapshot()["frame"]
        self.assertEqual(frame.loop_ms, 12.5)
        self.assertEqual(frame.scale, 2)
        self.assertEqual(frame.state, "idle")

    def test_loop_done_counts_iterations_and_records_their_length(self):
        telemetry = Telemetry()
        for _ in range(3):
            telemetry.loop_done(0.01)
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["frame"].loop, 3)
        self.assertEqual(snapshot["durations"], [0.01, 0.01, 0.01])

    def test_a_keypress_is_both_a_key_and_a_log_line(self):
        telemetry = Telemetry()
        telemetry.key("a", "rhythm arrow 'left' matched")
        snapshot = telemetry.snapshot()
        self.assertEqual(len(snapshot["keypresses"]), 1)
        self.assertEqual(snapshot["keypresses"][0].key, "a")
        self.assertEqual(len(snapshot["log"]), 1)
        self.assertIn("rhythm arrow", snapshot["log"][0].text)

    def test_keypress_logging_can_be_turned_off(self):
        telemetry = Telemetry()
        telemetry.log_keypresses = False
        telemetry.key("a", "rhythm arrow")
        snapshot = telemetry.snapshot()
        self.assertEqual(len(snapshot["keypresses"]), 1)
        self.assertEqual(snapshot["log"], [])

    def test_a_snapshot_does_not_share_state_with_the_next_one(self):
        telemetry = Telemetry()
        telemetry.update(rects=[Rect(0, 0, 1, 1)], keybinds={"space": "space"})
        first = telemetry.snapshot()
        telemetry.update(rects=[], keybinds={})
        self.assertEqual(len(first["frame"].rects), 1)
        self.assertEqual(first["frame"].keybinds, {"space": "space"})

    def test_a_reader_is_told_which_events_it_has_not_seen(self):
        telemetry = Telemetry()
        for index in range(5):
            telemetry.log(f"line {index}")
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["log_first"], 0)
        self.assertEqual(snapshot["log_total"], 5)
        self.assertEqual(len(snapshot["log"]), 5)

    def test_events_that_fell_off_the_front_are_counted(self):
        from telemetry import KEYPRESS_HISTORY

        telemetry = Telemetry()
        for _ in range(KEYPRESS_HISTORY + 10):
            telemetry.key("a")
        snapshot = telemetry.snapshot()
        self.assertEqual(len(snapshot["keypresses"]), KEYPRESS_HISTORY)
        self.assertEqual(snapshot["keypress_first"], 10)
        self.assertEqual(snapshot["keypress_total"], KEYPRESS_HISTORY + 10)

    def test_clearing_the_log_bumps_the_generation_and_forgets_the_lines(self):
        telemetry = Telemetry()
        telemetry.log("before")
        before = telemetry.snapshot()["log_generation"]
        telemetry.clear_log()
        snapshot = telemetry.snapshot()
        self.assertNotEqual(snapshot["log_generation"], before)
        self.assertEqual(snapshot["log"], [])
        self.assertEqual(snapshot["log_total"], 1)

    def test_reset_starts_a_new_run(self):
        telemetry = Telemetry()
        telemetry.update(loop_ms=99, counter=12)
        telemetry.log("old run")
        telemetry.key("a")
        telemetry.reset("fishing")

        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["frame"].mode, "fishing")
        self.assertEqual(snapshot["frame"].loop, 0)
        self.assertEqual(snapshot["frame"].counter, 0)
        self.assertEqual(snapshot["frame"].state, "starting")
        self.assertEqual(snapshot["log"], [])
        self.assertEqual(snapshot["keypresses"], [])

    def test_reset_also_clears_a_stop_from_the_last_run(self):
        telemetry = Telemetry()
        telemetry.stop()
        telemetry.reset("mining")
        self.assertFalse(telemetry.should_stop())

    def test_stop_asks_the_loop_to_finish_and_says_so(self):
        telemetry = Telemetry()
        telemetry.set_state(STATE_RUNNING, "watching")
        telemetry.stop()
        self.assertTrue(telemetry.should_stop())
        self.assertEqual(telemetry.snapshot()["frame"].state, "stopping")

    def test_finish_is_reported_once(self):
        telemetry = Telemetry()
        telemetry.finish("Fishing stopped.")
        telemetry.finish("Fishing stopped.")
        self.assertEqual(telemetry.snapshot()["frame"].state, STATE_STOPPED)
        self.assertEqual(len(telemetry.snapshot()["log"]), 1)

    def test_a_failure_is_not_overwritten_by_finishing(self):
        telemetry = Telemetry()
        telemetry.fail("ValueError: something broke")
        telemetry.finish()
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["frame"].state, STATE_ERROR)
        self.assertEqual(snapshot["error"], "ValueError: something broke")

    def test_a_reader_in_another_thread_sees_what_the_writer_writes(self):
        telemetry = Telemetry()
        seen = []

        def reader():
            for _ in range(200):
                if telemetry.snapshot()["frame"].state == STATE_RUNNING:
                    seen.append(True)
                    return
                time.sleep(0.005)
            seen.append(False)

        thread = threading.Thread(target=reader)
        thread.start()
        for index in range(50):
            telemetry.set_state(STATE_RUNNING, f"loop {index}")
            telemetry.update(matches=[Match("ok", 1.0, 2.0, True, (1, 2))])
        thread.join(5)

        self.assertEqual(seen, [True])

    def test_timings_are_reported_with_the_file_they_came_from(self):
        telemetry = Telemetry()
        telemetry.set_timings({"fishing_key_delay": 0.25}, "timings.json")
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["timings"], {"fishing_key_delay": 0.25})
        self.assertEqual(snapshot["timings_path"], "timings.json")


if __name__ == "__main__":
    unittest.main()
