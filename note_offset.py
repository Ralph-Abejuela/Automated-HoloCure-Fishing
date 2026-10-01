"""Working out how far the note search window has to move, from the presses.

The window used to be moved by a fixed table: 15 pixels to the left at the top
speed, scaled by the level, on the reasoning that the compensation is for one
machine's latency hardcoded into every machine. It was a guess about a
quantity that is already on screen.

Every press the bot makes can be measured instead. The note's position is
known at the moment the key goes down, the circle's middle is a fixed place on
the strip, and the difference between them is how far early or late the press
was. A bot that is consistently a few pixels early is telling you the window
is a few pixels too far left, and the correction is that many pixels back the
other way.

One learned offset is kept per speed level, because the right amount clearly
differs between level 1 and level 7: a level 7 note crosses the strip several
times faster, so the same error in pixels is a much smaller error in time.

The correction is deliberately unhurried. A window of fifteen presses is
averaged before anything moves, and the window moves at most
:data:`MAX_STEP_PIXELS` each time, so a few notes are mistimed while a level
settles and the value does not jump about on one odd press. A level the game
speeds past before a full window has gathered still uses what it has, because
the next level is not going to wait.

The table in :mod:`platform_UNF` is only where each level starts, and it never
changes: it is a constant in the source, the learned values live in memory for
the run, and nothing is written back. Every run starts from the same guesses.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

#: How far left the window is at the top speed, and the chain the game reaches
#: it at. This is the starting guess, not the answer.
#:
#: It was 15, from the value Linux needed, and that was far too much: a
#: measured run put the presses eighteen pixels early with the window there,
#: and the window that actually lands them on the circle is a couple of
#: pixels left. The number was fitted to a search that looked at a different
#: stretch of the strip, and starting fifteen pixels wrong costs more notes
#: than learning back from it saves.
OFFSET_AT_MAX_SPEED = 4
CHAIN_AT_MAX_SPEED = 70
MAX_SPEED_LEVEL = 7

#: How many presses are averaged before the window moves at all. A chain round
#: is three to six presses, so fifteen is two or three rounds: long enough
#: that one odd note does not move the window, short enough to arrive within a
#: level rather than after it.
WINDOW_PRESSES = 15

#: How few presses still count when a level ends before a full window has
#: gathered. The game speeds up every ten fish whether the window is ready or
#: not, and a level that kept getting cut short would otherwise never learn.
MIN_FLUSH_PRESSES = 4

#: The most the window moves at once, in pixels. Small on purpose: the notes
#: are a couple of pixels apart at the top speed, so a jump of more than this
#: would overshoot the thing it is correcting.
MAX_STEP_PIXELS = 1.5

#: How much of the average error is corrected each time. Under one, so the
#: window eases towards the right value rather than arriving at it and
#: oscillating around it.
GAIN = 0.5

#: How far the window is allowed to move, either way. Past this the note would
#: be leaving the searched strip altogether, and the offset is there to
#: correct a timing, not to find a note somewhere else.
MIN_OFFSET = -30
MAX_OFFSET = 5


def seed_offset(speed_level: Optional[int] = None, chain: int = 0) -> int:
    """The starting guess for a level: today's fixed table.

    Kept because it gets close in one guess, so a level does not have to be
    learned from nothing on every run, and because a level with no reading yet
    still needs an answer.
    """
    if speed_level is not None:
        level = min(max(speed_level, 1), MAX_SPEED_LEVEL)
        return math.floor(-OFFSET_AT_MAX_SPEED * (level - 1) / (MAX_SPEED_LEVEL - 1))
    reached = min(chain, CHAIN_AT_MAX_SPEED)
    return math.floor(-OFFSET_AT_MAX_SPEED * reached / CHAIN_AT_MAX_SPEED)


@dataclass
class LevelOffset:
    """What one speed level has been taught so far."""

    level: int
    #: Where it started, so it can be told apart from what was measured.
    seed: int
    #: The window's current position, in pixels, negative for left.
    offset: int
    #: The presses waiting to be averaged in.
    errors: List[float] = field(default_factory=list)
    #: The last window of presses, for what the level is landing by now. The
    #: average over every press would still read early long after the window
    #: has settled, because it remembers the presses it learned from.
    recent: Deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW_PRESSES))
    #: Every error seen, and how many.
    total: float = 0.0
    count: int = 0

    @property
    def mean(self) -> float:
        """How far off the recent presses have been landing, early negative.

        This is the number to watch, not the average over the whole run: a
        level that started eleven pixels out spends its first hundred presses
        proving it, and a cumulative average would keep reporting that long
        after the window had arrived.
        """
        return sum(self.recent) / len(self.recent) if self.recent else 0.0

    def observe(self, error: float) -> None:
        self.total += error
        self.count += 1
        self.errors.append(error)
        self.recent.append(error)
        if len(self.errors) < WINDOW_PRESSES:
            return
        mean = sum(self.errors) / len(self.errors)
        self.errors.clear()
        self._step(mean)

    def flush(self) -> bool:
        """Use a part-filled window anyway, because the level is moving on.

        The game raises the speed every ten fish whether the window is ready
        or not, so a level that is gone before fifteen presses have gathered
        would take its evidence with it. What was gathered is still evidence,
        and it is used and dropped, so a level that keeps getting cut short
        still learns something on the way past.
        """
        if len(self.errors) < MIN_FLUSH_PRESSES:
            self.errors.clear()
            return False
        mean = sum(self.errors) / len(self.errors)
        self.errors.clear()
        self._step(mean)
        return True

    def _step(self, mean: float) -> None:
        """Move the window by its share of the error it has been making."""
        # Early is negative, and an early press means the window was too far
        # left, so the correction is the other way: offset rises towards zero.
        step = max(-MAX_STEP_PIXELS, min(MAX_STEP_PIXELS, -GAIN * mean))
        self.offset = int(
            max(MIN_OFFSET, min(MAX_OFFSET, round(self.offset + step)))
        )


class OffsetLearner:
    """The search window's position at each speed level, learned as it plays.

    Not thread safe, and does not need to be: only the game loop touches it,
    from its own thread.
    """

    def __init__(self) -> None:
        self._levels: Dict[int, LevelOffset] = {}
        #: The level in use, so the one being left behind can be flushed.
        self._active: Optional[int] = None

    def _entry(self, speed_level: Optional[int], chain: int) -> LevelOffset:
        level = effective_level(speed_level, chain)
        if self._active is not None and level != self._active:
            leaving = self._levels.get(self._active)
            if leaving is not None:
                leaving.flush()
        self._active = level
        entry = self._levels.get(level)
        if entry is None:
            seed = seed_offset(speed_level, chain)
            entry = LevelOffset(level=level, seed=seed, offset=seed)
            self._levels[level] = entry
        return entry

    def offset_for(self, speed_level: Optional[int] = None, chain: int = 0) -> int:
        """Where the search window should sit, in pixels, negative for left."""
        return self._entry(speed_level, chain).offset

    def observe(self, error: float, speed_level: Optional[int] = None, chain: int = 0) -> None:
        """Tell it how far early or late a press was, in pixels."""
        self._entry(speed_level, chain).observe(error)

    def report(self, speed_level: Optional[int] = None, chain: int = 0) -> dict:
        """What the level in use has been taught, for the window to show."""
        entry = self._entry(speed_level, chain)
        return {
            "level": entry.level,
            "offset": entry.offset,
            "seed": entry.seed,
            "learned": entry.offset != entry.seed,
            "presses": entry.count,
            "mean_error": entry.mean,
            "settling": len(entry.errors),
        }

    def flush(self) -> None:
        """Use every level's part-filled window, for a run that has stopped.

        Not needed while the game is playing, where a level changing flushes
        itself. It is here so that a value can be read out of a learner that
        was fed presses and then abandoned.
        """
        for entry in self._levels.values():
            entry.flush()


def effective_level(speed_level: Optional[int], chain: int) -> int:
    """The level to learn against, from the panel if it has been read.

    The panel is the authority, but it is not read on the first iteration of
    a run, and the level can be worked out from the chain when it is not.
    """
    if speed_level is not None:
        return min(max(speed_level, 1), MAX_SPEED_LEVEL)
    return min(max(chain // 10, 1), MAX_SPEED_LEVEL)
