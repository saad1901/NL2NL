"""
Provider: Ollama (local)
base_url comes from the user's LLMProvider record (Settings UI → Base URL field).
Models: qwen2.5-coder, llama3.1, mistral, codellama, etc.
"""
import os


def get_llm(model: str, tools: list, api_key: str = "", base_url: str = ""):
    from langchain_ollama import ChatOllama
    url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    return ChatOllama(model=model, base_url=url, temperature=0).bind_tools(tools)


def get_summary_llm(model: str, api_key: str = "", base_url: str = ""):
    from langchain_ollama import ChatOllama
    url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    return ChatOllama(model=model, base_url=url, temperature=0)
