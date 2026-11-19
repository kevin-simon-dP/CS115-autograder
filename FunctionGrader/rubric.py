"""The rubric base function. Defines which functions to call,
 the args, and worth how many points"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
# format of a test
class Format:
    label: str
    points: float
    kind: str = "cases" # cases(call fn, all must pass), signature(name + param count), terminates(no timeouts), manual(by hand), code(by hand, shows code)
    compare: str = "eq" # eq (==), typeEq(== typecheck), #bool(checks 1/0)
    cases: list[tuple[tuple, Any]] = field(default_factory=list) # [(args, expected)], args always a tuple: ((10, 5), True) -> fn(10, 5) == True

@dataclass
# function signiture to test
class Function:
    name: str
    params: int #int for now, can be changed in future
    checks: list[Format] # type of checks to perform

@dataclass
# the whole rubric
class Rubric:
    functions: list[Function]
    filename_pattern: str | None = None
    filename_penalty: float = 0.0

    def cases(self) -> list[tuple[int, Function, Format, tuple, Any]]:
        out = []
        for fn in self.functions:
            for check in fn.checks:
                if check.kind == "cases":
                    for args, expected in check.cases:
                        out.append((len(out), fn, check, args, expected))
        return out

    def total(self) -> float:
        return sum(check.points for fn in self.functions for check in fn.checks)

def load_spec(path: Path) -> Rubric:
    """import a rubric file and build function classes from it"""
    module_spec = importlib.util.spec_from_file_location("grading_rubric", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return Rubric(
        functions = module.FUNCTIONS,
        filename_pattern=getattr(module, "FILENAME_PATTERN", None),
        filename_penalty=getattr(module, "FILENAME_PENALTY", 0.0)
        )