"""
Provider: Anthropic Claude
API key comes from the user's LLMProvider record (Settings UI).
Models: claude-3-5-sonnet-20241022, claude-3-5-haiku-20241022, claude-3-opus-20240229, etc.
"""
import os


def get_llm(model: str, tools: list, api_key: str = ""):
    from langchain_anthropic import ChatAnthropic
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise EnvironmentError("Anthropic API key is missing. Add it in Settings → Providers.")
    return ChatAnthropic(model=model, api_key=key, temperature=0).bind_tools(tools)


def get_summary_llm(model: str, api_key: str = ""):
    from langchain_anthropic import ChatAnthropic
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    return ChatAnthropic(model=model, api_key=key, temperature=0)
