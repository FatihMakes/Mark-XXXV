from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

import groq
from groq import Groq

BASE_DIR = Path(__file__).resolve().parent.parent
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


class GroqResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"<GroqResponse {self.text[:40]!r}>"

    def __getattr__(self, name: str) -> Any:
        return getattr(self.text, name)


def _get_api_key() -> str:
    env_key = os.environ.get("GROQ_API_KEY")
    if env_key:
        return env_key

    if not API_CONFIG_PATH.exists():
        raise FileNotFoundError("Groq API key file not found")

    data = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get("groq_api_key") or data.get("gemini_api_key") or ""


def get_client(api_key: str | None = None) -> Groq:
    return groq.Groq(api_key=api_key or _get_api_key())


def _normalize_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    if hasattr(message, "role") and hasattr(message, "content"):
        return {"role": getattr(message, "role"), "content": getattr(message, "content")}
    return {"role": "user", "content": str(message)}


def _build_messages(
    prompt: str | None = None,
    messages: Iterable[Any] | None = None,
    system_instruction: str | None = None,
) -> list[dict[str, Any]]:
    if messages is None:
        messages_list: list[Any] = []
    elif isinstance(messages, list):
        messages_list = messages
    else:
        messages_list = list(messages)

    if prompt is not None and not isinstance(prompt, list):
        messages_list.insert(0, {"role": "user", "content": prompt})

    if system_instruction:
        messages_list.insert(0, {"role": "system", "content": system_instruction})

    normalized = [_normalize_message(m) for m in messages_list]
    if not normalized:
        raise ValueError("No prompt or messages provided for Groq chat completion")
    return normalized


def _extract_text(response: Any) -> str:
    if response is None:
        return ""

    if hasattr(response, "choices"):
        if hasattr(response.choices, "__iter__"):
            choices = list(response.choices)
        else:
            choices = response.choices
        if choices:
            choice = choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                content = choice.message.content
                if content is not None:
                    return str(content)
            if hasattr(choice, "text"):
                return str(choice.text)

    if hasattr(response, "text"):
        return str(response.text)

    if isinstance(response, dict):
        if response.get("choices"):
            choice = response["choices"][0]
            message = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(message, dict) and message.get("content"):
                return str(message["content"])
            if choice.get("text"):
                return str(choice["text"])
        if response.get("text"):
            return str(response["text"])

    return str(response)


def groq_chat_response(
    prompt: str | None = None,
    messages: Iterable[Any] | None = None,
    model: str = DEFAULT_GROQ_MODEL,
    temperature: float = 0.7,
    max_completion_tokens: int = 1024,
    system_instruction: str | None = None,
    **kwargs: Any,
) -> GroqResponse:
    if messages is None and isinstance(prompt, list):
        messages = prompt
        prompt = None

    messages_payload = _build_messages(prompt=prompt, messages=messages, system_instruction=system_instruction)
    client = get_client()
    response = client.chat.completions.create(
        messages=messages_payload,
        model=model,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
        **kwargs,
    )
    return GroqResponse(_extract_text(response))


def groq_transcribe_audio(
    audio_bytes: bytes,
    model: str = "whisper-large-v3",
    language: str | None = None,
    response_format: str = "text",
) -> str:
    client = get_client()
    params: dict[str, object] = {"model": model, "file": audio_bytes, "response_format": response_format}
    if language:
        params["language"] = language
    response = client.audio.transcriptions.create(**params)
    if hasattr(response, "text") and response.text is not None:
        return str(response.text)
    if hasattr(response, "transcription") and response.transcription is not None:
        return str(response.transcription)
    if isinstance(response, dict) and response.get("text"):
        return str(response["text"])
    return str(response)


def groq_text_to_speech(
    text: str,
    model: str = "playai-tts",
    voice: str = "alloy",
    response_format: str = "wav",
    sample_rate: int = 24000,
) -> bytes:
    client = get_client()
    response = client.audio.speech.create(
        input=text,
        model=model,
        voice=voice,
        response_format=response_format,
        sample_rate=sample_rate,
    )
    if hasattr(response, "read"):
        return response.read()
    if hasattr(response, "content"):
        return response.content
    return bytes(str(response), "utf-8")


class GroqModel:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def generate_content(self, prompt: str, **kwargs: Any) -> GroqResponse:
        return groq_chat_response(prompt=prompt, model=self.model_name, **kwargs)


def get_model(model_name: str) -> GroqModel:
    return GroqModel(model_name)


groq_response = groq_chat_response
