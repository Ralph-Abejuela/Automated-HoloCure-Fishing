"""Tests for the timings table.

Run with: python -m unittest discover -s tests -t .
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import timings
from timings import TimingError, Timings, parse_value, validate


class TestParseValue(unittest.TestCase):
    def test_plain_number_is_seconds_for_delays(self):
        self.assertEqual(parse_value(timings.SPECS["fishing_key_delay"], "0.25"), 0.25)

    def test_millisecond_suffix(self):
        self.assertEqual(parse_value(timings.SPECS["fishing_key_delay"], "250ms"), 0.25)

    def test_second_suffix(self):
        self.assertEqual(parse_value(timings.SPECS["mining_enter_delay"], "1s"), 1.0)

    def test_suffix_is_case_insensitive(self):
        self.assertEqual(parse_value(timings.SPECS["mining_enter_delay"], "400 MS"), 0.4)

    def test_counts_must_be_whole_numbers(self):
        self.assertEqual(parse_value(timings.SPECS["mining_ok_presses"], "7"), 7)
        with self.assertRaises(TimingError):
            parse_value(timings.SPECS["mining_ok_presses"], "7.5")

    def test_numbers_pass_through_unchanged(self):
        self.assertEqual(parse_value(timings.SPECS["mining_ok_presses"], 7), 7)

    def test_booleans_are_rejected(self):
        with self.assertRaises(TimingError):
            parse_value(timings.SPECS["mining_ok_presses"], True)

    def test_garbage_is_rejected(self):
        with self.assertRaises(TimingError):
            parse_value(timings.SPECS["mining_enter_delay"], "soon")

    def test_empty_is_rejected(self):
        with self.assertRaises(TimingError):
            parse_value(timings.SPECS["mining_enter_delay"], "   ")

    def test_out_of_range_is_rejected(self):
        with self.assertRaises(TimingError):
            parse_value(timings.SPECS["fishing_key_delay"], "99")
        with self.assertRaises(TimingError):
            parse_value(timings.SPECS["mining_ok_presses"], "0")

    def test_nan_and_infinity_are_rejected(self):
        # NaN compares false against both bounds, so the range check alone
        # would wave it through.
        for text in ("nan", "inf", "-inf"):
            with self.assertRaises(TimingError):
                parse_value(timings.SPECS["fishing_key_delay"], text)
        with self.assertRaises(TimingError):
            parse_value(timings.SPECS["fishing_key_delay"], float("nan"))


class TestValidate(unittest.TestCase):
    def test_missing_names_fall_back_to_defaults(self):
        result = validate({"fishing_key_delay": 0.3}, "windows")
        self.assertEqual(result["fishing_key_delay"], 0.3)
        self.assertEqual(result["mining_enter_delay"], 0.4)
        self.assertEqual(set(result), set(timings.SPECS))

    def test_platform_default_is_used(self):
        self.assertEqual(validate({}, "windows")["keypress_gap"], 0.015)
        self.assertEqual(validate({}, "linux")["keypress_gap"], 0.03)

    def test_unknown_name_lists_a_suggestion(self):
        with self.assertRaises(TimingError) as caught:
            validate({"fishing_key_delayy": 0.3})
        self.assertIn("did you mean 'fishing_key_delay'", str(caught.exception))

    def test_every_problem_is_reported(self):
        with self.assertRaises(TimingError) as caught:
            validate({"mining_ok_presses": 0, "mining_enter_delay": -1})
        self.assertEqual(len(str(caught.exception).splitlines()), 2)

    def test_platform_names_are_normalized(self):
        self.assertEqual(timings.normalize_platform("linux"), "linux")
        self.assertEqual(timings.normalize_platform("win32"), "windows")
        self.assertEqual(timings.normalize_platform("windows"), "windows")


class TestTimings(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "timings.json"

    def test_missing_file_yields_defaults(self):
        table = Timings(self.path, "windows")
        self.assertEqual(table["fishing_key_delay"], 0.05)
        self.assertTrue(table.is_default("fishing_key_delay"))

    def test_save_then_load(self):
        Timings(self.path, "windows").save({"fishing_key_delay": 0.35})
        reloaded = Timings(self.path, "windows")
        self.assertEqual(reloaded["fishing_key_delay"], 0.35)
        self.assertFalse(reloaded.is_default("fishing_key_delay"))
        self.assertEqual(reloaded["mining_enter_delay"], 0.4)

    def test_saved_file_is_json_and_keeps_every_name(self):
        table = Timings(self.path, "windows")
        table.save()
        written = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(written), set(timings.SPECS))
        self.assertEqual(written["keypress_gap"], 0.015)

    def test_save_of_one_timing_keeps_the_others(self):
        table = Timings(self.path, "windows")
        table.save({"mining_enter_delay": 0.5, "fishing_ok_presses": 4})
        table.save({"mining_enter_delay": 0.6})
        self.assertEqual(table["mining_enter_delay"], 0.6)
        self.assertEqual(table["fishing_ok_presses"], 4)

    def test_save_rejects_bad_values_and_writes_nothing(self):
        table = Timings(self.path, "windows")
        with self.assertRaises(TimingError):
            table.save({"mining_ok_presses": 999})
        self.assertFalse(self.path.exists())

    def test_partial_file_keeps_defaults_for_the_rest(self):
        self.path.write_text(json.dumps({"mining_enter_delay": 0.5}), encoding="utf-8")
        table = Timings(self.path, "windows")
        self.assertEqual(table["mining_enter_delay"], 0.5)
        self.assertEqual(table["fishing_ok_presses"], 6)

    def test_invalid_json_is_reported(self):
        self.path.write_text("{nope", encoding="utf-8")
        with self.assertRaises(TimingError):
            Timings(self.path, "windows")

    def test_non_object_json_is_reported(self):
        self.path.write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(TimingError):
            Timings(self.path, "windows")

    def test_overrides_beat_the_file(self):
        self.path.write_text(json.dumps({"fishing_key_delay": 0.5}), encoding="utf-8")
        table = Timings(self.path, "windows", {"fishing_key_delay": 0.1})
        self.assertEqual(table["fishing_key_delay"], 0.1)

    def test_unknown_timing_lookup_raises(self):
        table = Timings(self.path, "windows")
        with self.assertRaises(KeyError):
            table["nope"]
        self.assertIsNone(table.get("nope"))

    def test_assignment_checks_the_name_and_the_value(self):
        table = Timings(self.path, "windows")
        table["mining_enter_delay"] = "350ms"
        self.assertEqual(table["mining_enter_delay"], 0.35)

        with self.assertRaises(KeyError):
            table["nope"] = 1
        with self.assertRaises(TimingError):
            table["mining_enter_delay"] = "99s"

    def test_reload_if_changed_picks_up_an_edit(self):
        table = Timings(self.path, "windows")
        self.assertFalse(table.reload_if_changed())

        # Some filesystems have a coarse mtime, so make the change explicit.
        self.path.write_text(json.dumps({"mining_enter_delay": 0.6}), encoding="utf-8")
        import os

        os.utime(self.path, (1, 1))
        self.assertTrue(table.reload_if_changed())
        self.assertEqual(table["mining_enter_delay"], 0.6)
        self.assertFalse(table.reload_if_changed())

    def test_reload_if_changed_keeps_going_after_a_bad_edit(self):
        table = Timings(self.path, "windows")
        self.path.write_text("garbage", encoding="utf-8")
        import io
        import os
        from contextlib import redirect_stderr

        os.utime(self.path, (1, 1))
        with redirect_stderr(io.StringIO()) as warning:
            self.assertFalse(table.reload_if_changed())
        self.assertEqual(table["mining_enter_delay"], 0.4)
        self.assertIn("invalid JSON", warning.getvalue())

    def test_reset_restores_defaults_without_writing(self):
        table = Timings(self.path, "windows")
        table.save({"mining_enter_delay": 0.5})
        table.reset(["mining_enter_delay"])
        self.assertEqual(table["mining_enter_delay"], 0.4)
        self.assertEqual(Timings(self.path, "windows")["mining_enter_delay"], 0.5)

    def test_reset_rejects_unknown_names(self):
        table = Timings(self.path, "windows")
        with self.assertRaises(KeyError):
            table.reset(["nope"])

    def test_default_timings_ignore_the_file(self):
        table = timings.default_timings()
        self.assertIs(timings.default_timings(), table)
        self.assertIn(table["keypress_gap"], (0.015, 0.03))


class TestFormatValue(unittest.TestCase):
    def test_delays_are_shown_in_milliseconds(self):
        self.assertEqual(timings.format_value(timings.SPECS["fishing_ok_gap"], 0.01), "10")
        self.assertEqual(timings.format_value(timings.SPECS["mining_enter_delay"], 0.35), "350")

    def test_counts_have_no_unit(self):
        self.assertEqual(timings.format_value(timings.SPECS["mining_ok_presses"], 5), "5")


if __name__ == "__main__":
    unittest.main()
