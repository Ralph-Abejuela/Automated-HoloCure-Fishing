"""Command line editor for the timings used by the fishing and mining loops.

Run 'python timings_cli.py list' to see every timing and its current value,
'python timings_cli.py set mining_enter_delay=350ms' to change one, and
'python timings_cli.py gui' to open the same editor as a window.

Values are stored in seconds in a JSON file (timings.json next to this
script by default). Delays accept a unit suffix: 0.35, 350ms or 1s.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from timings import (
    SPECS,
    TIMINGS,
    TimingError,
    Timings,
    default_path,
    format_value,
    normalize_platform,
    parse_value,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timings_cli.py",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Timings:\n  " + "\n  ".join(
            f"{spec.name:<24} {spec.description}" for spec in TIMINGS
        ),
    )
    parser.add_argument(
        "--timings-file",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"file to edit (default: {default_path()})",
    )
    parser.add_argument(
        "--platform",
        choices=("auto", "windows", "linux"),
        default="auto",
        help="whose defaults to report (default: the platform you are on)",
    )

    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="show every timing, its value and its default")
    commands.add_parser("path", help="print the timings file path and whether it exists")

    show = commands.add_parser("show", help="print the current table as JSON")
    show.add_argument("name", nargs="?", help="only this timing")

    defaults = commands.add_parser("defaults", help="print the built-in defaults as JSON")
    defaults.add_argument(
        "--other-platform",
        choices=("windows", "linux"),
        help="print the other platform's defaults instead of this one's",
    )

    setter = commands.add_parser("set", help="change one or more timings and save")
    setter.add_argument(
        "assignment",
        nargs="+",
        metavar="NAME=VALUE",
        help="e.g. fishing_key_delay=250ms mining_ok_presses=4",
    )
    setter.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would change without writing",
    )

    reset = commands.add_parser("reset", help="put timings back to their defaults and save")
    reset.add_argument("name", nargs="*", help="only these timings (default: all)")
    reset.add_argument(
        "--dry-run", action="store_true", help="print what would change without writing"
    )

    commands.add_parser("gui", help="open the graphical timings editor")

    return parser


def open_table(arguments) -> Timings:
    """Load the table the arguments point at, exiting with a message on error."""
    platform = None if arguments.platform == "auto" else arguments.platform
    try:
        return Timings(path=arguments.timings_file, platform=platform)
    except TimingError as error:
        raise SystemExit(f"Error: {error}\nFix the file, or run 'reset' to start over.")


def format_table(table: Timings) -> str:
    """Render the table for 'list': value, default and where it came from."""
    rows = []
    for spec in TIMINGS:
        value = table[spec.name]
        unit = "ms" if spec.is_delay else ""
        source = "default" if table.is_default(spec.name) else str(table.path)
        rows.append((spec.name, f"{format_value(spec, value)}{unit}", source, spec.description))

    name_width = max(len(row[0]) for row in rows)
    value_width = max(len(row[1]) for row in rows)

    lines = []
    for name, value, source, description in rows:
        lines.append(f"{name:<{name_width}}  {value:>{value_width}}  ({source})")
        lines.append(f"{'':<{name_width}}  {'':<{value_width}}  {description}")
    return "\n".join(lines)


def command_list(table: Timings) -> int:
    print(format_table(table))
    print(f"\nDefaults are per platform; you are on {table.platform}.")
    print(f"Edit with 'timings_cli.py set NAME=VALUE' or 'timings_cli.py gui'.")
    return 0


def command_path(table: Timings) -> int:
    exists = "exists" if table.path.is_file() else "does not exist yet"
    print(f"{table.path} ({exists})")
    return 0


def command_show(table: Timings, arguments) -> int:
    if arguments.name:
        spec = SPECS.get(arguments.name)
        if spec is None:
            raise SystemExit(
                f"Error: unknown timing {arguments.name!r}. "
                f"Known timings: {', '.join(SPECS)}"
            )
        print(json.dumps({arguments.name: table[arguments.name]}, indent=2))
        return 0

    print(json.dumps(table.values, indent=2))
    return 0


def command_defaults(arguments) -> int:
    platform = (
        arguments.other_platform
        if arguments.other_platform
        else normalize_platform(None)
    )
    table = Timings(platform=platform, read_file=False)
    print(json.dumps(table.values, indent=2))
    return 0


def command_set(table: Timings, arguments) -> int:
    changes = {}
    for assignment in arguments.assignment:
        name, separator, value = assignment.partition("=")
        name = name.strip()
        if not separator or name not in SPECS:
            raise SystemExit(
                f"Error: want NAME=VALUE for a known timing, got {assignment!r}.\n"
                f"Known timings: {', '.join(SPECS)}"
            )
        try:
            changes[name] = parse_value(SPECS[name], value)
        except TimingError as error:
            raise SystemExit(f"Error: {error}") from None

    for name, value in changes.items():
        before = table[name]
        if before == value:
            print(f"{name} is already {format_value(SPECS[name], value)}")
            continue
        print(
            f"{name}: {format_value(SPECS[name], before)} -> "
            f"{format_value(SPECS[name], value)}"
        )

    if arguments.dry_run:
        print("Dry run, nothing written.")
        return 0

    table.save(changes)
    print(f"Saved {table.path}.")
    return 0


def command_reset(table: Timings, arguments) -> int:
    names = list(arguments.name or SPECS)
    for name in names:
        if name not in SPECS:
            raise SystemExit(
                f"Error: unknown timing {name!r}. Known timings: {', '.join(SPECS)}"
            )

    defaults = {name: SPECS[name].default_for(table.platform) for name in names}
    changed = False
    for name, value in defaults.items():
        if table[name] == value:
            continue
        changed = True
        print(
            f"{name}: {format_value(SPECS[name], table[name])} -> "
            f"{format_value(SPECS[name], value)}"
        )

    if not changed:
        print("Everything is already at its default.")

    if arguments.dry_run:
        print("Dry run, nothing written.")
        return 0

    table.save(defaults)
    print(f"Saved {table.path}.")
    return 0


def command_gui(arguments) -> int:
    import timings_gui

    return timings_gui.launch(arguments.timings_file, arguments.platform)


def main(argv=None) -> int:
    arguments = build_parser().parse_args(argv)

    if arguments.command == "gui":
        return command_gui(arguments)

    table = open_table(arguments)

    handlers = {
        "list": lambda: command_list(table),
        "path": lambda: command_path(table),
        "show": lambda: command_show(table, arguments),
        "defaults": lambda: command_defaults(arguments),
        "set": lambda: command_set(table, arguments),
        "reset": lambda: command_reset(table, arguments),
    }
    return handlers[arguments.command]()


if __name__ == "__main__":
    sys.exit(main())
