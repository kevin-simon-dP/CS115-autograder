"""Run submission scripts (or test scripts) and compare output to expected."""

from __future__ import annotations

import difflib
import os
import subprocess
from pathlib import Path


def _run(
    command: list[str],
    timeout: float,
    cwd: Path | None,
    env: dict[str, str] | None = None,
) -> tuple[int | None, bytes, bytes, bool]:
    """Run ``command``, returning (returncode, stdout, stderr, timed_out)."""
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        return None, exc.stdout or b"", exc.stderr or b"", True


def _env_with_pythonpath(dirs: list[Path]) -> dict[str, str]:
    """Copy the environment and prepend ``dirs`` to PYTHONPATH."""
    env = dict(os.environ)
    entries = [str(directory) for directory in dirs]
    existing = env.get("PYTHONPATH")
    if existing:
        entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


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
        env = _env_with_pythonpath([extra_pythonpath])
    return _run([python, str(script)], timeout, cwd or script.parent, env)


def run_tests(
    tests: Path,
    submission: Path,
    python: str,
    timeout: float,
    cwd: Path,
    pythonpath: list[Path],
) -> tuple[int | None, bytes, bytes, bool]:
    """Run a test script against one submission's extracted.py.

    The script is invoked as ``python <tests> <submission>`` so it can locate
    the submission through ``sys.argv[1]``, through the ``AUTOGRADER_SUBMISSION``
    environment variable, or by importing ``extracted`` (the graded directory is
    on PYTHONPATH). Returns (returncode, stdout, stderr, timed_out).
    """
    env = _env_with_pythonpath(pythonpath)
    env["AUTOGRADER_SUBMISSION"] = str(submission)
    env["AUTOGRADER_SUBMISSION_DIR"] = str(submission.parent)
    return _run([python, str(tests), str(submission)], timeout, cwd, env)


def decode(data: bytes) -> str:
    """Decode subprocess output as UTF-8, tolerating invalid bytes."""
    return data.decode("utf-8", errors="replace")


def make_diff(
    expected: bytes,
    actual: bytes,
    fromfile: str = "expected.txt",
    tofile: str = "actual.txt",
) -> str:
    """Return a human-readable unified diff between expected and actual output."""
    if expected == actual:
        return "No differences.\n"
    diff = "\n".join(
        difflib.unified_diff(
            decode(expected).splitlines(),
            decode(actual).splitlines(),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    if not diff:
        return "Byte contents differ, but no line-based differences were found.\n"
    return diff + "\n"


def write_error_log(
    path: Path,
    command: str,
    returncode: int | None,
    timed_out: bool,
    timeout: float,
    stderr: bytes,
    extra_lines: list[str] | None = None,
) -> None:
    """Write a diagnostics file for a submission that ran into trouble."""
    lines = [
        f"command: {command}",
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
