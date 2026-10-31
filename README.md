# Sales Q&A: a small business-intelligence assistant

A small web app where a business user types a question about sales data in plain English
(for example "Which product generated the highest revenue?") and gets an answer together with
the figures and the SQL query that produced it.

I built it for the AI-Assisted Development Challenge. It is a 3-4 hour assignment project, not a
production system.

## Problem being solved

The sales data is a CSV file of transactions. Someone who does not know SQL should still be able
to ask basic questions about it. The answers must come from real database queries, and the
application should refuse questions it cannot answer instead of guessing.

## Technologies

- Python 3 and Flask for the backend API
- SQLite (in memory) for the data
- Plain HTML, CSS and JavaScript for the frontend, with no frontend libraries
- The Anthropic API (optional) to interpret questions
- pytest for the tests

## Project structure

```
app/
  main.py          Flask app and API endpoints
  db.py            CSV loading, validation, SQLite tables
  analytics.py     The SQL queries and the functions that run them
  interpreter.py   Turns a question into an intent (LLM or keyword rules)
  static/
    index.html     Page
    style.css      Styles
    app.js         Calls the API and shows the results
data/sales.csv     The supplied dataset (unchanged)
tests/
  conftest.py      Shared test data and fixtures
  test_data.py     Tests for CSV loading and analytics
  test_api.py      Tests for the API and the interpreter
AI_USAGE.md        How AI tools were used
requirements.txt
```

## How it works

```
Browser  ->  POST /api/ask  ->  interpreter  ->  analytics  ->  SQLite
                                (picks an        (runs a fixed
                                 intent)          SQL query)
```

1. When the server starts, `db.py` reads `data/sales.csv`, validates every row and loads it into SQLite.
2. The browser sends the question to `POST /api/ask`.
3. `interpreter.py` decides which of a fixed list of intents the question matches
   (`total_revenue`, `top_product`, `top_region`, `top_category`, `monthly_trend`, `month_comparison`).
   - If `ANTHROPIC_API_KEY` is set, I ask the LLM to pick the intent and reply with JSON.
     The reply is checked: it must be valid JSON, the intent must be in the list, and months must look
     like `2026-03`. Extra fields are ignored.
   - If there is no key, the API call fails, or the reply is invalid, simple keyword rules are used instead.
4. `analytics.py` runs the SQL query for that intent. The SQL is written in advance in `analytics.py`.
   The LLM never writes SQL, and the only values passed into a query are two month strings, passed as `?` parameters.
5. The API returns the answer text, the supporting figures, the SQL that was used, and whether the LLM
   or the keyword rules interpreted the question. The page shows these.

As an extra safety net, the database connection is switched to read-only (`PRAGMA query_only`) after the
data is loaded, so a `DROP` or `DELETE` would fail even if one were somehow executed.

### API

| Endpoint | Purpose |
|---|---|
| `POST /api/ask` | Body `{"question": "..."}`. Returns `answer`, `figures`, `sql`, `intent`, `interpreted_by`. Errors return `{"error": "..."}` with status 400 (bad request) or 422 (question not supported / no data). |
| `GET /api/health` | Rows loaded, rows rejected, and whether the LLM is configured |
| `GET /api/data-quality` | The rejected rows with their line number and reason |

## Database design

Two tables (see `SCHEMA` in `db.py`):

- `sales`: one row per valid transaction. Dates are stored as `yyyy-mm-dd`, and there is a `month`
  column (`yyyy-mm`) used for the monthly queries. `transaction_id` is the primary key, and CHECK
  constraints require `quantity > 0`, `unit_price > 0` and `discount >= 0`.
- `rejected_rows`: every row that failed validation, with its CSV line number, transaction id, the
  reason and the raw row. Rows are never silently dropped.

A row is rejected if it has a missing product, category, region, channel, status, quantity or unit
price, an invalid date (expected `DD-MM-YYYY`), a non-numeric or non-finite number, a quantity that is
zero, negative or fractional, a price of zero or less, a negative discount, a discount larger than the
order amount, or a transaction id that already appeared earlier in the file (the first one is kept).
A blank discount is treated as 0.

With the supplied CSV, 49 rows are loaded and 2 are rejected: `TXN0034` (quantity 0) and `TXN0051`
(blank unit price).

## How revenue is calculated

```
revenue = quantity * unit_price - discount
```

I calculate it once when loading the data and store it in `sales.revenue`. Only orders with status
`Completed` are counted, so returned orders (`TXN0033` in the supplied data) are excluded. I treated
`Discount_amount` as the total discount for the whole row, not per unit. The CSV does not say which it
is, so this is an assumption.

## Supported questions

| Question type | Example |
|---|---|
| Total revenue | "What is the total revenue?" |
| Top product by revenue | "Which product generated the highest revenue?" |
| Top region by sales | "Which region generated the highest sales?" |
| Monthly revenue trend | "What is the monthly revenue trend?" |
| Compare two months | "How did revenue change between February and March?" |
| Top category by revenue | "Which category has the highest revenue?" |

Anything else returns a message explaining what can be asked.

## Setup

```
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

The LLM is optional. To use it:

```
export ANTHROPIC_API_KEY=your-key       # Windows PowerShell: $env:ANTHROPIC_API_KEY="your-key"
```

Optional environment variables: `LLM_MODEL` (default `claude-sonnet-4-6`), `USE_LLM=0` to force the keyword rules
even when a key is set, `PORT` (default 5000), and `SALES_CSV` for a different CSV path.

## Running the application

```
python -m app.main
```

Then open http://127.0.0.1:5000.

## Running the tests

```
python -m pytest
```

Run this from the project folder (using `python -m` makes the `app` package importable).
The tests do not call the real API (a fake client is used), so they need no key and no network.
They cover the five required questions, unsupported and empty questions, missing values, duplicate ids,
fractional quantities, returned orders, an empty database, invalid months, SQL injection attempts, and
the LLM fallback.

## Known limitations

- Only the question types listed above work. There is no filtering ("revenue in the North region"),
  no revenue for a single month, and no "top 3" lists. Those questions are refused.
- The keyword rules are simple. Unusual wording is refused, and the word "may" is read as the month.
  With an API key the LLM handles more phrasing.
- If a question gives a month but no year, I assume 2026 (`DEFAULT_YEAR` in `interpreter.py`).
- Questions about units sold, profit, customers or forecasts are refused, because the data cannot
  answer them correctly or the meaning is ambiguous ("best selling" could mean units or revenue).
- The database is rebuilt in memory every time the server starts. There is no login and no multi-user support.
- A discount is assumed to be per row, and only `Completed` orders count as revenue (see above).
- The tests check the LLM path with a fake client. A successful call to the real API has not been tested.
- The frontend was checked with a simulated DOM (jsdom), not in real browsers, so the visual layout on
  different screens has not been verified.
