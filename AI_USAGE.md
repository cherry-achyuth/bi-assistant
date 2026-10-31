# AI Usage

I used an AI assistant (Claude, in the Claude chat interface) to help build this project. This
document says what the AI did, what was checked and how, and what I still need to be able to explain.

## What the AI did

Most of the code was written by Claude. I did not write the first version myself. The process was:

1. I gave Claude the assignment document and the CSV file and asked it to complete the task. It
   produced the first version of the backend, the frontend, the tests, the README and this file.
2. In a second round I asked Claude to review and refactor that version. It read all the files, fixed
   problems (listed below), rewrote the frontend, expanded the tests and rewrote the documentation.

The AI helped in these areas:

- **Assignment requirements and architecture.** Choosing to have the LLM only pick an intent from a fixed
  list, instead of writing SQL (text-to-SQL), so that no generated query is ever executed.
- **SQL.** The queries in `analytics.py`.
- **CSV parsing and validation.** The rules in `db.py` and the handling of the bad rows in the dataset
  (zero quantity, blank price, a returned order).
- **LLM response handling.** The prompt, the JSON parsing and the checks on the reply in `interpreter.py`.
- **Error handling.** The API error responses and the fallback to keyword rules.
- **Tests.** The test cases and the hand-calculated test data.
- **Frontend.** The layout, styles and JavaScript.

## What was checked, and how

These checks were run by Claude during development, and the commands and outputs were shown in the chat:

- The automated tests (`python -m pytest`): 100 tests passed in the final run.
- The total revenue (1,439,200 from 48 orders) was recalculated from the raw CSV with a separate plain-Python
  script, and a test compares the SQL results for total, product, region and month with the same kind of
  independent calculation.
- A set of deliberate code changes (for example, counting returned orders, accepting fractional quantities,
  skipping month validation) was made one at a time to confirm that the tests fail when the code is wrong.
- The server was started and the API was called with curl. The real page and JavaScript were run in a
  simulated browser (jsdom) against the live server: the five example buttons, the unsupported and empty
  question messages, and a question containing HTML.
- The fallback was tried with an invalid API key. The real Anthropic client failed and the keyword rules answered.

## Problems found during the work

- The first test had a wrong expected total revenue (1,070,550). It failed against the app's 1,439,200. I recalculated
  the total independently from the CSV, which gave 1,439,200, so the test was wrong, not the app.
- During the review, Claude found problems in its own first version: fractional quantities were silently cut to
  whole numbers, `nan` was accepted as a number, a regular expression had an operator-precedence mistake, and
  "What is the revenue for March?" returned the all-time total instead of being refused.
- An old test file set `USE_LLM=0` for the whole test run, which made some LLM tests fail only when the full suite
  ran. That file was removed and the new tests clear the variable.
- One test was too loose: a deliberate bug in month validation was not detected until the test checked for the
  specific error message.

## What I still need to do myself

The AI wrote most of this code, so I should not claim I developed it alone. Before submitting I need to
read every file and be able to explain it, including how the CSV is validated, how revenue is calculated,
what the SQL queries do, why the LLM is not allowed to write SQL, and how the fallback works. I should also run the
app and the tests on my own machine and try the questions myself.

[Add here, only if true: what I personally ran, changed or tested.]

## Limitations

See "Known limitations" in `README.md`. The main ones: only fixed question types are supported, a successful call to the
real LLM API has not been tested (only a fake client and a failing call), and the frontend has not been checked in
real browsers.
