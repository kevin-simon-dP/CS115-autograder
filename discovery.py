"""Locate student submissions and identify their entry points."""

from __future__ import annotations

import re
from pathlib import Path

# Example dir: "First Last_35644_assignsubmission_file"
_STUDENT_DIR_RE = re.compile(
    r"^(?P<name>.+?)_\d+_assignsubmission_file$", re.IGNORECASE
)

# Jupyter keeps stale notebook copies in this directory; never treat them as submissions.
_CHECKPOINT_DIR = ".ipynb_checkpoints"


def display_name(dir_name: str) -> str:
    """Turn a submission folder name into a readable student name."""
    match = _STUDENT_DIR_RE.match(dir_name)
    if match:
        return match.group("name").strip()
    marker = "_assignsubmission_file"
    index = dir_name.lower().find(marker)
    if index != -1:
        return dir_name[:index].strip()
    return dir_name


def find_py_files(student_dir: Path) -> list[Path]:
    """Return every .py file under a submission, sorted for determinism."""
    return sorted(p for p in student_dir.rglob("*.py") if p.is_file())


def find_notebooks(student_dir: Path) -> list[Path]:
    """Return every .ipynb under a submission, ignoring Jupyter checkpoints."""
    return sorted(
        p
        for p in student_dir.rglob("*.ipynb")
        if p.is_file() and _CHECKPOINT_DIR not in p.parts
    )
