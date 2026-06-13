"""
Provider: OpenAI
API key comes from the user's LLMProvider record (Settings UI).
Models: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo, etc.
"""
import os


def get_llm(model: str, tools: list, api_key: str = ""):
    from langchain_openai import ChatOpenAI
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise EnvironmentError("OpenAI API key is missing. Add it in Settings → Providers.")
    return ChatOpenAI(model=model, api_key=key, temperature=0).bind_tools(tools)


def get_summary_llm(model: str, api_key: str = ""):
    from langchain_openai import ChatOpenAI
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    return ChatOpenAI(model=model, api_key=key, temperature=0)
