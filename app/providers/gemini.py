"""
Provider: Google Gemini
API key comes from the user's LLMProvider record (Settings UI).
Models: gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash, etc.
"""
import os
from langchain_google_genai import ChatGoogleGenerativeAI


def get_llm(model: str, tools: list, api_key: str = ""):
    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    print(f"[GEMINI] model={model} key={key[:8] if key else 'EMPTY'}...")
    if not key:
        raise EnvironmentError("Gemini API key is missing. Add it in Settings → Providers.")
    return ChatGoogleGenerativeAI(model=model, google_api_key=key, temperature=0).bind_tools(tools)


def get_summary_llm(model: str, api_key: str = ""):
    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    print(f"[GEMINI summary] model={model} key={key[:8] if key else 'EMPTY'}...")
    return ChatGoogleGenerativeAI(model=model, google_api_key=key, temperature=0)
