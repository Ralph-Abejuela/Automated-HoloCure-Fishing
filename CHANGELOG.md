# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

This is the first tagged release. Everything below happened between the last
untagged snapshot and `v0.1.0`, so it is listed together.

## [0.1.0] - 2026-10-01

### Added

- **Every delay is now a timing you can edit.** `timings.json` holds them,
  `timings_cli.py` lists and sets them from a shell, and `timings_gui.py` is
  a window for the same. A run already going picks up a saved change within a
  second, so the delays can be tuned while the bot is playing.
- **A monitor window** (`monitor_gui.py`, or `holocure_fishing.py --gui`)
  that shows what the bot is doing while it does it: the capture region with
  every searched window drawn on it and a dot on each best match, the score
  of every template in the last iteration, every keypress with the grade the
  game gave it and how early or late it landed, the timings in use, and the
  length of each iteration.
- **A compact status in the terminal.** Without `--gui`, a run draws a ten
  line block in the console instead of printing nothing until it ends. Press
  Ctrl+C to stop the run and get the prompt back. `--no-status` turns it off.
- **The chain and the speed level are read off the game's own panel**, rather
  than guessed from the bot's own catch count. A missed fish, a bonus fish or
  a run started half way through a chain used to leave the two disagreeing,
  and the note offset was then compensating for a speed the notes were not
  travelling at.
- **The grade the game gave each press.** The word under the circle is read
  after every keypress, so a run can be told apart from one that presses at
  the right times in the wrong places. The share of GOOD is the number worth
  watching.
- **How early or late each press was, in pixels.** The game writes OK for
  both, so this is the only thing that can tell them apart.
- **The note offset is learned from the presses instead of read from a
  table.** One value is kept per speed level, averaged over a window of
  presses and moved at most 1.5 pixels at a time, so a few notes are mistimed
  while a level settles rather than the value jumping about.
- **A build script**, `build_release.bat`, which produces the Windows binary
  with Nuitka and zips it for the release.

### Fixed

- `fishing_key_delay` no longer caps the bot at five presses a second.
- The note search window moves with the chain, so Windows stops missing
  notes at low chains.
- The timings editor window stays on screen, instead of its value boxes
  disappearing behind it when a description runs long.
- A broken import in `platform_linux.py`.
- The built executable finds its `img/` templates and its `timings.json`
  whatever folder it was started from, and saves timings somewhere writable
  when it was unpacked somewhere read only. The templates used to be read
  through a path relative to the current directory, which worked from the
  project folder and nowhere else.

### Changed

- Setup and launch go through [uv](https://docs.astral.sh/uv/): the
  `requirements.txt` files are replaced by `pyproject.toml` and `uv.lock`.
- The console asks for a mode before each run, as it always did, and the
  built executable is `holocure_fishing.exe` inside the release zip.

[0.1.0]: https://github.com/Ralph-Abejuela/Automated-HoloCure-Fishing/releases/tag/v0.1.0