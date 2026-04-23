# core/groq_client.py  (renombrarlo a llm_client.py es opcional pero más limpio)

import json
from openai import OpenAI

OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL   = "qwen2.5:3b"

_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def groq_chat_response(
    messages: list,
    tools: list | None = None,
    model: str = DEFAULT_MODEL,
    **kwargs,
):
    """
    Drop-in para el groq_chat_response anterior.
    Retorna el objeto de respuesta de openai — mismo shape que antes.
    """
    params = dict(
        model=model,
        messages=messages,
        temperature=0.6,
    )
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
        params["parallel_tool_calls"] = False   # mismo fix que con Groq

    return _client.chat.completions.create(**params)