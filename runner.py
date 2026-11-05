"""Run submission scripts and compare their output to the expected file."""

from __future__ import annotations

import difflib
import os
import subprocess
from pathlib import Path


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
    """Decode subprocess output as UTF-8, tolerating invalid bytes."""
    return data.decode("utf-8", errors="replace")


def make_diff(expected: bytes, actual: bytes) -> str:
    """Return a human-readable unified diff between expected and actual output."""
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
    """Write a diagnostics file for a submission that ran into trouble."""
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
