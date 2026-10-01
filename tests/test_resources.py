"""Tests for where the program looks for its files.

The built executable is the reason this module exists, so most of what is
checked here is that a path does not depend on the current directory any
more: that is the bug a relative ``./img/360p/...`` had, and it only shows
up when something runs the program from somewhere else.

Run with: python -m unittest discover -s tests -t .
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import resources


class ResourceDirTests(unittest.TestCase):
    def tearDown(self):
        # the fake only lasts as long as the patch does, but be explicit
        resources.sys.frozen = False

    def test_unfrozen_it_is_the_project_folder(self):
        self.assertEqual(resources.resource_dir(), ROOT)

    def test_frozen_it_is_the_folder_holding_the_executable(self):
        exe = ROOT / "dist" / "holocure_fishing.exe"
        with mock.patch.object(resources.sys, "frozen", True, create=True), \
                mock.patch.object(resources.sys, "executable", str(exe)):
            self.assertEqual(resources.resource_dir(), exe.parent)

    def test_templates_load_from_any_working_directory(self):
        """The real check: import the module from somewhere else entirely."""
        script = (
            "import sys; sys.path.insert(0, r'%s');"
            "from imgproc import templates;"
            "print(all(image is not None for image in templates.values()))" % ROOT
        )
        done = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "True")


class WritableDirTests(unittest.TestCase):
    def test_a_writable_program_folder_is_used_as_is(self):
        with mock.patch.object(resources.os, "access", return_value=True):
            self.assertEqual(resources.writable_dir(), ROOT)

    def test_a_read_only_program_folder_falls_back_per_user(self):
        fallback = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        fallback = fallback / "Automated-HoloCure-Fishing"
        with mock.patch.object(resources.os, "access", return_value=False), \
                mock.patch.object(Path, "mkdir"):
            self.assertEqual(resources.writable_dir(), fallback)


if __name__ == "__main__":
    unittest.main()