"""
Provider: Anthropic Claude (via langchain-anthropic)
Requires: ANTHROPIC_API_KEY in .env
          uv add langchain-anthropic
Models:   claude-3-5-sonnet-20241022, claude-3-5-haiku-20241022,
          claude-3-opus-20240229, etc.
"""
import os


def get_llm(model: str, tools: list):
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ImportError("Run: uv add langchain-anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set in .env")
    llm = ChatAnthropic(model=model, api_key=api_key, temperature=0)
    return llm.bind_tools(tools)


def get_summary_llm(model: str):
    from langchain_anthropic import ChatAnthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    return ChatAnthropic(model=model, api_key=api_key, temperature=0)
