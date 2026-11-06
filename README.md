# Summary
NOTE: The code (and comments within code) in this repo was generated with the aid of an LLM. This README is human written.

This repo contains a set of scripts to automate grading CS115 submissions. The script takes in an input directory
where each folder in the directory corresponds to the name of a student and inside it their submission.

The autograder will walk the input directory and grade the submission. Grading the submission entails:
- parsing ipynb files to extract the executable python code within
- running executable python code in the submission
- diffing stdout from submission against expected output
- create a graded directory for each student with diff details

The output directory will contain a 'summary.txt' file in the root of the directory summarizing results of the
autograder run. This is intended to get a high level view of which students had their output match exactly
and which did not, the later requiring some additional inspection to grade.

# Example usage

## Run against sample assignment
`uv run autograder.py`

## Run against real assignment (default output)
`uv run autograder.py --submissions "C:\example\path\to\submissions" --expected "C:\example\path\to\expected.txt"`
NOTE: --output is not provided so output directory will default to same directory as submissions

## Run against real assignment (custom output)
`uv run autograder.py --submissions "C:\example\path\to\submissions" --out "C:\example\path\to\graded\submissions" --expected "C:\example\path\to\expected.txt"`

# Some additional arguments
## --timeout
- Control timeout a submission can run for before we terminate. Defaults to 10 seconds.
## --python
- Use a custom provided interpreter. Idk I guess the clanker thought this was necesscary?
