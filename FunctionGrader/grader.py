"""Runs harness.py for a student and collects results"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rubric import Rubric

HARNESS = Path(__file__).resolve().parent / "harness.py"

@dataclass
class HarnessResult:
    signatures: dict[str, dict] = field(default_factory=dict)   # fn name -> record
    cases: dict[int, dict] = field(default_factory=dict)        # case index -> record
    load_error: str | None = None     # student script raised while loading
    load_timeout: bool = False        # student top-level code hung
    harness_error: str | None = None  # harness itself crashed (stderr tail)
    runs: int = 0

def build_env(extra_pythonpath: Path | None) -> dict | None:
    if extra_pythonpath is None:
        return None
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(extra_pythonpath) + (os.pathsep + existing if existing else "")
    return env

# run grading, restart if a function hangs
def run_harness(
    script: Path,
    rubric_path: Path,
    rubric: Rubric,
    python: str,
    timeout: float,
    cwd: Path | None = None,
    extra_pythonpath: Path | None = None,
    max_restarts: int = 5,
) -> HarnessResult:
    script = script.resolve()
    rubric_path = rubric_path.resolve()
    all_cases = rubric.cases()
    env = build_env(extra_pythonpath)
    result = HarnessResult()
    start = 0

    while True:
        result.runs += 1
        try:
            proc = subprocess.run(
                [python, str(HARNESS), str(script), str(rubric_path), str(start)],
                cwd=str(cwd or script.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
            )
            stdout, timed_out = proc.stdout, False
            if proc.returncode != 0:
                result.harness_error = proc.stderr.decode("utf-8", "replace")[-1000:]
        except subprocess.TimeoutExpired as exc:
            stdout, timed_out = exc.stdout or b"", True

        # Store every JSON line the harness managed to send.
        loaded = False
        last = start - 1
        for line in stdout.decode("utf-8", "replace").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # ignore anything that isn't ours
            event = record.get("event")
            if event == "loaded":
                loaded = True
            elif event == "load_error":
                result.load_error = record["error"]
            elif event == "signature":
                result.signatures[record["fn"]] = record
            elif event == "case":
                result.cases[record["i"]] = record
                last = record["i"]

        if not timed_out:
            break
        if not loaded:
            result.load_timeout = True
            break

        # The case after the last one reported is the one that hung.
        hung = last + 1
        if hung >= len(all_cases):
            break
        _, fn, _, args, expected = all_cases[hung]
        result.cases[hung] = {
            "event": "case", "i": hung, "fn": fn.name,
            "args": repr(args), "expected": repr(expected), "status": "timeout",
        }
        start = hung + 1
        if start >= len(all_cases) or result.runs > max_restarts:
            break

    return result

"""=============== scoring related======================"""

@dataclass
# score per rubric line
class LineScore:
    fn: str
    label: str
    earned: float | None  # None = graded by hand, no automatic points
    points: float
    note: str = ""        # why points were lost, or evidence for manual grading


@dataclass
# score per student
class Report:
    lines: list[LineScore]
    total: float
    penalty: float = 0.0                            # filename penalty, in points
    notes: list[str] = field(default_factory=list)  # whole-submission problems

    def auto_earned(self) -> float:
        return sum(line.earned for line in self.lines if line.earned is not None)

    def auto_points(self) -> float:
        return sum(line.points for line in self.lines if line.earned is not None)

    def manual_points(self) -> float:
        return sum(line.points for line in self.lines if line.earned is None)

    def final(self) -> float | None:
        """Final score, or None while manual lines are still ungraded."""
        if self.manual_points():
            return None
        return max(0.0, self.auto_earned() - self.penalty)

    def review_reasons(self) -> list[str]:
        reasons = list(self.notes)
        reasons += [f"{line.fn}: {line.label} (manual)" for line in self.lines if line.earned is None]
        return reasons

    def text(self) -> str:
        out = [f"Auto-graded: {self.auto_earned():g}/{self.auto_points():g}"]
        if self.manual_points():
            out.append(f"Manual:      __/{self.manual_points():g}   (lines marked [ ] below)")
        if self.penalty:
            out.append(f"Penalty:     -{self.penalty:g}")
        final = self.final()
        if final is not None:
            out.append(f"Final:       {final:g}/{self.total:g}")
        else:
            minus = " - penalty" if self.penalty else ""
            out.append(f"Final:       auto + manual{minus}, min 0 (out of {self.total:g})")
        out.append("[+] full   [-] lost points   [ ] grade by hand")
        for note in self.notes:
            out.append(f"!! {note}")
        current = None
        for line in self.lines:
            if line.fn != current:
                out += ["", line.fn]
                current = line.fn
            if line.earned is None:
                out.append(f"  [ ] __/{line.points:g}  {line.label}")
            else:
                mark = "+" if line.earned == line.points else "-"
                out.append(f"  [{mark}] {line.earned:g}/{line.points:g}  {line.label}")
            for detail in line.note.splitlines():
                out.append(f"        {detail}")
        return "\n".join(out) + "\n"

def describe_case(record: dict) -> str:
    status = record["status"]
    if status == "fail":
        text = f"{record['args']} -> {record['got']}, want {record['expected']}"
    elif status == "error":
        text = f"{record['args']} raised {record['got']}"
    else:  # timeout / missing / not run
        text = f"{record['args']} {status}"
    if record.get("printed"):
        text += f"  (printed {record['printed'].strip()[:60]!r})"
    return text

# string of student's code for manual grading
def function_source(source: str, name: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "(could not parse source)"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or "(source not available)"
    return "(function not found in source)"

# file name match
def filename_ok(pattern: str, file_name: str, student_name: str) -> bool:
    parts = student_name.split()
    if len(parts) < 2:
        return False
    regex = pattern.format(first=re.escape(parts[0]), last=re.escape(parts[-1]))
    return re.fullmatch(regex, file_name, re.IGNORECASE) is not None

# write result of one row
def score_line(fn, check, result: HarnessResult, records: list[dict],
               fn_records: list[dict], source: str) -> LineScore:
    line = LineScore(fn.name, check.label, 0, check.points)

    if check.kind == "signature":
        sig = result.signatures.get(fn.name, {})
        if not sig.get("found"):
            line.note = "function not found"
        elif sig.get("params") != fn.params:
            line.note = f"takes {sig.get('params')} params, want {fn.params}"
        else:
            line.earned = check.points

    elif check.kind == "cases":
        bad = [r for r in records if r["status"] != "pass"]
        if bad and all(r["status"] == "missing" for r in bad):
            line.note = "function not defined"
        elif bad:
            details = [describe_case(r) for r in bad[:3]]
            if len(bad) > 3:
                details.append(f"... and {len(bad) - 3} more")
            line.note = "\n".join(details)
        else:
            line.earned = check.points

    elif check.kind == "terminates":
        ran = [r for r in fn_records if r["status"] not in ("missing", "not run")]
        hung = [r for r in ran if r["status"] == "timeout"]
        if not ran:
            line.note = "no cases ran"
        elif hung:
            line.note = "timed out on " + ", ".join(r["args"] for r in hung)
        else:
            line.earned = check.points

    elif check.kind == "manual":   # graded by hand, nothing shown
        line.earned = None

    elif check.kind == "code":     # graded by hand, student's function shown
        line.earned = None
        line.note = function_source(source, fn.name)

    else:
        raise ValueError(f"unknown check kind in rubric: {check.kind!r}")

    return line

# results -> report
def score(rubric: Rubric, result: HarnessResult, *, source: str,
          file_name: str, student_name: str) -> Report:
    # Group case results by the rubric line they belong to.
    by_check: dict[int, list[dict]] = {}
    for index, fn, check, args, expected in rubric.cases():
        record = result.cases.get(index) or {
            "status": "not run", "args": repr(args), "expected": repr(expected)}
        by_check.setdefault(id(check), []).append(record)

    lines: list[LineScore] = []
    for fn in rubric.functions:
        fn_records = [r for chk in fn.checks for r in by_check.get(id(chk), [])]
        for check in fn.checks:
            lines.append(score_line(fn, check, result, by_check.get(id(check), []),
                                    fn_records, source))

    notes: list[str] = []
    if result.load_error:
        notes.append(f"notebook raised while loading: {result.load_error}")
    if result.load_timeout:
        notes.append("notebook's top-level code timed out; no functions could be called")
    if result.harness_error:
        last = (result.harness_error.strip().splitlines() or ["?"])[-1]
        notes.append(f"harness crashed: {last}")

    penalty = 0.0
    if rubric.filename_pattern:
        if not file_name.lower().endswith(".ipynb"):
            notes.append(f"submitted {file_name}, not a notebook - filename not checked")
        elif not filename_ok(rubric.filename_pattern, file_name, student_name):
            penalty = rubric.filename_penalty * rubric.total()
            parts = student_name.split() or ["?"]
            expected = rubric.filename_pattern.format(first=parts[0], last=parts[-1]).replace("\\", "")
            notes.append(f"filename mismatch - {penalty:g} point penalty\n"
                         f"     got:      {file_name}\n"
                         f"     expected: {expected}")

    return Report(lines, rubric.total(), penalty, notes)


if __name__ == "__main__":
    import sys

    from rubric import load_spec

    here = Path(__file__).resolve().parent
    rubric_path = here / "rubrics" / "functions_1.py"
    rubric = load_spec(rubric_path)
    student = here / sys.argv[1]

    result = run_harness(student, rubric_path, rubric, sys.executable, timeout=3)
    report = score(rubric, result,
                   source=student.read_text(encoding="utf-8"),
                   file_name=student.name,
                   student_name="Test Student")
    print(report.text())
    print("review:", report.review_reasons())