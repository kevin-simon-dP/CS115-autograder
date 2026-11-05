#!/usr/bin/env python3
"""Grade Python submissions by diffing their stdout against an expected file.

Typical usage:
    uv run autograder.py
    uv run autograder.py --submissions "cs115f26-a.us-Assignment - Test"
    uv run autograder.py --submissions "$SUB" --expected expected.txt --out results

For every immediate subdirectory of the submissions folder, the script:
  * locates a single entry point inside it: a .ipynb notebook (preferred when
    present, even alongside helper .py modules) or a lone .py file
    (flags ambiguous dirs for review),
  * turns a notebook into an equivalent plain-Python script (see notebook.py),
  * runs that script in a subprocess with a timeout,
  * writes captured stdout to        <out>/<student dir>_graded/actual.txt,
  * writes a unified diff to         <out>/<student dir>_graded/diff.txt,
  * writes diagnostics to            <out>/<student dir>_graded/error.txt
    only when the run crashes, writes to stderr, or times out.

A summary.txt at the root of <out> splits submissions into "matched exactly"
(no further review needed) and "needs manual review".

Supporting modules:
  * discovery.py - student naming and entry-point discovery,
  * notebook.py  - turning .ipynb files into plain Python scripts,
  * runner.py    - subprocess execution, diffing, and error logs,
  * summary.py   - building summary.txt.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from discovery import display_name, find_notebooks, find_py_files
from notebook import NotebookError, NotebookScript, build_notebook_script
from runner import decode, make_diff, run_submission, write_error_log
from summary import build_summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run student submissions and diff their output against an expected file.",
    )
    parser.add_argument(
        "--submissions",
        type=Path,
        default=Path("cs115f26-a.us-Assignment - Test"),
        help="Folder containing one directory per student (default: %(default)s)",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=Path("expected.txt"),
        help="File containing the expected stdout (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output folder (default: '<submissions> - graded')",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-submission timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to run submissions (default: current interpreter)",
    )
    return parser.parse_args(argv)


@dataclass
class GradedSubmission:
    """Outcome of grading one student.

    An empty ``reasons`` list means the submission matched exactly. ``skipped``
    marks submissions that could not be run automatically (and therefore do not
    count toward the ``processed`` total).
    """

    name: str
    reasons: list[str] = field(default_factory=list)
    skipped: bool = False


def grade_student(
    student_dir: Path,
    expected: bytes,
    args: argparse.Namespace,
    out_dir: Path,
) -> GradedSubmission:
    """Grade a single student directory, writing artifacts under ``out_dir``."""
    name = display_name(student_dir.name)
    graded_dir = out_dir / f"{student_dir.name}_graded"
    if graded_dir.exists():
        shutil.rmtree(graded_dir)
    graded_dir.mkdir(parents=True, exist_ok=True)

    notebooks = find_notebooks(student_dir)
    py_files = find_py_files(student_dir)

    notebook_script: NotebookScript | None = None
    extra_pythonpath: Path | None = None
    run_cwd: Path | None = None

    if len(notebooks) > 1:
        listing = ", ".join(p.name for p in notebooks)
        (graded_dir / "diff.txt").write_text(
            f"Multiple notebooks found; not run automatically:\n{listing}\n",
            encoding="utf-8",
        )
        return GradedSubmission(name, [f"multiple notebooks ({listing})"], skipped=True)

    if notebooks:
        # A notebook is the entry point even when helper .py modules sit
        # next to it; notebooks routinely import sibling files.
        notebook_path = notebooks[0]
        try:
            notebook_script = build_notebook_script(notebook_path)
        except NotebookError as exc:
            (graded_dir / "diff.txt").write_text(
                f"Notebook could not be prepared for grading: {exc}\n",
                encoding="utf-8",
            )
            (graded_dir / "error.txt").write_text(
                f"notebook: {notebook_path}\n{exc}\n", encoding="utf-8"
            )
            return GradedSubmission(name, [f"notebook error: {exc}"], skipped=True)
        script_path = graded_dir / "extracted.py"
        script_path.write_text(notebook_script.code, encoding="utf-8")
        (graded_dir / "notebook.txt").write_text(
            notebook_script.describe(notebook_path.name), encoding="utf-8"
        )
        # Run from the submission dir so relative data paths and sibling
        # imports behave the way they do inside Jupyter.
        run_cwd = student_dir
        extra_pythonpath = student_dir
    elif not py_files:
        (graded_dir / "diff.txt").write_text(
            "No .py or .ipynb file found in submission.\n", encoding="utf-8"
        )
        return GradedSubmission(name, ["no .py or .ipynb file found"], skipped=True)
    elif len(py_files) > 1:
        listing = ", ".join(p.name for p in py_files)
        (graded_dir / "diff.txt").write_text(
            f"Multiple .py files found; not run automatically:\n{listing}\n",
            encoding="utf-8",
        )
        return GradedSubmission(name, [f"multiple .py files ({listing})"], skipped=True)
    else:
        script_path = py_files[0]

    returncode, stdout, stderr, timed_out = run_submission(
        script_path,
        args.python,
        args.timeout,
        cwd=run_cwd,
        extra_pythonpath=extra_pythonpath,
    )

    (graded_dir / "actual.txt").write_bytes(stdout)
    (graded_dir / "diff.txt").write_text(
        make_diff(expected, stdout), encoding="utf-8"
    )

    problems: list[str] = []
    if timed_out:
        problems.append(f"timed out after {args.timeout:g}s")
    elif returncode != 0:
        problems.append(f"exited with code {returncode}")
    if stderr.strip():
        problems.append("wrote to stderr")

    reasons = list(problems)
    if stdout != expected:
        reasons.append("output differs from expected")

    if problems:
        extra_lines = None
        if notebook_script is not None:
            failing = notebook_script.failing_cells(decode(stderr))
            if failing:
                extra_lines = [
                    "notebook cells in traceback: "
                    + ", ".join(str(cell) for cell in failing)
                ]
        write_error_log(
            graded_dir / "error.txt",
            script_path,
            returncode,
            timed_out,
            args.timeout,
            stderr,
            extra_lines=extra_lines,
        )

    return GradedSubmission(name, reasons)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    submissions = args.submissions.resolve()
    expected_path = args.expected.resolve()

    if not submissions.is_dir():
        print(f"error: submissions folder not found: {submissions}", file=sys.stderr)
        return 2
    if not expected_path.is_file():
        print(f"error: expected output file not found: {expected_path}", file=sys.stderr)
        return 2

    expected = expected_path.read_bytes()

    out_dir = args.out
    if out_dir is None:
        out_dir = submissions.parent / f"{submissions.name} - graded"
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    matched: list[str] = []
    review: list[tuple[str, str]] = []
    processed = 0

    students = sorted(
        child
        for child in submissions.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and child.resolve() != out_dir
    )

    for student_dir in students:
        result = grade_student(student_dir, expected, args, out_dir)
        if result.reasons:
            review.append((result.name, "; ".join(result.reasons)))
            label = "SKIP" if result.skipped else "REVIEW"
            print(f"[{label}] {result.name}: {result.reasons[0]}")
        else:
            matched.append(result.name)
            print(f"[MATCH] {result.name}")
        if not result.skipped:
            processed += 1

    summary_path = out_dir / "summary.txt"
    summary_path.write_text(
        build_summary(
            submissions=submissions,
            expected=expected_path,
            out_dir=out_dir,
            matched=matched,
            review=review,
            processed=processed,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Matched: {len(matched)}  |  Needs review: {len(review)}")
    print(f"Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
