"""Reading what the game thought of each key press.

After a note is hit, the game writes a word under the circle: GOOD! for a
clean hit, OK for one that landed early or late, BAD for a miss. That is the
only honest measure of whether a press worked, and the bot cannot work it out
for itself: it knows when it pressed and roughly where the note was, not what
the game made of it.

The words are read by colour and width rather than by matching a template
against the whole word, because two grades are usually on screen at once. A
press is judged a moment after it happens and the word for the press before it
is still fading underneath, so the fresh one is counted and the faded one,
which is a blend towards the dark ground, is not.

Freshness is what the colour is for. A crisp word is the game's own colour;
a fading one is that colour mixed into the background, so it lands nowhere
near it. A word that is only half faded therefore reads as no word at all,
rather than as a wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

#: The words sit under the target circle, in the same 360p base coordinates
#: the loops work in: left, top, width, height.
ROI = (368, 268, 52, 24)

#: Inside that box, where each word's ink actually falls, as (x0, y0, x1, y1)
#: relative to the box. Measured off frames of each, not guessed.
GOOD_BOX = (5, 0, 44, 16)
OK_BOX = (9, 2, 34, 18)

#: The colours the game draws the words in, as BGR, taken from the crisp
#: pixels of real frames. A pixel has to be near one of these to count: a
#: fading word is the same colour mixed into the dark background and lands
#: well outside the window.
BLUE = (247, 132, 64)
RED = (29, 29, 202)
COLOUR_TOLERANCE = 60

#: How much of a word has to be there to believe it. A word is a few hundred
#: pixels at this size, and a grade caught mid-fade can be well under a
#: hundred.
MIN_INK = 60

#: GOOD! and OK are the same colour, and are told apart by how wide the word
#: is: GOOD! runs the width of the box, OK is a third of it.
WIDE_ENOUGH = 30


@dataclass(frozen=True)
class Grade:
    """What the panel under the circle says, if anything."""

    #: "GOOD", "OK", "BAD", or None where there is no fresh word.
    grade: Optional[str] = None
    #: Pixels of each colour, and how wide the word runs.
    blue: int = 0
    red: int = 0
    width: int = 0

    @property
    def seen(self) -> bool:
        return self.grade is not None


def _near(patch: np.ndarray, colour, tolerance: int = COLOUR_TOLERANCE) -> np.ndarray:
    distance = np.abs(patch.astype(int) - np.array(colour)).max(axis=2)
    return distance <= tolerance


def read_grade(patch: np.ndarray) -> Grade:
    """Read the grade out of a capture of :data:`ROI`, at the 360p base.

    ``patch`` is the capture already resized, the way the loops resize the
    note area before looking at it.
    """
    blue = _near(patch, BLUE)
    red = _near(patch, RED)

    red_pixels = int(red.sum())
    blue_pixels = int(blue.sum())
    if red_pixels >= MIN_INK:
        return Grade(grade="BAD", blue=blue_pixels, red=red_pixels)

    if blue_pixels >= MIN_INK:
        ink = blue[GOOD_BOX[1] : GOOD_BOX[3], GOOD_BOX[0] : GOOD_BOX[2]]
        columns = np.flatnonzero(ink.any(axis=0))
        width = int(columns.max() - columns.min() + 1) if len(columns) else 0
        return Grade(
            grade="GOOD" if width >= WIDE_ENOUGH else "OK",
            blue=blue_pixels,
            red=red_pixels,
            width=width,
        )

    return Grade(blue=blue_pixels, red=red_pixels)
