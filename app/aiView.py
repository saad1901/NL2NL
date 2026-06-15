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

from .models import DatabaseConnection, LLMModel
from .aiTools import execute_query, fetch_schema
from .providers.router import get_llm, get_summary_llm, LLM_PROVIDER, LLM_MODEL

logger = logging.getLogger('app.ai')


# ── LLM error classifier ───────────────────────────────────────────────────────

def _classify_llm_error(exc: Exception) -> tuple[str, str]:
    """
    Inspect an LLM exception and return (short_code, user_message).

    short_code is one of: 'rate_limit' | 'auth' | 'model_not_found' | 'unreachable' | 'unknown'
    user_message is a clean, actionable string safe to show in the UI.
    """
    msg = str(exc).lower()
    exc_type = type(exc).__name__

    # ── Rate limit / quota exhausted ──────────────────────────────────────────
    if any(k in msg for k in ('resource_exhausted', 'rate_limit', 'ratelimit',
                               '429', 'quota', 'too many requests', 'retry')):
        # Try to extract the retry-after hint from the message
        import re
        delay_match = re.search(r'retry.{0,20}?(\d+(?:\.\d+)?)\s*s', str(exc), re.I)
        hint = f" Try again in ~{int(float(delay_match.group(1)))}s." if delay_match else ""
        return ('rate_limit',
                f"Rate limit reached for this model.{hint} "
                "Consider switching to a different model or waiting before retrying.")

    # ── Authentication / API key ───────────────────────────────────────────────
    if any(k in msg for k in ('api_key', 'api key', 'authentication', 'unauthorized',
                               'unauthenticated', '401', 'invalid key', 'permission denied',
                               'api-key')):
        return ('auth',
                "Invalid or missing API key. Check your key in Settings.")

    # ── Model not found ────────────────────────────────────────────────────────
    if any(k in msg for k in ('model not found', 'no such model', '404', 'does not exist',
                               'model_not_found', 'invalid model')):
        return ('model_not_found',
                "Model not found. The model ID may be incorrect — check it in Settings.")

    # ── Network / connection ───────────────────────────────────────────────────
    if any(k in msg for k in ('connection', 'timeout', 'unreachable', 'network',
                               'econnrefused', 'name or service not known',
                               'failed to connect', 'ssl', 'certificate')):
        return ('unreachable',
                "Could not reach the AI provider. Check your internet connection "
                "or — for Ollama — make sure the local server is running.")

    # ── Context / token length ─────────────────────────────────────────────────
    if any(k in msg for k in ('context length', 'token', 'maximum context', 'too long',
                               'context_length_exceeded', 'string too long')):
        return ('context_length',
                "The request was too long for this model. "
                "Try a simpler question or a model with a larger context window.")

    return ('unknown', f"The AI model returned an error: {type(exc).__name__}.")


def _log_llm_error(code: str, exc: Exception, context: str = "") -> None:
    """Log LLM errors — full traceback only for unexpected errors."""
    prefix = f"[LLM ERROR:{code.upper()}]{' ' + context if context else ''}"
    if code == 'unknown':
        # Unexpected — log full traceback so developers can investigate
        logger.error(f"{prefix} {exc}", exc_info=True)
    else:
        # Known operational error — one-liner is enough, no traceback spam
        logger.warning(f"{prefix} {exc}")


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
2. Write a correct SQL query that answers it and call run_sql.
3. When you receive results, summarise the answer in plain English — clear, concise, no jargon.
4. If the query returns no rows, say so clearly.
5. If the question cannot be answered with SQL (e.g. it is conversational), answer directly without calling the tool.

IMPORTANT — Schema accuracy:
- You MUST use the EXACT table and column names shown in the schema above. Never guess or invent names.
- If you are unsure whether a table or column exists with the exact name, run a small exploratory query first:
  - SQLite:    SELECT name FROM sqlite_master WHERE type='table'
  - PostgreSQL/MySQL: SELECT table_name FROM information_schema.tables WHERE table_schema='public'  (or DATABASE())
  - Or peek at a table: SELECT * FROM <table> LIMIT 3
- You MAY run up to 8 queries total to explore, verify, and answer the question. Use this ability when:
  - You are unsure of exact table/column names
  - The first query returned an error
  - You need intermediate data to formulate the final query
