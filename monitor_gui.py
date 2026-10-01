"""A window that shows what the fishing and mining loops are doing, live.

Run 'python monitor_gui.py', or 'python holocure_fishing.py --gui' to get
the same window from the program that owns the game loops.

The loops run in a worker thread, so the window keeps repainting while the
game runs. Every iteration the loop hands over what it did through
:mod:`telemetry` - the pixels it captured, the templates it matched, the
keys it sent, how long each part took - and this window draws it a few
times a second:

  * the live capture region, with every searched window drawn on it and a
    dot on the best match of each template
  * each template match of the last iteration: its score, the threshold it
    has to stay under, and whether it was used
  * every key sent to the game, and what asked for it
  * the timings in use, where they came from, and the keybinds the game is
    reading
  * the length of each iteration, as a number and as a graph

Timings are edited in the existing editor window; a game that is already
running picks a saved change up within a second, and this window shows the
new values as soon as it does.
"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import ttk
from typing import Optional

import cv2
import numpy as np

from telemetry import STATE_ERROR, Telemetry
from timings import TIMINGS, Timings, format_value

#: How often the window redraws itself, in seconds.
REFRESH = 0.1

#: Rows kept in the tables, so a long run cannot grow the window forever.
MATCH_ROWS = 24
KEY_ROWS = 400
LOG_LINES = 400

#: How long a close waits for the worker thread before giving up on it.
SHUTDOWN_GRACE = 5.0

#: Debug capture regions, in the same 360p base coordinates the loops use,
#: so what is saved lines up with what the bot is looking at.
CAPTURE_REGIONS = {
    "Note area": (276, 242, 133, 38),
    "Bottom third": (0, 240, 640, 120),
    "Bottom half": (0, 180, 640, 180),
    "Full window": (0, 0, 640, 360),
}

#: Where the debug captures go, next to this script.
CAPTURE_FOLDER = Path(__file__).resolve().parent / "debug_captures"

MONITOR_BACKGROUND = "#141418"
COLOUR_MATCH = "#3ddc84"
COLOUR_MISS = "#888888"
COLOUR_ERROR = "#ff6b6b"
COLOUR_GOOD = "#7ee787"
LEVEL_COLOURS = {"error": COLOUR_ERROR, "good": COLOUR_GOOD}


def bgr(colour) -> tuple:
    """Turn the RGB a :class:`telemetry.Rect` carries into OpenCV's BGR."""
    return (colour[2], colour[1], colour[0])


def render(image: np.ndarray, rects, dots, zoom: int) -> bytes:
    """Scale the capture up, draw the annotations, and return PPM bytes.

    Tk reads PPM directly, which saves pulling in Pillow just to show a
    133 by 38 strip of pixels.
    """
    scaled = np.repeat(np.repeat(image, zoom, axis=0), zoom, axis=1)
    for rect in rects:
        cv2.rectangle(
            scaled,
            (rect.x * zoom, rect.y * zoom),
            ((rect.x + rect.width) * zoom - 1, (rect.y + rect.height) * zoom - 1),
            bgr(rect.color),
            1,
        )
    for dot in dots:
        cv2.rectangle(
            scaled,
            (dot.x * zoom - 2, dot.y * zoom - 2),
            (dot.x * zoom + 2, dot.y * zoom + 2),
            bgr(dot.color),
            1,
        )
    rgb = cv2.cvtColor(scaled, cv2.COLOR_BGR2RGB)
    return b"P6\n%d %d\n255\n" % (rgb.shape[1], rgb.shape[0]) + rgb.tobytes()


