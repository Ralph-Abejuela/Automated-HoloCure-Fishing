"""Window for editing the timings used by the fishing and mining loops.

Run 'python timings_gui.py', or 'python timings_cli.py gui'.

Delays are shown in milliseconds, which is easier to type than seconds; the
file on disk keeps seconds. Saving writes the whole table at once, so a game
that is already running picks the change up on its next loop.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from timings import (
    SPECS,
    TIMINGS,
    TimingError,
    Timings,
    format_value,
    parse_value,
)


#: How wide a description may get before it wraps onto another line. The
#: description is the last column, and a label in a grid is as wide as its
#: text, so an unwrapped one decides the width of the whole window. A
#: window wider than the screen is not a wide window, it is a broken one:
#: Tk refuses to map any of its children, so the value boxes vanish with
#: everything else. Cap the column and the window can never outgrow the
#: screen, whatever a description says.
DESCRIPTION_WRAP = 460


class TimingsWindow:
    """One row per timing: a description, a value box and a default hint."""

    def __init__(self, master: tk.Tk, table: Timings):
        self.master = master
        self.table = table
        self.entries = {}
        self.dirty = False

        master.title("HoloCure timings")
        master.minsize(560, 420)

        header = ttk.Frame(master, padding=(12, 10, 12, 4))
        header.pack(fill="x")
        ttk.Label(header, text="HoloCure timings", font=("TkDefaultFont", 13, "bold")).pack(
            anchor="w"
        )
        ttk.Label(header, text=f"Saved in {table.path}").pack(anchor="w")
        ttk.Label(
            header,
            text="Changes apply to a game that is already running, within a second.",
        ).pack(anchor="w")

        columns = ttk.Frame(master, padding=(12, 4))
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(1, weight=1)
        ttk.Label(columns, text="Timing").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(columns, text="Value").grid(row=0, column=1, sticky="w", pady=(0, 6))
        ttk.Label(columns, text="Default").grid(row=0, column=2, sticky="w", pady=(0, 6))

        for row, spec in enumerate(TIMINGS, start=1):
            unit = "ms" if spec.is_delay else ""
            variable = tk.StringVar(value=f"{format_value(spec, table[spec.name])}{unit}")

            name = ttk.Label(columns, text=spec.name)
            name.grid(row=row, column=0, sticky="w", pady=3)
            name.bind("<Button-1>", lambda _event, key=spec.name: self.show_help(key))

            entry = ttk.Entry(columns, textvariable=variable, width=12)
            entry.grid(row=row, column=1, sticky="w", padx=10, pady=3)
            entry.bind("<KeyRelease>", lambda _event: self.mark_dirty())
            self.entries[spec.name] = (variable, unit)

            default = spec.default_for(table.platform)
            ttk.Label(
                columns,
                text=f"{format_value(spec, default)}{unit}",
                foreground="#666666",
            ).grid(row=row, column=2, sticky="w", pady=3)

            ttk.Label(
                columns,
                text=spec.description,
                foreground="#666666",
                wraplength=DESCRIPTION_WRAP,
            ).grid(row=row, column=3, sticky="w", padx=(12, 0), pady=3)

        buttons = ttk.Frame(master, padding=(12, 8))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right")
        ttk.Button(buttons, text="Revert changes", command=self.reload_fields).pack(
            side="right", padx=6
        )
        ttk.Button(buttons, text="All defaults", command=self.fill_defaults).pack(
            side="right"
        )

        self.status = tk.StringVar(value="No changes yet.")
        ttk.Label(master, textvariable=self.status, padding=(12, 0, 12, 10)).pack(
            fill="x"
        )

        master.bind("<Control-s>", lambda _event: self.save())
        master.protocol("WM_DELETE_WINDOW", master.destroy)
        self.reload_fields()

    # -- helpers ---------------------------------------------------------

    def mark_dirty(self) -> None:
        self.dirty = True
        self.status.set("Unsaved changes.")

    def read_fields(self) -> dict:
        """Turn what is typed into a complete table, or explain what is wrong.

        The boxes are in milliseconds while the specs and the file are in
        seconds, so delays are converted here before the range is checked.
        """
        values = {}
        problems = []
        for spec in TIMINGS:
            variable, unit = self.entries[spec.name]
            text = variable.get().strip()
            if unit and text.endswith(unit):
                text = text[: -len(unit)].strip()
            try:
                if spec.is_delay:
                    try:
                        seconds = float(text) / 1000
                    except ValueError:
                        # Let parse_value name the problem.
                        seconds = text
                    values[spec.name] = parse_value(spec, seconds)
                else:
                    values[spec.name] = parse_value(spec, text)
            except TimingError as error:
                problems.append(str(error))

        if problems:
            raise TimingError("\n".join(problems))
        return values

    def fill(self, values: dict) -> None:
        for spec in TIMINGS:
            variable, unit = self.entries[spec.name]
            variable.set(f"{format_value(spec, values[spec.name])}{unit}")

    # -- actions ---------------------------------------------------------

    def save(self) -> None:
        try:
            values = self.read_fields()
        except TimingError as error:
            messagebox.showerror("Cannot save", str(error), parent=self.master)
            self.status.set("Fix the highlighted values and save again.")
            return

        try:
            self.table.save(values)
        except OSError as error:
            messagebox.showerror(
                "Cannot save", f"{self.table.path}\n{error}", parent=self.master
            )
            self.status.set("Could not write the file.")
            return

        self.dirty = False
        self.status.set(f"Saved {self.table.path.name}.")

    def reload_fields(self) -> None:
        try:
            self.table.reload()
        except TimingError as error:
            messagebox.showerror(
                "Cannot read timings",
                f"{self.table.path}\n\n{error}",
                parent=self.master,
            )
            self.status.set("Showing the values from before the bad file.")
            return

        self.fill(self.table.values)
        self.dirty = False
        self.status.set(f"Loaded {self.table.path.name}.")

    def fill_defaults(self) -> None:
        self.fill(
            {name: SPECS[name].default_for(self.table.platform) for name in SPECS}
        )
        self.mark_dirty()
        self.status.set("Defaults filled in. Save to keep them.")

    def show_help(self, name: str) -> None:
        spec = SPECS[name]
        unit = "milliseconds" if spec.is_delay else "a whole number"
        messagebox.showinfo(
            name,
            f"{spec.description}\n\n"
            f"Enter {unit} between {spec.minimum:g} and {spec.maximum:g}.\n"
            f"Default: {format_value(spec, spec.default_for(self.table.platform))}"
            + ("ms" if spec.is_delay else "")
            + ".",
            parent=self.master,
        )


def launch(path: Optional[Path] = None, platform: Optional[str] = None) -> int:
    """Open the editor window. Returns the process exit code."""
    platform = None if platform in (None, "auto") else platform
    master = tk.Tk()

    try:
        table = Timings(path=path, platform=platform)
    except TimingError as error:
        # Still open the window, on the built-in defaults, so a broken file can be
        # fixed in here instead of only by hand.
        messagebox.showerror("Cannot read timings", str(error), parent=master)
        table = Timings(path=path, platform=platform, read_file=False)

    TimingsWindow(master, table)
    master.mainloop()
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Edit the HoloCure timings in a window.")
    parser.add_argument("--timings-file", type=Path, default=None, metavar="PATH")
    parser.add_argument(
        "--platform", choices=("auto", "windows", "linux"), default="auto"
    )
    arguments = parser.parse_args()

    try:
        sys.exit(launch(arguments.timings_file, arguments.platform))
    except TimingError as error:
        raise SystemExit(f"Error: {error}")
