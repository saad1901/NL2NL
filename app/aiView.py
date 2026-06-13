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
# import logging

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

from .models import DatabaseConnection, LLMModel
from .aiTools import execute_query, fetch_schema
from .providers.router import get_llm, get_summary_llm, LLM_PROVIDER, LLM_MODEL

#logger = #logging.get#logger('app.ai')


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

#logger = #logging.get#logger('app.ai')



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
- Always SELECT all columns that are relevant to the answer — including labels, names, numeric/value columns.
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
        #logger.debug(f"[FALLBACK] No JSON object found in response")
        return None

    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        #logger.debug(f"[FALLBACK] JSON parse failed: {e}")
        return None

    args  = obj.get("arguments") or obj.get("parameters") or {}
    query = args.get("query", "").strip().rstrip(';')
    if not query:
        #logger.debug(f"[FALLBACK] Parsed JSON but no 'query' field: {obj}")
        return None

    #logger.warning(f"[FALLBACK] Extracted SQL from text (model skipped tool_calls): {query[:200]}")
    return {"query": query, "id": "text_fallback"}


# ── Main entry point ───────────────────────────────────────────────────────────

def run_nl_query(question: str, db: DatabaseConnection, status_cb=None,
                 llm_model: LLMModel = None) -> dict:
    """
    Full NL→SQL→NL pipeline.

    llm_model: a LLMModel instance from the database (user's configured model).
               Falls back to .env LLM_PROVIDER/LLM_MODEL if None.
    """

    def notify(step, detail=""):
        if status_cb:
            try: status_cb(step, detail)
            except Exception: pass

    # Resolve provider/model
    if llm_model:
        provider_name = llm_model.provider.provider
        model_id      = llm_model.model_id
        api_key       = llm_model.provider.api_key
        base_url      = llm_model.provider.base_url
        # #logger.info(f"[QUERY START] db='{db.label}' provider={provider_name} model={model_id} question='{question}'")

        def _get_llm(tools):
            import importlib
            mod = importlib.import_module(f"app.providers.{provider_name}")
            kwargs = {'api_key': api_key}
            if provider_name in ('ollama', 'openrouter'):
                kwargs['base_url'] = base_url
            return mod.get_llm(model_id, tools, **kwargs)

        def _get_summary_llm():
            import importlib
            mod = importlib.import_module(f"app.providers.{provider_name}")
            kwargs = {'api_key': api_key}
            if provider_name in ('ollama', 'openrouter'):
                kwargs['base_url'] = base_url
            return mod.get_summary_llm(model_id, **kwargs)
    else:
        # Fallback to .env config
        ##logger.info(f"[QUERY START] db='{db.label}' provider={LLM_PROVIDER} model={LLM_MODEL} question='{question}'")
        _get_llm = lambda tools: get_llm(tools)
        _get_summary_llm = get_summary_llm

    schema = db.fetched_schema or fetch_schema(db)
    # if schema:
    #     #logger.debug(f"[SCHEMA] {len(schema.splitlines())} tables for '{db.label}'")
    # else:
    #     #logger.warning(f"[SCHEMA] No schema for '{db.label}'")

    llm = _get_llm(tools=[run_sql])

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
    try:
        response: AIMessage = llm.invoke(messages)
    except Exception as e:
        notify("done")
        return {
            "sql": "", "columns": [], "rows": [], "error": str(e),
            "nl_response": (
                "The AI model could not be reached. "
                "Check your RATE LIMIT, .env configuration and API keys."
            ),
        }

    messages.append(response)

    # ── Step 2: resolve SQL ───────────────────────────────────────────────────
    tool_call_args = None

    if response.tool_calls:
        tc = response.tool_calls[0]
        tool_call_args = {"query": tc["args"].get("query", "").strip().rstrip(';'), "id": tc["id"]}
    else:
        tool_call_args = _extract_tool_call_from_text(_extract_text(response.content))
        if tool_call_args:
            pass

    if tool_call_args:
        executed_sql = tool_call_args["query"]
        notify("generating", "Writing SQL query…")

        first_word = executed_sql.strip().split()[0].upper() if executed_sql.strip() else ""
        if first_word not in ("SELECT", "WITH", "EXPLAIN"):
            notify("done")
            return {
                "sql": executed_sql, "columns": [], "rows": [],
                "error": "Non-SELECT query blocked.",
                "nl_response": "I can only run read-only queries. The generated query was blocked for safety.",
            }

        # ── Step 3: execute SQL ───────────────────────────────────────────────
        notify("querying", executed_sql)
        result      = execute_query(db, executed_sql)
        columns     = result["columns"]
        rows        = result["rows"]
        query_error = result["error"]

        if query_error:
            tool_result_text = f"Error executing query: {query_error}"
        else:
            notify("reading", f"{len(rows)} row{'s' if len(rows) != 1 else ''} returned")
            if not rows:
                tool_result_text = "Query executed successfully. No rows returned."
            else:
                header     = " | ".join(columns)
                divider    = "-" * len(header)
                data_lines = [" | ".join(r) for r in rows[:50]]
                suffix     = f"\n... ({len(rows)} rows total)" if len(rows) > 50 else ""
                tool_result_text = f"{header}\n{divider}\n" + "\n".join(data_lines) + suffix

        if response.tool_calls:
            messages.append(ToolMessage(content=tool_result_text, tool_call_id=tool_call_args["id"]))
        else:
            messages.append(HumanMessage(
                content=f"Query result:\n{tool_result_text}\n\nNow summarise this in plain English."
            ))

        # ── Step 4: summary LLM call ──────────────────────────────────────────
        notify("summarising", "Preparing your answer…")
        try:
            summary_llm = _get_summary_llm()
            final: AIMessage = summary_llm.invoke(messages)
            nl_response = _extract_text(final.content)
        except Exception as e:
            nl_response = "Query ran successfully. See the data table below."

        if query_error:
            nl_response = "The query could not be completed. Please try rephrasing your question."

    else:
        nl_response = _extract_text(response.content)

    notify("done")

    return {
        "sql":         executed_sql,
        "nl_response": nl_response,
        "columns":     columns,
        "rows":        rows,
        "error":       query_error,
    }


