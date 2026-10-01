from abc import ABC, abstractmethod
from typing import Callable, Optional, Tuple
from numpy import ndarray

import timings
from timings import Timings, default_timings


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

    @abstractmethod
    def offset(self, fish_count: int) -> int:
        """Specify the offset from the main circle when we should hit the key.

        Parameters
        ----------
        fish_count : int,

        Returns
        -------
        An int, the offset in pixels, right is positive
        """
        pass
  

