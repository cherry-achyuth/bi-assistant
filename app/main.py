import os
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from . import analytics, db, interpreter

ROOT = Path(__file__).resolve().parent.parent
MAX_QUESTION_LENGTH = 500


def create_app(csv_path=None):
    app = Flask(__name__)
    conn = db.get_connection(csv_path or os.getenv("SALES_CSV", ROOT / "data" / "sales.csv"))

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/health")
    def health():
        loaded = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM rejected_rows").fetchone()[0]
        return {"status": "ok", "rows_loaded": loaded, "rows_rejected": rejected,
                "llm_configured": interpreter.llm_enabled()}

    @app.get("/api/data-quality")
    def data_quality():
        rows = conn.execute("SELECT line_number, transaction_id, reason FROM rejected_rows "
                            "ORDER BY line_number").fetchall()
        return {"rejected": [dict(row) for row in rows]}

    @app.post("/api/ask")
    def ask():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("question"), str):
            return jsonify(error='Send JSON like {"question": "What is the total revenue?"}'), 400

        question = body["question"].strip()
        if not question:
            return jsonify(error="Please type a question."), 400
        if len(question) > MAX_QUESTION_LENGTH:
            return jsonify(error=f"The question is too long (maximum {MAX_QUESTION_LENGTH} characters)."), 400

        intent, method = interpreter.interpret(question)
        if intent["intent"] == "unsupported":
            return jsonify(error="I can't answer that from this sales data. Try asking for the total "
                                 "revenue, the top product, the top region, the monthly trend, or a "
                                 "comparison of two months."), 422

        parameters = {key: value for key, value in intent.items() if key != "intent"}
        try:
            result = analytics.INTENTS[intent["intent"]](conn, **parameters)
        except analytics.AnalyticsError as error:
            return jsonify(error=str(error)), 422

        return jsonify(question=question, intent=intent["intent"], interpreted_by=method, **result)

    @app.errorhandler(Exception)
    def handle_error(error):
        if isinstance(error, HTTPException):          # 404, 405, ...
            return jsonify(error=error.description), error.code
        app.logger.exception(error)
        return jsonify(error="Something went wrong on the server."), 500

    return app


if __name__ == "__main__":
    create_app().run(port=int(os.getenv("PORT", 5000)))
