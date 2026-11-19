"""
loads a student script, call its functions, report JSON lines
python harness.py <student_script> <rubric_file> <start_index>
"""
from __future__ import annotations

import builtins
import contextlib
import copy
import inspect
import io
import json
import sys
from pathlib import Path

from rubric import Format, Function, load_spec

_OUT = sys.stdout

def emit(record: dict) ->None:
    _OUT.write(json.dumps(record) + "\n")
    _OUT.flush()

def trunc(value, limit: int = 200) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."

# return value check
def matchesOutput(got, expected, compare: str)-> bool:
    if compare =="eq":
        return got == expected
    if compare == "typeEq":
        return type(got) is type(expected) and got == expected
    if compare =="bool":
        return got is not None and bool(got) == bool(expected)
    raise ValueError(f"unknown compare mode in rubric: {compare!r}")

def main() -> None:
    script = Path(sys.argv[1])
    rubric = load_spec(Path(sys.argv[2]))
    start = int(sys.argv[3])

    builtins.input = lambda *args, **kwargs: ""

    # 1. run student's script
    ns: dict = {"__name__": "__student__", "__file__": str(script)}
    try:
        source = script.read_text(encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(source, str(script), "exec"), ns)
    except BaseException as exc:
        emit({"event": "load_error", "error": f"{type(exc).__name__}: {exc}"})

    emit({"event": "loaded"})

    # 2. function signatures check
    if start == 0:
            for fn in rubric.functions:
                obj = ns.get(fn.name)
                params = None
                if callable(obj):
                    try:
                        params = len(inspect.signature(obj).parameters)
                    except(TypeError, ValueError):
                        pass
                emit({"event": "signature", "fn": fn.name, 
                             "found": callable(obj), "params": params})

    # 3. run all test cases
    for index, fn, check, args, expected in rubric.cases():
        if index < start:
            continue
        record = {"event": "case", "i": index, "fn": fn.name,
                  "args": trunc(args), "expected": trunc(expected)}
        obj = ns.get(fn.name)
        if not callable(obj):
            record["status"] = "missing"
            emit(record)
            continue

        printed = io.StringIO()
        try:
            with contextlib.redirect_stdout(printed):
                got = obj(*copy.deepcopy(args))
        except BaseException as exc:
            record["status"] = "error"
            record["got"] = f"{type(exc).__name__}: {exc}"
        else:
            record["status"] = "pass" if matchesOutput(got, expected, check.compare) else "fail"
            record["got"] = trunc(got)
        record["printed"] = printed.getvalue()[:500]
        emit(record)


if __name__ == "__main__":
    main()