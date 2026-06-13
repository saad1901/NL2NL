"""
Provider: Google Gemini (via langchain-google-genai)
Requires: GEMINI_API_KEY in .env
Models:   gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash, etc.
"""
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool


def get_llm(model: str, tools: list):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set in .env")
    llm = ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=0,
    )
    return llm.bind_tools(tools)


def get_summary_llm(model: str):
    api_key = os.environ.get("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=0,
    )
    return llm
