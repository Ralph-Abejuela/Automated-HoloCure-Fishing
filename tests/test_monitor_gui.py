"""Tests for the monitor window and the reporting the game loops do.

The window tests are skipped when there is no display, since Tk cannot
start without one. Run with: python -m unittest discover -s tests -t .

The loop tests drive the real fishing and mining loops against a fake
platform that hands out a made-up capture, so they prove what the window
would be shown without needing HoloCure open.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from math import floor
from pathlib import Path

import numpy as np

import monitor_gui

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def setUpModule():
    # imgproc reads the templates out of ./img, so run from the project root
    # no matter where the tests were started.
    os.chdir(ROOT)

    try:
        import tkinter

        root = tkinter.Tk()
    except Exception as error:  # no display, or no tkinter at all
        raise unittest.SkipTest(f"cannot open a Tk window here: {error}")
    root.destroy()


def fishing_capture(width: int, height: int) -> np.ndarray:
    """A capture with the space arrow sitting at the left of its search box."""
    from imgproc import templates

    image = np.zeros((height, width, 3), dtype=np.uint8)
    template = templates["space"]
    t_height, t_width = template.shape[:2]
    top = 10 - floor(t_height / 2)
    left = 103 + 10 - floor(t_width / 2)
    image[top : top + t_height, left : left + t_width] = template
    return image


def mining_capture(width: int, height: int) -> np.ndarray:
    """A capture with the red bar, and an 'ok' prompt waiting on it."""
    from imgproc import templates

    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[34, 20:40] = (0, 0, 255)  # the bar, in BGR red
    template = templates["ok"]
    image[0 : template.shape[0], 69 : 69 + template.shape[1]] = template
    return image


class FakePlatform:
    """Just enough platform for a loop to run without the game.

    ``capture`` is asked for an image of any size and answers with the
    region the loop asked for, so the loop can pretend to be reading a real
    window.
    """

    def __init__(self, capture, bounds=(0, 0, 640, 360)):
        from timings import Timings

        self.timings = Timings(read_file=False, platform="windows")
        self.keys = []
        self.capture = capture
        self.bounds = bounds

    def timing(self, name):
        return self.timings[name]

    def stopping(self):
        return False

    def config_file_path(self):
        return None

    def wait_until_application_handle(self):
        return None

    def get_holocure_bounds(self):
        return self.bounds

    def holocure_screenshot(self, roi):
        return self.capture(int(roi[2]), int(roi[3]))

    def press_key(self, key):
        self.keys.append(key)

    def offset(self, fish_count, speed_level=None):
        # The real arithmetic, so a loop running on this fake is answering
        # with the same window shift a real platform would.
        from platform_UNF import Platform

        return Platform.offset(self, fish_count, speed_level)


class LoopHarness(unittest.TestCase):
    """Run a real loop against a fake platform, then stop it."""

    def run_loop(self, loop, platform, telemetry, until=None, seconds=15.0):
        """Run ``loop`` until ``until(snapshot)`` is true, then stop it.

        Without ``until`` the loop is stopped as soon as it has reported
        something, so a test never waits for a game that will not arrive.
        """
        if until is None:
            until = lambda snapshot: snapshot["frame"].loop > 2

        thread = threading.Thread(
            target=loop, args=(platform, self.settings, telemetry), daemon=True
        )
        thread.start()
        deadline = time.monotonic() + seconds
        while thread.is_alive() and time.monotonic() < deadline:
            if until(telemetry.snapshot()):
                telemetry.stop()
                break
            time.sleep(0.01)
        thread.join(5)
        self.assertFalse(thread.is_alive(), f"{loop.__name__} did not stop")
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["error"], "", "the loop died")
        return snapshot


class TestFishingLoopReporting(LoopHarness):
    def setUp(self):
        from timings import Timings

        self.settings = Timings(read_file=False, platform="windows")
        for name in (
            "fishing_key_delay",
            "fishing_ok_gap",
            "fishing_loop_interval",
            "press_jitter",
            "keypress_gap",
        ):
            self.settings[name] = 0

    def test_the_loop_reports_every_template_it_looked_at(self):
        from holocure_fishing import fishing_mode
        from telemetry import Telemetry

        telemetry = Telemetry()
        platform = FakePlatform(fishing_capture)
        snapshot = self.run_loop(
            fishing_mode, platform, telemetry, until=lambda s: len(s["keypresses"]) >= 3
        )

        frame = snapshot["frame"]
        self.assertEqual(frame.mode, "fishing")
        self.assertEqual(frame.state, "stopped")
        self.assertGreater(frame.loop, 1)
        # the loop stops looking at arrows once one matches, so only the one
        # it pressed, and then the ok button
        self.assertEqual(
            [match.template for match in frame.matches], ["space", "ok"]
        )
        self.assertTrue(frame.matches[0].matched, "the space arrow should have matched")
        self.assertEqual(frame.matches[0].threshold, 1000)
        self.assertFalse(frame.matches[-1].matched)
        self.assertEqual(frame.scale, 1)
        self.assertEqual(frame.roi, (276, 242, 146, 52))
        self.assertEqual(frame.bounds, (0, 0, 640, 360))

    def test_a_matched_arrow_becomes_a_keypress_with_a_reason(self):
        from holocure_fishing import fishing_mode
        from telemetry import Telemetry

        telemetry = Telemetry()
        platform = FakePlatform(fishing_capture)
        snapshot = self.run_loop(
            fishing_mode, platform, telemetry, until=lambda s: len(s["keypresses"]) >= 3
        )

        keys = snapshot["keypresses"]
        self.assertGreaterEqual(len(keys), 3)
        self.assertEqual([press.key for press in keys[:3]], ["space"] * 3)
        self.assertIn("space", keys[0].reason)
        self.assertEqual(platform.keys[:3], ["space"] * 3)

    def test_the_frame_carries_the_capture_and_where_it_was_read(self):
        from holocure_fishing import fishing_mode
        from telemetry import Telemetry

        telemetry = Telemetry()
        platform = FakePlatform(fishing_capture)
        # Wait for the iterations themselves, not for a keypress: the stop
        # arrives between iterations, so a keypress can be seen with only one
        # iteration behind it and the count below would be a coin toss.
        snapshot = self.run_loop(
            fishing_mode,
            platform,
            telemetry,
            until=lambda s: len(s["durations"]) >= 3 and len(s["keypresses"]) >= 1,
        )

        frame = snapshot["frame"]
        # the note capture runs past the strip the note is searched in, to
        # carry the grade the game writes under the circle
        self.assertEqual(frame.image.shape, (52, 146, 3))
        # the arrow window it searched, and the ok window
        self.assertEqual(len(frame.rects), 2)
        # only the arrow that matched is marked
        self.assertEqual(len(frame.dots), 1)
        self.assertEqual(frame.dots[0].color, (0, 200, 255))
        self.assertGreaterEqual(frame.capture_ms, 0.0)
        self.assertGreater(len(snapshot["durations"]), 1)

    def test_the_loop_says_what_it_is_doing(self):
        from holocure_fishing import fishing_mode
        from telemetry import Telemetry

        telemetry = Telemetry()
        platform = FakePlatform(fishing_capture)
        running = []

        def until(snapshot):
            if snapshot["frame"].message.startswith("Arrow"):
                running.append(snapshot)
                return True
            return False

        self.run_loop(fishing_mode, platform, telemetry, until=until)
        self.assertIn("space", running[0]["frame"].message)
        self.assertIn("Keybinds", telemetry.snapshot()["log"][0].text)

    def test_the_keybinds_the_game_reports_are_shown(self):
        from holocure_fishing import fishing_mode
        from telemetry import Telemetry

        telemetry = Telemetry()
        platform = FakePlatform(fishing_capture)
        snapshot = self.run_loop(
            fishing_mode, platform, telemetry, until=lambda s: len(s["keypresses"]) >= 1
        )
        self.assertEqual(
            snapshot["frame"].keybinds,
            {"space": "space", "left": "a", "right": "d", "up": "w", "down": "s"},
        )

    def test_a_minimised_game_is_reported_instead_of_read(self):
        from holocure_fishing import fishing_mode
        from telemetry import STATE_WAITING, Telemetry

        telemetry = Telemetry()
        platform = FakePlatform(fishing_capture, bounds=(0, 0, 0, 0))
        waiting = []

        def until(snapshot):
            if snapshot["frame"].state == STATE_WAITING:
                waiting.append(snapshot)
                return True
            return False

        snapshot = self.run_loop(fishing_mode, platform, telemetry, until=until)
        self.assertEqual(snapshot["frame"].state, "stopped")
        self.assertIsNone(snapshot["frame"].image)
        self.assertEqual(platform.keys, [])
        self.assertIn("minimised", waiting[0]["frame"].message)


class TestMiningLoopReporting(LoopHarness):
    def setUp(self):
        from timings import Timings

        self.settings = Timings(read_file=False, platform="windows")
        for name in ("mining_enter_delay", "mining_ok_gap", "press_jitter", "keypress_gap"):
            self.settings[name] = 0

    def test_the_red_bar_becomes_a_pointer_scan_and_a_prompt_becomes_keys(self):
        from holocure_fishing import pick_axe_mode
        from telemetry import Telemetry

        telemetry = Telemetry()
        platform = FakePlatform(mining_capture)
        snapshot = self.run_loop(
            pick_axe_mode, platform, telemetry, until=lambda s: s["frame"].counter >= 1
        )

        frame = snapshot["frame"]
        self.assertEqual(frame.mode, "mining")
        self.assertEqual(frame.state, "stopped")
        self.assertEqual(frame.roi, (203, 251, 216, 44))
        # the bar, the strip it is scanned in, and the ok window
        self.assertEqual(len(frame.rects), 3)
        names = [match.template for match in frame.matches]
        self.assertIn("pointer", names)
        self.assertIn("ok", names)

    def test_dismissing_the_prompt_presses_enter_the_configured_number_of_times(self):
        from holocure_fishing import pick_axe_mode
        from telemetry import Telemetry

        telemetry = Telemetry()
        platform = FakePlatform(mining_capture)
        snapshot = self.run_loop(
            pick_axe_mode, platform, telemetry, until=lambda s: s["frame"].counter >= 1
        )

        first_round = snapshot["keypresses"][:5]
        self.assertEqual([press.key for press in first_round], ["enter"] * 5)
        self.assertIn("1 of 5", first_round[0].reason)
        self.assertGreaterEqual(snapshot["frame"].counter, 1)
        self.assertIn("Mining count: 1", [line.text for line in snapshot["log"]])


class TestRender(unittest.TestCase):
    def test_a_capture_becomes_a_ppm_tk_can_read(self):
        from monitor_gui import render
        from telemetry import Dot, Rect

        image = np.zeros((4, 6, 3), dtype=np.uint8)
        image[1, 2] = (10, 20, 30)
        data = render(
            image,
            [Rect(1, 1, 2, 2, (255, 0, 0))],
            [Dot(3, 2, (0, 255, 0))],
            zoom=3,
        )
        header, pixels = data.split(b"255\n", 1)
        self.assertEqual(header, b"P6\n18 12\n")
        self.assertEqual(len(pixels), 18 * 12 * 3)

        def at(x, y):
            start = (y * 18 + x) * 3
            return pixels[start : start + 3]

        # the red rectangle is drawn at 3,3; the dot marks 3,2 as a small box
        self.assertEqual(at(3, 3), b"\xff\x00\x00")
        self.assertEqual(at(9, 4), b"\x00\xff\x00")
        # a pixel nothing was drawn on keeps the capture's colour
        self.assertEqual(at(0, 0), b"\x00\x00\x00")
        self.assertEqual(at(9, 6), b"\x00\x00\x00")


class TestMonitorWindow(unittest.TestCase):
    def setUp(self):
        import tkinter

        from monitor_gui import MonitorWindow
        from telemetry import Telemetry
        from timings import TIMINGS, Timings

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "timings.json"

        self.root = tkinter.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

        self.settings = Timings(self.path, "windows", read_file=False)
        self.telemetry = Telemetry()
        self.telemetry.reset("fishing")
        self.telemetry.set_timings(self.settings.values, str(self.path))

        self.window = MonitorWindow(
            self.root, self.telemetry, self.settings, FakePlatform(fishing_capture)
        )
        self.addCleanup(self._cancel_refresh)
        self.TIMINGS = TIMINGS

    def _cancel_refresh(self):
        if self.window._job is not None:
            self.root.after_cancel(self.window._job)
            self.window._job = None

    def rows(self, tree):
        return [tree.item(item, "values") for item in tree.get_children()]

    def test_nothing_to_show_yet_leaves_every_table_empty(self):
        self.window.refresh()
        self.assertEqual(self.window.values["state"].get(), "starting")
        self.assertEqual(self.rows(self.window.match_tree), [])
        self.assertEqual(self.rows(self.window.key_tree), [])

    def test_the_status_panel_shows_what_the_loop_reported(self):
        self.telemetry.update(
            state="running",
            message="Arrow 'space' matched, pressed 'space'.",
            loop=1234,
            scale=2,
            bounds=(0, 0, 640, 720),
            roi=(552, 484, 266, 76),
            keybinds={"space": "space", "left": "a"},
            counter=7,
            capture_ms=1.5,
            match_ms=0.25,
            loop_ms=3.0,
            sleep_ms=7.0,
        )
        self.window.refresh()

        values = self.window.values
        self.assertEqual(values["state"].get(), "running")
        self.assertEqual(values["loops"].get(), "1,234")
        self.assertEqual(values["counter"].get(), "7")
        self.assertEqual(values["loop_ms"].get(), "3.00 ms")
        self.assertEqual(values["capture_ms"].get(), "1.50 ms")
        self.assertEqual(values["match_ms"].get(), "0.25 ms")
        self.assertEqual(values["sleep_ms"].get(), "7.00 ms")
        self.assertEqual(values["bounds"].get(), "0, 0  640 x 720")
        self.assertEqual(values["roi"].get(), "552, 484, 266, 76 at 2x")
        self.assertEqual(values["keybinds"].get(), "space=space, left=a")
        self.assertEqual(values["timings_file"].get(), str(self.path))
        self.assertIn("Arrow 'space' matched", self.window.message.get())

    def test_the_rate_comes_from_the_recent_iterations(self):
        self.telemetry.update(state="running", loop_ms=10.0)
        for _ in range(4):
            self.telemetry.loop_done(0.01)
        self.window.refresh()
        self.assertEqual(self.window.values["rate"].get(), "100.0 /s")

    # -- debug captures -------------------------------------------------

    def set_capture_folder(self):
        """Point the capture at a folder of this test's own.

        The real one holds frames off a real run, and a test that empties it
        to count what it wrote throws away the only copy of the very frames
        the chain reader is built from.
        """
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name) / "debug_captures"
        folder.mkdir()
        original = monitor_gui.CAPTURE_FOLDER
        self.addCleanup(setattr, monitor_gui, "CAPTURE_FOLDER", original)
        monitor_gui.CAPTURE_FOLDER = folder
        return folder

    def saved_captures(self):
        return sorted(path.name for path in monitor_gui.CAPTURE_FOLDER.glob("*.png"))

    def _clear_captures(self):
        for path in monitor_gui.CAPTURE_FOLDER.glob("*.png"):
            path.unlink()

    def test_nothing_is_captured_until_it_is_asked_for(self):
        self.set_capture_folder()

        self.telemetry.key("space", "rhythm arrow 'space' matched")
        self.window.refresh()
        self.assertEqual(self.saved_captures(), [], "off by default")

    def test_each_press_saves_a_pair_named_after_that_press(self):
        self.set_capture_folder()

        self.window.capture_on_press.set(True)
        self.window.set_capture_state()
        self.assertIn("capturing", self.window.capture_status.get())

        self.telemetry.key("space", "rhythm arrow 'space' matched")
        self.window.refresh()
        self.window.refresh()  # the follow-up frame

        self.telemetry.key("enter", "dismissing the prompt 1 of 3")
        self.window.refresh()
        self.window.refresh()

        self.assertEqual(
            self.saved_captures(),
            [
                "0000_space_a.png",
                "0001_space_b.png",
                "0002_enter_a.png",
                "0003_enter_b.png",
            ],
        )

    def test_the_capture_region_is_scaled_like_the_bot_ones(self):
        import cv2

        self.set_capture_folder()

        self.window.capture_on_press.set(True)
        self.window.capture_region.set("Full window")
        self.telemetry.update(state="running", mode="fishing", scale=2, loop=1)
        self.telemetry.key("space", "rhythm arrow 'space' matched")
        self.window.refresh()

        frame = cv2.imread(str(monitor_gui.CAPTURE_FOLDER / self.saved_captures()[0]))
        # the full window is 640x360 in base coordinates, doubled on a 720p one
        self.assertEqual((frame.shape[1], frame.shape[0]), (1280, 720))

    def test_a_capture_that_fails_says_so_rather_than_raising(self):
        self.set_capture_folder()

        self.window.capture_on_press.set(True)

        def broken(roi):
            raise OSError("the window went away")

        self.window.platform.holocure_screenshot = broken
        self.telemetry.key("space", "rhythm arrow 'space' matched")
        self.window.refresh()  # must not raise
        self.assertIn("capture failed", self.window.capture_status.get())
        self.assertEqual(self.saved_captures(), [])

    def test_matches_are_listed_with_their_scores_and_threshold(self):
        from telemetry import Match

        self.telemetry.update(
            state="running",
            loop=9,
            matches=[
                Match("space", 812.0, 1000, True, (4, 5)),
                Match("left", 41000.0, 1000, False, (0, 0)),
            ],
        )
        self.window.refresh()

        rows = self.rows(self.window.match_tree)
        self.assertEqual(rows[0][0], "space")
        self.assertEqual(rows[0][1], "812")
        self.assertEqual(rows[0][2], "1,000")
        self.assertEqual(rows[0][3], "match")
        self.assertEqual(rows[0][4], "4, 5")
        self.assertEqual(rows[1][3], "-")

    def test_a_matched_row_is_marked_so_it_stands_out(self):
        from telemetry import Match

        self.telemetry.update(
            state="running", loop=3, matches=[Match("ok", 1.0, 60_000_000, True)]
        )
        self.window.refresh()
        item = self.window.match_tree.get_children()[0]
        self.assertEqual(self.window.match_tree.item(item, "tags"), ("matched",))

    def test_keypresses_are_appended_not_redrawn(self):
        self.telemetry.key("space", "rhythm arrow 'space' matched")
        self.window.refresh()
        self.assertEqual(len(self.rows(self.window.key_tree)), 1)

        self.telemetry.key("enter", "dismissing the prompt 1 of 6")
        self.window.refresh()
        rows = self.rows(self.window.key_tree)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][2], "enter")

    def test_the_activity_log_lines_are_shown_once_each(self):
        self.telemetry.log("Keybinds: {'space': 'space'}")
        self.window.refresh()
        self.window.refresh()
        text = self.window.log_text.get("1.0", "end")
        self.assertEqual(text.count("Keybinds"), 1)

        self.telemetry.log("Fishing count: 1", level="good")
        self.window.refresh()
        self.assertIn("Fishing count: 1", self.window.log_text.get("1.0", "end"))

    def test_clearing_the_log_empties_the_view(self):
        self.telemetry.log("something happened")
        self.window.refresh()
        self.window.clear_log()
        self.window.refresh()
        self.assertEqual(self.window.log_text.get("1.0", "end").strip(), "")

    def test_the_timings_table_shows_what_the_loop_is_using(self):
        self.settings["mining_enter_delay"] = 0.35
        self.telemetry.set_timings(self.settings.values, str(self.path))
        self.window.refresh()

        tree = self.window.timing_tree
        self.assertEqual(len(tree.get_children()), len(self.TIMINGS))
        changed = tree.item("mining_enter_delay", "values")
        self.assertEqual(changed, ("mining_enter_delay", "350ms", "400ms", "file"))
        untouched = tree.item("mining_ok_presses", "values")
        self.assertEqual(untouched, ("mining_ok_presses", "5", "5", "default"))

    def test_the_capture_is_drawn_and_can_be_zoomed(self):
        self.telemetry.update(
            state="running", loop=2, image=fishing_capture(133, 38)
        )
        self.window.refresh()
        photo = self.window._photo
        self.assertIsNotNone(photo)
        auto_width = photo.width()

        self.window.zoom.set("4x")
        self.window._redraw_image()
        self.assertEqual(self.window._photo.width(), 133 * 4)
        self.assertGreaterEqual(self.window.canvas.winfo_reqwidth(), 133 * 4)
        self.assertGreater(auto_width, 0)

    def test_the_graph_is_drawn_from_the_iteration_times(self):
        self.telemetry.update(state="running", loop_ms=12.0)
        for value in (0.01, 0.02, 0.03, 0.005):
            self.telemetry.loop_done(value)
        self.window.refresh()
        items = self.window.graph.find_all()
        self.assertTrue(items, "the graph should have drawn something")

    def test_the_graph_says_so_when_nothing_has_run_yet(self):
        self.window.refresh()
        texts = [
            self.window.graph.itemcget(item, "text")
            for item in self.window.graph.find_all()
            if self.window.graph.type(item) == "text"
        ]
        self.assertIn("No iterations yet", texts)

    def test_the_run_buttons_lock_while_a_mode_is_running(self):
        self.window._set_running(True)
        self.assertTrue(self.window.fish_button.instate(["disabled"]))
        self.assertTrue(self.window.stop_button.instate(["!disabled"]))
        self.window._set_running(False)
        self.assertTrue(self.window.fish_button.instate(["!disabled"]))
        self.assertTrue(self.window.stop_button.instate(["disabled"]))

    def test_turning_off_keypress_logging_is_passed_to_the_loops(self):
        self.window.log_keys.set(False)
        self.window.set_log_keypresses()
        self.assertFalse(self.telemetry.log_keypresses)


if __name__ == "__main__":
    unittest.main()
