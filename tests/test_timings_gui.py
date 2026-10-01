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

#: One Tk interpreter for the module. A second one, outliving a destroyed
#: first, makes Tk broadcast theme changes to an interpreter that has already
#: gone, and that prints to stderr in the middle of a test run where it reads
#: like a failure. Tests withdraw this and put it back up rather than making
#: their own.
_ROOT = None


def setUpModule():
    global _ROOT
    try:
        import tkinter

        _ROOT = tkinter.Tk()
    except Exception as error:  # no display, or no tkinter at all
        raise unittest.SkipTest(f"cannot open a Tk window here: {error}")


def tearDownModule():
    if _ROOT is not None:
        _ROOT.destroy()


class TestTimingsWindow(unittest.TestCase):
    def setUp(self):
        from timings_gui import TimingsWindow

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "timings.json"
        self.table = Timings(self.path, "windows")

        self.root = _ROOT
        for child in self.root.winfo_children():
            child.destroy()
        self.root.withdraw()
        self.window = TimingsWindow(self.root, self.table)

    def text(self, name):
        return self.window.entries[name][0].get()

    def set_text(self, name, value):
        self.window.entries[name][0].set(value)

    def test_delays_are_shown_in_milliseconds(self):
        self.assertEqual(self.text("fishing_key_delay"), "50ms")
        self.assertEqual(self.text("fishing_ok_gap"), "140ms")

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

    # -- the value boxes are always on screen ---------------------------

    # A description is a label in a grid cell, and a label in a grid is as
    # wide as its text, so the longest description decides the width of the
    # whole window. One long enough to ask for more pixels than the screen
    # has gives a window Tk refuses to map, and a window that is not mapped
    # does not draw its children: the editor opens, and the value boxes are
    # not in it. These two put the window on screen and look at the boxes,
    # which is what a person opening the editor would get.

    def lay_out(self, specs=None):
        """Put the window on screen and return the value boxes in it.

        ``specs`` replaces the timing table the window is built from, so a
        description far longer than any real one can be tried. They live in
        this class rather than one of their own because a second Tk()
        outliving another one's destroyed roots prints theme errors that
        read like failures.
        """
        from tkinter import ttk

        import timings_gui
        from timings import TIMINGS

        chosen = TIMINGS if specs is None else specs
        for child in self.root.winfo_children():
            child.destroy()

        if specs is None:
            timings_gui.TimingsWindow(self.root, self.table)
        else:
            with unittest.mock.patch.object(timings_gui, "TIMINGS", chosen):
                timings_gui.TimingsWindow(self.root, self.table)

        # setUp withdrew the window, and a withdrawn window lays nothing out.
        self.root.deiconify()
        self.root.update()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        entries = [
            widget
            for widget in descendants(self.root)
            if isinstance(widget, ttk.Entry)
        ]
        return entries, len(chosen)

    def assert_boxes_are_editable(self, entries, expected):
        self.assertEqual(len(entries), expected)
        for entry in entries:
            # Requested size, not mapped size: a window too wide for the
            # screen is never mapped at all, and asking one that never
            # renders whether it has mapped is a way of testing Tk's mood
            # instead of the editor. The width below is what decides that.
            self.assertGreater(
                entry.winfo_reqwidth(),
                1,
                "a value box was laid out with no width, so it cannot be "
                "typed into",
            )

    def test_every_timing_has_an_editable_value_box(self):
        entries, expected = self.lay_out()
        self.assert_boxes_are_editable(entries, expected)

    def test_a_description_longer_than_the_screen_does_not_hide_them(self):
        import dataclasses

        from timings import TIMINGS

        huge = dataclasses.replace(
            TIMINGS[0], description="compensation for the loop latency " * 400
        )
        entries, expected = self.lay_out((huge, *TIMINGS[1:]))

        # The symptom: the value boxes are gone, because the window asked for
        # more width than the screen has and Tk does not map a window that
        # does not fit. Checked before the boxes themselves, since that is
        # the order a person meets it in.
        self.assertLessEqual(
            self.root.winfo_reqwidth(),
            self.root.winfo_screenwidth(),
            "the window asks for more width than the screen has, so Tk will "
            "not map it and the value boxes disappear",
        )
        self.assert_boxes_are_editable(entries, expected)


if __name__ == "__main__":
    unittest.main()
