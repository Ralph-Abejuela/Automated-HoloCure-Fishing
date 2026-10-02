"""A compact live status for the console run, from the same telemetry.

The monitor window (:mod:`monitor_gui`) shows everything a run is doing, but
it needs tkinter and a desktop. The console run has neither: it asks for a
mode on the terminal and then prints nothing at all until the mode ends, so a
long run looks exactly like a hung one.

This is that window, in about ten lines of terminal. The same
:class:`telemetry.Telemetry` is read on a timer and redrawn in place, so the
numbers on screen are the ones the loop is working from, not a second copy of
them. What is left out is everything the terminal is bad at: the captured
image, the tables of every match and every key, the timings list. What is kept
is what you watch a run for - how long it has been going, what the game says,
what the game thinks of the presses, and the last few log lines.

The game loop runs in a worker thread and the terminal is drawn from the main
one, so Ctrl+C stops the run without waiting for an iteration to finish.

Drawing is optional and degrades twice over: with ``--no-status`` nothing is
drawn at all, and when the output is not a terminal (a pipe, a log file) the
log lines are simply printed as they arrive instead of being redrawn over.

Nothing here imports OpenCV or the game loops at module level, so the
formatting can be tested without HoloCure, a display, or a capture.
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
import traceback
from typing import List, Optional

from telemetry import STATE_ERROR, Telemetry

#: How often the block is redrawn, in seconds. Ten times a second is fast
#: enough to read as live and slow enough that the redraw never shows up as
#: the thing slowing a run down.
REFRESH = 0.1

#: Log lines kept on screen, under the numbers. Enough to see what happened
#: a moment ago without pushing the numbers off a small terminal.
LOG_LINES = 6

#: Width of the loop-time graph, in characters.
GRAPH_WIDTH = 48

#: Block characters for the loop-time graph, best match for the encoding the
#: terminal can actually take. An old code page renders them as noise, and a
#: row of noise is worse than a row of ASCII.
GRAPH_CHARS = "▁▂▃▄▅▆▇█"
GRAPH_CHARS_ASCII = ".:-=+*#@"

#: How long a stop waits for the worker to finish its current iteration
#: before the console gives up on it and goes back to the prompt.
SHUTDOWN_GRACE = 5.0

#: How close to the circle a press has to land, in pixels, to be counted as on
#: time. Same rule the monitor window and the loop use: at the top speed a
#: note crosses about this much in one iteration, so anything nearer is the
#: loop's resolution rather than a real miss.
ON_TIME_PIXELS = 1.5

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREEN = "\x1b[32m"
CYAN = "\x1b[36m"

#: The colour each grade gets. GOOD is a clean hit, OK landed early or late,
#: BAD is a miss, and the share of GOOD is the number worth watching.
GRADE_COLOURS = {"GOOD": GREEN, "OK": YELLOW, "BAD": RED}

STATE_MARKS = {
    "starting": YELLOW + "◌",
    "running": GREEN + "●",
    "waiting for window": YELLOW + "◌",
    "stopping": YELLOW + "◌",
    "stopped": DIM + "■",
    "error": RED + "✗",
}


def graph_chars(stream=None) -> str:
    """The graph characters this terminal can show, ASCII if it cannot."""
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        GRAPH_CHARS.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return GRAPH_CHARS_ASCII
    return GRAPH_CHARS


def sparkline(values: List[float], width: int = GRAPH_WIDTH, chars: str = GRAPH_CHARS) -> str:
    """A one-line bar per value, scaled so the tallest fills the row.

    Zero is the floor of the row rather than the bottom of the tallest bar,
    so a run that is fast and steady still shows its shape instead of a flat
    line at the top.
    """
    if not values or width <= 0:
        return ""
    if len(values) > width:
        values = values[-width:]
    low = min(values)
    high = max(values)
    span = high - low
    top = len(chars) - 1
    if span <= 0:
        return chars[top] * len(values)
    return "".join(
        chars[round((value - low) / span * top)] for value in values
    )


def format_rate(durations: List[float], window: int = 30) -> str:
    """Iterations a second, from the last ``window`` of them."""
    recent = durations[-window:]
    if not recent:
        return "-"
    return f"{1 / (sum(recent) / len(recent)):.1f}/s"


def format_run_time(seconds: float) -> str:
    """How long the run has been going, as ``1h02m`` or ``2m13s``."""
    seconds = max(int(seconds), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def format_press_bias(recent: List[float]) -> str:
    """How far off the circle the presses have been landing, in pixels.

    The game writes OK for both early and late, so this is the only thing
    that can tell them apart. A mean near zero with a wide spread is a
    different problem from a steady bias: presses scattered rather than
    shifted, which widening the window would help more than moving it.
    """
    if not recent:
        return "no presses measured yet"
    mean = sum(recent) / len(recent)
    spread = (max(recent) - min(recent)) / 2
    if abs(mean) <= ON_TIME_PIXELS:
        return f"on time ({mean:+.1f}px, {spread:.0f}px spread)"
    side = "early" if mean < 0 else "late"
    return f"{abs(mean):.1f}px {side} ({spread:.0f}px spread)"


def format_press_gap(snapshot: dict) -> str:
    """How far apart the last two presses were, and how stale they are.

    The gap is what ``press_jitter`` is there to spread out. A run of
    identical gaps means every press landed at exactly the same point in the
    note's travel, and one sitting on the settings' own limits means the bot
    is as fast as it is allowed to be and would fall behind on a faster
    chain.
    """
    presses = snapshot.get("keypresses") or []
    if not presses:
        return "no presses yet"
    latest = presses[-1]
    age = (time.time() - latest.at) * 1000
    if len(presses) == 1:
        return f"1 press {age:.0f}ms ago"
    gap = (latest.at - presses[-2].at) * 1000
    return f"{gap:.0f}ms apart, {age:.0f}ms ago"


def format_grades(frame) -> str:
    """How the game has graded the presses, which is the only honest score."""
    total = frame.grade_good + frame.grade_ok + frame.grade_bad
    if not total:
        return "none graded yet"
    clean = frame.grade_good / total * 100
    return (
        f"{frame.grade_good} GOOD {frame.grade_ok} OK {frame.grade_bad} BAD"
        f" ({clean:.0f}% clean of {total})"
    )


def format_panel(frame) -> str:
    """What the game's own panel said, beside the count the bot kept.

    The two disagreeing is the interesting case: the count is the bot's own
    and the panel is the game's, and the panel is the one the note speed
    follows.
    """
    chain = "?" if frame.chain is None else str(frame.chain)
    speed = "?" if frame.speed_level is None else f"Lv {frame.speed_level}"
    return f"chain {chain} speed {speed} ({frame.counter} counted here)"


def format_offset(frame) -> str:
    """The note search window's shift, and how it came by that value.

    Once a level has been played the shift is measured. Until then it is the
    fixed guess, and saying which it is matters, because a number that looks
    settled may only be the guess it started from. The sign is carried by the
    word, so the shift is shown as a distance. Under the velocity model the
    two things it was worked out from are shown instead of the presses, since
    a latency and a note speed are what a wrong window has to be argued
    against.
    """
    report = frame.offset_report or {}
    level = report.get("level")
    if not frame.offset:
        where = "the window is where it always is"
    else:
        where = f"{abs(frame.offset)}px left"
    if not report:
        return where
    if report.get("modelled"):
        latency = report.get("latency_ms")
        if latency is None:
            return f"{where} (modelled, no latency yet)"
        speed = report.get("speed_px_s")
        if speed is None:
            return f"{where} ({latency:.0f}ms delay, speed unknown)"
        return f"{where} ({latency:.0f}ms delay at {speed:.0f}px/s)"
    if not report.get("learned"):
        return f"{where} (Lv {level}, the guess, {report.get('presses', 0)} presses)"
    mean = report.get("mean_error", 0.0)
    side = "early" if mean < 0 else "late"
    return (
        f"{where} (Lv {level}, learned, landing {abs(mean):.1f}px {side})"
    )


def format_log(line, colour: bool = True) -> str:
    """One log line, stamped and shortened to fit a terminal line."""
    stamp = time.strftime("%H:%M:%S", time.localtime(line.at))
    if not colour:
        return f"{stamp} {line.text}"
    return f"{DIM}{stamp}{RESET} {line.text}"


def render(
    snapshot: dict,
    width: int = 80,
    log_lines: int = LOG_LINES,
    chars: str = GRAPH_CHARS,
    colour: bool = True,
) -> List[str]:
    """The whole block, as a list of already-coloured terminal lines.

    Split out from the drawing so the layout can be checked without a
    terminal. Returns exactly ``5 + log_lines`` lines, so the redraw can move
    a known number of lines up rather than counting what it wrote last time.
    """
    frame = snapshot["frame"]
    durations = snapshot["durations"]
    timings = snapshot.get("timings") or {}
    started = snapshot.get("started", time.time())
    target = timings.get("fishing_loop_interval", 0) * 1000

    mark = STATE_MARKS.get(frame.state, DIM + "·") if colour else "*"
    narrow = max(width - 1, 20)
    peak = max(durations) * 1000 if durations else 0.0
    dim, reset, bold = (DIM, RESET, BOLD) if colour else ("", "", "")

    lines = [
        # what the loop is doing right now, in its own words
        f"{mark}{reset} {bold}{clip(frame.message or '-', narrow)}{reset}",
        # the run: how long, how fast, and where the time in an iteration goes
        f"{dim}{frame.mode or '-'}{reset} loop {frame.loop:,} · "
        f"{format_rate(durations)} · {frame.loop_ms:.2f}ms "
        f"{dim}(cap {frame.capture_ms:.2f} match {frame.match_ms:.2f} "
        f"sleep {frame.sleep_ms:.2f}){reset} · {format_run_time(time.time() - started)}",
        # what the game says, and what the bot believes about its own timing
        f"{format_panel(frame)} · {format_offset(frame)}",
        # what the game thinks of the presses, which is the only real score
        f"{format_grades(frame)} · "
        f"{format_press_bias(list((snapshot.get('timing') or {}).values())[-60:])} · "
        f"press {format_press_gap(snapshot)}",
        # the shape of the last iterations, and how they compare to the target
        f"{dim}loop{reset} {sparkline(durations, min(GRAPH_WIDTH, max(narrow - 22, 8)), chars)} "
        f"{dim}peak {peak:.1f}ms of {target:g}ms{reset}",
    ]

    log = snapshot.get("log") or []
    recent = log[-log_lines:]
    # pad rather than shrink, so the block keeps its height when it is quiet
    lines.extend(format_log(line, colour) for line in recent)
    lines.extend(
        [f"{dim}(nothing logged yet){reset}"] * (log_lines - len(recent))
    )
    return [clip(line, width) for line in lines]


def clip(text: str, width: int) -> str:
    """Cut a line to the terminal width, ignoring the escape codes in it.

    The escapes are zero width on screen but count in the string, so a line
    of colour would otherwise wrap at a different place than it is drawn.
    """
    if width <= 0:
        return ""
    shown = 0
    out = []
    index = 0
    while index < len(text):
        if text[index] == "\x1b":
            end = text.find("m", index)
            if end == -1:
                break
            out.append(text[index : end + 1])
            index = end + 1
            continue
        if shown >= width:
            break
        out.append(text[index])
        shown += 1
        index += 1
    return "".join(out)


class ConsoleStatus:
    """Redraws the block in place, from the main thread, while a loop runs.

    Owns nothing the loop is using: it reads a snapshot and prints it, so it
    can be dropped without changing what the loop does.
    """

    def __init__(
        self,
        telemetry: Telemetry,
        stream=None,
        refresh: float = REFRESH,
        log_lines: int = LOG_LINES,
    ) -> None:
        self.telemetry = telemetry
        self.stream = stream or sys.stdout
        self.refresh_interval = refresh
        self.log_lines = log_lines
        self.colour = bool(getattr(self.stream, "isatty", lambda: False)())
        self.chars = graph_chars(self.stream) if self.colour else GRAPH_CHARS_ASCII
        self.started = time.monotonic()
        self._drawn = 0
        self._shown_log = 0
        self._log_generation = None
        self._closed = False
        #: Set once the console cannot be written to any more, so a closed
        #: pipe stops the drawing instead of raising on every redraw.
        self._broken = False

    # -- plain output, for a pipe or a log file -----------------------

    def _plain(self, snapshot: dict) -> None:
        """Print new log lines and the odd status, without any cursor moves.

        With the output redirected there is no screen to redraw, so the
        in-place block would only ever scroll: what is written is appended,
        and the numbers are repeated rarely enough not to drown the log.
        """
        if snapshot["log_generation"] != self._log_generation:
            self._log_generation = snapshot["log_generation"]
            self._shown_log = snapshot["log_first"]
        first = snapshot["log_first"]
        if self._shown_log < first:
            self._shown_log = first
        for line in snapshot["log"][self._shown_log - first :]:
            self.stream.write(format_log(line, False) + "\n")
        self._shown_log = snapshot["log_total"]
        self.stream.flush()
        if snapshot["frame"].loop and snapshot["frame"].loop % 100 == 0:
            frame = snapshot["frame"]
            self.stream.write(
                f"-- loop {frame.loop:,} · {format_grades(frame)} · "
                f"{format_panel(frame)}\n"
            )
            self.stream.flush()

    # -- in place ------------------------------------------------------

    def draw(self, snapshot: dict) -> None:
        """Put one frame of the block on screen.

        A console that cannot be written to any more (a closed pipe, a
        detached terminal) drops the drawing rather than raising: the game
        loop is still worth running, and it is not this display's job to
        stop it.
        """
        if self._broken:
            return
        try:
            if not self.colour:
                self._plain(snapshot)
                return
            width = shutil.get_terminal_size((80, 24)).columns
            block = render(snapshot, width, self.log_lines, self.chars)
            out = []
            if self._drawn:
                out.append(f"\x1b[{self._drawn}A")
            out.extend(f"\x1b[2K{line}\n" for line in block)
            self.stream.write("".join(out))
            self.stream.flush()
            self._drawn = len(block)
        except (OSError, ValueError):
            self._broken = True

    def run(self, thread: threading.Thread) -> None:
        """Draw until ``thread`` finishes, or until Ctrl+C asks it to stop.

        The loop is in the worker, so the interrupt lands here where it can
        be turned into an orderly stop: the telemetry is told, and the worker
        is given its ``SHUTDOWN_GRACE`` to finish the iteration it is in.
        """
        try:
            while thread.is_alive():
                self.draw(self.telemetry.snapshot())
                time.sleep(self.refresh_interval)
        except KeyboardInterrupt:
            self.stream.write("\nStopping after this iteration...\n")
            self.stream.flush()
            self.telemetry.stop()
        finally:
            thread.join(timeout=SHUTDOWN_GRACE)
            # the worker may have made one more frame after the last draw
            self.draw(self.telemetry.snapshot())

    def close(self) -> None:
        """Leave the terminal where it was found."""
        if self._closed:
            return
        self._closed = True


def run_mode(
    mode: str,
    platform,
    settings,
    telemetry: Optional[Telemetry] = None,
    refresh: float = REFRESH,
) -> int:
    """Run ``mode`` with the console status up, and return an exit code.

    The same worker-then-draw shape the monitor window uses, so the console
    run and the windowed run drive the identical loop: only what is drawn
    differs.
    """
    from holocure_fishing import fishing_mode, pick_axe_mode

    telemetry = telemetry or Telemetry()
    platform.timings = settings
    # lets the loop, and waiting for the game window, be stopped from here
    platform.stop_check = telemetry.should_stop
    telemetry.reset(mode)
    telemetry.set_timings(settings.values, str(settings.path))

    def work() -> None:
        try:
            run = fishing_mode if mode == "fishing" else pick_axe_mode
            run(platform, settings, telemetry)
        except Exception:
            details = traceback.format_exc()
            telemetry.log(details, level="error")
            telemetry.fail(details.strip().splitlines()[-1])
        finally:
            telemetry.finish()

    thread = threading.Thread(target=work, name=f"holocure-{mode}", daemon=True)
    thread.start()
    status = ConsoleStatus(telemetry, refresh=refresh)
    try:
        status.run(thread)
    finally:
        status.close()
    snapshot = telemetry.snapshot()
    if snapshot["error"]:
        sys.stderr.write(snapshot["error"] + "\n")
        return 1
    return 0