"""Reading the chain and the speed level off the game's own panel.

The bot used to count the catches it thought it had made and infer the note
speed from that number. It cannot check its own work: a missed fish, a bonus
one, or a run started half way through a chain all leave the count disagreeing
with the game, and the offset that depends on it is then compensating for a
speed that is not the speed the notes are travelling at. The panel in the top
right of the fishing screen says both numbers outright, so that is what gets
read.

The numbers are drawn in the game's own pixel font, at a fixed place, in
fixed-width cells: three cells for the chain, one for the speed level. Each
glyph is matched against the templates cut out of real frames, by counting
the pixels that disagree, because the font never varies and an exact
comparison is both simpler and stricter than a colour match.

A cell whose pixels match no known digit is reported as unread rather than
guessed at, and the caller keeps whatever it read last. The same goes for a
digit with no template yet: they are cut from frames of a real run, so the
digits that run has not reached yet are simply not there to be matched.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

#: The panel, in the same 360p base coordinates the loops work in: left, top,
#: width, height. It holds both readouts and nothing else, so it is safe to
#: take on its own while the notes are playing.
ROI = (496, 230, 68, 58)

#: Where the chain's three digits sit inside the ROI, as (x0, y0, x1, y1).
#: The cells are fixed: the number does not shuffle along as it changes
#: length, and a cell with nothing in it is a digit that is not drawn yet.
CHAIN_CELLS = (
    (30, 4, 42, 22),
    (42, 4, 54, 22),
    (54, 4, 66, 22),
)

#: Where the speed level sits inside the ROI, in its own smaller font. It is
#: cut wider than the digit needs on purpose: a 1 is a narrow glyph against
#: the left edge of its cell, and a cell sized to the 7 clips it.
SPEED_CELL = (0, 44, 14, 58)

#: What counts as a match, in pixels that disagree. The font is drawn the same
#: every time, so a real digit matches exactly; anything above this is a frame
#: caught mid-redraw, and is better reported as unread than believed.
MATCH_TOLERANCE = 3

#: The panel is white and red text on a dark background. The chain is white,
#: and the speed line is red, which no amount of brightness picks up.
WHITE_LEVEL = 140
RED_LEVEL = 110
RED_CEILING = 90

TEMPLATE_DIR = Path(__file__).resolve().parent / "img" / "360p"


@dataclass(frozen=True)
class PanelRead:
    """What the panel said, and how much of it was legible."""

    chain: Optional[int] = None
    speed: Optional[int] = None
    #: Cells that had ink in them but matched no known digit, as
    #: ``"chain"`` or ``"speed"``, for the log and the monitor.
    unreadable: Tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return self.chain is not None


@lru_cache(maxsize=None)
def _templates(folder: str) -> Dict[str, np.ndarray]:
    """The digit templates in ``folder``, by name, as boolean ink masks.

    A folder with a template missing is not an error: it is a digit this run
    has never needed. :func:`missing` says which ones they are.
    """
    found = {}
    for path in sorted((TEMPLATE_DIR / folder).glob("*.png")):
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None or image.ndim != 3 or image.shape[2] != 4:
            continue
        # Black on transparent: the alpha channel is the glyph, and matching
        # that against the panel's own ink is what the comparison is for.
        found[path.stem] = image[..., 3] > 0
    return found


def missing() -> Dict[str, List[str]]:
    """Which digits have no template yet, by font."""
    return {
        font: sorted(set("0123456789") - set(_templates(folder)))
        for font, folder in (("chain", "digits"), ("speed", "speed"))
    }


def _ink(panel: np.ndarray, red: bool) -> np.ndarray:
    """The lit pixels of the panel, as a boolean mask."""
    if red:
        blue, green, r = panel[:, :, 0], panel[:, :, 1], panel[:, :, 2]
        return (r > RED_LEVEL) & (green < RED_CEILING) & (blue < RED_CEILING)
    return panel.min(axis=2) > WHITE_LEVEL


def _cell_digit(cell: np.ndarray, templates: Dict[str, np.ndarray]) -> Optional[str]:
    """The digit whose template disagrees with ``cell`` least, if any is close.

    Cells are the size of the templates by construction, so a cell of another
    shape is something else entirely and is reported unread rather than
    compared.
    """
    if not cell.any():
        return None
    best, runner_up = None, None
    for digit, template in templates.items():
        if template.shape != cell.shape:
            continue
        disagreement = int(np.count_nonzero(template != cell))
        if best is None or disagreement < best[0]:
            best, runner_up = (disagreement, digit), best
        elif runner_up is None or disagreement < runner_up[0]:
            runner_up = (disagreement, digit)
    if best is None or best[0] > MATCH_TOLERANCE:
        return None
    # Two digits that are equally good are not a reading.
    if runner_up is not None and runner_up[0] == best[0]:
        return None
    return best[1]


def read_panel(panel: np.ndarray) -> PanelRead:
    """Read the chain and the speed level out of a capture of :data:`ROI`.

    ``panel`` is the capture already resized to the 360p base, the same way
    the loops resize the note area before looking at it.
    """
    chain_templates = _templates("digits")
    speed_templates = _templates("speed")
    unreadable = []

    digits = []
    for x0, y0, x1, y1 in CHAIN_CELLS:
        cell = _ink(panel, red=False)[y0:y1, x0:x1]
        digit = _cell_digit(cell, chain_templates)
        if digit is None and cell.any():
            unreadable.append("chain")
        elif digit is not None:
            digits.append(digit)

    # An empty leading cell is a number that has not reached three digits, so
    # the digits that are there are the whole number, wherever they sit.
    chain = int("".join(digits)) if digits and not unreadable else None

    x0, y0, x1, y1 = SPEED_CELL
    speed_cell = _ink(panel, red=True)[y0:y1, x0:x1]
    speed_digit = _cell_digit(speed_cell, speed_templates)
    if speed_digit is None and speed_cell.any():
        unreadable.append("speed")

    return PanelRead(
        chain=chain,
        speed=int(speed_digit) if speed_digit is not None else None,
        unreadable=tuple(unreadable),
    )
