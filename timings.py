"""User-tunable delays and loop rates for the fishing and mining loops.

These used to be hardcoded sleeps sprinkled through ``holocure_fishing.py``
and the platform modules. They live here instead, so ``timings_cli.py`` and
``timings_gui.py`` can change them without editing code.

Values are stored as seconds in a flat JSON file (``timings.json`` next to
this module by default) so a hand-edited file stays readable. The GUI shows
milliseconds, which is easier to type.

A few timings differ per platform: the key press gap is longer on Linux
because X needs a frame between press and release. Those defaults are
listed in ``TimingSpec.platform_default``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

#: Overrides the location of the timings file when set.
ENV_VAR = "HCF_TIMINGS_FILE"

#: File name used when no path is given.
CONFIG_FILENAME = "timings.json"

#: A delay in seconds. The GUI edits these as milliseconds.
KIND_DELAY = "delay"

#: A plain number of repeats, never shown with a unit.
KIND_COUNT = "count"


class TimingError(Exception):
    """A timing value is missing, unparseable or out of range."""


@dataclass(frozen=True)
class TimingSpec:
    """One editable timing: what it is called, what it may be set to."""

    name: str
    kind: str
    default: float
    description: str
    minimum: float = 0.0
    maximum: float = 10.0
    platform_default: Optional[Mapping[str, float]] = None

    def default_for(self, platform: Optional[str]) -> float:
        """Return the default for ``platform``, falling back to the generic one."""
        if platform and self.platform_default:
            if platform in self.platform_default:
                return self.platform_default[platform]
        return self.default

    @property
    def is_delay(self) -> bool:
        return self.kind == KIND_DELAY


TIMINGS = (
    TimingSpec(
        "keypress_gap",
        KIND_DELAY,
        0.015,
        "Wait between a key going down and coming back up.",
        maximum=1.0,
        platform_default={"linux": 0.03},
    ),
    TimingSpec(
        "window_search_interval",
        KIND_DELAY,
        1.0,
        "Wait between searches for the HoloCure window while it is closed.",
        maximum=60.0,
    ),
    TimingSpec(
        "config_poll_interval",
        KIND_DELAY,
        1.0,
        "How often HoloCure's settings.json is re-read for keybinds.",
        maximum=60.0,
    ),
    TimingSpec(
        "fishing_key_delay",
        KIND_DELAY,
        0.2,
        "Wait after pressing a rhythm-game arrow.",
        maximum=5.0,
    ),
    TimingSpec(
        "fishing_ok_gap",
        KIND_DELAY,
        0.01,
        "Wait between the Enter presses that dismiss the fishing prompt.",
        maximum=5.0,
    ),
    TimingSpec(
        "fishing_ok_presses",
        KIND_COUNT,
        6,
        "How many times Enter is pressed to dismiss the fishing prompt.",
        minimum=1,
        maximum=20,
    ),
    TimingSpec(
        "fishing_loop_interval",
        KIND_DELAY,
        0.01,
        "Target duration of one fishing loop, which caps it at 100 Hz.",
        maximum=1.0,
    ),
    TimingSpec(
        "mining_enter_delay",
        KIND_DELAY,
        0.4,
        "Wait after pressing Enter on the mining pointer.",
        maximum=5.0,
    ),
    TimingSpec(
        "mining_ok_gap",
        KIND_DELAY,
        0.01,
        "Wait between the Enter presses that dismiss the mining prompt.",
        maximum=5.0,
    ),
    TimingSpec(
        "mining_ok_presses",
        KIND_COUNT,
        5,
        "How many times Enter is pressed to dismiss the mining prompt.",
        minimum=1,
        maximum=20,
    ),
)

#: Specs by name, in the order they are shown and written.
SPECS: Dict[str, TimingSpec] = {spec.name: spec for spec in TIMINGS}


def normalize_platform(platform: Optional[str]) -> str:
    """Reduce a platform name to ``"windows"`` or ``"linux"``."""
    if platform is None:
        platform = sys.platform
    if platform.startswith("linux"):
        return "linux"
    if platform.startswith("win"):
        return "windows"
    return platform


def default_path() -> Path:
    """Return the timings file location, honouring ``HCF_TIMINGS_FILE``."""
    from_env = os.environ.get(ENV_VAR)
    if from_env:
        return Path(from_env).expanduser()
    return Path(__file__).resolve().parent / CONFIG_FILENAME


def parse_value(spec: TimingSpec, text: Any) -> float:
    """Turn user input into a number of the right kind.

    Delays accept a unit suffix (``250ms``, ``0.25``, ``1s``) and are always
    stored as seconds. Counts must be whole numbers.

    Raises:
        TimingError: if the text is not a number, carries an unknown unit, or
            falls outside the spec's range.
    """
    if isinstance(text, bool):
        raise TimingError(f"{spec.name}: expected a number, got a boolean")
    if isinstance(text, (int, float)):
        value = float(text)
        if not spec.is_delay and value != int(value):
            raise TimingError(f"{spec.name}: expected a whole number, got {text!r}")
        return _check_range(spec, value)

    raw = str(text).strip().lower().replace(" ", "")
    if not raw:
        raise TimingError(f"{spec.name}: value is empty")

    multiplier = 1.0
    for suffix, factor in (("ms", 0.001), ("s", 1.0)):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            multiplier = factor
            break

    try:
        value = float(raw) * multiplier
    except ValueError:
        raise TimingError(f"{spec.name}: {text!r} is not a number") from None

    if not spec.is_delay and value != int(value):
        raise TimingError(f"{spec.name}: expected a whole number, got {text!r}")
    return _check_range(spec, int(value) if not spec.is_delay else value)


def _check_range(spec: TimingSpec, value: float) -> float:
    if value < spec.minimum or value > spec.maximum:
        shown = int(value) if not spec.is_delay else value
        raise TimingError(
            f"{spec.name}: {shown} is outside the allowed range "
            f"{spec.minimum} to {spec.maximum}"
        )
    return int(value) if not spec.is_delay else value


def format_value(spec: TimingSpec, value: float) -> str:
    """Render a value the way the GUI shows it: milliseconds or a count."""
    if not spec.is_delay:
        return str(int(value))
    return f"{round(value * 1000, 3):g}"


def validate(values: Mapping[str, Any], platform: Optional[str] = None) -> Dict[str, float]:
    """Coerce a partial mapping into a complete, checked timing table.

    Missing names fall back to their defaults for ``platform``.

    Raises:
        TimingError: if any name is unknown or any value is out of range.
            Every problem found is listed, not just the first.
    """
    problems = []
    for name in sorted(values):
        if name not in SPECS:
            near = _suggest(name)
            problems.append(f"unknown timing {name!r}{near}")

    result: Dict[str, float] = {}
    for spec in TIMINGS:
        if spec.name not in values:
            result[spec.name] = spec.default_for(normalize_platform(platform))
            continue
        try:
            result[spec.name] = parse_value(spec, values[spec.name])
        except TimingError as error:
            problems.append(str(error))

    if problems:
        raise TimingError("\n".join(problems))
    return result


def _suggest(name: str) -> str:
    """Offer the closest known name, if one is close enough to be a typo."""
    import difflib

    matches = difflib.get_close_matches(str(name).lower(), SPECS, n=1, cutoff=0.6)
    return f", did you mean {matches[0]!r}?" if matches else ""


class Timings:
    """The timing table in use, backed by a JSON file.

    Load order is defaults, then the file, then ``overrides``. Missing names
    in the file are not an error: a file written by an older version of the
    program still loads, and the names it lacks keep their defaults.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        platform: Optional[str] = None,
        overrides: Optional[Mapping[str, Any]] = None,
        *,
        read_file: bool = True,
    ):
        self.path = Path(path) if path is not None else default_path()
        self.platform = normalize_platform(platform)
        self._values: Dict[str, float] = {
            spec.name: spec.default_for(self.platform) for spec in TIMINGS
        }
        self._mtime: Optional[float] = None
        self._warned = False

        if read_file:
            self.reload()

        if overrides:
            # Overrides are command line input, so they are strict about
            # names and ranges but still tolerate a partial table.
            self._values.update(validate(dict(overrides), self.platform))

    # -- reading ---------------------------------------------------------

    def __getitem__(self, name: str) -> float:
        try:
            return self._values[name]
        except KeyError:
            raise KeyError(
                f"unknown timing {name!r}{_suggest(name)}"
            ) from None

    def get(self, name: str, fallback: Optional[float] = None) -> float:
        """Return a timing, or ``fallback`` if the name is unknown."""
        return self._values.get(name, fallback)

    @property
    def values(self) -> Dict[str, float]:
        """A copy of the whole table, in display order."""
        return dict(self._values)

    def is_default(self, name: str) -> bool:
        """True when ``name`` still holds its default, i.e. the file does not set it."""
        return self[name] == SPECS[name].default_for(self.platform)

    def reload(self) -> None:
        """Re-read the file, replacing the table.

        Raises:
            TimingError: if the file is not valid JSON or holds a bad value.
        """
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._values = {
                spec.name: spec.default_for(self.platform) for spec in TIMINGS
            }
            self._mtime = self._stat()
            return
        except json.JSONDecodeError as error:
            raise TimingError(f"{self.path}: invalid JSON ({error})") from None

        if not isinstance(raw, dict):
            raise TimingError(f"{self.path}: expected a JSON object of timings")

        self._values = validate(raw, self.platform)
        self._mtime = self._stat()
        self._warned = False

    def reload_if_changed(self) -> bool:
        """Reload when the file changed on disk. Returns True if it did.

        Used by the game loops so the GUI or CLI can change a delay without a
        restart. A file that is momentarily invalid - a half-written save, or
        a typo - is reported once and then ignored until it changes again, so a
        running game never dies over a bad edit.
        """
        mtime = self._stat()
        if mtime == self._mtime:
            return False

        try:
            self.reload()
        except TimingError as error:
            if not self._warned:
                print(f"Warning: keeping previous timings, {error}", file=sys.stderr)
                self._warned = True
            self._mtime = mtime
            return False
        return True

    def _stat(self) -> Optional[float]:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    # -- writing ---------------------------------------------------------

    def save(self, values: Optional[Mapping[str, Any]] = None) -> Path:
        """Write the table to ``self.path`` and return the path.

        ``values`` is a partial update: names it does not mention keep the value
        they have now, so saving one timing never resets the others.

        Raises:
            TimingError: if any value is invalid; nothing is written then.
        """
        table = (
            dict(self._values)
            if values is None
            else validate({**self._values, **values}, self.platform)
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temporary file and move it into place, so a reader (the
        # game loop) never sees a half-written file.
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(
                # Round so a value typed as 350ms comes back as 0.35, not
                # 0.35000000000000003.
                {spec.name: round(table[spec.name], 6) for spec in TIMINGS},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

        self._values = table
        self._mtime = self._stat()
        self._warned = False
        return self.path

    def reset(self, names: Optional[Iterable[str]] = None) -> Dict[str, float]:
        """Return the named timings (or all of them) to their defaults, in memory.

        Call :meth:`save` to keep the change.
        """
        wanted = list(SPECS) if names is None else list(names)
        for name in wanted:
            self[name]  # validates the name before touching anything
        for name in wanted:
            spec = SPECS[name]
            self._values[name] = spec.default_for(self.platform)
        return {name: self._values[name] for name in wanted}

    def __repr__(self) -> str:
        return f"Timings(path={str(self.path)!r}, platform={self.platform!r})"


_DEFAULTS_CACHE: Dict[str, Timings] = {}


def default_timings() -> Timings:
    """A shared, in-memory table of defaults for the running platform.

    Never reads the file: it is the fallback for code that wants a timing
    without a config (the platform classes, before ``main`` installs one).
    """
    platform = normalize_platform(None)
    if platform not in _DEFAULTS_CACHE:
        _DEFAULTS_CACHE[platform] = Timings(read_file=False, platform=platform)
    return _DEFAULTS_CACHE[platform]
