"""
Provider router — reads LLM_PROVIDER and LLM_MODEL from environment
and returns the appropriate LangChain chat model.

Usage:
    from app.providers.router import get_llm, get_summary_llm, LLM_MODEL

    llm         = get_llm(tools=[run_sql])          # tool-bound model
    summary_llm = get_summary_llm()                 # plain model for summarisation
"""
import os
import importlib
import logging

logger = logging.getLogger('app.ai')

# Read once at import time — restart server to pick up .env changes
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower().strip()
LLM_MODEL    = os.environ.get("LLM_MODEL", "qwen2.5-coder").strip()

_SUPPORTED = ("gemini", "openai", "anthropic", "openrouter", "ollama")

if LLM_PROVIDER not in _SUPPORTED:
    raise EnvironmentError(
        f"LLM_PROVIDER='{LLM_PROVIDER}' is not supported. "
        f"Choose one of: {', '.join(_SUPPORTED)}"
    )

logger.info(f"[PROVIDER] Using {LLM_PROVIDER} / {LLM_MODEL}")

# Lazy-import the provider module
_provider = importlib.import_module(f"app.providers.{LLM_PROVIDER}")


def get_llm(tools: list):
    """Return the LLM with tools bound, using .env config (admin fallback)."""
    kwargs = {}
    if LLM_PROVIDER in ('ollama', 'openrouter'):
        kwargs['base_url'] = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434") if LLM_PROVIDER == 'ollama' else os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    return _provider.get_llm(LLM_MODEL, tools, **kwargs)


def get_summary_llm():
    """Return the plain LLM (no tools), using .env config (admin fallback)."""
    kwargs = {}
    if LLM_PROVIDER in ('ollama', 'openrouter'):
        kwargs['base_url'] = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434") if LLM_PROVIDER == 'ollama' else os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    return _provider.get_summary_llm(LLM_MODEL, **kwargs)