class MonitorWindow:
    """The window: a monitor image, the tables behind it, and the controls.

    Everything is redrawn from :meth:`telemetry.Telemetry.snapshot`, which
    the loop thread fills in; the window itself never touches a loop.
    """

    def __init__(
        self,
        master: tk.Tk,
        telemetry: Telemetry,
        settings: Timings,
        platform,
        refresh: float = REFRESH,
    ):
        self.master = master
        self.telemetry = telemetry
        self.settings = settings
        self.platform = platform
        self.refresh_interval = refresh

        self._thread: Optional[threading.Thread] = None
        self._closing = False
        self._closing_since = 0.0
        self._job = None
        # what the tables were last filled from, so a redraw only does work
        # when the loop has actually produced something new
        self._shown_loop = -1
        self._shown_timings = None
        self._next_keypress = 0
        self._next_log = 0
        self._keys_generation = None
        self._log_generation = None
        self._photo = None
        # debug capture state: see _build_debug_tools
        self._capture_seq = 0
        self._burst = 0
        self._last_scale = 1
        self._newest_press = None

        master.title("HoloCure monitor")
        master.minsize(940, 620)

        self._build_header()
        self._build_toolbar()
        self._build_body()
        self._build_status()

        master.protocol("WM_DELETE_WINDOW", self.close)
        self._schedule()

    # -- building -------------------------------------------------------

    def _build_header(self) -> None:
        header = ttk.Frame(self.master, padding=(12, 10, 12, 0))
        header.pack(fill="x")
        ttk.Label(header, text="HoloCure monitor", font=("TkDefaultFont", 13, "bold")).pack(
            anchor="w"
        )
        self.message = tk.StringVar(value="Choose a mode to start.")
        ttk.Label(header, textvariable=self.message).pack(anchor="w")

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.master, padding=(12, 6))
        bar.pack(fill="x")

        self.fish_button = ttk.Button(bar, text="Fishing", command=lambda: self.start("fishing"))
        self.mine_button = ttk.Button(bar, text="Mining", command=lambda: self.start("mining"))
        self.stop_button = ttk.Button(bar, text="Stop", command=self.stop, state="disabled")
        for button in (self.fish_button, self.mine_button):
            button.pack(side="left")
        self.stop_button.pack(side="left", padx=6)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="Edit timings...", command=self.open_timings_editor).pack(
            side="left"
        )
        ttk.Button(bar, text="Clear log", command=self.clear_log).pack(side="left", padx=6)
        self.log_keys = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bar,
            text="Log keypresses",
            variable=self.log_keys,
            command=self.set_log_keypresses,
        ).pack(side="left")
        self._build_debug_tools(bar)

    def _build_debug_tools(self, bar) -> None:
        """Grabs a frame every time the loop presses something.

        The keypress log already knows when the bot pressed and why, so the
        only thing missing to judge a press is what the game thought of it.
        The grade it shows afterwards lives on screen for a moment, so this
        saves the frames either side of the press and lets them be read
        later, against the log.

        Off by default, and self contained: nothing here changes what the
        loop does, and dropping the branch loses all of it.
        """
        debug = ttk.LabelFrame(bar, text="Capture", padding=(6, 2))
        debug.pack(side="left", padx=(12, 0))

        self.capture_on_press = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            debug,
            text="Save frames on keypress",
            variable=self.capture_on_press,
            command=self.set_capture_state,
        ).pack(side="left")

        ttk.Label(debug, text="Region").pack(side="left", padx=(8, 0))
        self.capture_region = tk.StringVar(value="Bottom half")
        chooser = ttk.Combobox(
            debug,
            textvariable=self.capture_region,
            values=tuple(CAPTURE_REGIONS),
            state="readonly",
            width=13,
        )
        chooser.pack(side="left", padx=4)

        ttk.Button(debug, text="Save one", command=self.capture_now).pack(side="left")
        self.capture_status = tk.StringVar(value=CAPTURE_FOLDER.name)
        ttk.Label(debug, textvariable=self.capture_status, foreground="#666666").pack(
            side="left", padx=(8, 0)
        )

    def set_capture_state(self) -> None:
        """Note whether captures are wanted, and say where they land."""
        self._burst = 0
        if self.capture_on_press.get():
            self.capture_status.set(f"capturing to {CAPTURE_FOLDER.name}/")
        else:
            self.capture_status.set(CAPTURE_FOLDER.name)

    def _capture(self, label: str) -> Optional[Path]:
        """Save one frame of the chosen region, and say so on failure."""
        base = CAPTURE_REGIONS[self.capture_region.get()]
        scale = round(self._last_scale or 1)
        roi = tuple(int(value) for value in np.multiply(scale, base))
        try:
            frame = self.platform.holocure_screenshot(roi)
        except Exception as error:  # the game closing mid-capture is normal
            self.capture_status.set(f"capture failed: {error}")
            return None
        if frame is None:
            self.capture_status.set("capture came back empty")
            return None
        CAPTURE_FOLDER.mkdir(exist_ok=True)
        path = CAPTURE_FOLDER / f"{self._capture_seq:04d}_{label}.png"
        self._capture_seq += 1
        cv2.imwrite(str(path), frame)
        return path

    def capture_now(self) -> None:
        path = self._capture("manual")
        self.capture_status.set(
            f"saved {path.name}" if path else "capture failed"
        )

    def _build_body(self) -> None:
        body = ttk.Panedwindow(self.master, orient="horizontal")
        body.pack(fill="both", expand=True, padx=12, pady=6)

        left = ttk.Frame(body, padding=0)
        body.add(left, weight=3)

        ttk.Label(left, text="Capture region", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w"
        )
        self.canvas = tk.Canvas(
            left, background=MONITOR_BACKGROUND, highlightthickness=1, borderwidth=0
        )
        self.canvas.pack(fill="both", expand=True, pady=(4, 4))
        # centred, so a narrow capture does not sit in a corner of a wide box
        self._image_item = self.canvas.create_image(0, 0, anchor="center")
        self._hint_item = self.canvas.create_text(
            0,
            0,
            text="Press Fishing or Mining to start.\nThe capture region appears here.",
            fill="#666666",
            justify="center",
        )

        caption = ttk.Frame(left)
        caption.pack(fill="x")
        self.zoom = tk.StringVar(value="auto")
        ttk.Label(caption, text="Zoom").pack(side="left")
        chooser = ttk.Combobox(
            caption,
            textvariable=self.zoom,
            values=("auto", "1x", "2x", "3x", "4x", "5x", "6x"),
            state="readonly",
            width=6,
        )
        chooser.pack(side="left", padx=6)
        chooser.bind("<<ComboboxSelected>>", lambda _event: self._redraw_image())
        self.legend_text = tk.StringVar(value="")
        ttk.Label(caption, textvariable=self.legend_text, foreground="#666666").pack(
            side="left"
        )

        right = ttk.Frame(body, padding=(12, 0, 0, 0))
        body.add(right, weight=2)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        self._build_stats_tab()
        self._build_matches_tab()
        self._build_keys_tab()
        self._build_timings_tab()
        self._build_log_tab()

    def _build_stats_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(8, 8))
        self.tabs.add(tab, text="Status")
        self.values = {}
        rows = (
            ("state", "State"),
            ("mode", "Mode"),
            ("loops", "Iterations"),
            ("rate", "Rate"),
            ("loop_ms", "Loop time"),
            ("capture_ms", "Capture time"),
            ("match_ms", "Matching time"),
            ("sleep_ms", "Sleeping"),
            ("press_gap", "Press cadence"),
            ("offset", "Note offset"),
            ("counter", "Fished / mined"),
            ("bounds", "HoloCure window"),
            ("roi", "Captured region"),
            ("scale", "Scale"),
            ("keybinds", "Keybinds"),
            ("timings_file", "Timings from"),
        )
        for row, (name, title) in enumerate(rows):
            ttk.Label(tab, text=title, foreground="#666666").grid(
                row=row, column=0, sticky="nw", pady=2
            )
            variable = tk.StringVar(value="-")
            ttk.Label(tab, textvariable=variable, wraplength=260).grid(
                row=row, column=1, sticky="w", padx=(12, 0), pady=2
            )
            self.values[name] = variable

    def _build_matches_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(8, 8))
        self.tabs.add(tab, text="Matches")
        ttk.Label(
            tab,
            text="Template scores from the last iteration. TM_SQDIFF: lower is better, "
            "and a match has to stay under the threshold.",
            foreground="#666666",
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        columns = ("template", "score", "threshold", "result", "at")
        self.match_tree = ttk.Treeview(tab, columns=columns, show="headings", height=10)
        for column, title, width, anchor in (
            ("template", "Template", 80, "w"),
            ("score", "Score", 100, "e"),
            ("threshold", "Threshold", 100, "e"),
            ("result", "Result", 60, "e"),
            ("at", "Found at", 70, "e"),
        ):
            self.match_tree.heading(column, text=title)
            self.match_tree.column(column, width=width, anchor=anchor)
        self.match_tree.tag_configure("matched", foreground=COLOUR_MATCH)
        self.match_tree.tag_configure("missed", foreground=COLOUR_MISS)
        self.match_tree.pack(fill="both", expand=True)

    def _build_keys_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(8, 8))
        self.tabs.add(tab, text="Keypresses")
        self.key_tree = ttk.Treeview(
            tab, columns=("time", "loop", "key", "why"), show="headings", height=10
        )
        for column, title, width, anchor in (
            ("time", "Time", 80, "w"),
            ("loop", "Loop", 60, "e"),
            ("key", "Key", 60, "w"),
            ("why", "What asked for it", 220, "w"),
        ):
            self.key_tree.heading(column, text=title)
            self.key_tree.column(column, width=width, anchor=anchor)
        self.key_tree.tag_configure("recent", foreground=COLOUR_GOOD)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.key_tree.yview)
        self.key_tree.configure(yscrollcommand=scrollbar.set)
        self.key_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")

    def _build_timings_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(8, 8))
        self.tabs.add(tab, text="Timings")
        ttk.Label(
            tab,
            text="The table the running loops use. Edit it in the editor window and "
            "the game picks the change up within a second.",
            foreground="#666666",
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        columns = ("name", "value", "default", "source")
        self.timing_tree = ttk.Treeview(tab, columns=columns, show="headings", height=10)
        for column, title, width, anchor in (
            ("name", "Timing", 140, "w"),
            ("value", "In use", 60, "e"),
            ("default", "Default", 60, "e"),
            ("source", "From", 70, "w"),
        ):
            self.timing_tree.heading(column, text=title)
            self.timing_tree.column(column, width=width, anchor=anchor)
        self.timing_tree.tag_configure("changed", foreground=COLOUR_GOOD)
        self.timing_tree.pack(fill="both", expand=True)

    def _build_log_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(8, 8))
        self.tabs.add(tab, text="Activity log")
        self.log_text = tk.Text(tab, wrap="word", height=10, state="disabled")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")
        for level, colour in LEVEL_COLOURS.items():
            self.log_text.tag_configure(level, foreground=colour)
        self.log_text.tag_configure("stamp", foreground="#666666")

    def _build_status(self) -> None:
        bar = ttk.Frame(self.master, padding=(12, 0, 12, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Loop time, last iterations").pack(anchor="w")
        self.canvas.bind("<Configure>", lambda _event: self._centre_image())
        self.graph = tk.Canvas(
            bar, height=64, background=MONITOR_BACKGROUND, highlightthickness=0
        )
        self.graph.pack(fill="x", pady=(2, 0))
        self.graph.bind("<Configure>", lambda _event: self._redraw_graph())
        self.footer = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.footer, foreground="#666666").pack(anchor="w")

    # -- running a mode -------------------------------------------------

    def start(self, mode: str) -> None:
        """Run ``mode`` in a worker thread, after stopping anything running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, args=(mode,), name=f"holocure-{mode}", daemon=True
        )
        self._shown_loop = -1
        self._next_keypress = 0
        self._next_log = 0
        self._keys_generation = None
        self._log_generation = None
        self._set_running(True)
        self._thread.start()

    def _run(self, mode: str) -> None:
        """The worker: one game loop, reporting until it is told to stop."""
        # Imported here so the window itself opens without loading the
        # template images, and so the import happens off the Tk thread.
        from holocure_fishing import fishing_mode, pick_axe_mode

        telemetry = self.telemetry
        telemetry.reset(mode)
        try:
            run = fishing_mode if mode == "fishing" else pick_axe_mode
            run(self.platform, self.settings, telemetry)
        except Exception:
            details = traceback.format_exc()
            telemetry.log(details, level="error")
            telemetry.fail(details.strip().splitlines()[-1])
        finally:
            telemetry.finish()

    def stop(self) -> None:
        """Ask the running loop to finish after its current iteration."""
        self.telemetry.stop()
        self.message.set("Stopping...")
        self.stop_button.configure(state="disabled")

    def close(self) -> None:
        """Stop the loop if one is running, then close when it is gone."""
        if self._thread is not None and self._thread.is_alive():
            self.telemetry.stop()
            self._closing = True
            self._closing_since = time.monotonic()
            self.message.set("Waiting for the game loop to finish...")
            return
        self._finish_close()

    def _finish_close(self) -> None:
        self._closing = False
        if self._job is not None:
            self.master.after_cancel(self._job)
            self._job = None
        self.master.destroy()

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.fish_button.configure(state=state)
        self.mine_button.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    def set_log_keypresses(self) -> None:
        self.telemetry.log_keypresses = self.log_keys.get()

    def clear_log(self) -> None:
        self.telemetry.clear_log()

    def open_timings_editor(self) -> None:
        """Open the timings editor on the same file, in its own window."""
        from tkinter import messagebox

        from timings import TimingError
        from timings_gui import TimingsWindow

        top = tk.Toplevel(self.master)
        try:
            table = Timings(path=self.settings.path, platform=self.settings.platform)
        except TimingError as error:
            messagebox.showerror(
                "Cannot read timings", str(error), parent=top
            )
            table = Timings(
                path=self.settings.path, platform=self.settings.platform, read_file=False
            )
        TimingsWindow(top, table)

    # -- redrawing ------------------------------------------------------

    def _schedule(self) -> None:
        self._job = self.master.after(int(self.refresh_interval * 1000), self.refresh)

    def refresh(self) -> None:
        """Read one snapshot and put everything on screen that changed."""
        if self._closing:
            alive = self._thread is not None and self._thread.is_alive()
            if not alive or time.monotonic() - self._closing_since > SHUTDOWN_GRACE:
                if alive:
                    self.message.set("The game loop did not stop; closing anyway.")
                self._finish_close()
                return

        snapshot = self.telemetry.snapshot()
        frame = snapshot["frame"]
        self._refresh_stats(frame, snapshot)
        self._refresh_image(frame)
        self._debug_after_refresh(frame, snapshot)
        self._refresh_graph(snapshot["durations"])
        self._refresh_matches(frame)
        self._refresh_keypresses(snapshot)
        self._refresh_log(snapshot)
        self._refresh_timings(snapshot)

        if self._thread is not None and not self._thread.is_alive():
            self._set_running(False)
        if frame.state == STATE_ERROR:
            self._set_running(False)

        self._schedule()

    def _debug_after_refresh(self, frame, snapshot: dict) -> None:
        """If capturing is on, save a frame or two for each new keypress.

        The keypress list is the same one the Keypresses tab is built from,
        so a capture and its row always agree on what was pressed and why.
        Two frames per press, one on the refresh that saw the press and one
        on the next, because the grade the game shows arrives just after the
        key goes down.
        """
        if not self.capture_on_press.get():
            return
        self._last_scale = frame.scale or 1
        press = snapshot["keypresses"][-1] if snapshot["keypresses"] else None
        if press is None:
            return
        if press is not self._newest_press:
            # a new press, so start its pair
            self._newest_press = press
            self._burst = 1
            self._capture_for_press(press)
        elif self._burst == 1:
            # same press as last time, so this is its follow-up
            self._burst = 2
            self._capture_for_press(press)

    def _capture_for_press(self, press) -> None:
        label = str(press.key).replace("/", "_")[:12] or "key"
        self._capture(f"{label}_{'a' if self._burst == 1 else 'b'}")

    def _refresh_stats(self, frame, snapshot: dict) -> None:
        durations = snapshot["durations"]
        recent = durations[-30:]
        rate = f"{1 / (sum(recent) / len(recent)):.1f} /s" if recent else "-"
        bounds = frame.bounds
        window_text = (
            f"{bounds[0]}, {bounds[1]}  {bounds[2]} x {bounds[3]}" if bounds else "-"
        )
        roi = frame.roi
        roi_text = ", ".join(str(value) for value in roi) if roi else "-"
        timings = snapshot["timings"]

        self.values["state"].set(frame.state)
        self.values["mode"].set(frame.mode or "-")
        self.values["loops"].set(f"{frame.loop:,}")
        self.values["rate"].set(rate)
        self.values["loop_ms"].set(f"{frame.loop_ms:.2f} ms")
        self.values["capture_ms"].set(f"{frame.capture_ms:.2f} ms")
        self.values["match_ms"].set(f"{frame.match_ms:.2f} ms")
        self.values["sleep_ms"].set(f"{frame.sleep_ms:.2f} ms")
        self.values["press_gap"].set(self._press_cadence(snapshot))
        self.values["offset"].set(self._offset_text(frame))
        self.values["counter"].set(str(frame.counter))
        self.values["bounds"].set(window_text)
        self.values["roi"].set(f"{roi_text} at {frame.scale}x")
        self.values["scale"].set(f"{frame.scale}x (window is {frame.scale * 360}px tall equivalent)")
        self.values["keybinds"].set(
            ", ".join(f"{name}={key}" for name, key in frame.keybinds.items()) or "-"
        )
        self.values["timings_file"].set(snapshot["timings_path"] or "-")
        self.message.set(frame.message)

        slowest = max(durations) * 1000 if durations else 0
        self.footer.set(
            f"{len(timings)} timings in use. "
            f"Slowest of the last {len(durations)} iterations: {slowest:.2f} ms."
        )

    def _press_cadence(self, snapshot: dict) -> str:
        """How far apart the last two presses were, and how stale they are.

        The gap is what press_jitter is there to spread out: a run of
        identical gaps means every press landed at exactly the same point in
        the note's travel, and one sitting on keypress_gap plus
        fishing_key_delay means the bot is as fast as the settings allow and
        would fall behind on a faster chain.
        """
        presses = snapshot["keypresses"]
        if not presses:
            return "no presses yet"
        latest = presses[-1]
        age = (time.time() - latest.at) * 1000
        if len(presses) == 1:
            return f"one press, {latest.key!r}, {age:.0f} ms ago"
        gap = (latest.at - presses[-2].at) * 1000
        jitter = snapshot["timings"].get("press_jitter")
        jitter_text = "" if jitter is None else f", {jitter * 1000:.0f} ms jitter on"
        return (
            f"{gap:.1f} ms between the last two{jitter_text}, "
            f"{age:.0f} ms since {latest.key!r}"
        )

    def _offset_text(self, frame) -> str:
        """The note search window's shift, which is what offset() decided."""
        if not frame.offset:
            return "0 px (start of a chain)"
        return f"{frame.offset} px left, at chain {frame.counter}"

    def _zoom_for(self, width: int, height: int) -> int:
        """How many times to blow the capture up, given the canvas size."""
        chosen = self.zoom.get()
        if chosen != "auto":
            return int(chosen.rstrip("x"))
        available_width = max(self.canvas.winfo_width(), 320)
        available_height = max(self.canvas.winfo_height(), 140)
        return max(
            1,
            min(
                6,
                available_width // max(width, 1),
                available_height // max(height, 1),
            ),
        )

    def _redraw_image(self) -> None:
        frame = self.telemetry.snapshot()["frame"]
        self._refresh_image(frame)

    def _refresh_image(self, frame) -> None:
        if frame.image is None:
            return
        height, width = frame.image.shape[:2]
        zoom = self._zoom_for(width, height)
        try:
            self._photo = tk.PhotoImage(
                data=render(frame.image, frame.rects, frame.dots, zoom)
            )
        except tk.TclError:
            return
        # the requested size is a minimum, so the box still fills the window
        self.canvas.configure(width=self._photo.width(), height=self._photo.height())
        self.canvas.itemconfigure(self._image_item, image=self._photo)
        self.canvas.itemconfigure(self._hint_item, state="hidden")
        self._centre_image()
        self.legend_text.set(f"{width} x {height} px, drawn {zoom}x")

    def _centre_image(self) -> None:
        """Keep the capture in the middle of the box, whatever size it is."""
        self.canvas.coords(
            self._image_item,
            self.canvas.winfo_width() / 2,
            self.canvas.winfo_height() / 2,
        )
        self.canvas.coords(self._hint_item, 0, 0)

    def _refresh_matches(self, frame) -> None:
        if frame.loop == self._shown_loop:
            return
        self._shown_loop = frame.loop
        tree = self.match_tree
        tree.delete(*tree.get_children())
        for match in frame.matches[-MATCH_ROWS:]:
            found = f"{match.location[0]}, {match.location[1]}" if match.location else "-"
            tree.insert(
                "",
                "end",
                values=(
                    match.template,
                    f"{match.min_val:,.0f}",
                    f"{match.threshold:,.0f}",
                    "match" if match.matched else "-",
                    found,
                ),
                tags=("matched" if match.matched else "missed",),
            )

    def _refresh_keypresses(self, snapshot: dict) -> None:
        """Append the keys sent since the last redraw."""
        tree = self.key_tree
        if snapshot["keypress_generation"] != self._keys_generation:
            self._keys_generation = snapshot["keypress_generation"]
            self._next_keypress = snapshot["keypress_first"]
            tree.delete(*tree.get_children())

        # if the loop outran the window, skip what is already gone
        first = snapshot["keypress_first"]
        if self._next_keypress < first:
            self._next_keypress = first
        for press in snapshot["keypresses"][self._next_keypress - first :]:
            tree.insert(
                "",
                "end",
                values=(
                    time.strftime("%H:%M:%S", time.localtime(press.at)),
                    f"{press.loop:,}",
                    press.key,
                    press.reason,
                ),
            )
        self._next_keypress = snapshot["keypress_total"]

        children = tree.get_children()
        if len(children) > KEY_ROWS:
            tree.delete(*children[: len(children) - KEY_ROWS])
            children = tree.get_children()
        if children:
            tree.see(children[-1])

    def _refresh_log(self, snapshot: dict) -> None:
        """Append the log lines written since the last redraw."""
        if snapshot["log_generation"] != self._log_generation:
            self._log_generation = snapshot["log_generation"]
            self._next_log = snapshot["log_first"]
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")

        first = snapshot["log_first"]
        if self._next_log < first:
            self._next_log = first
        lines = snapshot["log"][self._next_log - first :]
        if not lines:
            return
        self._next_log = snapshot["log_total"]

        started = snapshot["started"]
        self.log_text.configure(state="normal")
        for line in lines[-LOG_LINES:]:
            stamp = time.strftime("%H:%M:%S", time.localtime(line.at))
            self.log_text.insert(
                "end",
                f"{stamp}  T+{line.at - started:7.1f}s  loop {line.loop:>8,}  {line.text}\n",
            )
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _refresh_timings(self, snapshot: dict) -> None:
        table = snapshot["timings"]
        if table == self._shown_timings:
            return
        self._shown_timings = dict(table)
        tree = self.timing_tree
        tree.delete(*tree.get_children())
        for spec in TIMINGS:
            if spec.name not in table:
                continue
            unit = "ms" if spec.is_delay else ""
            default = spec.default_for(self.settings.platform)
            changed = table[spec.name] != default
            tree.insert(
                "",
                "end",
                iid=spec.name,
                values=(
                    spec.name,
                    f"{format_value(spec, table[spec.name])}{unit}",
                    f"{format_value(spec, default)}{unit}",
                    "file" if changed else "default",
                ),
                tags=("changed",) if changed else (),
            )

    def _redraw_graph(self) -> None:
        self._refresh_graph(self.telemetry.snapshot()["durations"])

    def _refresh_graph(self, durations) -> None:
        """One dot per iteration, with the target loop interval marked."""
        canvas = self.graph
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 40)
        if not durations:
            canvas.create_text(
                width / 2, height / 2, text="No iterations yet", fill="#666666"
            )
            return
        values = [value * 1000 for value in durations]
        peak = max(max(values), 1.0)
        target = self.settings.get("fishing_loop_interval", 0) * 1000
        if target:
            target_y = height - (target / peak) * height
            canvas.create_line(0, target_y, width, target_y, fill="#3a3a44", dash=(3, 3))
            canvas.create_text(
                4, max(target_y - 8, 8), text=f"loop target {target:g} ms", fill="#666666", anchor="w"
            )
        count = len(values)
        step = width / max(count - 1, 1)
        points = []
        for index, value in enumerate(values):
            x = index * step
            y = height - (value / peak) * height
            points.extend((x, y))
            if target and value > target:
                canvas.create_oval(
                    x - 1, y - 1, x + 1, y + 1, fill=COLOUR_ERROR, outline=""
                )
            else:
                canvas.create_oval(
                    x - 1, y - 1, x + 1, y + 1, fill=COLOUR_MATCH, outline=""
                )
        if count > 1:
            canvas.create_line(*points, fill="#4a4a58")
        canvas.create_text(
            width - 4,
            10,
            text=f"peak {peak:.1f} ms over {count} iterations",
            fill="#666666",
            anchor="ne",
        )


