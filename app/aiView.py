"""
aiView.py — LLM pipeline, provider-agnostic.
Provider and model are selected via LLM_PROVIDER / LLM_MODEL in .env.

run_nl_query(question, db, status_cb=None) -> dict

  status_cb is an optional callable(step, detail) invoked at each stage:
    ("thinking",    "Understanding your question...")
    ("generating",  "Writing SQL query...")
    ("querying",    "SELECT COUNT(*) FROM film")
    ("reading",     "Reading 42 rows...")
    ("summarising", "Preparing your answer...")
    ("done",        "")
"""

import json
import logging

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

from .models import DatabaseConnection
from .aiTools import execute_query, fetch_schema
from .providers.router import get_llm, get_summary_llm, LLM_PROVIDER, LLM_MODEL

logger = logging.getLogger('app.ai')


def _extract_text(content) -> str:
    """
    Normalise LLM response content to a plain string.
    - Ollama / OpenAI return a str directly.
    - Gemini returns a list of content parts like [{'type': 'text', 'text': '...'}]
      or sometimes ContentBlock objects with a .text attribute.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get('text', str(part)))
            elif hasattr(part, 'text'):
                parts.append(part.text)
            else:
                parts.append(str(part))
        return ''.join(parts)
    if hasattr(content, 'text'):
        return content.text
    return str(content)
from langchain_core.tools import tool

from .models import DatabaseConnection
from .aiTools import execute_query, fetch_schema

logger = logging.getLogger('app.ai')

OLLAMA_MODEL = "qwen2.5-coder:3b"


# ── Tool definition ────────────────────────────────────────────────────────────

@tool
def run_sql(query: str) -> str:
    """
    Execute a SQL query against the connected database and return the results.
    Always call this tool to retrieve data — never guess the result yourself.

    Args:
        query: A valid SQL SELECT statement.
    """
    return ""


# ── System prompt ──────────────────────────────────────────────────────────────

def _build_system_prompt(db: DatabaseConnection, schema: str) -> str:
    db_type_label = db.get_db_type_display()
    schema_section = (
        f"DATABASE SCHEMA ({db.label}):\n{schema}"
        if schema
        else "DATABASE SCHEMA: Not available. Use your best judgment based on the question."
    )
    user_description = (
        f"\nUser-provided description: {db.schema_description}"
        if db.schema_description
        else ""
    )
    return f"""You are a data analyst assistant. The user is connected to a {db_type_label} database labelled "{db.label}".

{schema_section}{user_description}

Your job:
1. Understand the user's plain-English question.
2. Write a correct SQL query that answers it.
3. Call the run_sql tool with that query.
4. When you receive the results, summarise the answer in plain English — clear, concise, no jargon.
5. If the query returns no rows, say so clearly.
6. If the question cannot be answered with SQL (e.g. it is conversational), answer directly without calling the tool.