- Always finish with a plain-English summary once you have the answer.

Rules:
- Only SELECT statements. Never INSERT, UPDATE, DELETE, DROP, or any DDL.
- Always SELECT all columns relevant to the answer — labels, names, numeric/value columns.
- Limit final results to 100 rows unless the user asks for more.
- Highlight key numbers and insights in your summary.
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

    # Resolve provider/model — llm_model can be:
    #   - an LLMModel instance (user's own model)
    #   - a dict {'provider', 'model_id', 'api_key', 'base_url'} (community model)
    #   - None (falls back to .env)
    if llm_model:
        if isinstance(llm_model, dict):
            provider_name = llm_model['provider']
            model_id      = llm_model['model_id']
            api_key       = llm_model['api_key']
            base_url      = llm_model.get('base_url', '')
        else:
            provider_name = llm_model.provider.provider
            model_id      = llm_model.model_id
            api_key       = llm_model.provider.api_key
            base_url      = llm_model.provider.base_url

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

    llm = _get_llm(tools=[run_sql])

    messages = [
        SystemMessage(content=_build_system_prompt(db, schema)),
        HumanMessage(content=question),
    ]

    executed_sql = ""   # last SQL that produced real data rows
    columns      = []
    rows         = []
    query_error  = ""
    all_sql      = []   # every SQL attempted this turn (for "View SQL")

    MAX_ITERATIONS = 8
    iteration      = 0

    notify("thinking", "Understanding your question…")

    # ── Agentic loop ──────────────────────────────────────────────────────────
    while iteration < MAX_ITERATIONS:
        iteration += 1

        # ── LLM call ─────────────────────────────────────────────────────────
        try:
            response: AIMessage = llm.invoke(messages)
        except Exception as e:
            code, user_msg = _classify_llm_error(e)
            _log_llm_error(code, e, context=f"db='{db.label}' iter={iteration}")
            notify("done")
            return {"sql": executed_sql or "", "columns": [], "rows": [],
                    "error": user_msg, "nl_response": user_msg}

        messages.append(response)

        # ── Extract tool call (structured or text fallback) ───────────────────
        tool_call_args = None
        if response.tool_calls:
            tc = response.tool_calls[0]
            tool_call_args = {
                "query": tc["args"].get("query", "").strip().rstrip(';'),
                "id":    tc["id"],
            }
        else:
            tool_call_args = _extract_tool_call_from_text(_extract_text(response.content))

        # ── No tool call → LLM is done, extract final answer ─────────────────
        if not tool_call_args:
            nl_response = _extract_text(response.content)
            break

        sql = tool_call_args["query"]
        tc_id = tool_call_args["id"]

        # Safety: block non-SELECT
        first_word = sql.strip().split()[0].upper() if sql.strip() else ""
        if first_word not in ("SELECT", "WITH", "EXPLAIN"):
            tool_result_text = "Error: only SELECT queries are allowed."
            logger.warning(f"[QUERY BLOCKED] iter={iteration} sql='{sql[:80]}'")
        else:
            all_sql.append(sql)
            is_exploratory = (
                len(rows) == 0            # haven't got real data yet
                or "sqlite_master" in sql.lower()
                or "information_schema" in sql.lower()
                or sql.strip().upper().startswith("EXPLAIN")
            )

            if is_exploratory and iteration > 1:
                notify("querying", f"Exploring… ({sql[:60]}{'…' if len(sql)>60 else ''})")
            elif iteration == 1:
                notify("generating", "Writing SQL query…")
                notify("querying", sql)
            else:
                notify("querying", f"Retrying… ({sql[:60]}{'…' if len(sql)>60 else ''})")

            result      = execute_query(db, sql)
            res_cols    = result["columns"]
            res_rows    = result["rows"]
            res_error   = result["error"]

            if res_error:
                tool_result_text = f"Error executing query: {res_error}"
                query_error = res_error
                logger.info(f"[QUERY ERROR] iter={iteration} err='{res_error[:120]}'")
            else:
                query_error = ""
                notify("reading", f"{len(res_rows)} row{'s' if len(res_rows) != 1 else ''} returned")

                # Only promote to "final result" if this looks like real answer data
                # (not just a schema-exploration query)
                if not is_exploratory or (res_rows and iteration >= MAX_ITERATIONS - 1):
                    executed_sql = sql
                    columns      = res_cols
                    rows         = res_rows

                if not res_rows:
                    tool_result_text = "Query executed successfully. No rows returned."
                else:
                    header     = " | ".join(res_cols)
                    divider    = "-" * len(header)
                    data_lines = [" | ".join(r) for r in res_rows[:50]]
                    suffix     = f"\n... ({len(res_rows)} rows total)" if len(res_rows) > 50 else ""
                    tool_result_text = f"{header}\n{divider}\n" + "\n".join(data_lines) + suffix

        # Feed result back into conversation
        if response.tool_calls:
            messages.append(ToolMessage(content=tool_result_text, tool_call_id=tc_id))
        else:
            messages.append(HumanMessage(
                content=f"Query result:\n{tool_result_text}\n\nContinue."
            ))

    else:
        # Hit iteration limit — ask for a summary of what we have
        nl_response = "Reached the maximum number of query attempts."

    # ── Final summary call ─────────────────────────────────────────────────────
    # Needed when the loop ran out of iterations, OR when it broke out but the
    # last message in the conversation is still a ToolMessage (not a text reply).
    last_msg = messages[-1] if messages else None
    needs_summary = (
        last_msg is not None
        and not isinstance(last_msg, AIMessage)  # last msg is a ToolMessage or HumanMessage
    ) or (
        isinstance(last_msg, AIMessage) and bool(getattr(last_msg, 'tool_calls', None))
    )

    if needs_summary:
        notify("summarising", "Preparing your answer…")
        try:
            summary_llm = _get_summary_llm()
            final: AIMessage = summary_llm.invoke(messages)
            nl_response = _extract_text(final.content)
        except Exception as e:
            code, user_msg = _classify_llm_error(e)
            _log_llm_error(code, e, context=f"db='{db.label}' [summary]")
            nl_response = "Query ran successfully — see the table below." if rows else user_msg

    if query_error and not rows:
        nl_response = "The query could not be completed. Please try rephrasing your question."

    notify("done")

    # Use the last SQL that produced data; fall back to last attempted SQL
    display_sql = executed_sql or (all_sql[-1] if all_sql else "")

    return {
        "sql":         display_sql,
        "nl_response": nl_response,
        "columns":     columns,
        "rows":        rows,
        "error":       query_error,
    }


