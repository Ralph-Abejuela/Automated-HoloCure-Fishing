"""Measuring how fast the notes actually move, instead of assuming.

The search window is moved to cancel press latency, and the offset that does
that is a physical quantity: a press that takes ``latency`` seconds to reach
the game has to be made that much earlier, which at a note speed of ``v``
pixels a second is ``-latency * v`` pixels. Every part of that product was
being guessed. The latency was a number somebody measured on one machine once.
The speed was taken off the HUD panel, on the reasoning that the speed level
means one speed.

The level does not mean one speed. Two species at the same level travel at
different pixel speeds, so a single learned offset per level cannot be right
for both, and the notes a learner gets wrong are exactly the ones from the
species it has not seen. Nothing on the panel says how fast the pixels are
going, so the speed has to be measured, and it can be: the loop matches the
same note on several consecutive iterations, a note is thirty pixels wide in a
window that barely moves between frames, and the difference of two positions
divided by the difference of two clock readings is the speed, to the accuracy
the template matching gives.

What makes this awkward is that the only evidence arrives while a note is on
screen, and by then the press that consumes it is the same iteration. So the
reading belongs to a note that is already gone: it is a description of the
strip rather than a prediction of the next note, and it is worth exactly as
much as the last one was worth. Which is why the estimate is smoothed over
several raw samples, and why an implausible reading is thrown away without
disturbing the last good one.

Two failures are guarded against specifically. A note can be measured twice
with the clock not advancing, or not advancing usefully, which would divide by
nothing or by almost nothing; and a note that appears not to move right is not
a slow note, it is a new note that happened to be matched one frame after the
old one was consumed, or a mis-match inside the strip. Both restart tracking
rather than producing a number, because a number is what the caller will act
on and a wrong one is worse than none.

What this does not know: it never sees the notes that arrive and are pressed
and gone within a single iteration, so a strip running much faster than the
loop would leave it with nothing to say. That has not been observed, but it is
the limit of the method and the reason the caller must treat a missing reading
as normal rather than as a fault.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

#: The slowest note speed believed to be real, in pixels a second. Below this
#: the note is not travelling, it is a mis-match or a still frame, and the
#: reading it gives is not a velocity. It also keeps a near-stationary note
#: from dividing a pixel error into a nonsense latency later on.
MIN_SPEED_PX_S = 10.0

#: The fastest note speed believed to be real, in pixels a second. The strip
#: is a few hundred pixels long and a note crosses it in about a second, so
#: anything near this figure comes from a clock that barely moved between two
#: matches rather than from a note that really is that quick.
MAX_SPEED_PX_S = 4000.0


@dataclass(frozen=True)
class Motion:
    """One note's measured speed, as of the reading just taken."""

    #: Which arrow the reading came from. Only the key that matched on this
    #: frame is ever tracked, so this is the key the caller should believe.
    key: str
    #: The smoothed speed, in pixels a second, positive because notes travel
    #: left to right towards the circle.
    px_per_second: float
    #: How many raw speed samples that figure is a mean of. Fewer than the
    #: smoothing window early on, and it says so rather than pretending.
    samples: int


def implied_latency(error_px: float, px_per_second: float) -> Optional[float]:
    """The press latency a miss of ``error_px`` at that speed works out to.

    Negative is early, matching the sign of the error itself, so the caller
    gets one number that means "seconds late" in either direction. It is
    ``None`` at a speed too slow to measure: an error at an unknowable speed
    is not evidence of anything, and dividing by a number near zero would
    report an enormous latency as if it had been found.
    """
    if not math.isfinite(px_per_second) or px_per_second < MIN_SPEED_PX_S:
        return None
    return -error_px / px_per_second


class NoteTracker:
    """Turns successive matches of the same note into a note speed.

    :meth:`update` is called once per loop iteration with the key that matched
    this frame and where its centre landed. It answers with a :class:`Motion`
    when it has a speed worth acting on, and with ``None`` when it does not:
    the first sighting of a note, and any frame it had to throw away. A
    ``None`` is the normal answer and not a fault.

    Not thread safe, and does not need to be: only the game loop touches it,
    from its own thread.
    """

    def __init__(self, max_gap: float = 0.25, smoothing: int = 5) -> None:
        self._max_gap = max_gap
        self._smoothing = smoothing
        #: The key, centre and clock of the sample the next one is measured
        #: against, and ``None`` for each before anything has been seen.
        self._key: Optional[str] = None
        self._centre: Optional[float] = None
        self._now: Optional[float] = None
        #: The recent accepted speeds, oldest first, from which the reported
        #: speed is the mean.
        self._speeds: Deque[float] = deque(maxlen=smoothing)
        self._last: Optional[Motion] = None

    @property
    def last(self) -> Optional[Motion]:
        """The most recent good reading, which outlives a bad frame after it."""
        return self._last

    @property
    def last_speed(self) -> Optional[float]:
        """Just the speed from :attr:`last`, for callers that want no more."""
        return None if self._last is None else self._last.px_per_second

    def reset(self) -> None:
        """Forget everything, at a catch or a chain change.

        Nothing before the reset is a measurement of anything after it: a new
        fish is a different species at a different speed, and the window will
        be moved by whatever this last reported if it is carried over.
        """
        self._key = None
        self._centre = None
        self._now = None
        self._speeds.clear()
        self._last = None

    def update(self, key: str, centre_x: float, now: float) -> Optional[Motion]:
        """Take one match of ``key`` and say what speed it implies.

        The previous sample only counts if it was the same key, the clock moved
        forward by no more than the gap allowed, and the note moved right.
        Anything else is a different note rather than this one further along,
        so tracking restarts and this call answers ``None``.
        """
        usable = (
            self._key == key
            and self._centre is not None
            and self._now is not None
            and 0.0 < now - self._now <= self._max_gap
            and centre_x > self._centre
        )
        if not usable:
            self._restart(key, centre_x, now)
            return None

        speed = (centre_x - self._centre) / (now - self._now)
        # The baseline moves on even when the reading is refused, so that a
        # frame which was good for nothing still leaves somewhere to measure
        # the next one from.
        self._centre = centre_x
        self._now = now
        if not math.isfinite(speed) or not MIN_SPEED_PX_S <= speed <= MAX_SPEED_PX_S:
            # Refused, and deliberately not recorded: one impossible reading
            # must not be averaged into the estimate, and must not cost the
            # caller the last good speed it was still using.
            return None

        self._speeds.append(speed)
        self._last = Motion(
            key=key,
            px_per_second=sum(self._speeds) / len(self._speeds),
            samples=len(self._speeds),
        )
        return self._last

    def _restart(self, key: str, centre_x: float, now: float) -> None:
        """Begin again from this match, dropping the speeds collected so far.

        The window of speeds is dropped because those were measured off a note
        this one has nothing to do with, and averaging them in would report a
        speed that no note on the strip is travelling at.
        """
        self._key = key
        self._centre = centre_x
        self._now = now
        self._speeds.clear()