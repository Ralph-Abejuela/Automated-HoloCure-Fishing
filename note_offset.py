"""Working out how far the note search window has to move, from the presses.

The window used to be moved by a fixed table: four pixels to the left at the
top speed, scaled by the level, on the reasoning that the compensation is for
one machine's latency hardcoded into every machine. It was a guess about a
quantity that is already on screen, and it was then learned into seven
separate numbers, one per speed level, which was a second guess wearing the
first guess's coat.

The thing being compensated for is not a distance. It is a delay between the
moment the bot decides to press and the moment the key actually goes down, and
a delay is only ever visible as a distance once you multiply it by how fast
the thing was moving. Half a frame of scheduling jitter is three pixels on a
note crawling across the strip and thirty on one tearing across it. The same
error, in the same run, at the same instant, means a completely different
latency depending on what kind of fish is on screen. So what is learned here
is the delay itself, in seconds, and the pixel offset is worked out from it
each time it is needed, by multiplying by the note's measured speed.

That is why the speed is measured rather than read off the HUD level. The
level is not a velocity. It is a difficulty dial that the game turns, and the
game does not promise that every species travels at the same speed within a
level: the fishing minigame draws different fish, and at one level a slow one
and a fast one can be crossing the strip together. Keying on the level
therefore splits presses into seven buckets that do not mean what they appear
to mean, and averages a wide spread of real latencies into a number that
describes none of them. The velocity of a note is a measurement, taken where
the note is, so it is used where it is available. The level survives only as
the cold-start answer, for the stretches of a run where nothing has been
measured yet, which is exactly what it is good at: it gets close in one
guess, so the window is not miles out on the first note.

Re-anchoring is the part that makes the change safe rather than merely
different. The moment the first velocity arrives the latency is not reset to
a new number; it is set so that the offset the model produces at that
velocity is exactly the offset the level table would have produced anyway.
The first reading through the model is therefore the same window position as
the last reading through the table, and the presses that follow can only
improve on what the table said. Nothing about the notes the bot has already
hit gets worse at the handover, and a run in progress does not visibly change
behaviour at the moment the changeover happens.

A press whose velocity is not known is not evidence about latency and is
thrown away rather than averaged in. A pixel error divided by an unknown
speed is not a small measurement, it is no measurement, and letting those
presses into the window would quietly poison the average with numbers that
are only large because the divisor was small. The presses are not counted
either, because the number the window shows is a number of presses the offset
was learned from, and counting ones that were thrown away would make it say
something untrue. What this cannot do is tell you which fish you caught, and
it does not try: it is handed a speed and an error and nothing else, which is
all it needs, because the species is not a variable in the delay.

The correction is deliberately unhurried. A window of fifteen presses is
averaged before anything moves, and the window moves at most
:data:`MAX_STEP_LATENCY` of a second at a time, so a few notes are mistimed
while the delay settles and the value does not jump about on one odd press.
A level the game speeds past before a full window has gathered still uses
what it has, because the next level is not going to wait.

The table in :mod:`platform_UNF` is only where each level starts, and it never
changes: it is a constant in the source, the learned latency lives in memory
for the run, and nothing is written back. Every run starts from the same
guesses.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, NamedTuple, Optional

import note_motion

#: How far left the window is at the top speed, and the chain the game reaches
#: it at. This is the starting guess, not the answer, and it is the whole
#: reason the level table survives: the offset is a distance derived from the
#: latency, so with no latency yet the table is all there is, and it is right
#: to within a couple of pixels on most machines.
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

#: How few presses still count when a window is cut short. The game speeds up
#: every ten fish whether the window is ready or not, and a run that kept
#: getting cut short would otherwise take its evidence away with it.
MIN_FLUSH_PRESSES = 4

#: The most the latency moves at once, in seconds. The old cap was
#: ``MAX_STEP_PIXELS``, one and a half pixels, which is a cap that only means
#: anything at some particular speed: at a typical top speed of around four
#: hundred pixels a second, one and a half pixels is about four milliseconds,
#: which is roughly the smallest change in a press latency that means anything
#: to the hand that caused it. Four milliseconds is therefore the same
#: restraint the old cap was, expressed in the units the step is now actually
#: in, and it holds that restraint at every speed rather than at one.
MAX_STEP_LATENCY = 0.004

#: How much of the gap between the measured delay and the current one is
#: closed each time. Under one, so the window eases towards the right value
#: rather than arriving at it and oscillating around it.
GAIN = 0.5

#: How far the window is allowed to move, either way. Past this the note would
#: be leaving the searched strip altogether, and the offset is there to
#: correct a timing, not to find a note somewhere else. The model is in
#: seconds but the search is in pixels, so this is the clamp that keeps a
#: long latency from asking for a strip the game does not have.
MIN_OFFSET = -30
MAX_OFFSET = 5

#: How slow a note has to be travelling before its velocity is worth dividing
#: by. The implied latency of a press is its pixel error over its speed, so
#: the divisor sets the size of the noise: at a hundred pixels a second one
#: pixel of measurement is ten milliseconds of implied delay, and at twenty
#: it is fifty, which is the entire range the clamp below allows. Below that
#: the division is amplifying the rounding in the match position into a
#: statement about the machine, and the press is dropped instead.
#:
#: This is deliberately stricter than :data:`note_motion.MIN_SPEED_PX_S`,
#: which is the floor for believing the tracker measured a velocity at all.
#: Here the question asked of the number is different and the answer needed is
#: higher: a note slow enough to be tracked is not automatically fast enough
#: to divide by.
MIN_TRACKABLE_SPEED = 20.0

#: The bounds the learned latency is kept inside, in seconds. The top is a
#: delay of a quarter of a second, which at any speed this game runs at is
#: more travel than :data:`MAX_OFFSET` allows, so it is a stop against a wild
#: reading rather than a limit that will ever be reached by learning. The
#: bottom is slightly negative, because presses can land late as well as
#: early, and a run that is systematically late needs the window to move the
#: other way; thirty milliseconds negative is about the six pixels of positive
#: offset that strip has room for.
MIN_LATENCY = -0.03
MAX_LATENCY = 0.25


def seed_offset(speed_level: Optional[int] = None, chain: int = 0) -> int:
    """The starting guess for a level: today's fixed table.

    Kept because it gets close in one guess, so a note does not have to be
    learned from nothing on every run, and because a run with no measured
    velocity anywhere in it still needs an answer.
    """
    if speed_level is not None:
        level = min(max(speed_level, 1), MAX_SPEED_LEVEL)
        return math.floor(-OFFSET_AT_MAX_SPEED * (level - 1) / (MAX_SPEED_LEVEL - 1))
    reached = min(chain, CHAIN_AT_MAX_SPEED)
    return math.floor(-OFFSET_AT_MAX_SPEED * reached / CHAIN_AT_MAX_SPEED)


def effective_level(speed_level: Optional[int], chain: int) -> int:
    """The level the panel is on, or the one the chain implies.

    It no longer decides what is learned, because what is learned is a latency
    and a latency is not per level. It is still read, for two things: naming
    the level in the report, and seeding the offset on the runs where no
    velocity has been measured and the table is the only answer there is. The
    panel is the authority, but it is not read on the first iteration of a
    run, and the level can be worked out from the chain when it is not.
    """
    if speed_level is not None:
        return min(max(speed_level, 1), MAX_SPEED_LEVEL)
    return min(max(chain // 10, 1), MAX_SPEED_LEVEL)


def _trackable_speed(speed_px_s: Optional[float]) -> Optional[float]:
    """The velocity to reason with, or ``None`` when there is nothing to use.

    Three separate ways a number fails to be evidence, all of them the same
    failure from here: absent, not a number, or too small to divide a pixel
    error by without the rounding deciding the answer.
    """
    if speed_px_s is None:
        return None
    try:
        speed = float(speed_px_s)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(speed) or speed < MIN_TRACKABLE_SPEED:
        return None
    return speed


def _clamp_latency(latency: float) -> float:
    return max(MIN_LATENCY, min(MAX_LATENCY, latency))


def _clamp_offset(offset: int) -> int:
    return max(MIN_OFFSET, min(MAX_OFFSET, offset))


class Sample(NamedTuple):
    """One press, in both of the units it is needed in.

    The pixel error is what the window shows and what the player is judging by.
    The implied latency is what is actually averaged and learned from, because
    the pixel error means something different at every speed and the implied
    latency does not.
    """

    error: float
    implied: float


@dataclass
class LatencyCell:
    """The one thing this module learns: how late the bot's presses are.

    There used to be one of these per speed level. There is one now, because
    the delay belongs to the machine and not to the fish: the same run, the
    same scheduler, the same hand on the same key, whether the note crossing
    the strip is a slow one or a fast one.
    """

    #: The learned delay, in seconds, or ``None`` while there is nothing but
    #: the table to go on.
    latency: Optional[float] = None
    #: Whether the latency has been set to agree with the table for the
    #: velocity that turned up. Set once, on that arrival, and never again.
    anchored: bool = False
    #: The implied latencies waiting to be averaged in.
    pending: List[float] = field(default_factory=list)
    #: The last window of presses, for what the offset is landing by now. The
    #: average over every press would still read early long after the window
    #: has settled, because it remembers the presses it learned from.
    recent: Deque[Sample] = field(
        default_factory=lambda: deque(maxlen=WINDOW_PRESSES)
    )
    #: How many presses have been learned from.
    count: int = 0

    @property
    def mean(self) -> float:
        """How far off the recent presses have been landing, in pixels.

        Early is negative. This is the number to watch, not the average over
        the whole run: a run that started eleven pixels out spends its first
        hundred presses proving it, and a cumulative average would keep
        reporting that long after the window had arrived.
        """
        if not self.recent:
            return 0.0
        return sum(sample.error for sample in self.recent) / len(self.recent)

    @property
    def mean_latency(self) -> float:
        """What the recent presses imply the delay to be, in seconds."""
        if not self.recent:
            return 0.0
        return sum(sample.implied for sample in self.recent) / len(self.recent)

    def observe(self, error: float, speed: float) -> None:
        """Take one press, in pixels, at a speed already known to be usable.

        The division is :func:`note_motion.implied_latency` rather than an
        expression written out again here, so that the one place in the project
        turning a pixel error into a delay stays the one place it is written
        down. That it cannot answer ``None`` at a speed which has already
        passed :func:`_trackable_speed` is why the press is not counted below
        without checking: the count is a count of presses the offset was
        learned from, and it should not rise for one that was not.
        """
        implied = note_motion.implied_latency(error, speed)
        if implied is None:
            return
        self.count += 1
        self.pending.append(implied)
        self.recent.append(Sample(error=error, implied=implied))
        if len(self.pending) < WINDOW_PRESSES:
            return
        mean = sum(self.pending) / len(self.pending)
        self.pending.clear()
        self._step(mean)

    def flush(self) -> bool:
        """Use a part-filled window anyway, because the run is moving on.

        The game raises the speed every ten fish whether the window is ready
        or not, and the presses already made are still evidence about a
        latency that does not care what speed the game has reached. What was
        gathered is used and dropped, so a run that keeps getting cut short
        still learns something on the way past.
        """
        if len(self.pending) < MIN_FLUSH_PRESSES:
            self.pending.clear()
            return False
        mean = sum(self.pending) / len(self.pending)
        self.pending.clear()
        self._step(mean)
        return True

    def _step(self, mean: float) -> None:
        """Close :data:`GAIN` of the gap between the measured delay and ours."""
        if self.latency is None:
            self.latency = _clamp_latency(mean)
            return
        step = max(
            -MAX_STEP_LATENCY,
            min(MAX_STEP_LATENCY, GAIN * (mean - self.latency)),
        )
        self.latency = _clamp_latency(self.latency + step)


class OffsetLearner:
    """The search window's position, from one learned press latency.

    Not thread safe, and does not need to be: only the game loop touches it,
    from its own thread.
    """

    def __init__(self) -> None:
        self._cell = LatencyCell()

    @property
    def cell(self) -> LatencyCell:
        """The learning state, for a test or a readout to look at."""
        return self._cell

    def offset_for(
        self,
        speed_level: Optional[int] = None,
        chain: int = 0,
        speed_px_s: Optional[float] = None,
    ) -> int:
        """Where the search window should sit, in pixels, negative for left.

        Without a measured velocity this is the level's starting guess, which
        is what it has always been. With one it is the learned latency scaled
        by that velocity, which is the same distance the guess described, and
        a different one at every speed the notes are actually running.
        """
        return self._modelled_offset(speed_level, chain, speed_px_s)

    def observe(
        self,
        error: float,
        speed_level: Optional[int] = None,
        chain: int = 0,
        speed_px_s: Optional[float] = None,
    ) -> None:
        """Tell it how far early or late a press was, in pixels, and how fast
        the note it was aimed at was going.

        Three presses are dropped without touching the learned latency. A press
        with no usable velocity says nothing about a delay, because the
        divisor is the whole question. A press with no level is dropped for
        the reason the game loop already drops it before calling here: until
        the panel has said what level this is the level is a guess off the
        chain, and a guess is not worth learning from. The velocity model
        makes the level far less important than it used to be, but the guard
        is the loop's to make and this does not quietly undo it.
        """
        speed = _trackable_speed(speed_px_s)
        if speed is None or speed_level is None:
            return
        self._anchor(speed, seed_offset(speed_level, chain))
        self._cell.observe(error, speed)

    def report(
        self,
        speed_level: Optional[int] = None,
        chain: int = 0,
        speed_px_s: Optional[float] = None,
    ) -> dict:
        """What the offset in use is and where it came from, for the window.

        ``level``, ``seed``, ``offset``, ``learned``, ``presses``,
        ``mean_error`` and ``settling`` mean what they always did. The three
        new keys say what the model is doing: how long the presses are landing
        late, how fast the note was, and whether the velocity model is the
        thing answering or the level table is. ``mean_error`` stays in pixels
        because pixels are what the offset is applied in and what the player
        reading the window is judging the bot by.
        """
        level = effective_level(speed_level, chain)
        seed = seed_offset(speed_level, chain)
        speed = _trackable_speed(speed_px_s)
        offset = self._modelled_offset(speed_level, chain, speed_px_s)
        latency = self._cell.latency
        return {
            "level": level,
            "offset": offset,
            "seed": seed,
            "learned": offset != seed,
            "presses": self._cell.count,
            "mean_error": self._cell.mean,
            "settling": len(self._cell.pending),
            "latency_ms": None if latency is None else latency * 1000.0,
            "speed_px_s": speed,
            "modelled": speed is not None and latency is not None,
        }

    def flush(self) -> None:
        """Use the part-filled window, for a run that has stopped.

        Not needed while the game is playing: the pending presses are evidence
        about a latency that does not change with the speed, so a level
        moving on is no longer a reason to spend them. It is here so that a
        value can be read out of a learner that was fed presses and then
        abandoned.
        """
        self._cell.flush()

    def _anchor(self, speed: float, seed: int) -> None:
        """Set the latency once, on the first velocity, so nothing jumps.

        The latency is chosen so that the offset the model produces at this
        velocity is the offset the level table would have produced for this
        level. That is measured data being reinterpreted rather than a new
        guess: the table is a claim about how late this machine's presses are,
        and the only thing the model changes is the claim being multiplied by
        a velocity instead of read off a dial. The first note through the
        model is therefore the last note's window, unchanged.
        """
        if self._cell.latency is not None or self._cell.anchored:
            return
        self._cell.latency = _clamp_latency(-seed / speed)
        self._cell.anchored = True

    def _modelled_offset(
        self,
        speed_level: Optional[int],
        chain: int,
        speed_px_s: Optional[float],
    ) -> int:
        speed = _trackable_speed(speed_px_s)
        seed = seed_offset(speed_level, chain)
        if speed is None:
            return seed
        self._anchor(speed, seed)
        latency = self._cell.latency
        if latency is None:
            return seed
        return _clamp_offset(round(-latency * speed))
