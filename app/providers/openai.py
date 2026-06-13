"""
Provider: OpenAI (via langchain-openai)
Requires: OPENAI_API_KEY in .env
          uv add langchain-openai
Models:   gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo, etc.
"""
import os


def get_llm(model: str, tools: list):
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError("Run: uv add langchain-openai")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set in .env")
    llm = ChatOpenAI(model=model, api_key=api_key, temperature=0)
    return llm.bind_tools(tools)


def get_summary_llm(model: str):
    from langchain_openai import ChatOpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    return ChatOpenAI(model=model, api_key=api_key, temperature=0)
