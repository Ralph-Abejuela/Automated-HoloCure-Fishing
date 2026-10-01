"""What the game loops are doing, right now, for the monitor window.

The fishing and mining loops run in a worker thread; after every iteration
they push a short report into a :class:`Telemetry`. The monitor window
(:mod:`monitor_gui`) calls :meth:`Telemetry.snapshot` from the Tk thread a
few times a second and draws what it finds.

Everything a window needs is in that one snapshot, so the window never
touches an object the loop still owns. The only shared mutable state is the
snapshot itself, which is copied under a lock.

Nothing here imports tkinter or OpenCV, so this module can be tested
without a display and without the game running.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

#: How many keypresses, and how many log lines, are kept for the window.
KEYPRESS_HISTORY = 400
LOG_HISTORY = 300

#: How many loop durations are kept for the loop-time graph, in seconds.
DURATION_HISTORY = 240

#: The states :meth:`Telemetry.set_state` is given. They are plain strings so
#: the window can show them without importing this module.
STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_WAITING = "waiting for window"
STATE_RUNNING = "running"
STATE_STOPPING = "stopping"
STATE_STOPPED = "stopped"
STATE_ERROR = "error"


@dataclass(frozen=True)
class Rect:
    """A box to draw over the monitor image, in capture pixels.

    ``color`` is RGB, the order a display uses; the image itself is BGR.
    """

    x: int
    y: int
    width: int
    height: int
    color: Tuple[int, int, int] = (255, 255, 0)
    label: str = ""


@dataclass(frozen=True)
class Dot:
    """A single point to mark, usually the best template match."""

    x: int
    y: int
    color: Tuple[int, int, int] = (0, 255, 0)
    label: str = ""


@dataclass
class Match:
    """One template match from one loop iteration.

    ``min_val`` is the lowest score :func:`cv2.matchTemplate` found, and
    ``threshold`` is the number it has to stay under for the loop to act on
    it. A lower score is a better match for ``TM_SQDIFF``, so ``matched``
    means ``min_val < threshold``.
    """

    template: str
    min_val: float
    threshold: float
    matched: bool
    location: Optional[Tuple[int, int]] = None


@dataclass
class KeyPress:
    """A key the loop sent to the game, and why."""

    at: float
    loop: int
    key: str
    reason: str


@dataclass
class LogLine:
    """One line in the activity log."""

    at: float
    loop: int
    text: str
    level: str = "info"


@dataclass
class LoopFrame:
    """What a single iteration of a loop did.

    Everything is a plain value or a copy, so a snapshot can be read while
    the loop is already building the next frame. ``image`` is the exception:
    it is the capture the loop is working on, handed over read-only.
    """

    mode: str = ""
    loop: int = 0
    state: str = STATE_IDLE
    message: str = "Not started."
    image: Any = None
    rects: List[Rect] = field(default_factory=list)
    dots: List[Dot] = field(default_factory=list)
    matches: List[Match] = field(default_factory=list)
    bounds: Optional[Tuple[int, int, int, int]] = None
    roi: Optional[Tuple[int, int, int, int]] = None
    scale: int = 1
    keybinds: Dict[str, str] = field(default_factory=dict)
    counter: int = 0
    #: Pixels the note search window was moved left by, from Platform.offset.
    offset: int = 0
    #: The chain the game's own panel is showing, read off it. None until it
    #: has been read, which is different from zero: zero is a real chain.
    chain: Optional[int] = None
    #: The speed level the panel is showing, likewise.
    speed_level: Optional[int] = None
    #: How the game has graded the presses so far: GOOD, OK and BAD counts.
    grade_good: int = 0
    grade_ok: int = 0
    grade_bad: int = 0
    capture_ms: float = 0.0
    match_ms: float = 0.0
    loop_ms: float = 0.0
    sleep_ms: float = 0.0

    def copy(self) -> "LoopFrame":
        """A copy that shares no list with the live frame."""
        clone = LoopFrame(**vars(self))
        clone.rects = list(self.rects)
        clone.dots = list(self.dots)
        clone.matches = list(self.matches)
        clone.keybinds = dict(self.keybinds)
        return clone


class _Stream:
    """A bounded event log that a slow reader can follow.

    A reader is told how many events ever arrived (``total``) and how many
    fell off the front (``first``), so it can append what is new, notice it
    fell behind, and rebuild instead of guessing. ``generation`` changes
    when the stream is emptied, which is how a reader knows to forget
    everything it drew before.
    """

    def __init__(self, limit: int) -> None:
        self._items: deque = deque(maxlen=limit)
        self._limit = limit
        self._dropped = 0
        self.total = 0
        self.generation = 0

    def append(self, item: Any) -> None:
        if len(self._items) == self._limit:
            self._dropped += 1
        self._items.append(item)
        self.total += 1

    def clear(self) -> None:
        self._items.clear()
        self._dropped = self.total
        self.generation += 1

    @property
    def first(self) -> int:
        """Stream position of the oldest item still kept."""
        return self._dropped

    def copy(self) -> Tuple[List[Any], int, int, int]:
        return list(self._items), self._dropped, self.total, self.generation


class Telemetry:
    """A report the game loops write and the monitor window reads.

    Every method is safe to call from the loop thread while the window
    thread is reading, and cheap enough to call on every iteration of a
    100 Hz loop. A loop started without a window is given a plain
    ``Telemetry``: the events are simply kept, not shown, and
    :meth:`should_stop` never becomes true.
    """

    def __init__(self) -> None:
        # Re-entrant, so a method that reports an event may report another
        # one on the way out without releasing the lock half way.
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._frame = LoopFrame()
        self._keypresses = _Stream(KEYPRESS_HISTORY)
        self._log = _Stream(LOG_HISTORY)
        self._durations: deque = deque(maxlen=DURATION_HISTORY)
        self._grades: Dict[int, str] = {}
        #: How far early or late each press was, in pixels, by the loop it was
        #: made on. Empty until a press is made.
        self._timing: Dict[int, float] = {}
        self._started = time.time()
        self._timings: Dict[str, float] = {}
        self._timings_path = ""
        self._error = ""
        #: Whether :meth:`key` also writes a line into the activity log.
        self.log_keypresses = True

    # -- read by the window --------------------------------------------

    def snapshot(self) -> dict:
        """Everything a window needs, copied so the loop can carry on.

        The two event lists come with the position of their oldest item
        (``*_first``), how many ever arrived (``*_total``) and a
        ``*_generation`` that changes when the list was emptied, which is
        how a window appends what is new instead of redrawing everything.
        """
        with self._lock:
            keypresses, key_first, key_total, key_gen = self._keypresses.copy()
            log, log_first, log_total, log_gen = self._log.copy()
            return {
                "frame": self._frame.copy(),
                "keypresses": keypresses,
                "keypress_first": key_first,
                "keypress_total": key_total,
                "keypress_generation": key_gen,
                "log": log,
                "log_first": log_first,
                "log_total": log_total,
                "log_generation": log_gen,
                "started": self._started,
                "durations": list(self._durations),
                "timings": dict(self._timings),
                "timings_path": self._timings_path,
                "grades": dict(self._grades),
                "timing": dict(self._timing),
                "error": self._error,
                "stopping": self._stop.is_set(),
            }

    def should_stop(self) -> bool:
        """True once :meth:`stop` has been called. Loops check it every pass."""
        return self._stop.is_set()

    # -- written by the loop -------------------------------------------

    def reset(self, mode: str = "") -> None:
        """Start a fresh run of ``mode``, clearing everything shown so far."""
        with self._lock:
            self._stop.clear()
            self._error = ""
            self._frame = LoopFrame(
                mode=mode,
                state=STATE_STARTING,
                message=f"Starting {mode}..." if mode else "Starting...",
            )
            self._started = time.time()
            self._keypresses.clear()
            self._log.clear()
            self._durations.clear()
            self._grades.clear()
            self._timing.clear()

    def set_state(self, state: str, message: str = "") -> None:
        """Record what the loop is doing, and optionally why."""
        with self._lock:
            self._frame.state = state
            if message:
                self._frame.message = message

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._frame.mode = mode

    def update(self, **fields: Any) -> None:
        """Replace fields of the current frame, e.g. ``update(loop_ms=3.1)``."""
        with self._lock:
            for name, value in fields.items():
                setattr(self._frame, name, value)

    def loop_done(self, elapsed: float) -> None:
        """Close off the current frame and start the next one.

        Records how long the iteration took and counts it, which is what
        the loop counter, the rate and the graph are built from.
        """
        with self._lock:
            self._durations.append(elapsed)
            self._frame.loop += 1

    def key(self, key: str, reason: str = "") -> None:
        """Record a key sent to the game."""
        with self._lock:
            self._keypresses.append(
                KeyPress(at=time.time(), loop=self._frame.loop, key=key, reason=reason)
            )
            if self.log_keypresses:
                self._log.append(
                    LogLine(
                        at=time.time(),
                        loop=self._frame.loop,
                        text=f"key {key!r}" + (f" - {reason}" if reason else ""),
                        level="key",
                    )
                )

    def log(self, text: str, level: str = "info") -> None:
        """Add a line to the activity log."""
        with self._lock:
            self._log.append(
                LogLine(at=time.time(), loop=self._frame.loop, text=text, level=level)
            )

    def current_loop(self) -> int:
        """Which iteration the loop is on, without copying a whole frame.

        A press has to remember which iteration it belongs to, and taking a
        whole snapshot to find that out would copy the frame's lists on every
        keypress.
        """
        with self._lock:
            return self._frame.loop

    def grade(self, loop: int, grade: Optional[str]) -> None:
        """Record what the game made of the press made on ``loop``.

        A grade of None means it never turned up, which is a real answer: the
        press is counted as ungraded rather than as a good one.
        """
        with self._lock:
            self._grades[loop] = grade or "none"
            if len(self._grades) > KEYPRESS_HISTORY:
                for stale in sorted(self._grades)[: len(self._grades) - KEYPRESS_HISTORY]:
                    del self._grades[stale]

    def timing(self, loop: int, pixels: float) -> None:
        """Record how far early or late a press was, in pixels.

        Negative is early: the note had not reached the circle yet. Positive
        is late: it had gone past. This is the loop's own measurement of
        where the note was, not the game's word, which only ever says OK.
        """
        with self._lock:
            self._timing[loop] = pixels
            if len(self._timing) > KEYPRESS_HISTORY:
                for stale in sorted(self._timing)[: len(self._timing) - KEYPRESS_HISTORY]:
                    del self._timing[stale]

    def clear_log(self) -> None:
        """Empty the activity log, so a window can start its log view over."""
        with self._lock:
            self._log.clear()

    def set_timings(self, values: Mapping[str, float], path: str = "") -> None:
        """Record the timing table in use, so the window can show it."""
        with self._lock:
            self._timings = dict(values)
            self._timings_path = path

    def fail(self, message: str) -> None:
        """Record that the loop died, so the window can say so."""
        with self._lock:
            self._error = message
            self._frame.state = STATE_ERROR
            self._frame.message = message
            self.log(message, level="error")

    def finish(self, message: str = "Stopped.") -> None:
        """Record that the loop returned. Calling it twice is harmless.

        The frame keeps the message of the last iteration, so a window can
        still say what the loop was doing when it was told to stop.
        """
        with self._lock:
            if self._frame.state in (STATE_ERROR, STATE_STOPPED):
                return
            self._frame.state = STATE_STOPPED
            self._log.append(
                LogLine(at=time.time(), loop=self._frame.loop, text=message)
            )

    # -- stopping ------------------------------------------------------

    def stop(self) -> None:
        """Ask the running loop to return after its current iteration."""
        self._stop.set()
        with self._lock:
            if self._frame.state in (STATE_RUNNING, STATE_WAITING, STATE_STARTING):
                self._frame.state = STATE_STOPPING
                self._frame.message = "Stopping after this iteration..."
