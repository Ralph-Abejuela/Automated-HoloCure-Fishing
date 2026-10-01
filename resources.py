"""Where the program looks for its files, in every way it can be run.

The scripts read two kinds of file, and they have opposite requirements.

The templates under ``img/`` ship with the program and are only ever read:
they are the pixels the loops match against. :func:`resource_dir` says where
they are, which is this file's own folder when running from source, and the
folder the built executable sits in when it is frozen. Nuitka copies the
data files next to the executable, so one place covers both.

``timings.json`` is the opposite: the user edits it, in the editor window or
by hand, and the running loops re-read it. It has to be somewhere writable,
so :func:`writable_dir` falls back to a per-user folder when the program's
own folder is read only - which is what happens when the folder is Program
Files, or when the executable was unzipped somewhere the user cannot write.

Nothing here touches the network or the game, and nothing is cached, so a
test can move ``timings.json`` and see the path follow it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: The folder the per-user fallback writes to, per platform. Both are the
#: conventional place for a program's own settings on that platform.
FALLBACK_DIRS = {
    "win32": Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    / "Automated-HoloCure-Fishing",
    "linux": Path(
        os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    )
    / "automated-holocure-fishing",
}

#: The name used when no platform specific folder is known.
FALLBACK_NAME = "Automated-HoloCure-Fishing"


def is_frozen() -> bool:
    """True when this is the built program rather than a script."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """The folder the shipped ``img/`` templates are read from.

    Frozen, that is the folder holding the executable: Nuitka puts the data
    files beside it. Unfrozen, it is this file's own folder, which is the
    project root.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def writable_dir() -> Path:
    """A folder this program can write ``timings.json`` and captures into.

    The program's own folder is the first choice, because a file next to the
    executable is the easiest one to find and to edit by hand. It is only a
    choice if it is actually writable, so a frozen copy in a read-only place
    falls back to a per-user folder instead of failing to save.
    """
    base = resource_dir()
    if os.access(base, os.W_OK):
        return base
    fallback = FALLBACK_DIRS.get(sys.platform)
    if fallback is None:
        fallback = Path.home() / f".{FALLBACK_NAME.lower()}"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback