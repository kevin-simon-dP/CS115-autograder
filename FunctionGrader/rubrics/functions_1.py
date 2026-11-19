"""Rubric for Functions(1). Total 20 points."""

from rubric import Format, Function

FILENAME_PATTERN = r"CS 115-Functions-1-{first}_{last}\.ipynb"
FILENAME_PENALTY = 0.5

FUNCTIONS = [
    Function("is_divisible_by", params=2, checks=[
        Format("defines function with name + 2 params", 1, kind="signature"),
        Format("checks remainder is zero", 2, compare="bool", cases=[
            ((10, 5), True),
            ((10, 3), False),
            ((0, 7), True),
            ((-9, 3), True),
        ]),
        Format("returns bool, not just printing", 1, compare="typeEq", cases=[
            ((10, 5), True),
            ((10, 3), False),
        ]),
        Format("markdown cell describing function", 1, kind="manual"),
    ]),

    Function("find_max_common", params=2, checks=[
        Format("defines function with name + 2 params", 1, kind="signature"),
        Format("largest common value (order/duplicates)", 2, cases=[
            (([1, 5, 3], [3, 5, 9]), 5),
            (([9, 9, 2], [2, 9, 9]), 9),
            (([3, 1], [1, 3]), 3),
            (([-4, -2], [-2, -7]), -2),
        ]),
        Format("None when no common / empty list", 1, compare="typeEq", cases=[
            (([1, 2], [3, 4]), None),
            (([], [1]), None),
            (([1], []), None),
            (([], []), None),
        ]),
        Format("markdown cell describing function", 1, kind="manual"),
    ]),

    Function("find_gcd", params=2, checks=[
        Format("defines function with name + 2 params", 1, kind="signature"),
        Format("handles either input order", 2, cases=[
            ((48, 18), 6),
            ((18, 48), 6),
            ((270, 192), 6),
            ((192, 270), 6),
        ]),
        Format("implements Euclid's algorithm (1 remainder, 2 updates)", 3, kind="code"),
        Format("terminates", 1, kind="terminates"),
        Format("correct GCD incl. edge cases", 2, cases=[
            ((12, 12), 12),   # equal inputs
            ((5, 25), 5),     # one divides the other
            ((25, 5), 5),
            ((17, 13), 1),    # relatively prime
            ((1, 9), 1),
        ]),
        Format("markdown cell describing function", 1, kind="manual"),
    ]),
]