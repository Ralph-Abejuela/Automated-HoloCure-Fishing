"""Tests for the timings editor window.

Skipped when there is no display, since Tk cannot start without one.
Run with: python -m unittest discover -s tests -t .
"""

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timings import Timings


def setUpModule():
    try:
        import tkinter

        root = tkinter.Tk()
    except Exception as error:  # no display, or no tkinter at all
        raise unittest.SkipTest(f"cannot open a Tk window here: {error}")
    root.destroy()


class TestTimingsWindow(unittest.TestCase):
    def setUp(self):
        import tkinter

        from timings_gui import TimingsWindow

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "timings.json"
        self.table = Timings(self.path, "windows")

        self.root = tkinter.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.window = TimingsWindow(self.root, self.table)

    def text(self, name):
        return self.window.entries[name][0].get()

    def set_text(self, name, value):
        self.window.entries[name][0].set(value)

    def test_delays_are_shown_in_milliseconds(self):
        self.assertEqual(self.text("fishing_key_delay"), "50ms")
        self.assertEqual(self.text("fishing_ok_gap"), "10ms")

    def test_counts_are_shown_without_a_unit(self):
        self.assertEqual(self.text("mining_ok_presses"), "5")

    def test_typing_a_value_saves_it_in_seconds(self):
        self.set_text("mining_enter_delay", "350ms")
        self.window.save()
        self.assertEqual(Timings(self.path, "windows")["mining_enter_delay"], 0.35)

    def test_a_unit_typed_in_by_hand_is_accepted(self):
        self.set_text("mining_enter_delay", "350 ms")
        self.window.save()
        self.assertEqual(Timings(self.path, "windows")["mining_enter_delay"], 0.35)

    def test_saving_one_value_keeps_the_others(self):
        self.set_text("fishing_ok_presses", "4")
        self.window.save()
        self.set_text("mining_enter_delay", "350ms")
        self.window.save()
        reloaded = Timings(self.path, "windows")
        self.assertEqual(reloaded["fishing_ok_presses"], 4)
        self.assertEqual(reloaded["mining_enter_delay"], 0.35)

    def test_all_defaults_only_fills_in_until_save(self):
        self.set_text("mining_enter_delay", "350ms")
        self.window.save()

        self.window.fill_defaults()
        self.assertEqual(self.text("mining_enter_delay"), "400ms")
        self.assertEqual(Timings(self.path, "windows")["mining_enter_delay"], 0.35)

        self.window.save()
        self.assertEqual(Timings(self.path, "windows")["mining_enter_delay"], 0.4)

    def test_revert_reloads_the_file(self):
        self.set_text("mining_enter_delay", "350ms")
        self.window.save()
        self.set_text("mining_enter_delay", "999ms")
        self.window.reload_fields()
        self.assertEqual(self.text("mining_enter_delay"), "350ms")

    def test_a_value_out_of_range_does_not_reach_the_file(self):
        before = self.table.values
        self.set_text("mining_enter_delay", "9999ms")
        with unittest.mock.patch("timings_gui.messagebox.showerror"):
            self.window.save()
        self.assertEqual(self.table.values, before)

    def test_garbage_does_not_reach_the_file(self):
        before = self.table.values
        self.set_text("mining_ok_presses", "abc")
        with unittest.mock.patch("timings_gui.messagebox.showerror"):
            self.window.save()
        self.assertEqual(self.table.values, before)


if __name__ == "__main__":
    unittest.main()
