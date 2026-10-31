"""Tests for the Flask API and the question interpreter."""
from types import SimpleNamespace

import pytest

from app import interpreter
from tests.conftest import write_csv


def ask(client, question):
    return client.post("/api/ask", json={"question": question})


# ---------- The five required questions, through the API ----------

def test_total_revenue(small_client):
    response = ask(small_client, "What is the total revenue?")
    assert response.status_code == 200
    assert response.json["figures"][0]["revenue"] == 4400
    assert response.json["interpreted_by"] == "keyword"
    assert "SELECT" in response.json["sql"]


def test_highest_revenue_product(small_client):
    response = ask(small_client, "Which product generated the highest revenue?")
    assert response.status_code == 200
    assert response.json["figures"][0]["product"] == "Desk"


def test_monthly_revenue(small_client):
    response = ask(small_client, "What is the monthly revenue trend?")
    assert response.status_code == 200
    assert [r["revenue"] for r in response.json["figures"]] == [1900, 2500]


def test_highest_sales_region(small_client):
    response = ask(small_client, "Which region generated the highest sales?")
    assert response.status_code == 200
    assert response.json["figures"][0]["region"] == "South"


@pytest.mark.parametrize("question", [
    "How did revenue change between January and February?",
    "Compare January and February revenue",
    "compare 2026-01 and 2026-02",
    "Jan vs Feb 2026 revenue difference",
])
def test_month_comparison(small_client, question):
    response = ask(small_client, question)
    assert response.status_code == 200
    assert response.json["intent"] == "month_comparison"
    assert response.json["figures"][2]["revenue"] == 600


def test_comparison_with_month_outside_the_data(small_client):
    response = ask(small_client, "How did revenue change between January and December?")
    assert response.status_code == 422
    assert "2026-12" in response.json["error"]


def test_comparison_with_only_one_month(small_client):
    response = ask(small_client, "How did revenue change in February?")
    assert response.status_code == 422
    assert "two months" in response.json["error"]


def test_real_dataset_answers(real_client):
    assert ask(real_client, "What is the total revenue?").json["figures"][0]["revenue"] == 1439200
    assert len(ask(real_client, "What is the monthly revenue trend?").json["figures"]) == 6


# ---------- Unsupported and invalid input ----------

@pytest.mark.parametrize("question", [
    "What will the revenue be next year?",
    "Which product sold the most units?",           # we only calculate revenue
    "What is the revenue for February?",            # a single month is not supported
    "Who is the best customer?",
    "Tell me a joke",
    "Which product has the lowest revenue?",
])
def test_unsupported_questions_return_422(small_client, question):
    response = ask(small_client, question)
    assert response.status_code == 422
    assert "can't answer" in response.json["error"]


def test_empty_and_blank_questions(small_client):
    assert ask(small_client, "").status_code == 400
    assert ask(small_client, "    ").status_code == 400


def test_malformed_requests(small_client):
    assert small_client.post("/api/ask", data="not json").status_code == 400
    assert small_client.post("/api/ask", json={"q": "hi"}).status_code == 400
    assert small_client.post("/api/ask", json={"question": 123}).status_code == 400
    assert small_client.post("/api/ask", json=["question"]).status_code == 400


def test_too_long_question(small_client):
    assert ask(small_client, "revenue " * 100).status_code == 400


def test_unknown_url_and_wrong_method_return_json(small_client):
    assert small_client.get("/api/nothing").status_code == 404
    assert small_client.get("/api/nothing").json["error"]
    assert small_client.get("/api/ask").status_code == 405


def test_empty_database_returns_error_not_crash(tmp_path):
    from app.main import create_app
    client = create_app(write_csv(tmp_path, [])).test_client()
    response = ask(client, "What is the total revenue?")
    assert response.status_code == 422
    assert "no completed sales" in response.json["error"]


# ---------- SQL injection ----------

@pytest.mark.parametrize("question", [
    "'; DROP TABLE sales; --",
    "What is the total revenue?'; DELETE FROM sales; --",
    "Which product generated the highest revenue? UNION SELECT * FROM rejected_rows",
    "compare 2026-01'; DROP TABLE sales;-- and 2026-02",
    "Robert'); DROP TABLE sales;--",
])
def test_sql_injection_does_not_change_data(small_client, question):
    response = ask(small_client, question)
    assert response.status_code in (200, 422)
    # the data is still all there and still answers normally
    assert ask(small_client, "What is the total revenue?").json["figures"][0]["revenue"] == 4400
    assert small_client.get("/api/health").json["rows_loaded"] == 5


def test_injected_text_is_not_returned_as_a_month(small_client):
    response = ask(small_client, "compare 2026-01'; DROP TABLE sales;-- and 2026-02")
    assert response.status_code == 200
    assert [r["month"] for r in response.json["figures"]] == ["2026-01", "2026-02", "change"]


