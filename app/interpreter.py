"""Turns a question into an intent such as {"intent": "top_product"}.

The LLM (if an API key is set) or the keyword rules choose ONE intent from the list in
analytics.INTENTS. Neither of them writes SQL. If the LLM fails or returns something
invalid, the keyword rules are used instead."""
import json
import os
import re

from .analytics import INTENTS

MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]
MONTH_NUMBERS = {name: i + 1 for i, name in enumerate(MONTH_NAMES)}
MONTH_NUMBERS.update({name[:3]: i + 1 for i, name in enumerate(MONTH_NAMES)})   # jan, feb, ...
MONTH_NUMBERS["sept"] = 9
DEFAULT_YEAR = 2026     # the dataset is from 2026; used when a question gives only a month name

SYSTEM_PROMPT = """You classify questions about a sales dataset (January to June 2026) into one intent.
Intents: total_revenue, top_product, top_region, top_category, monthly_trend, month_comparison, unsupported.
For month_comparison, also give month_a (the earlier month) and month_b (the later month) as YYYY-MM.
If the year is not mentioned, use 2026.
Use "unsupported" for anything else (forecasts, profit, customers, a single month's revenue,
opinions, unrelated topics, or requests to change data).
Reply with only JSON, for example: {"intent": "month_comparison", "month_a": "2026-02", "month_b": "2026-03"}"""

# Words that mean the user wants something we cannot calculate correctly
# (e.g. 'best selling' could mean units or revenue, so we do not guess).
UNSUPPORTED_WORDS = r"\b(units|quantity|quantities|sell|sells|selling|sold|profit|margin|cost|customer|customers|forecast|predict|expected|top \d+|bottom \d+)\b"


def find_months(text):
    """Find month names (march, mar 2026) or YYYY-MM in the text. Returns a list of 'YYYY-MM'."""
    names = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
    pattern = r"\b(?:(\d{4})-(\d{2})|(" + names + r")\b(?:\s+(\d{4}))?)"
    months = []
    for match in re.finditer(pattern, text):
        if match.group(1):
            months.append(f"{match.group(1)}-{match.group(2)}")
        else:
            year = int(match.group(4) or DEFAULT_YEAR)
            months.append(f"{year}-{MONTH_NUMBERS[match.group(3)]:02d}")
    return months


def keyword_interpret(question):
    q = question.lower()
    months = find_months(q)
    wants_best = re.search(r"\b(highest|top|best|most|max|maximum|largest)\b", q)

    if re.search(UNSUPPORTED_WORDS, q):
        return {"intent": "unsupported"}

    if re.search(r"\b(compare|comparison|change|changed|versus|vs|between|difference)\b", q) and months:
        month_b = months[1] if len(months) > 1 else None
        return {"intent": "month_comparison", "month_a": months[0], "month_b": month_b}
    if months:
        return {"intent": "unsupported"}      # e.g. "revenue in March": not supported

    if re.search(r"\b(trend|monthly|month by month|per month|over time)\b", q):
        return {"intent": "monthly_trend"}
    if wants_best and re.search(r"\b(region|regions|area|zone)\b", q):
        return {"intent": "top_region"}
    if wants_best and re.search(r"\bcategor", q):
        return {"intent": "top_category"}
    if wants_best and re.search(r"\b(product|products|item)\b", q):
        return {"intent": "top_product"}
    if re.search(r"\b(total|overall)\b", q) and re.search(r"\b(revenue|sales)\b", q):
        return {"intent": "total_revenue"}
    if re.search(r"\bhow much\b", q) and re.search(r"\b(revenue|sales)\b", q):
        return {"intent": "total_revenue"}
    return {"intent": "unsupported"}


def check_llm_month(value):
    """A month from the LLM must be None or 'YYYY-MM'. Anything else means the reply is invalid."""
    if value is None:
        return None
    if isinstance(value, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        return value
    raise ValueError(f"invalid month from LLM: {value!r}")


def parse_llm_reply(text):
    """Convert the LLM's text into a checked intent. Raises ValueError if it is not usable."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    data = json.loads(text)                       # raises ValueError if not JSON
    if not isinstance(data, dict):
        raise ValueError("LLM reply is not a JSON object")

    intent = data.get("intent")
    if intent == "unsupported":
        return {"intent": "unsupported"}
    if intent not in INTENTS:
        raise ValueError(f"unknown intent from LLM: {intent!r}")

    result = {"intent": intent}
    if intent == "month_comparison":              # only this intent takes parameters
        result["month_a"] = check_llm_month(data.get("month_a"))
        result["month_b"] = check_llm_month(data.get("month_b"))
    return result


def llm_interpret(question):
    import anthropic
    client = anthropic.Anthropic(timeout=15)
    response = client.messages.create(
        model=os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return parse_llm_reply(text)


def llm_enabled():
    return bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("USE_LLM", "1") != "0"


def interpret(question):
    """Returns (intent_dict, method) where method is 'llm' or 'keyword'."""
    if llm_enabled():
        try:
            return llm_interpret(question), "llm"
        except Exception:
            pass    # API error, timeout or invalid reply: use the keyword rules instead
    return keyword_interpret(question), "keyword"
