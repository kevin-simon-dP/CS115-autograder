#!/usr/bin/env python3
"""Grade Python submissions by diffing their output against an expected file.

Typical usage:
    uv run autograder.py
    uv run autograder.py --submissions "cs115f26-a.us-Assignment - Test"
    uv run autograder.py --submissions "$SUB" --expected expected.txt --out results
    uv run autograder.py --tests tests.py --expected expected_tests.txt

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

With --tests PATH the entry point is not run directly. Each submission is
materialised as <out>/<student dir>_graded/extracted.py (generated for
notebooks, copied for .py files) and PATH is run once against it as:

    python PATH <out>/<student dir>_graded/extracted.py

The test script can locate the submission via sys.argv[1], via the
AUTOGRADER_SUBMISSION / AUTOGRADER_SUBMISSION_DIR environment variables, or by
importing ``extracted`` (the graded directory is on PYTHONPATH). It runs with
the submission directory as its working directory, so relative data files work.

The test script's stdout is written to test_output.txt and diffed against the
expected file, so the diff shows which test cases failed. A non-zero exit or a
timeout also needs review, and stderr is captured in error.txt (it is not by
itself a failure in this mode, since test runners such as unittest use it).

Because the submission is imported rather than executed for its output, --tests
mode also silences it: print(...) calls in extracted.py are rewritten to a
no-op (see sanitize.py) and notebooks are generated without Jupyter-style
trailing-expression display. The original submission is never modified; the
number of silenced calls is recorded in tests.txt. Tests should therefore
assert on return values rather than captured stdout.

A summary.txt at the root of <out> splits submissions into "matched exactly"
(no further review needed) and "needs manual review".

Supporting modules:
  * discovery.py - student naming and entry-point discovery,
  * notebook.py  - turning .ipynb files into plain Python scripts,
  * runner.py    - subprocess execution, diffing, and error logs,
  * sanitize.py  - silencing print() output for --tests mode,
  * summary.py   - building summary.txt.
"""

from __future__ import annotations

import argparse
import io
import shlex
import shutil
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from discovery import display_name, find_notebooks, find_py_files
from notebook import NotebookError, NotebookScript, build_notebook_script
from runner import make_diff, run_submission, run_tests, write_error_log
from sanitize import strip_prints
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
        "--tests",
        type=Path,
        default=None,
        help=(
            "Python script to run against each submission's extracted.py instead "
            "of running extracted.py directly; its stdout is diffed against --expected"
        ),
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


def _copy_without_prints(source: Path, destination: Path) -> int:
    """Copy a .py submission to the graded dir with print() calls silenced.

    Falls back to a byte-for-byte copy when the file cannot be parsed, so a
    student's syntax error is still reported by the test run rather than being
    hidden by the autograder.
    """
    data = source.read_bytes()
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        text = data.decode(encoding)
        cleaned, removed = strip_prints(text)
        destination.write_bytes(cleaned.encode(encoding))
        return removed
    except (SyntaxError, UnicodeDecodeError, LookupError, ValueError):
        destination.write_bytes(data)
        return 0


def grade_student(
    student_dir: Path,
    expected: bytes,
    args: argparse.Namespace,
    out_dir: Path,
    tests: Path | None,
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
    script_path: Path
    source_dir: Path
    silenced = 0

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
            notebook_script = build_notebook_script(
                notebook_path,
                # In tests mode the submission is imported, so Jupyter's
                # trailing-expression display would pollute the test output.
                display_expressions=tests is None,
            )
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
        code = notebook_script.code
        if tests is not None:
            try:
                code, silenced = strip_prints(code)
            except (SyntaxError, ValueError):
                silenced = 0
        script_path.write_text(code, encoding="utf-8")
        (graded_dir / "notebook.txt").write_text(
            notebook_script.describe(notebook_path.name), encoding="utf-8"
        )
        # Run from the submission dir so relative data paths and sibling
        # imports behave the way they do inside Jupyter.
        source_dir = student_dir
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
        source_script = py_files[0]
        source_dir = source_script.parent
        if tests is None:
            script_path = source_script
        else:
            # Give every submission the same canonical module name in the
            # graded dir so a single test script can import/extract it.
            script_path = graded_dir / "extracted.py"
            silenced = _copy_without_prints(source_script, script_path)

    if tests is not None:
        (graded_dir / "tests.txt").write_text(
            "\n".join(
                [
                    f"tests script: {tests}",
                    f"submission: {script_path}",
                    f"print calls silenced: {silenced}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return _grade_with_tests(
            name=name,
            script_path=script_path,
            source_dir=source_dir,
            graded_dir=graded_dir,
            tests=tests,
            expected=expected,
            args=args,
        )

    run_cwd = source_dir if notebooks else None
    extra_pythonpath = source_dir if notebooks else None

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
            failing = notebook_script.failing_cells(stderr.decode("utf-8", "replace"))
            if failing:
                extra_lines = [
                    "notebook cells in traceback: "
                    + ", ".join(str(cell) for cell in failing)
                ]
        write_error_log(
            graded_dir / "error.txt",
            command=shlex.join([args.python, str(script_path)]),
            returncode=returncode,
            timed_out=timed_out,
            timeout=args.timeout,
            stderr=stderr,
            extra_lines=extra_lines,
        )

    return GradedSubmission(name, reasons)


def _grade_with_tests(
    name: str,
    script_path: Path,
    source_dir: Path,
    graded_dir: Path,
    tests: Path,
    expected: bytes,
    args: argparse.Namespace,
) -> GradedSubmission:
    """Run the instructor's test script against one submission."""
    pythonpath = [graded_dir, source_dir]
    if tests.parent not in pythonpath:
        pythonpath.append(tests.parent)

    returncode, stdout, stderr, timed_out = run_tests(
        tests,
        script_path,
        args.python,
        args.timeout,
        cwd=source_dir,
        pythonpath=pythonpath,
    )

    (graded_dir / "test_output.txt").write_bytes(stdout)
    (graded_dir / "diff.txt").write_text(
        make_diff(expected, stdout, tofile="test_output.txt"),
        encoding="utf-8",
    )

    problems: list[str] = []
    if timed_out:
        problems.append(f"test script timed out after {args.timeout:g}s")
    elif returncode != 0:
        problems.append(f"test script exited with code {returncode}")

    reasons = list(problems)
    if stdout != expected:
        reasons.append("test output differs from expected")

    if problems:
        write_error_log(
            graded_dir / "error.txt",
            command=shlex.join([args.python, str(tests), str(script_path)]),
            returncode=returncode,
            timed_out=timed_out,
            timeout=args.timeout,
            stderr=stderr,
        )

    return GradedSubmission(name, reasons)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    submissions = args.submissions.resolve()
    tests = args.tests.resolve() if args.tests is not None else None

    if not submissions.is_dir():
        print(f"error: submissions folder not found: {submissions}", file=sys.stderr)
        return 2
    if tests is not None and not tests.is_file():
        print(f"error: test script not found: {tests}", file=sys.stderr)
        return 2

    expected_path = args.expected.resolve()

    if not expected_path.is_file():
        print(
            f"error: expected output file not found: {expected_path}",
            file=sys.stderr,
        )
        return 2
    expected = expected_path.read_bytes()

    out_dir = args.out
    if out_dir is None:
        out_dir = submissions.parent / f"{submissions.name} - graded"
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if tests is not None:
        print(f"Tests   : {tests}")
    print(f"Expected: {expected_path}")
    print()

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
        result = grade_student(student_dir, expected, args, out_dir, tests)
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
            tests=tests,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Matched: {len(matched)}  |  Needs review: {len(review)}")
    print(f"Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