Rules:
- Only write SELECT statements. Never INSERT, UPDATE, DELETE, DROP, or any DDL.
- Use the exact table and column names from the schema above.
- Always SELECT all columns that are relevant to the answer — including numeric/value columns, not just name/label columns.
- Limit results to 100 rows unless the user asks for more.
- When summarising results, highlight key numbers and insights.
"""


# ── Text fallback parser ───────────────────────────────────────────────────────

def _extract_tool_call_from_text(text: str) -> dict | None:
    """
    When Ollama doesn't produce a structured tool_call, parse the JSON it
    embeds in content:
      {"name": "run_sql", "arguments": {"query": "SELECT ..."}}
    No regex on the SQL value itself — uses json.loads on the full object.
    """
    cleaned = text.strip()
    for fence in ['```json', '```']:
        cleaned = cleaned.replace(fence, '')
    cleaned = cleaned.strip()

    start = cleaned.find('{')
    end   = cleaned.rfind('}')
    if start == -1 or end == -1:
        logger.debug(f"[FALLBACK] No JSON object found in response")
        return None

    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        logger.debug(f"[FALLBACK] JSON parse failed: {e}")
        return None

    args  = obj.get("arguments") or obj.get("parameters") or {}
    query = args.get("query", "").strip().rstrip(';')
    if not query:
        logger.debug(f"[FALLBACK] Parsed JSON but no 'query' field: {obj}")
        return None

    logger.warning(f"[FALLBACK] Extracted SQL from text (model skipped tool_calls): {query[:200]}")
    return {"query": query, "id": "text_fallback"}


# ── Main entry point ───────────────────────────────────────────────────────────

def run_nl_query(question: str, db: DatabaseConnection, status_cb=None) -> dict:
    """
    Full NL→SQL→NL pipeline.

    status_cb: optional callable(step: str, detail: str) called at each stage.
      Steps emitted:
        "thinking"    — LLM is reading the question
        "generating"  — LLM produced a tool call, about to execute
        "querying"    — SQL sent to database (detail = the SQL string)
        "reading"     — rows returned (detail = "N rows")
        "summarising" — second LLM call for plain-English answer
        "done"        — pipeline complete

    Returns dict with keys: sql, nl_response, columns, rows, error
    """

    def notify(step, detail=""):
        if status_cb:
            try:
                status_cb(step, detail)
            except Exception:
                pass

    logger.info(f"[QUERY START] db='{db.label}' (id={db.id}) question='{question}'")

    schema = db.fetched_schema or fetch_schema(db)
    if schema:
        logger.debug(f"[SCHEMA] {len(schema.splitlines())} tables for '{db.label}'")
    else:
        logger.warning(f"[SCHEMA] No schema for '{db.label}'")

    llm = get_llm(tools=[run_sql])

    messages = [
        SystemMessage(content=_build_system_prompt(db, schema)),
        HumanMessage(content=question),
    ]

    executed_sql = ""
    columns = []
    rows = []
    query_error = ""

    # ── Step 1: first LLM call ────────────────────────────────────────────────
    notify("thinking", "Understanding your question…")
    logger.debug(f"[LLM CALL 1] Sending to {LLM_PROVIDER}/{LLM_MODEL}")
    try:
        response: AIMessage = llm.invoke(messages)
    except Exception as e:
        logger.error(f"[LLM CALL 1 FAILED] {e}", exc_info=True)
        notify("done")
        return {
            "sql": "", "columns": [], "rows": [], "error": str(e),
            "nl_response": (
                "The AI model could not be reached. "
                f"Provider: {LLM_PROVIDER}, model: {LLM_MODEL}. "
                "Check your .env configuration and API keys."
            ),
        }

    logger.debug(f"[LLM RESPONSE 1] tool_calls={bool(response.tool_calls)} preview='{_extract_text(response.content)[:200]}'")
    messages.append(response)

    # ── Step 2: resolve SQL ───────────────────────────────────────────────────
    tool_call_args = None

    if response.tool_calls:
        tc = response.tool_calls[0]
        tool_call_args = {"query": tc["args"].get("query", "").strip().rstrip(';'), "id": tc["id"]}
        logger.debug(f"[TOOL CALL] Structured. SQL: {tool_call_args['query'][:200]}")
    else:
        tool_call_args = _extract_tool_call_from_text(_extract_text(response.content))

    if tool_call_args:
        executed_sql = tool_call_args["query"]
        notify("generating", "Writing SQL query…")

        # Safety: block non-SELECT
        first_word = executed_sql.strip().split()[0].upper() if executed_sql.strip() else ""
        if first_word not in ("SELECT", "WITH", "EXPLAIN"):
            logger.warning(f"[BLOCKED] {executed_sql[:120]}")
            notify("done")
            return {
                "sql": executed_sql, "columns": [], "rows": [],
                "error": "Non-SELECT query blocked.",
                "nl_response": "I can only run read-only queries. The generated query was blocked for safety.",
            }

        # ── Step 3: execute SQL ───────────────────────────────────────────────
        notify("querying", executed_sql)
        logger.info(f"[EXECUTE SQL] {executed_sql}")
        result      = execute_query(db, executed_sql)
        columns     = result["columns"]
        rows        = result["rows"]
        query_error = result["error"]

        if query_error:
            logger.error(f"[SQL ERROR] {query_error}")
            tool_result_text = f"Error executing query: {query_error}"
        else:
            notify("reading", f"{len(rows)} row{'s' if len(rows) != 1 else ''} returned")
            logger.info(f"[SQL OK] {len(rows)} rows, cols: {columns}")
            if not rows:
                tool_result_text = "Query executed successfully. No rows returned."
            else:
                header     = " | ".join(columns)
                divider    = "-" * len(header)
                data_lines = [" | ".join(r) for r in rows[:50]]
                suffix     = f"\n... ({len(rows)} rows total)" if len(rows) > 50 else ""
                tool_result_text = f"{header}\n{divider}\n" + "\n".join(data_lines) + suffix
                logger.debug(f"[RESULT PREVIEW]\n{tool_result_text[:400]}")

        if response.tool_calls:
            messages.append(ToolMessage(content=tool_result_text, tool_call_id=tool_call_args["id"]))
        else:
            messages.append(HumanMessage(
                content=f"Query result:\n{tool_result_text}\n\nNow summarise this in plain English."
            ))

        # ── Step 4: summary LLM call ──────────────────────────────────────────
        notify("summarising", "Preparing your answer…")
        logger.debug("[LLM CALL 2] Requesting summary")
        try:
            summary_llm = get_summary_llm()
            final: AIMessage = summary_llm.invoke(messages)
            nl_response = _extract_text(final.content)
            logger.info(f"[SUMMARY] {nl_response[:200]}")
        except Exception as e:
            logger.error(f"[LLM CALL 2 FAILED] {e}", exc_info=True)
            nl_response = "Query ran successfully. See the data table below."

        if query_error:
            nl_response = "The query could not be completed. Please try rephrasing your question."

    else:
        logger.info(f"[NO SQL] Conversational answer: {_extract_text(response.content)[:200]}")
        nl_response = _extract_text(response.content)

    notify("done")
    logger.info(f"[QUERY DONE] sql={bool(executed_sql)} rows={len(rows)} error={bool(query_error)}")

    return {
        "sql":         executed_sql,
        "nl_response": nl_response,
        "columns":     columns,
        "rows":        rows,
        "error":       query_error,
    }
