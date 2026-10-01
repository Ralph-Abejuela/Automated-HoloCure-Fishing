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
#: speed by one level every 10 fish, and caps the level at 7. Only the
#: fallback uses this: the panel says what level the game is actually at.
CHAIN_AT_MAX_SPEED = 70

#: The fastest the game goes, and the level it counts from.
MAX_SPEED_LEVEL = 7


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

    def offset(self, fish_count: int, speed_level: Optional[int] = None) -> int:
        """Where the note search window has to move to, given the speed.

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

        ``speed_level`` is the level the game's own panel is showing, which is
        the thing the note speed actually follows, so it is what this uses
        when it has one: 0 at level 1, and 15 pixels to the left at level 7,
        the cap.

        Without one, it falls back to the chain the bot counted itself, on the
        game's rule that the level rises by one every 10 fish up to a chain
        of 70. That is a guess about the game's state made from the bot's
        own count, and it is only ever a fallback now: the panel is read
        directly, so a missed fish or a bonus one no longer leaves the
        compensation answering for a speed the notes are not travelling at.

        The 15 is measured, not derived, because the latency belongs to the
        machine, its loop rate and its timing settings, not to the game. If
        the notes start being missed, this is the number to widen.
        """
        if speed_level is not None:
            level = min(max(speed_level, 1), MAX_SPEED_LEVEL)
            return math.floor(
                -OFFSET_AT_MAX_SPEED * (level - 1) / (MAX_SPEED_LEVEL - 1)
            )
        reached = min(fish_count, CHAIN_AT_MAX_SPEED)
        return math.floor(-OFFSET_AT_MAX_SPEED * reached / CHAIN_AT_MAX_SPEED)


