import json
from openai import OpenAI

OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "llama3.2:3b"

_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def get_model(model=None) -> str:
    return DEFAULT_MODEL


def groq_chat_response(
    messages: list,
    tools: list | None = None,
    model: str = DEFAULT_MODEL,
    **kwargs,
):
    params = dict(
    model=model,
    messages=messages,
    temperature=0.6,
    max_tokens=256,   
)
    
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
        params["parallel_tool_calls"] = False

    return _client.chat.completions.create(**params)