# ---------- Health and data quality endpoints ----------

def test_health(real_client):
    data = real_client.get("/api/health").json
    assert data["rows_loaded"] == 49 and data["rows_rejected"] == 2
    assert data["llm_configured"] is False


def test_data_quality_lists_rejected_rows(real_client):
    rejected = real_client.get("/api/data-quality").json["rejected"]
    assert [(r["line_number"], r["transaction_id"]) for r in rejected] == [(35, "TXN0034"), (52, "TXN0051")]


def test_home_page_and_static_files_are_served(small_client):
    page = small_client.get("/")
    assert page.status_code == 200 and b"question" in page.data
    assert small_client.get("/static/app.js").status_code == 200
    assert small_client.get("/static/style.css").status_code == 200


# ---------- LLM interpretation and fallback ----------

def fake_anthropic(monkeypatch, reply_text=None, error=None):
    """Replace the Anthropic client with a fake so no real API call is made."""
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        class messages:
            @staticmethod
            def create(**kwargs):
                if error:
                    raise error
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply_text)])

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_llm_answer_is_used_when_valid(small_client, monkeypatch):
    fake_anthropic(monkeypatch, '{"intent": "top_region"}')
    response = ask(small_client, "where do we sell best?")      # keyword rules would not understand this
    assert response.status_code == 200
    assert response.json["interpreted_by"] == "llm"
    assert response.json["figures"][0]["region"] == "South"


def test_llm_month_comparison_parameters(small_client, monkeypatch):
    fake_anthropic(monkeypatch, '```json\n{"intent": "month_comparison", "month_a": "2026-01", "month_b": "2026-02"}\n```')
    response = ask(small_client, "was February better than January?")
    assert response.json["interpreted_by"] == "llm"
    assert response.json["figures"][2]["revenue"] == 600


def test_llm_saying_unsupported_is_respected(small_client, monkeypatch):
    fake_anthropic(monkeypatch, '{"intent": "unsupported"}')
    assert ask(small_client, "What is the total revenue?").status_code == 422


@pytest.mark.parametrize("bad_reply", [
    "I think you want the total revenue.",                     # not JSON
    "",                                                        # empty
    "[1, 2, 3]",                                               # JSON but not an object
    '{"intent": "run_sql", "sql": "DROP TABLE sales"}',        # intent not in the allowed list
    '{"intent": "month_comparison", "month_a": "2026-01\'; DROP TABLE sales;--", "month_b": "2026-02"}',
    '{"intent": "month_comparison", "month_a": 202601, "month_b": "2026-02"}',
])
def test_invalid_llm_reply_falls_back_to_keywords(small_client, monkeypatch, bad_reply):
    fake_anthropic(monkeypatch, bad_reply)
    response = ask(small_client, "What is the total revenue?")
    assert response.status_code == 200
    assert response.json["interpreted_by"] == "keyword"
    assert response.json["figures"][0]["revenue"] == 4400


def test_llm_api_error_falls_back_to_keywords(small_client, monkeypatch):
    fake_anthropic(monkeypatch, error=TimeoutError("API timed out"))
    response = ask(small_client, "Which region generated the highest sales?")
    assert response.status_code == 200
    assert response.json["interpreted_by"] == "keyword"


def test_llm_not_used_without_api_key(small_client):
    assert ask(small_client, "What is the total revenue?").json["interpreted_by"] == "keyword"


def test_use_llm_switch_turns_llm_off(small_client, monkeypatch):
    fake_anthropic(monkeypatch, '{"intent": "top_region"}')
    monkeypatch.setenv("USE_LLM", "0")
    assert ask(small_client, "What is the total revenue?").json["interpreted_by"] == "keyword"


def test_parse_llm_reply_drops_extra_fields():
    reply = '{"intent": "total_revenue", "sql": "DROP TABLE sales", "extra": 1}'
    assert interpreter.parse_llm_reply(reply) == {"intent": "total_revenue"}


# ---------- Keyword interpreter on its own ----------

@pytest.mark.parametrize("question, intent", [
    ("What is the total revenue?", "total_revenue"),
    ("How much revenue did we make?", "total_revenue"),
    ("Which product generated the highest revenue?", "top_product"),
    ("What is the best selling item?", "unsupported"),     # no clear measure: rejected rather than guessed
    ("Which region generated the highest sales?", "top_region"),
    ("Which category is the best?", "top_category"),
    ("What is the monthly revenue trend?", "monthly_trend"),
])
def test_keyword_interpreter_intents(question, intent):
    assert interpreter.keyword_interpret(question)["intent"] == intent


def test_keyword_interpreter_extracts_months():
    result = interpreter.keyword_interpret("How did revenue change from February to March?")
    assert result == {"intent": "month_comparison", "month_a": "2026-02", "month_b": "2026-03"}
