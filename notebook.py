#!/usr/bin/env python3
"""Notebook (.ipynb) support for the autograder.

Everything that knows about the JSON notebook format lives in this module. The
rest of the autograder only ever executes a plain Python script and compares
its stdout, so this module's job is to turn a notebook into such a script.

Execution model
---------------
* Code cells run once, top to bottom, in a fresh interpreter.
* Markdown and raw cells are ignored.
* Outputs saved inside the notebook are never used for grading; the notebook
  is always executed from scratch.
* Line magics (%matplotlib, ...), shell escapes (!pip, ...) and get_ipython()
  calls are dropped. Cells that begin with a %% cell magic are skipped.
* The value of a cell's final expression is printed with repr(), matching
  Jupyter's displayhook closely enough for stdout comparisons.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_CELL_MAGIC_RE = re.compile(r"^[ \t]*%%")
_LINE_MAGIC_RE = re.compile(r"^[ \t]*%")
_SHELL_ESCAPE_RE = re.compile(r"^[ \t]*!")
_GET_IPYTHON_RE = re.compile(r"^[ \t]*get_ipython[ \t]*\(")
_TRACEBACK_LINE_RE = re.compile(r"line (\d+)")

# Matches Jupyter's displayhook: show the repr of a cell's final expression,
# but not when it evaluates to None.
_DISPLAY_WRAPPER = "(lambda __v: None if __v is None else print(repr(__v)))"


class NotebookError(Exception):
    """Raised when a notebook cannot be turned into a runnable script."""

    def __init__(self, message: str, cell: int | None = None) -> None:
        super().__init__(message)
        self.cell = cell


@dataclass
class NotebookScript:
    """A notebook that has been prepared for execution."""

    code: str
    notebook_cells: int
    code_cells: int
    skipped: list[str] = field(default_factory=list)
    line_to_cell: dict[int, int] = field(default_factory=dict)
    language: str = "python"

    def failing_cells(self, stderr: str) -> list[int]:
        """Map line numbers in a traceback back to notebook cell numbers."""
        cells: list[int] = []
        for match in _TRACEBACK_LINE_RE.finditer(stderr):
            cell = self.line_to_cell.get(int(match.group(1)))
            if cell is not None and cell not in cells:
                cells.append(cell)
        return cells

    def describe(self, notebook_name: str) -> str:
        lines = [
            f"notebook: {notebook_name}",
            f"kernel language: {self.language}",
            f"cells: {self.notebook_cells} total, {self.code_cells} code",
            "skipped cells and lines:",
        ]
        if self.skipped:
            lines.extend(f"  {item}" for item in self.skipped)
        else:
            lines.append("  (none)")
        return "\n".join(lines) + "\n"


def is_notebook(path: Path) -> bool:
    return path.suffix.lower() == ".ipynb"


def read_notebook(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise NotebookError(f"cannot read notebook: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NotebookError(f"notebook is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NotebookError("notebook JSON is not an object")
    return data


def _notebook_cells(notebook: dict) -> list[dict]:
    cells = notebook.get("cells")
    if isinstance(cells, list):
        return [cell for cell in cells if isinstance(cell, dict)]
    # nbformat 3 nests cells in worksheets and stores source under "input".
    collected: list[dict] = []
    worksheets = notebook.get("worksheets")
    if isinstance(worksheets, list):
        for sheet in worksheets:
            if isinstance(sheet, dict) and isinstance(sheet.get("cells"), list):
                collected.extend(c for c in sheet["cells"] if isinstance(c, dict))
    return collected


def _cell_source(cell: dict) -> str:
    source = cell.get("source", cell.get("input", ""))
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return source if isinstance(source, str) else ""


def _kernel_language(notebook: dict) -> str:
    metadata = notebook.get("metadata")
    if not isinstance(metadata, dict):
        return "python"
    language_info = metadata.get("language_info")
    kernelspec = metadata.get("kernelspec")
    candidates = (
        (language_info, "name"),
        (kernelspec, "language"),
        (kernelspec, "name"),
    )
    for info, key in candidates:
        if isinstance(info, dict):
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "python"


def _is_python_kernel(language: str) -> bool:
    normalized = language.strip().lower()
    return normalized.startswith("python") or normalized.startswith("ipython")


def strip_ipython_syntax(source: str) -> tuple[str, bool, list[str]]:
    """Drop IPython-only syntax from one cell.

    Returns (remaining_source, is_cell_magic, removed_lines). A ``%%`` magic
    consumes the whole cell, so it is reported separately and the source is
    discarded.
    """
    if _CELL_MAGIC_RE.match(source):
        return "", True, []

    kept: list[str] = []
    removed: list[str] = []
    for line in source.splitlines():
        if (
            _LINE_MAGIC_RE.match(line)
            or _SHELL_ESCAPE_RE.match(line)
            or _GET_IPYTHON_RE.match(line)
        ):
            removed.append(line.strip())
            continue
        kept.append(line)
    return "\n".join(kept), False, removed


def _prepare_cell(
    source: str,
    number: int,
    futures: list[str],
    seen_futures: set[str],
) -> str:
    """Return plain Python for one cell, printing a trailing expression."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        detail = f"{exc.msg} (line {exc.lineno})" if exc.lineno else exc.msg
        raise NotebookError(f"syntax error in cell {number}: {detail}", cell=number) from exc

    kept: list[ast.stmt] = []
    removed_future = False
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module == "__future__":
            text = ast.unparse(statement).strip()
            if text not in seen_futures:
                seen_futures.add(text)
                futures.append(text)
            removed_future = True
            continue
        kept.append(statement)
    tree.body = kept

    if tree.body and isinstance(tree.body[-1], ast.Expr):
        expression = ast.unparse(tree.body.pop().value)
        prefix = ast.unparse(tree) if tree.body else ""
        wrapped = f"{_DISPLAY_WRAPPER}({expression})"
        return f"{prefix}\n{wrapped}\n" if prefix else f"{wrapped}\n"

    if removed_future:
        return f"{ast.unparse(tree)}\n" if tree.body else ""

    return source


