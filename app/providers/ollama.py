"""
Provider: Ollama (local, via langchain-ollama)
Requires: Ollama running locally, model pulled
          OLLAMA_BASE_URL defaults to http://localhost:11434
Models:   qwen2.5-coder, llama3.1, mistral, codellama, etc.
"""
import os


def get_llm(model: str, tools: list):
    from langchain_ollama import ChatOllama
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    llm = ChatOllama(model=model, base_url=base_url, temperature=0)
    return llm.bind_tools(tools)


def get_summary_llm(model: str):
    from langchain_ollama import ChatOllama
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    return ChatOllama(model=model, base_url=base_url, temperature=0)
