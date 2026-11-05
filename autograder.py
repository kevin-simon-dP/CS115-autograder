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
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from notebook import NotebookError, build_notebook_script

# Example dir: "First Last_35644_assignsubmission_file"
_STUDENT_DIR_RE = re.compile(r"^(?P<name>.+?)_\d+_assignsubmission_file$", re.IGNORECASE)

# Jupyter keeps stale notebook copies in this directory; never treat them as submissions.
_CHECKPOINT_DIR = ".ipynb_checkpoints"


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
    return sorted(p for p in student_dir.rglob("*.py") if p.is_file())


def find_notebooks(student_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in student_dir.rglob("*.ipynb")
        if p.is_file() and _CHECKPOINT_DIR not in p.parts
    )


def run_submission(
    script: Path,
    python: str,
    timeout: float,
    cwd: Path | None = None,
    extra_pythonpath: Path | None = None,
) -> tuple[int | None, bytes, bytes, bool]:
    """Run one submission script, returning (returncode, stdout, stderr, timed_out)."""
    env = None
    if extra_pythonpath is not None:
        env = dict(os.environ)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            str(extra_pythonpath)
            if not existing
            else str(extra_pythonpath) + os.pathsep + existing
        )
    try:
        proc = subprocess.run(
            [python, str(script)],
            cwd=str(cwd or script.parent),
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        return None, exc.stdout or b"", exc.stderr or b"", True


def decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def make_diff(expected: bytes, actual: bytes) -> str:
    if expected == actual:
        return "No differences.\n"
    diff = "\n".join(
        difflib.unified_diff(
            decode(expected).splitlines(),
            decode(actual).splitlines(),
            fromfile="expected.txt",
            tofile="actual.txt",
            lineterm="",
        )
    )
    if not diff:
        return "Byte contents differ, but no line-based differences were found.\n"
    return diff + "\n"


def write_error_log(
    path: Path,
    script: Path,
    returncode: int | None,
    timed_out: bool,
    timeout: float,
    stderr: bytes,
    extra_lines: list[str] | None = None,
) -> None:
    lines = [
        f"command: {script}",
        f"return code: {returncode if returncode is not None else 'N/A (killed)'}",
        f"timed out: {'yes' if timed_out else 'no'} (limit: {timeout:g}s)",
        "",
        "stderr:",
        decode(stderr).rstrip() or "(empty)",
    ]
    if extra_lines:
        lines.extend(["", *extra_lines])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


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
        name = display_name(student_dir.name)
        graded_dir = out_dir / f"{student_dir.name}_graded"
        if graded_dir.exists():
            shutil.rmtree(graded_dir)
        graded_dir.mkdir(parents=True, exist_ok=True)

        notebooks = find_notebooks(student_dir)
        py_files = find_py_files(student_dir)

        notebook_script = None
        extra_pythonpath = None
        run_cwd = None

        if len(notebooks) > 1:
            listing = ", ".join(p.name for p in notebooks)
            review.append((name, f"multiple notebooks ({listing})"))
            (graded_dir / "diff.txt").write_text(
                f"Multiple notebooks found; not run automatically:\n{listing}\n",
                encoding="utf-8",
            )
            print(f"[SKIP] {name}: multiple notebooks")
            continue

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
                review.append((name, f"notebook error: {exc}"))
                print(f"[SKIP] {name}: {exc}")
                continue
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
            review.append((name, "no .py or .ipynb file found"))
            (graded_dir / "diff.txt").write_text(
                "No .py or .ipynb file found in submission.\n", encoding="utf-8"
            )
            print(f"[SKIP] {name}: no .py or .ipynb file found")
            continue
        elif len(py_files) > 1:
            listing = ", ".join(p.name for p in py_files)
            review.append((name, f"multiple .py files ({listing})"))
            (graded_dir / "diff.txt").write_text(
                f"Multiple .py files found; not run automatically:\n{listing}\n",
                encoding="utf-8",
            )
            print(f"[SKIP] {name}: multiple .py files")
            continue
        else:
            script_path = py_files[0]

        processed += 1
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

        runtime_problems: list[str] = []
        if timed_out:
            runtime_problems.append(f"timed out after {args.timeout:g}s")
        elif returncode != 0:
            runtime_problems.append(f"exited with code {returncode}")
        if stderr.strip():
            runtime_problems.append("wrote to stderr")

        reasons = list(runtime_problems)
        if stdout != expected:
            reasons.append("output differs from expected")

        if runtime_problems:
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

        if reasons:
            review.append((name, "; ".join(reasons)))
            print(f"[REVIEW] {name}: {reasons[0]}")
        else:
            matched.append(name)
            print(f"[MATCH] {name}")

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


def build_summary(
    submissions: Path,
    expected: Path,
    out_dir: Path,
    matched: list[str],
    review: list[tuple[str, str]],
    processed: int,
) -> str:
    lines = [
        "Autograder summary",
        "==================",
        f"Generated : {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Submissions: {submissions}",
        f"Expected  : {expected}",
        f"Output    : {out_dir}",
        f"Graded    : {processed} submission(s)",
        f"Matched   : {len(matched)}",
        f"Review    : {len(review)}",
        "",
        "MATCHED EXACTLY (no manual review needed)",
        "-----------------------------------------",
    ]
    lines.extend(f"  {name}" for name in sorted(matched))
    if not matched:
        lines.append("  (none)")

    lines.extend(
        [
            "",
            "NEEDS MANUAL REVIEW",
            "-------------------",
        ]
    )
    lines.extend(f"  {name}  -  {reason}" for name, reason in sorted(review))
    if not review:
        lines.append("  (none)")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
