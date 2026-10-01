import math
from abc import ABC, abstractmethod
from typing import Callable, Optional, Tuple
from numpy import ndarray

import timings
from timings import Timings, default_timings

#: How far left the note search window has to have moved by the time the game
#: is at its top speed. See Platform.offset for why it moves at all.
OFFSET_AT_MAX_SPEED = 15

#: The chain at which the game stops getting faster. HoloCure raises the note
#: speed by one level every 10 fish, and caps the level at 7.
CHAIN_AT_MAX_SPEED = 70


class Platform(ABC):

    #: Installed by main() so press_key() and friends can read the timings
    #: the user configured. Left None, they fall back to the built-in
    #: defaults for the running platform.
    timings: Optional[Timings] = None

    #: Installed by the monitor window so waiting for the game can be
    #: interrupted. Left None, which is the console run, it never stops.
    stop_check: Optional[Callable[[], bool]] = None

    def stopping(self) -> bool:
        """True when someone has asked the game loops to finish."""
        return self.stop_check is not None and self.stop_check()

    def timing(self, name: str) -> float:
        """Return the configured value of a timing, or its default."""
        source = self.timings if self.timings is not None else default_timings()
        return source[name]

    @abstractmethod
    def wait_until_application_handle(self):
        """
        Sleep until the Holocure application is found, after which the application handle is stored.
        """
        pass

    @abstractmethod
    def holocure_screenshot(self, roi=None) -> Optional[ndarray]:
        """Take a screenshot of Holocure

        Note: this is contingent on platform.wait_until_application_handle() being called first!

        Parameters
        ----------
        roi : tuple of 4 ints containing leftmost, topmost pixel, width, height of the area
        that needs to be captured.

        Returns
        -------
        np.ndarray, containing raw image data in BGRA format,
        None if screenshotting was unsuccessful
        """
        pass

    @abstractmethod
    def config_file_path(self) -> Optional[str]:
        """Find the file path to the Holocure settings.json file.

        On windows, is located under "<User folder>/AppData/Local/HoloCure/settings.json"

        On Linux with Steam Proton can be located in a number of places

        Returns
        -------
        file path: str, to the Holocure settings.json file,
        None if the path could not be found
        """
        pass

    @abstractmethod
    def get_holocure_bounds(self) -> Tuple[int, int, int, int]:
        """Get the location of the Holocure window within the display(s)

        Note: this is contingent on platform.wait_until_application_handle() being called first!

        Returns
        -------
        A tuple of
            x: int, horizontal location, from the left rightwards
            y: int, vertical location, from the top downwards
            width: int
            height: int
        """
        pass

    @abstractmethod
    def press_key(self, key: str):
        """Press a key

        Note: this is contingent on platform.wait_until_application_handle() being called first!

        Parameters
        ----------
        key: str, the key string
            TODO: not platform-agnostic for now, most windows keybinds should also work on linux
        """
        pass

    def offset(self, fish_count: int) -> int:
        """Where the note search window has to move to, given the chain.

        The notes slide left to right towards a target circle, and the bot
        presses as soon as one reaches the window it is watching. That press
        never lands instantly: the loop was already part way through a poll
        when the note turned up, then the key has to go down and the game has
        to see it. Call that whole pipeline the latency.

        A slow note spends the latency covering few pixels, so a fixed window
        works. A fast one covers a lot more, and the same press lands that
        much further past the circle than it should, until it falls outside
        the window the game accepts. So the search has to start earlier, by
        however far a note travels during the latency, and the further the
        game speeds up the more that is.

        HoloCure raises the note speed by one level every 10 fish caught in a
        row and caps it at 7 levels, which it reaches at a chain of 70. This
        returns the compensation in pixels, growing with the chain and
        stopping there: 0 at the start of a chain, and 15 pixels to the left
        at the cap.

        The 15 is measured, not derived, because the latency belongs to the
        machine, its loop rate and its timing settings, not to the game. If
        the notes start being missed, this is the number to widen.
        """
        reached = min(fish_count, CHAIN_AT_MAX_SPEED)
        return math.floor(-OFFSET_AT_MAX_SPEED * reached / CHAIN_AT_MAX_SPEED)


