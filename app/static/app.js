const EXAMPLES = [
  "What is the total revenue?",
  "Which product generated the highest revenue?",
  "What is the monthly revenue trend?",
  "Which region generated the highest sales?",
  "How did revenue change between February and March?",
];

const form = document.getElementById("ask-form");
const questionInput = document.getElementById("question");
const askButton = document.getElementById("ask-button");
const resultSection = document.getElementById("result");
const answerEl = document.getElementById("answer");
const methodEl = document.getElementById("method");
const table = document.getElementById("figures");
const sqlEl = document.getElementById("sql");
const statusEl = document.getElementById("status");

// Column names from the API -> labels shown in the table
const COLUMN_LABELS = {
  product: "Product", region: "Region", category: "Category", month: "Month",
  revenue: "Revenue", orders: "Orders", units: "Units",
  gross_amount: "Gross amount", discounts: "Discounts", change_pct: "Change %",
};

function formatValue(column, value) {
  if (value === null || value === undefined) return "-";
  if (typeof value !== "number") return value;
  const text = value.toLocaleString("en-IN", { maximumFractionDigits: 1 });
  return column === "change_pct" ? text + "%" : text;
}

function showTable(rows) {
  table.replaceChildren();
  const columns = Object.keys(rows[0]);

  const headerRow = table.insertRow();
  for (const column of columns) {
    const th = document.createElement("th");
    th.textContent = COLUMN_LABELS[column] || column;
    headerRow.appendChild(th);
  }
  for (const row of rows) {
    const tr = table.insertRow();
    for (const column of columns) {
      tr.insertCell().textContent = formatValue(column, row[column]);
    }
  }
}

function showError(message) {
  resultSection.hidden = false;
  answerEl.textContent = message;
  answerEl.className = "error";
  methodEl.textContent = "";
  table.replaceChildren();
  sqlEl.textContent = "";
  table.closest(".table-wrap").hidden = true;
  sqlEl.closest("details").hidden = true;
}

function showResult(data) {
  resultSection.hidden = false;
  answerEl.textContent = data.answer;
  answerEl.className = "";
  const how = data.interpreted_by === "llm" ? "LLM" : "keyword matching";
  methodEl.textContent = "Question interpreted by: " + how + " (" + data.intent + ")";
  showTable(data.figures);
  sqlEl.textContent = data.sql;
  table.closest(".table-wrap").hidden = false;
  sqlEl.closest("details").hidden = false;
}

async function ask(question) {
  askButton.disabled = true;
  askButton.textContent = "Asking...";
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question }),
    });
    const data = await response.json();
    if (response.ok) {
      showResult(data);
    } else {
      showError(data.error || "Request failed.");
    }
  } catch (err) {
    showError("Could not reach the server. Is it running?");
  } finally {
    askButton.disabled = false;
    askButton.textContent = "Ask";
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  ask(questionInput.value);
});

for (const text of EXAMPLES) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = text;
  button.addEventListener("click", () => {
    questionInput.value = text;
    ask(text);
  });
  document.getElementById("examples").appendChild(button);
}

// Header status and data-quality summary
async function loadStatus() {
  try {
    const health = await (await fetch("/api/health")).json();
    statusEl.textContent = health.llm_configured ? "Interpreter: LLM (keyword fallback)" : "Interpreter: keyword matching";
    document.getElementById("quality-summary").textContent =
      health.rows_loaded + " rows loaded, " + health.rows_rejected + " rejected.";

    if (health.rows_rejected > 0) {
      const quality = await (await fetch("/api/data-quality")).json();
      const list = document.getElementById("rejected-list");
      for (const row of quality.rejected) {
        const item = document.createElement("li");
        item.textContent = "Line " + row.line_number + " (" + (row.transaction_id || "no id") + "): " + row.reason;
        list.appendChild(item);
      }
      document.getElementById("rejected-details").hidden = false;
    }
  } catch (err) {
    statusEl.textContent = "Server not reachable";
  }
}
loadStatus();
