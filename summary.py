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


def build_score_summary(submissions: Path, rubric: Path, out_dir: Path, results: list) -> str:
    lines = [
        "Rubric grading summary",
        "======================",
        f"Generated  : {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Submissions: {submissions}",
        f"Rubric     : {rubric}",
        f"Output     : {out_dir}",
        f"Students   : {len(results)}",
    ]
    for r in sorted(results, key=lambda s: s.name):
        lines += ["", r.name, "-" * len(r.name)]
        if r.report is None:
            lines.append("  not graded")
            lines += [f"  - {reason}" for reason in r.reasons]
            continue
        rep = r.report
        lines.append(f"  auto score: {rep.auto_earned():g}/{rep.auto_points():g}")
        lines.append(f"  penalty:    {f'-{rep.penalty:g}' if rep.penalty else 'none'}")
        issues = _issues(rep)
        lines.append("  issues:" if issues else "  issues:     none")
        lines += [f"    - {issue}" for issue in issues]
    lines.append("")
    return "\n".join(lines)


def _issues(rep) -> list[str]:
    issues = [note.splitlines()[0] for note in rep.notes]
    for line in rep.lines:
        if line.earned is not None and line.earned < line.points:
            reason = line.note.splitlines()[0] if line.note else ""
            lost = line.points - line.earned
            issues.append(f"{line.fn}: {line.label} (-{lost:g})" + (f" - {reason}" if reason else ""))
    return issues