def launch(
    settings: Timings,
    platform,
    telemetry: Optional[Telemetry] = None,
    refresh: float = REFRESH,
) -> int:
    """Open the monitor window. Returns the process exit code."""
    telemetry = telemetry or Telemetry()
    platform.timings = settings
    # lets the loops, and waiting for the game window, be stopped from here
    platform.stop_check = telemetry.should_stop
    telemetry.set_timings(settings.values, str(settings.path))

    master = tk.Tk()
    monitor = MonitorWindow(master, telemetry, settings, platform, refresh=refresh)
    master.mainloop()
    return 0


def main(argv=None) -> int:
    """Run the monitor on its own, with the same timings as the game."""
    import argparse

    from holocure_fishing import load_timings, make_platform
    from timings import TimingError

    parser = argparse.ArgumentParser(
        description="Show what the HoloCure fishing and mining loops are doing."
    )
    parser.add_argument("--timings-file", type=Path, default=None, metavar="PATH")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="override one timing for this run only, e.g. --set fishing_key_delay=250ms",
    )
    arguments = parser.parse_args(argv)

    platform = make_platform()
    try:
        settings = load_timings(arguments.timings_file, arguments.set, sys.platform)
    except TimingError as error:
        raise SystemExit(f"Error: {error}")

    print("Open HoloCure, go to Holo House, then press Fishing or Mining.")
    return launch(settings=settings, platform=platform)


if __name__ == "__main__":
    sys.exit(main() or 0)
