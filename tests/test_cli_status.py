"""Tests for the console status: the layout, and the plain fallback.

Run with: python -m unittest discover -s tests -t .

Nothing here needs HoloCure, a capture, or a terminal: the layout is built
from a :class:`telemetry.Telemetry` snapshot, which is what the loop writes
anyway.
"""

import io
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cli_status
from telemetry import STATE_RUNNING, Telemetry


def strip_escapes(text: str) -> str:
    """A line as it looks on screen, with the colour codes taken out."""
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def setUpModule():
    # imgproc reads the templates out of ./img, so run from the project root
    os.chdir(ROOT)


def busy_telemetry(loops: int = 12, duration: float = 0.004) -> Telemetry:
    """A telemetry that looks like a run that has been going a moment."""
    telemetry = Telemetry()
    telemetry.reset("fishing")
    telemetry.set_state(STATE_RUNNING, "No template matched, watching the buttons.")
    telemetry.update(
        loop_ms=duration * 1000,
        capture_ms=1.4,
        match_ms=1.25,
        sleep_ms=0.45,
        counter=3,
        chain=24,
        speed_level=3,
        grade_good=41,
        grade_ok=6,
        grade_bad=2,
        offset=-3,
        offset_report={
            "level": 3,
            "offset": -3,
            "seed": -2,
            "learned": True,
            "presses": 12,
            "mean_error": -0.4,
            "settling": 4,
        },
    )
    telemetry.set_timings({"fishing_loop_interval": 0.01}, "timings.json")
    for _ in range(loops):
        telemetry.loop_done(duration)
    for index in range(4):
        telemetry.timing(index, -0.4)
    telemetry.key("a", "rhythm arrow 'left' matched")
    telemetry.log("Fishing count: 3", level="good")
    return telemetry


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = busy_telemetry().snapshot()

    def test_block_has_a_fixed_height(self):
        block = cli_status.render(self.snapshot, log_lines=6)
        self.assertEqual(len(block), 5 + 6)

    def test_fewer_lines_are_padded_not_dropped(self):
        quiet = Telemetry().snapshot()
        block = cli_status.render(quiet, log_lines=4)
        self.assertEqual(len(block), 5 + 4)
        self.assertTrue(any("nothing logged yet" in line for line in block))

    def test_numbers_come_from_the_snapshot(self):
        block = cli_status.render(self.snapshot, log_lines=0)
        text = "".join(block)
        self.assertIn("loop 12", text)
        self.assertIn("chain 24 speed Lv 3 (3 counted here)", text)
        self.assertIn("41 GOOD 6 OK 2 BAD (84% clean of 49)", text)
        self.assertIn("3px left", text)
        self.assertIn("No template matched", text)

    def test_every_line_fits_the_width(self):
        self.snapshot["frame"].message = "x" * 200
        block = cli_status.render(self.snapshot, width=40, log_lines=0)
        for line in block:
            self.assertLessEqual(len(strip_escapes(line)), 40)

    def test_unknown_values_read_as_unknown_not_zero(self):
        blank = Telemetry()
        blank.update(state=STATE_RUNNING, counter=0)
        block = cli_status.render(blank.snapshot(), log_lines=0)
        text = "".join(block)
        self.assertIn("chain ? speed ? (0 counted here)", text)
        self.assertIn("none graded yet", text)