# ── Chart / Dashboard pipeline ─────────────────────────────────────────────────

_CHART_SYSTEM = """You are a data visualisation expert. Given a database schema and a user's chart request, you must:
1. Write a SQL SELECT query that retrieves the data needed.
2. Choose the best ECharts chart type from: bar, line, pie, scatter, radar, funnel.
3. Identify which column is the category/label (x-axis) and which are values (y-axis / series).

Respond ONLY with a valid JSON object — no markdown, no explanation:
{
  "title": "Short descriptive chart title",
  "chart_type": "bar" | "line" | "pie" | "scatter" | "radar" | "funnel",
  "sql": "SELECT ...",
  "label_column": "column_name_for_labels",
  "value_columns": ["col1", "col2"]
}

Rules:
- Only SELECT statements. Never INSERT, UPDATE, DELETE, DROP.
- Use exact table/column names from the schema.
- Keep result sets under 50 rows.
- For trends over time use line. For comparisons use bar. For proportions use pie. For correlation use scatter. For multi-metric use radar.
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
    Generates an ECharts option object from a plain-English question.
    Returns:
    {
        title, chart_type, sql,
        echarts_option: { ... },   # full ECharts option dict
        error: ""
    }
    """
    schema = db.fetched_schema or fetch_schema(db)

    if llm_model:
        if isinstance(llm_model, dict):
            provider_name = llm_model['provider']
            model_id      = llm_model['model_id']
            api_key       = llm_model['api_key']
            base_url      = llm_model.get('base_url', '')
        else:
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

    schema_section = f"\nDATABASE SCHEMA:\n{schema}" if schema else ""
    prompt = f"{_CHART_SYSTEM}{schema_section}\n\nUser request: {question}"

    try:
        from langchain_core.messages import HumanMessage
        llm_instance = _llm()
        response = llm_instance.invoke([HumanMessage(content=prompt)])
        raw = _extract_text(response.content).strip()
        for fence in ['```json', '```']:
            raw = raw.replace(fence, '')
        raw = raw.strip()
        # find outermost JSON
        s, e = raw.find('{'), raw.rfind('}')
        spec = json.loads(raw[s:e+1])
    except Exception as ex:
        code, user_msg = _classify_llm_error(ex)
        _log_llm_error(code, ex, context=f"chart db='{db.label}'")
        return {'error': user_msg, 'title': '', 'chart_type': 'bar', 'sql': '', 'echarts_option': {}}

    sql        = spec.get('sql', '').strip().rstrip(';')
    chart_type = spec.get('chart_type', 'bar')
    title      = spec.get('title', question[:60])
    label_col  = spec.get('label_column', '')
    value_cols = spec.get('value_columns', [])

    first_word = sql.strip().split()[0].upper() if sql.strip() else ''
    if first_word not in ('SELECT', 'WITH', 'EXPLAIN'):
        return {'error': 'Non-SELECT query blocked.', 'title': title, 'chart_type': chart_type,
                'sql': sql, 'echarts_option': {}}

    result = execute_query(db, sql)
    if result['error']:
        return {'error': result['error'], 'title': title, 'chart_type': chart_type,
                'sql': sql, 'echarts_option': {}}

    columns, rows = result['columns'], result['rows']
    if not rows:
        return {'error': 'Query returned no data.', 'title': title, 'chart_type': chart_type,
                'sql': sql, 'echarts_option': {}}

    # Infer columns if LLM didn't specify
    if not label_col and columns:
        label_col = columns[0]
    if not value_cols:
        value_cols = [c for c in columns if c != label_col] or [columns[-1]]

    col_idx = {c: i for i, c in enumerate(columns)}
    label_i = col_idx.get(label_col, 0)
    labels  = [r[label_i] for r in rows]

    def to_num(v):
        try: return float(v)
        except: return 0

    # Rich ECharts color palette
    colors = ['#6366f1','#34d399','#f472b6','#fb923c','#38bdf8',
              '#facc15','#a78bfa','#4ade80','#f87171','#22d3ee']

    option = {
        'backgroundColor': 'transparent',
        'color': colors,
        'title': {
            'text': title,
            'textStyle': {'color': '#e5e7eb', 'fontSize': 13, 'fontWeight': '600', 'fontFamily': 'Inter'},
            'left': 'left', 'top': 4,
        },
        'tooltip': {
            'trigger': 'axis' if chart_type in ('bar','line','scatter') else 'item',
            'backgroundColor': 'rgba(15,15,25,0.92)',
            'borderColor': 'rgba(255,255,255,0.08)',
            'textStyle': {'color': '#e5e7eb', 'fontSize': 12},
        },
        'grid': {'left': '3%', 'right': '4%', 'bottom': '12%', 'top': '14%', 'containLabel': True},
        'animation': True,
        'animationDuration': 800,
        'animationEasing': 'cubicOut',
    }

    if chart_type == 'pie':
        pie_data = []
        vi = col_idx.get(value_cols[0], -1)
        for i, row in enumerate(rows):
            pie_data.append({'name': str(row[label_i]), 'value': to_num(row[vi]) if vi != -1 else 0})
        option['series'] = [{
            'type': 'pie', 'radius': ['35%', '65%'],
            'center': ['50%', '55%'],
            'data': pie_data,
            'label': {'color': '#9ca3af', 'fontSize': 11},
            'emphasis': {'itemStyle': {'shadowBlur': 20, 'shadowColor': 'rgba(0,0,0,0.5)'}},
        }]
        option.pop('grid', None)
        option.pop('tooltip', None)
        option['tooltip'] = {'trigger': 'item', 'backgroundColor': 'rgba(15,15,25,0.92)',
                              'borderColor': 'rgba(255,255,255,0.08)', 'textStyle': {'color': '#e5e7eb'}}

    elif chart_type == 'scatter':
        series_data = []
        xi = col_idx.get(value_cols[0], label_i)
        yi = col_idx.get(value_cols[1] if len(value_cols) > 1 else value_cols[0], -1)
        for row in rows:
            series_data.append([to_num(row[xi]), to_num(row[yi]) if yi != -1 else 0])
        option['xAxis'] = {'type': 'value', 'axisLabel': {'color': '#6b7280'}, 'splitLine': {'lineStyle': {'color': 'rgba(255,255,255,0.05)'}}}
        option['yAxis'] = {'type': 'value', 'axisLabel': {'color': '#6b7280'}, 'splitLine': {'lineStyle': {'color': 'rgba(255,255,255,0.05)'}}}
        option['series'] = [{'type': 'scatter', 'data': series_data, 'symbolSize': 8,
                              'emphasis': {'itemStyle': {'shadowBlur': 10}}}]

    elif chart_type == 'radar':
        indicators = [{'name': vc, 'max': max((to_num(r[col_idx.get(vc, 0)]) for r in rows), default=100) * 1.2}
                      for vc in value_cols]
        radar_data = []
        for row in rows:
            radar_data.append({
                'name': str(row[label_i]),
                'value': [to_num(row[col_idx.get(vc, 0)]) for vc in value_cols],
            })
        option['radar'] = {'indicator': indicators, 'axisLine': {'lineStyle': {'color': 'rgba(255,255,255,0.1)'}},
                           'splitLine': {'lineStyle': {'color': 'rgba(255,255,255,0.05)'}},
                           'name': {'textStyle': {'color': '#9ca3af'}}}
        option['series'] = [{'type': 'radar', 'data': radar_data,
                              'areaStyle': {'opacity': 0.3},
                              'lineStyle': {'width': 2}}]
        option.pop('grid', None)

    elif chart_type == 'funnel':
        vi = col_idx.get(value_cols[0], -1)
        funnel_data = sorted(
            [{'name': str(r[label_i]), 'value': to_num(r[vi]) if vi != -1 else 0} for r in rows],
            key=lambda x: x['value'], reverse=True
        )
        option['series'] = [{'type': 'funnel', 'left': '10%', 'width': '80%',
                              'data': funnel_data,
                              'label': {'position': 'inside', 'color': '#fff'},
                              'emphasis': {'label': {'fontSize': 14}}}]
        option.pop('grid', None)

    else:  # bar or line
        option['xAxis'] = {
            'type': 'category', 'data': [str(l) for l in labels],
            'axisLabel': {'color': '#6b7280', 'fontSize': 10, 'rotate': len(labels) > 8 and 30 or 0},
            'axisLine': {'lineStyle': {'color': 'rgba(255,255,255,0.1)'}},
        }
        option['yAxis'] = {
            'type': 'value',
            'axisLabel': {'color': '#6b7280', 'fontSize': 10},
            'splitLine': {'lineStyle': {'color': 'rgba(255,255,255,0.05)'}},
        }
        series_list = []
        for vi_idx, vcol in enumerate(value_cols):
            cidx = col_idx.get(vcol, -1)
            if cidx == -1:
                continue
            vals = [to_num(r[cidx]) for r in rows]
            color = colors[vi_idx % len(colors)]
            s = {
                'name': vcol, 'type': chart_type,
                'data': vals,
                'smooth': chart_type == 'line',
                'emphasis': {'focus': 'series'},
            }
            if chart_type == 'line':
                s['areaStyle'] = {'opacity': 0.15}
                s['lineStyle'] = {'width': 2, 'color': color}
                s['itemStyle'] = {'color': color}
                s['symbol'] = 'circle'
                s['symbolSize'] = 4
            else:
                s['itemStyle'] = {
                    'color': {
                        'type': 'linear', 'x': 0, 'y': 0, 'x2': 0, 'y2': 1,
                        'colorStops': [
                            {'offset': 0, 'color': color},
                            {'offset': 1, 'color': color + '55'},
                        ],
                    },
                    'borderRadius': [4, 4, 0, 0],
                }
            series_list.append(s)

        option['series'] = series_list
        if len(value_cols) > 1:
            option['legend'] = {'textStyle': {'color': '#9ca3af', 'fontSize': 11}, 'top': 'bottom'}

    return {
        'title': title, 'chart_type': chart_type, 'sql': sql,
        'echarts_option': option, 'error': '',
    }
