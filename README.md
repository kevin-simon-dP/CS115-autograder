# Summary
NOTE: The code (and comments within code) in this repo was generated with the aid of an LLM. This README is human written.

This repo contains a set of scripts to automate grading CS115 submissions. The script takes in an input directory
where each folder in the directory corresponds to the name of a student and inside it their submission.

The autograder will walk the input directory and grade the submission. Grading the submission entails:
- parsing ipynb files to extract the executable python code within
- running executable python code in the submission
- diffing stdout from submission against expected output
- create a graded directory for each student with diff details

It can also run your own test script against each submission instead of comparing raw stdout (see
[Testing with your own test cases](#testing-with-your-own-test-cases)).

The output directory will contain a 'summary.txt' file in the root of the directory summarizing results of the
autograder run. This is intended to get a high level view of which students had their output match exactly
and which did not, the later requiring some additional inspection to grade.

# Example usage

## Run against sample assignment
`uv run autograder.py`

## Run against real assignment (default output)
`uv run autograder.py --submissions "C:\example\path\to\submissions" --expected "C:\example\path\to\expected.txt"`
- NOTE: --output is not provided so output directory will default to same directory as submissions

## Run against real assignment (custom output)
`uv run autograder.py --submissions "C:\example\path\to\submissions" --out "C:\example\path\to\graded\submissions" --expected "C:\example\path\to\expected.txt"`

# Testing with your own test cases

Instead of diffing the raw stdout of each submission, you can run a Python runner script that tests
the submission's `extracted.py`:

`uv run autograder.py --tests "C:\example\path\to\tests.py" --expected "C:\example\path\to\expected_tests.txt"`

For every student the autograder:
- materializes the submission as `<out>/<student dir>_graded/extracted.py` (generated from a notebook,
  or copied from the submission's `.py` file),
- runs `python tests.py <out>/<student dir>_graded/extracted.py` with the submission directory as the
  working directory,
- saves the test script's stdout to `test_output.txt`, and diffs it against `--expected` (which
  defaults to `expected.txt`, just like a normal run).

Because the submission is imported rather than run for its stdout, `--tests` mode also silences it:
`print(...)` calls in `extracted.py` are replaced with a no-op (arguments are still evaluated) and
notebook trailing-expression output is turned off, so importing the submission does not pollute your
test output. The original submission file is never modified; `tests.txt` records how many calls were
silenced. Tests should therefore assert on return values rather than captured stdout.

The test script can locate the submission in any of these ways:
- `sys.argv[1]` - path to the submission's `extracted.py`
- `AUTOGRADER_SUBMISSION` / `AUTOGRADER_SUBMISSION_DIR` - environment variables
- `import extracted` - the graded directory is on `PYTHONPATH`, so this always works

Example `tests.py`:

```python
import contextlib
import io

buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    import extracted  # provided by the autograder
assert buffer.getvalue() == "", "submission produced output on import"

passed = extracted.add(2, 3) == 5
print("PASS" if passed else "FAIL")
raise SystemExit(0 if passed else 1)
```

NOTE: the test script is run directly with `python`, so it must do its work at module level or under
`if __name__ == "__main__":`. If you use pytest, add a `__main__` block, e.g.
`raise SystemExit(pytest.main([__file__]))`.

Pass/fail rules in `--tests` mode:
- The test script's stdout must match the expected file exactly, just like `extracted.py`'s stdout does
  in a normal run. A diff is written to `diff.txt`, so it shows exactly which test cases failed.
- The test script must also exit `0`; a non-zero exit or timeout needs manual review.
- stderr is recorded in `error.txt` when the run has a problem, but writing to stderr alone does not
  fail a submission (test runners such as `unittest` use it).

# Some additional arguments
## --timeout
- Control timeout a submission can run for before we terminate. Defaults to 10 seconds.
## --python
- Use a custom provided interpreter. Idk I guess the clanker thought this was necesscary?
## --tests
- Path to a Python runner script to run against each submission instead of running it directly.
  See [Testing with your own test cases](#testing-with-your-own-test-cases).
## --expected
- Expected output file. Defaults to `expected.txt`. In `--tests` mode this is the expected output of
  your test script.