# ── Chart / Dashboard pipeline ─────────────────────────────────────────────────

_CHART_SYSTEM = """You are a data visualisation expert. Given a database schema and a user's chart request, you must:
1. Write a SQL SELECT query that retrieves the data needed for the chart.
2. Decide the best chart type: bar, line, pie, doughnut, or scatter.
3. Identify which column is the label (x-axis / category) and which column(s) are values (y-axis / series).

Respond ONLY with a valid JSON object — no markdown, no explanation:
{{
  "title": "Short descriptive chart title",
  "chart_type": "bar" | "line" | "pie" | "doughnut" | "scatter",
  "sql": "SELECT ... FROM ...",
  "label_column": "column_name_for_labels",
  "value_columns": ["col1", "col2"]
}}

Rules:
- Only SELECT statements. Never INSERT, UPDATE, DELETE, DROP.
- Use exact table/column names from the schema.
- Keep result sets under 50 rows for readability.
- For time-series, use line. For comparisons, use bar. For proportions, use pie/doughnut.
"""

_CHART_COLORS = [
    'rgba(92,124,250,0.8)',   # brand blue
    'rgba(167,139,250,0.8)',  # purple
    'rgba(52,211,153,0.8)',   # green
    'rgba(251,191,36,0.8)',   # yellow
    'rgba(251,113,133,0.8)',  # pink
    'rgba(56,189,248,0.8)',   # sky
    'rgba(251,146,60,0.8)',   # orange
    'rgba(163,230,53,0.8)',   # lime
]