class FormatTests(unittest.TestCase):
    def test_rate_of_nothing(self):
        self.assertEqual(cli_status.format_rate([]), "-")

    def test_rate_from_recent_iterations(self):
        self.assertEqual(cli_status.format_rate([0.01] * 10), "100.0/s")

    def test_run_time(self):
        self.assertEqual(cli_status.format_run_time(9), "9s")
        self.assertEqual(cli_status.format_run_time(133), "2m13s")
        self.assertEqual(cli_status.format_run_time(3723), "1h02m")

    def test_sparkline_of_nothing_is_empty(self):
        self.assertEqual(cli_status.sparkline([]), "")
        self.assertEqual(cli_status.sparkline([1.0], width=0), "")

    def test_sparkline_is_one_character_per_iteration(self):
        values = [0.001 * (index % 7 + 1) for index in range(100)]
        line = cli_status.sparkline(values, width=20)
        self.assertEqual(len(line), 20)
        # the newest values are the ones kept
        self.assertEqual(line, cli_status.sparkline(values[-20:], width=20))

    def test_sparkline_of_a_flat_run_is_a_full_row(self):
        line = cli_status.sparkline([0.004] * 5, width=5)
        self.assertEqual(line, cli_status.graph_chars()[-1] * 5)

    def test_sparkline_marks_the_tallest_bar(self):
        line = cli_status.sparkline([0.001, 0.005], width=2)
        self.assertEqual(line[-1], cli_status.graph_chars()[-1])

    def test_ascii_fallback_when_the_terminal_cannot_encode(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
        self.assertEqual(cli_status.graph_chars(stream), cli_status.GRAPH_CHARS_ASCII)

    def test_clip_ignores_colour_codes(self):
        coloured = f"{cli_status.GREEN}abc{cli_status.RESET}de"
        clipped = cli_status.clip(coloured, 4)
        self.assertEqual(strip_escapes(clipped), "abcd")
        self.assertTrue(clipped.startswith(cli_status.GREEN))
        self.assertEqual(cli_status.clip("abcdef", 0), "")

    def test_press_bias_says_which_way_off(self):
        self.assertIn("early", cli_status.format_press_bias([-3.0, -4.0]))
        self.assertIn("late", cli_status.format_press_bias([3.0, 4.0]))
        self.assertIn("on time", cli_status.format_press_bias([-0.4, 0.4]))
        self.assertEqual(
            cli_status.format_press_bias([]), "no presses measured yet"
        )

    def test_press_gap_with_no_presses_yet(self):
        self.assertEqual(cli_status.format_press_gap({}), "no presses yet")

    def test_offset_says_when_it_is_only_the_guess(self):
        frame = busy_telemetry().snapshot()["frame"]
        frame.offset_report["learned"] = False
        text = cli_status.format_offset(frame)
        self.assertIn("the guess", text)

    def test_offset_with_nothing_learned(self):
        frame = busy_telemetry().snapshot()["frame"]
        frame.offset_report = {}
        self.assertEqual(cli_status.format_offset(frame), "3px left")


class DrawingTests(unittest.TestCase):
    def test_a_terminal_redraws_in_place(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        status = cli_status.ConsoleStatus(busy_telemetry(), stream=stream)
        status.draw(status.telemetry.snapshot())
        first = stream.getvalue()
        self.assertIn("\x1b[", first)
        # the second draw moves back up instead of scrolling on
        status.draw(status.telemetry.snapshot())
        self.assertIn("\x1b[11A", stream.getvalue())

    def test_a_pipe_gets_appended_lines_and_no_escapes(self):
        stream = io.StringIO()
        stream.isatty = lambda: False
        telemetry = busy_telemetry()
        status = cli_status.ConsoleStatus(telemetry, stream=stream)
        status.draw(telemetry.snapshot())
        drawn = stream.getvalue()
        self.assertNotIn("\x1b[", drawn)
        self.assertIn("Fishing count: 3", drawn)
        # the same lines are not repeated on the next redraw
        stream.truncate(0)
        stream.seek(0)
        status.draw(telemetry.snapshot())
        self.assertEqual(stream.getvalue(), "")

    def test_a_closed_console_does_not_stop_the_loop(self):
        class Broken(io.StringIO):
            def write(self, _text):
                raise OSError("closed")

            def flush(self):
                raise OSError("closed")

            def isatty(self):
                return True

        status = cli_status.ConsoleStatus(busy_telemetry(), stream=Broken())
        # a console that cannot be written to stops being drawn, quietly
        status.draw(status.telemetry.snapshot())
        self.assertTrue(status._broken)
        status.draw(status.telemetry.snapshot())


if __name__ == "__main__":
    unittest.main()