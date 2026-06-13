"""
Provider: OpenRouter (https://openrouter.ai)
OpenRouter exposes an OpenAI-compatible API, so we use langchain-openai
pointed at their base URL.

API key comes from the user's LLMProvider record in the database (Settings UI).
Models: any slug from https://openrouter.ai/models
  e.g.  google/gemini-2.0-flash-exp:free
        anthropic/claude-3.5-sonnet
        deepseek/deepseek-chat
        meta-llama/llama-3.3-70b-instruct
        mistralai/mistral-large
"""
import os

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _build(model: str, api_key: str, base_url: str = ""):
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError("Run: uv add langchain-openai")

    if not api_key:
        raise EnvironmentError(
            "OpenRouter API key is missing. "
            "Add it in Settings → Providers → OpenRouter."
        )

    effective_url = base_url or OPENROUTER_BASE_URL

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=effective_url,
        temperature=0,
        default_headers={
            "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "http://localhost:8000"),
            "X-Title":      "NL2SQL",
        },
    )


def get_llm(model: str, tools: list, api_key: str = "", base_url: str = ""):
    return _build(model, api_key, base_url).bind_tools(tools)


def get_summary_llm(model: str, api_key: str = "", base_url: str = ""):
    return _build(model, api_key, base_url)