def run_chart_query(question: str, db, llm_model=None) -> dict:
    """
    Generates a chart spec from a plain-English question.
    Returns a dict ready to pass to Chart.js:
    {
        title, chart_type, sql,
        labels: [...],
        datasets: [{ label, data: [...], backgroundColor, borderColor }],
        error: ""
    }
    """
    schema = db.fetched_schema or fetch_schema(db)

    # Resolve provider
    if llm_model:
        provider_name = llm_model.provider.provider
        model_id      = llm_model.model_id
        api_key       = llm_model.provider.api_key
        base_url      = llm_model.provider.base_url

        def _llm():
            import importlib
            mod = importlib.import_module(f"app.providers.{provider_name}")
            kwargs = {'api_key': api_key}
            if provider_name in ('ollama', 'openrouter'):
                kwargs['base_url'] = base_url
            return mod.get_summary_llm(model_id, **kwargs)
    else:
        _llm = get_summary_llm

    system = _CHART_SYSTEM
    schema_section = f"\nDATABASE SCHEMA:\n{schema}" if schema else ""
    prompt = f"{system}{schema_section}\n\nUser request: {question}"

    try:
        from langchain_core.messages import HumanMessage
        llm = _llm()
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = _extract_text(response.content).strip()
        # Strip markdown fences if present
        for fence in ['```json', '```']:
            raw = raw.replace(fence, '')
        raw = raw.strip()
        spec = json.loads(raw)
    except Exception as e:
        logger.error(f"[CHART LLM ERROR] {e}", exc_info=True)
        return {'error': f'Could not generate chart spec: {e}', 'title': '', 'chart_type': 'bar',
                'labels': [], 'datasets': [], 'sql': ''}

    sql            = spec.get('sql', '').strip().rstrip(';')
    chart_type     = spec.get('chart_type', 'bar')
    title          = spec.get('title', question[:60])
    label_col      = spec.get('label_column', '')
    value_cols     = spec.get('value_columns', [])

    # Safety check
    first_word = sql.split()[0].upper() if sql.strip() else ''
    if first_word not in ('SELECT', 'WITH', 'EXPLAIN'):
        return {'error': 'Non-SELECT query blocked.', 'title': title, 'chart_type': chart_type,
                'labels': [], 'datasets': [], 'sql': sql}

    result = execute_query(db, sql)
    if result['error']:
        return {'error': result['error'], 'title': title, 'chart_type': chart_type,
                'labels': [], 'datasets': [], 'sql': sql}

    columns = result['columns']
    rows    = result['rows']

    if not rows:
        return {'error': 'Query returned no data.', 'title': title, 'chart_type': chart_type,
                'labels': [], 'datasets': [], 'sql': sql}

    # If LLM didn't specify columns, infer: first col = labels, rest = values
    if not label_col and columns:
        label_col = columns[0]
    if not value_cols and len(columns) > 1:
        value_cols = [c for c in columns if c != label_col]
    if not value_cols and columns:
        value_cols = [c for c in columns if c != label_col] or [columns[-1]]

    col_idx  = {c: i for i, c in enumerate(columns)}
    label_i  = col_idx.get(label_col, 0)
    labels   = [r[label_i] for r in rows]

    datasets = []
    for vi, vcol in enumerate(value_cols):
        vi_idx = col_idx.get(vcol, -1)
        if vi_idx == -1:
            continue
        raw_vals = [r[vi_idx] for r in rows]
        # Convert to float where possible
        data = []
        for v in raw_vals:
            try:
                data.append(float(v))
            except (TypeError, ValueError):
                data.append(0)

        color  = _CHART_COLORS[vi % len(_CHART_COLORS)]
        border = color.replace('0.8', '1')
        datasets.append({
            'label':           vcol,
            'data':            data,
            'backgroundColor': [color] * len(data) if chart_type in ('pie', 'doughnut') else color,
            'borderColor':     border,
            'borderWidth':     2,
            'fill':            chart_type == 'area',
            'tension':         0.4,
        })

    # area is just line with fill=True in Chart.js
    if chart_type == 'area':
        chart_type = 'line'

    return {
        'title':      title,
        'chart_type': chart_type,
        'sql':        sql,
        'labels':     labels,
        'datasets':   datasets,
        'error':      '',
    }
