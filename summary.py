"""Build the summary report written at the root of the output folder."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def build_summary(
    submissions: Path,
    expected: Path,
    out_dir: Path,
    matched: list[str],
    review: list[tuple[str, str]],
    processed: int,
) -> str:
    """Return the contents of summary.txt."""
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
