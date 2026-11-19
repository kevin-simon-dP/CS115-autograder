"""Prepare extracted submission code for --tests mode.

In a normal run the submission is executed and its stdout is the graded value.
In --tests mode the submission is imported by an instructor test script
instead, so any output it produces would be mixed into the test script's stdout
and corrupt the diff. This module removes that output at the source level.

``print(...)`` calls are rewritten to calls to an inline no-op lambda rather
than deleted, because print itself returns None and its arguments may have side
effects. Only the ``print`` identifier itself is rewritten, so comments, blank
lines, and line numbers are preserved.
"""

from __future__ import annotations

import ast

# print() evaluates its arguments and returns None; this snippet does the same
# without writing anything.
_NOOP_PRINT = "(lambda *args, **kwargs: None)"


def strip_prints(source: str) -> tuple[str, int]:
    """Replace every ``print(...)`` call with a silent no-op.

    Returns ``(new_source, calls_replaced)``. A source that does not parse
    raises ``SyntaxError`` (or ``ValueError`` for e.g. null bytes); callers that
    want to keep an unparseable student file should catch it and fall back to
    the original text.
    """
    tree = ast.parse(source)

    # Record the source span of the ``print`` name in each call. spans use the
    # UTF-8 byte offsets that CPython stores on AST nodes.
    spans: list[tuple[int, int, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            spans.append(
                (node.func.lineno, node.func.col_offset, node.func.end_col_offset)
            )
    if not spans:
        return source, 0

    lines = source.splitlines(keepends=True)
    by_line: dict[int, list[tuple[int, int]]] = {}
    for lineno, start, end in spans:
        by_line.setdefault(lineno, []).append((start, end))

    replacement = _NOOP_PRINT.encode("utf-8")
    for lineno, ranges in by_line.items():
        raw = lines[lineno - 1].encode("utf-8")
        # Splice right-to-left so the offsets of earlier calls stay valid.
        for start, end in sorted(ranges, reverse=True):
            raw = raw[:start] + replacement + raw[end:]
        lines[lineno - 1] = raw.decode("utf-8")

    return "".join(lines), len(spans)
