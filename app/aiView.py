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
        code, user_msg = _classify_llm_error(e)
        _log_llm_error(code, e, context=f"db='{db.label}'")
        notify("done")
        return {
            "sql": "", "columns": [], "rows": [], "error": user_msg,
            "nl_response": user_msg,
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
            code, user_msg = _classify_llm_error(e)
            _log_llm_error(code, e, context=f"db='{db.label}' [summary]")
            # Data was retrieved successfully — show it even if summary failed
            nl_response = "Query ran successfully — see the table below." if not query_error else user_msg

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