def build_notebook_script(path: Path) -> NotebookScript:
    """Read ``path`` and produce an executable plain-Python equivalent."""
    notebook = read_notebook(path)
    language = _kernel_language(notebook)
    if not _is_python_kernel(language):
        raise NotebookError(f"unsupported kernel language: {language}")

    cells = _notebook_cells(notebook)
    futures: list[str] = []
    seen_futures: set[str] = set()
    prepared: list[tuple[int, str]] = []
    skipped: list[str] = []
    code_cells = 0

    for number, cell in enumerate(cells, start=1):
        if cell.get("cell_type") != "code":
            continue
        code_cells += 1
        raw = _cell_source(cell)
        cleaned, is_cell_magic, removed = strip_ipython_syntax(raw)
        if is_cell_magic:
            first_line = raw.strip().splitlines()[0] if raw.strip() else "%%"
            skipped.append(f"cell {number}: {first_line.strip()} (cell skipped)")
            continue
        for line in removed:
            skipped.append(f"cell {number}: {line} (line dropped)")
        if not cleaned.strip():
            continue
        prepared.append((number, _prepare_cell(cleaned, number, futures, seen_futures)))

    lines: list[str] = [f"# Extracted from notebook: {path.name}"]
    if futures:
        lines.append("# Future imports hoisted from notebook cells.")
        lines.extend(futures)
    lines.append("")

    line_to_cell: dict[int, int] = {}
    for number, code in prepared:
        if not code.strip():
            continue
        lines.append(f"# %% [cell {number}]")
        line_to_cell[len(lines)] = number
        for code_line in code.rstrip("\n").splitlines():
            lines.append(code_line)
            line_to_cell[len(lines)] = number
        lines.append("")

    return NotebookScript(
        code="\n".join(lines) + "\n",
        notebook_cells=len(cells),
        code_cells=code_cells,
        skipped=skipped,
        line_to_cell=line_to_cell,
        language=language,
    )
