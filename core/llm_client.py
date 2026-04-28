import json
from pathlib import Path

# ── BACKEND: descomenta UNO ──────────────────────────────────────────────────
BACKEND = "groq"
# BACKEND = "ollama"
# ────────────────────────────────────────────────────────────────────────────

GROQ_MODEL   = "qwen/qwen3-32b"
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_URL   = "http://localhost:11434/v1"

FAST_MODEL  = "llama-3.1-8b-instant"
SMART_MODEL = "llama-3.3-70b-versatile"
DEFAULT_MODEL = FAST_MODEL

DEFAULT_MODEL = GROQ_MODEL if BACKEND == "groq" else OLLAMA_MODEL


def _get_api_key() -> str:
    config = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    return data.get("groq_api_key") or data.get("gemini_api_key") or ""


def _get_client():
    if BACKEND == "groq":
        from groq import Groq
        return Groq(api_key=_get_api_key())
    from openai import OpenAI
    return OpenAI(base_url=OLLAMA_URL, api_key="ollama")


def get_model(model=None) -> str:
    return model or DEFAULT_MODEL


def groq_chat_response(
    messages: list,
    tools: list | None = None,
    model: str = DEFAULT_MODEL,
    **kwargs,
):
    import time
    client = _get_client()

    params = dict(
        model=model,
        messages=messages,
        temperature=0.6,
        max_tokens=kwargs.get("max_tokens", 512),
    )

    
    if "70b" in model or "versatile" in model:
        params["reasoning_effort"] = "none"

    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
        params["parallel_tool_calls"] = False

    for attempt in range(3):
        try:
            return client.chat.completions.create(**params)
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = 3 + attempt * 2
                print(f"[LLM] Rate limit, esperando {wait}s...")
                time.sleep(wait)
                continue
            raise