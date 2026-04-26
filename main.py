import asyncio
import threading
import json
import sys
import traceback
import io
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)

from actions.flight_finder     import flight_finder
from actions.open_app          import open_app, close_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.cmd_control       import cmd_control
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.volume_mixer import volume_mixer
from actions.screenshot import screenshot
from actions.timer import timer
from actions.writer import writer
import datetime



def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"

GROQ_MODEL          = "llama-3.3-70b-versatile"
SEND_SAMPLE_RATE    = 16000   # mic input
CHANNELS            = 1

# VAD settings
VAD_SILENCE_THRESHOLD  = 0.03 # RMS por debajo de esto = silencio
VAD_SILENCE_DURATION   = 1.2    # segundos de silencio para cortar
VAD_MIN_SPEECH_DURATION = 0.3   # mínimo de habla para procesar
VAD_CHUNK_DURATION     = 0.01   # segundos por chunk de mic (50ms)
VAD_CHUNK_SIZE         = int(SEND_SAMPLE_RATE * VAD_CHUNK_DURATION)

SILENCE_TENTATIVE  = 0.8   # "capaz terminó"
SILENCE_DEFINITIVE = 2.0


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Soporta tanto groq_api_key como gemini_api_key (nombre legacy)
    return data.get("groq_api_key") or data.get("gemini_api_key") or ""


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
"Always respond in the same language the user speaks. "
"Be concise, direct, and always use the provided tools to complete tasks. "
"Never simulate or guess results — always call the appropriate tool."
        )


# ── Memoria ───────────────────────────────────────────────────────────────────
_last_memory_input = ""


def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    global _last_memory_input
    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text
    try:
        if not should_extract_memory(user_text, jarvis_text):
            return
        data = extract_memory(user_text, jarvis_text)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ {list(data.keys())}")
    except Exception as e:
        print(f"[Memory] ⚠️ {e}")


# ── Tool declarations ─────────────────────────────────────────────────────────
# Formato OpenAI/Groq: type="function" con función anidada
def _groq_tools() -> list:
    raw_tools = [
        {
    "name": "writer",
    "description": (
        "Escribe texto directamente donde está el cursor del usuario. "
        "Útil para traducir y escribir el resultado, redactar texto en otro idioma, "
        "o simplemente escribir algo que el usuario dicta. "
        "IMPORTANTE: Si el usuario pide traducir, traducí el texto vos mismo y pasalo "
        "en el campo 'text' ya traducido — no pases el texto original. "
        "Ejemplos: 'traducí esto al inglés y escribilo', 'escribí hola mundo en francés', "
        "'dictame esto en el chat'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Texto final a escribir (ya traducido si corresponde)."
            },
            "target_lang": {
                "type": "string",
                "description": "Idioma al que se tradujo, para el log. Ej: 'inglés', 'francés'."
            },
            "delay": {
                "type": "number",
                "description": "Segundos de espera antes de escribir para que el usuario posicione el cursor. Default: 1.0"
            },
        },
        "required": ["text"]
    }
},
        {
    "name": "timer",
    "description": (
        "Crea timers y alarmas. "
        "Para timers: 'poneme un timer de 10 minutos', 'avisame en 30 segundos'. "
        "Para alarmas: 'despertame a las 8', 'alarma a las 14:30'. "
        "También puede cancelar timers activos o listarlos."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "set | alarm | cancel | list (default: set)"
            },
            "label": {
                "type": "string",
                "description": "Nombre del timer o alarma. Ej: 'pasta', 'reunión', 'despertar'."
            },
            "duration": {
                "type": "string",
                "description": "Duración para timers. Ej: '5 minutos', '30 segundos', '1 hora 30 minutos'."
            },
            "alarm_at": {
                "type": "string",
                "description": "Hora para alarmas. Ej: '14:30', '8 de la mañana', '9:00pm'."
            },
            "timer_id": {
                "type": "string",
                "description": "Nombre del timer a cancelar (para action=cancel)."
            },
        },
        "required": []
    }
},
        {
    "name": "screenshot",
    "description": (
        "Toma una captura de pantalla y la guarda en disco. "
        "Usar cuando el usuario pide 'captura', 'screenshot', 'screenshoot', 'foto de pantalla', 'capturá la pantalla'. "
        "Permite elegir dónde guardarla y con qué nombre."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "Carpeta donde guardar la captura. Ej: 'C:/Users/usuario/Desktop'. Si no se especifica usa Imágenes/Screenshots."
            },
            "filename": {
                "type": "string",
                "description": "Nombre del archivo sin extensión. Si no se especifica se usa la fecha y hora."
            },
            "monitor": {
                "type": "integer",
                "description": "Número de monitor (1 = principal, 2 = secundario). Default: 1."
            },
        },
        "required": []
    }
},
        {
    "name": "volume_mixer",
    "description": "Controls the audio volume of a specific application. Use when user says raise/lower/mute/set volume for a specific app like Discord, Spotify, Valorant, etc.",
    "parameters": {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "Application name"},
            "action":   {"type": "string", "description": "set | up | down | mute | unmute"},
            "level":    {"type": "number",  "description": "Volume 0-100 for action=set"}
        },
        "required": ["app_name", "action"]
    }
},
        
        {
            "name": "close_app",
            "description": "Closes a running application. Use when the user asks to close, quit, kill or exit any app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Name of the application to close (e.g. 'Discord', 'Spotify')"
                    }
                },
                "required": ["app_name"]
            }
        },
        {
            "name": "open_app",
            "description": (
                "Opens any application on the Windows computer. "
                "Use this whenever the user asks to open, launch, or start any app, "
                "website, or program. Always call this tool — never just say you opened it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                    }
                },
                "required": ["app_name"]
            }
        },
        {
            "name": "web_search",
            "description": "Searches the web for any information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query":  {"type": "string", "description": "Search query"},
                    "mode":   {"type": "string", "description": "search (default) or compare"},
                    "items":  {"type": "array", "items": {"type": "string"}, "description": "Items to compare"},
                    "aspect": {"type": "string", "description": "price | specs | reviews"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "weather_report",
            "description": "Gets real-time weather information for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"}
                },
                "required": ["city"]
            }
        },
        {
            "name": "send_message",
            "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
            "parameters": {
                "type": "object",
                "properties": {
                    "receiver":     {"type": "string", "description": "Recipient contact name"},
                    "message_text": {"type": "string", "description": "The message to send"},
                    "platform":     {"type": "string", "description": "Platform: WhatsApp, Telegram, etc."}
                },
                "required": ["receiver", "message_text", "platform"]
            }
        },
        {
            "name": "reminder",
            "description": "Sets a timed reminder using Windows Task Scheduler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date":    {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "time":    {"type": "string", "description": "Time in HH:MM format (24h)"},
                    "message": {"type": "string", "description": "Reminder message text"}
                },
                "required": ["date", "time", "message"]
            }
        },
        {
            "name": "youtube_video",
            "description": (
                "Controls YouTube. Use for: playing videos, summarizing a video's content, "
                "getting video info, or showing trending videos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "play | summarize | get_info | trending (default: play)"},
                    "query":  {"type": "string", "description": "Search query for play action"},
                    "save":   {"type": "boolean", "description": "Save summary to Notepad (summarize only)"},
                    "region": {"type": "string", "description": "Country code for trending e.g. TR, US"},
                    "url":    {"type": "string", "description": "Video URL for get_info action"},
                },
                "required": []
            }
        },
        {
            "name": "screen_process",
            "description": (
                "Captures and analyzes the screen or webcam image. "
                "MUST be called when user asks what is on screen, what you see, "
                "analyze my screen, look at camera, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "angle": {"type": "string", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                    "text":  {"type": "string", "description": "The question or instruction about the captured image"}
                },
                "required": ["text"]
            }
        },
        {
            "name": "computer_settings",
            "description": (
                "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
                "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action":      {"type": "string", "description": "The action to perform"},
                    "description": {"type": "string", "description": "Natural language description of what to do"},
                    "value":       {"type": "string", "description": "Optional value: volume level, text to type, etc."}
                },
                "required": []
            }
        },
        {
            "name": "browser_control",
            "description": (
                "Controls the web browser. Use for: opening websites, searching the web, "
                "clicking elements, filling forms, scrolling, any web-based task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action":      {"type": "string"},
                    "url":         {"type": "string"},
                    "query":       {"type": "string"},
                    "selector":    {"type": "string"},
                    "text":        {"type": "string"},
                    "description": {"type": "string"},
                    "direction":   {"type": "string"},
                    "key":         {"type": "string"},
                    "incognito":   {"type": "boolean"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "file_controller",
            "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action":      {"type": "string"},
                    "path":        {"type": "string"},
                    "destination": {"type": "string"},
                    "new_name":    {"type": "string"},
                    "content":     {"type": "string"},
                    "name":        {"type": "string"},
                    "extension":   {"type": "string"},
                    "count":       {"type": "integer"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "cmd_control",
            "description": (
                "Runs CMD/terminal commands via natural language."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task":    {"type": "string"},
                    "visible": {"type": "boolean"},
                    "command": {"type": "string"},
                },
                "required": ["task"]
            }
        },
        {
            "name": "desktop_control",
            "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "path":   {"type": "string"},
                    "url":    {"type": "string"},
                    "mode":   {"type": "string"},
                    "task":   {"type": "string"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "code_helper",
            "description": "Writes, edits, explains, runs, or builds code files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action":      {"type": "string"},
                    "description": {"type": "string"},
                    "language":    {"type": "string"},
                    "output_path": {"type": "string"},
                    "file_path":   {"type": "string"},
                    "code":        {"type": "string"},
                    "args":        {"type": "string"},
                    "timeout":     {"type": "integer"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "dev_agent",
            "description": "Builds complete multi-file projects from scratch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description":  {"type": "string"},
                    "language":     {"type": "string"},
                    "project_name": {"type": "string"},
                    "timeout":      {"type": "integer"},
                },
                "required": ["description"]
            }
        },
        {
            "name": "agent_task",
            "description": (
                "Executes complex multi-step tasks requiring multiple different tools. "
                "DO NOT use for single commands."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal":     {"type": "string"},
                    "priority": {"type": "string"},
                },
                "required": ["goal"]
            }
        },
        {
            "name": "computer_control",
            "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action":      {"type": "string"},
                    "text":        {"type": "string"},
                    "x":           {"type": "integer"},
                    "y":           {"type": "integer"},
                    "keys":        {"type": "string"},
                    "key":         {"type": "string"},
                    "direction":   {"type": "string"},
                    "amount":      {"type": "integer"},
                    "seconds":     {"type": "number"},
                    "title":       {"type": "string"},
                    "description": {"type": "string"},
                    "type":        {"type": "string"},
                    "field":       {"type": "string"},
                    "clear_first": {"type": "boolean"},
                    "path":        {"type": "string"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "game_updater",
            "description": (
                "THE ONLY tool for ANY Steam or Epic Games request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action":    {"type": "string"},
                    "platform":  {"type": "string"},
                    "game_name": {"type": "string"},
                    "app_id":    {"type": "string"},
                    "hour":      {"type": "integer"},
                    "minute":    {"type": "integer"},
                    "shutdown_when_done": {"type": "boolean"},
                },
                "required": []
            }
        },
        {
            "name": "flight_finder",
            "description": "Searches Google Flights and speaks the best options.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin":      {"type": "string"},
                    "destination": {"type": "string"},
                    "date":        {"type": "string"},
                    "return_date": {"type": "string"},
                    "passengers":  {"type": "integer"},
                    "cabin":       {"type": "string"},
                    "save":        {"type": "boolean"},
                },
                "required": ["origin", "destination", "date"]
            }
        },
        {
            "name": "save_memory",
            "description": (
                "Save an important personal fact about the user to long-term memory. "
                "Call silently whenever the user reveals something worth remembering."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "key":      {"type": "string"},
                    "value":    {"type": "string"},
                },
                "required": ["category", "key", "value"]
            }
        },
    ]
    return [{"type": "function", "function": t} for t in raw_tools]


# ── TTS ───────────────────────────────────────────────────────────────────────

async def _tts_speak(text: str) -> tuple[np.ndarray, int]:
    import edge_tts, io, soundfile as sf

    voice = "es-AR-TomasNeural"  # español 
    communicate = edge_tts.Communicate(text, voice)

    mp3_buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buf.write(chunk["data"])

    mp3_buf.seek(0)
    samples, sr = sf.read(mp3_buf, dtype="float32")
    return samples, sr
    


def _tts_pyttsx3_blocking(text: str) -> np.ndarray:
    import pyttsx3, tempfile, os

    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.setProperty("volume", 1.0)

    voices = engine.getProperty("voices")
    for v in voices:
        if "en" in v.id.lower() or "english" in v.name.lower():
            engine.setProperty("voice", v.id)
            break

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    engine.save_to_file(text, wav_path)
    engine.runAndWait()
    engine.stop()

    try:
        with wave.open(wav_path, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        os.unlink(wav_path)
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception as e:
        print(f"[TTS] pyttsx3 wav read failed: {e}")
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        return np.array([], dtype=np.float32)


def _play_audio_samples(samples: np.ndarray, samplerate: int):
    if samples.size == 0:
        return
    sd.play(samples, samplerate=samplerate)
    sd.wait()


# ── STT (Whisper via Groq) ────────────────────────────────────────────────────

from faster_whisper import WhisperModel
import os

_whisper_model = WhisperModel("small", device="cuda", compute_type="int8")

def _transcribe_audio(pcm_frames: list[np.ndarray]) -> str:
    """
    Convierte lista de chunks PCM int16 a WAV y transcribe con faster-whisper local.
    """
    try:
        audio = np.concatenate(pcm_frames, axis=0).flatten()

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SEND_SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        buf.seek(0)

        # faster-whisper necesita archivo en disco, no BytesIO
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(buf.read())
            tmp_path = f.name

        segments, _ = _whisper_model.transcribe(tmp_path, language="es")
        text = "".join(s.text for s in segments).strip()

        os.unlink(tmp_path)
        return text

    except Exception as e:
        print(f"[STT] ❌ Transcription failed: {e}")
        return ""


# ── Clase principal ───────────────────────────────────────────────────────────

class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._text_queue    = asyncio.Queue()   # texto desde UI
        self._conversation  = []               # historial de mensajes
        self._in_conversation     = False
        self._conversation_timeout = 20  # segundos sin hablar resetea
        self._last_interaction    = 0.0
        self._proactive_interval = 300  # revisar cada 5 minutos
        self._last_proactive     = 0.0  # timestamp última intervención
        self._proactive_cooldown = 600

        # Callback que usa la UI para enviar texto escrito
        self.ui.on_text_command = self._on_text_command

    # ── Interfaz ──────────────────────────────────────────────────────────────

    def _on_text_command(self, text: str):
        """Llamado desde la UI cuando el usuario escribe un comando."""
        if self._loop and text.strip():
            self._loop.call_soon_threadsafe(
                self._text_queue.put_nowait, text.strip()
            )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        self.ui.set_state("SPEAKING" if value else "LISTENING")

    def speak(self, text: str):
        """Habla un texto de forma síncrona desde otro thread."""
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._speak_async(text), self._loop
            )

    def speak_error(self, tool_name: str, error):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error.")

    # ── TTS interno ───────────────────────────────────────────────────────────

    async def _speak_async(self, text: str):
        if not text:
            return
        self.set_speaking(True)
        self.ui.write_log(f"Jarvis: {text}")
        try:
            samples, sr = await _tts_speak(text)
            await asyncio.to_thread(_play_audio_samples, samples, sr)
        finally:
            self.set_speaking(False)

    # ── System prompt ─────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        from datetime import datetime
        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)
        base    = _load_system_prompt()
        now     = datetime.now()
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {now.strftime('%A, %B %d, %Y — %I:%M %p')}\n\n"
        )
        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str + "\n\n")
        parts.append(base)
        return "".join(parts)

    # ── Tool execution ────────────────────────────────────────────────────────

    async def _proactive_check(self) -> None:
        """
    Evalúa si hay algo relevante que decirle al usuario sin que lo pida.
    Usa Ollama para decidir si intervenir y qué decir.
        """
        from openai import OpenAI
        import re

        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        if not mem_str:
            return  # sin memoria no hay contexto para ser proactivo

        now = datetime.now()
        time_str = now.strftime("%A %d/%m/%Y — %H:%M")

        prompt = (
        f"eres un asistente personal que conoce bien al usuario.\n"
        f"Hora actual: {time_str}\n\n"
        f"{mem_str}\n\n"
        f"¿Hay algo relevante que deberías mencionar al usuario AHORA, "
        f"sin que te lo pida? Por ejemplo:\n"
        f"- Es tarde y mañana tiene clases o algo importante\n"
        f"- Lleva mucho tiempo sin hacer algo que dijo que quería hacer\n"
        f"- Hay algo en su rutina que aplica a este momento del día\n"
        f"- Tiene un objetivo que podría estar descuidando\n\n"
        f"Si hay algo relevante, respondé con el mensaje exacto a decirle "
        f"(máximo 2 oraciones, natural, no intrusivo).\n"
        f"Si NO hay nada relevante, respondé exactamente: NADA\n\n"
        f"Respuesta:"
    )

        try:
            client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
            response = await asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model="qwen2.5:3b",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=120,
                )
            )
            msg = response.choices[0].message.content.strip()

            if not msg or "NADA" in msg.upper():
                return

        # limpiar si el modelo agrega comillas o prefijos
            msg = re.sub(r'^["""\']+|["""\']+$', "", msg).strip()
            if len(msg) < 5:
                return

            print(f"[Proactive] 💬 {msg}")
            self._last_proactive = asyncio.get_event_loop().time()
            self._in_conversation = True
            self._last_interaction = self._last_proactive
            await self._speak_async(msg)

        except Exception as e:
            print(f"[Proactive] ⚠️ {e}")


    async def _proactive_loop(self) -> None:
        """Thread de background que evalúa proactividad cada N minutos."""
        await asyncio.sleep(60)  # esperar 1 min antes de la primera revisión
        while True:
            await asyncio.sleep(self._proactive_interval)
            now = asyncio.get_event_loop().time()

        # no interrumpir si está hablando o si fue reciente
            with self._speaking_lock:
                is_speaking = self._is_speaking
            if is_speaking:
                continue
            if now - self._last_proactive < self._proactive_cooldown:
                continue

            await self._proactive_check()

    async def _execute_tool(self, name: str, args: dict) -> str:
        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")
        loop = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "save_memory":
                category = args.get("category", "notes")
                key      = args.get("key", "")
                value    = args.get("value", "")
                if key and value:
                    update_memory({category: {key: {"value": value}}})
                    print(f"[Memory] 💾 {category}/{key} = {value}")
                return ""   # silencioso
            
            elif name == "volume_mixer":
                result = await loop.run_in_executor(None, lambda: volume_mixer(parameters=args, player=self.ui))

            elif name == "weather_report":
                result = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))

            elif name == "browser_control":
                result = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))

            elif name == "file_controller":
                result = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))

            elif name == "send_message":
                result = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))

            elif name == "reminder":
                result = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))

            elif name == "youtube_video":
                result = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
            elif name == "screenshot":
                result = await loop.run_in_executor(None, lambda: screenshot(parameters=args, player=self.ui))

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None, "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = "Vision module activated."

            elif name == "computer_settings":
                result = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))

            elif name == "close_app":
                result = await loop.run_in_executor(None, lambda: close_app(parameters=args, player=self.ui))

            elif name == "open_app":
                result = await loop.run_in_executor(None, lambda: open_app(parameters=args, player=self.ui))

            elif name == "send_message":
                result = await loop.run_in_executor(None, lambda: send_message(parameters=args, player=self.ui))

            elif name == "cmd_control":
                result = await loop.run_in_executor(None, lambda: cmd_control(parameters=args, player=self.ui))

            elif name == "desktop_control":
                result = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))

            elif name == "code_helper":
                result = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))

            elif name == "dev_agent":
                result = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "web_search":
                result = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))

            elif name == "computer_control":
                result = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))

            elif name == "game_updater":
                result = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))

            elif name == "flight_finder":
                result = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))

            elif name == "timer":
                result = await loop.run_in_executor(
                None,
                lambda: timer(parameters=args, player=self.ui, speak=self.speak)
                )
            elif name == "writer":
                result = await loop.run_in_executor(
                None,
                lambda: writer(parameters=args, player=self.ui, speak=self.speak)
    )
    

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        self.ui.set_state("LISTENING")
        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        return result or "Done."

    # ── Chat con Groq ─────────────────────────────────────────────────────────

    @staticmethod
    def _clean_response(text: str) -> str:
        import re
        text = re.sub(r"<function=\w+\{.*?\}</function>", "", text, flags=re.DOTALL)
        text = re.sub(r"<function=[^>]*>", "", text)
        text = re.sub(r"\{[^}]*\}\s*$", "", text)
        return text.strip()

    async def _chat(self, user_text: str) -> str:
        import re, uuid
        from core.llm_client import groq_chat_response  # ← único import de LLM
        tools = _groq_tools()

        last = self._conversation[-1] if self._conversation else None
        if not (last and last.get("role") == "user" and last.get("content") == user_text):
            self._conversation.append({"role": "user", "content": user_text})

        if len(self._conversation) > 10:
            self._conversation = self._conversation[-10:]

        system_prompt = self._build_system_prompt()

        def _sanitize(msgs):
            clean = []
            for m in msgs:
                m = dict(m)
                if isinstance(m.get("content"), str):
                    m["content"] = re.sub(r"<function=\w+\{.*?\}</function>", "", m["content"], flags=re.DOTALL)
                    m["content"] = re.sub(r"<function=[^>]*>", "", m["content"]).strip()
                if m.get("role") in ("user", "assistant") and not m.get("content") and not m.get("tool_calls"):
                    continue
                clean.append(m)
            return clean

        messages = [{"role": "system", "content": system_prompt}] + _sanitize(self._conversation)

        MAX_TOOL_ROUNDS = 5
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = await asyncio.to_thread(
                    lambda: groq_chat_response(
                        messages=messages,
                        tools=tools,
                    )
                )
            except Exception as e:
                print(f"[JARVIS] ❌ LLM error: {e}")
                self._conversation.append({"role": "assistant", "content": ""})
                return "I encountered an error, sir. Please try again."

            msg = response.choices[0].message

        # qwen a veces mete tool calls en el texto en lugar de tool_calls struct
            if not msg.tool_calls and msg.content:
                match = re.search(r"<function=(\w+)(\{.*?)(?:</function>|$)", msg.content, re.DOTALL)
                if match:
                    fn_name  = match.group(1)
                    raw_args = match.group(2).strip()
                    if not raw_args.endswith("}"):
                        raw_args += "}"
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', raw_args)
                        args  = {k: v for k, v in pairs}

                    tool_result = await self._execute_tool(fn_name, args)
                    fake_id = str(uuid.uuid4())
                    messages.append({
                        "role": "assistant", "content": "",
                        "tool_calls": [{"id": fake_id, "type": "function", "function": {"name": fn_name, "arguments": json.dumps(args)}}]
                    })
                    messages.append({"role": "tool", "tool_call_id": fake_id, "content": str(tool_result)})
                    continue

            if msg.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id":       tc.id,
                            "type":     "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                        }
                        for tc in msg.tool_calls
                    ]
                })

                for tc in msg.tool_calls:
                    raw_args = tc.function.arguments or "{}"
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        fixed = raw_args.strip()
                        if not fixed.endswith("}"):
                            fixed += "}"
                        try:
                            args = json.loads(fixed)
                        except json.JSONDecodeError:
                            pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', fixed)
                            args = {k: v for k, v in pairs}

                    tool_result = await self._execute_tool(tc.function.name, args)
                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      str(tool_result),
                    })
                continue

            final_text = self._clean_response(msg.content or "")
            self._conversation.append({"role": "assistant", "content": final_text})
            return final_text

        return "I completed the requested actions, sir."

    # ── VAD + mic ─────────────────────────────────────────────────────────────

    async def _listen_and_process(self):
        """
        Escucha el micrófono continuamente.
        Detecta voz por RMS, acumula frames, y cuando hay silencio
        suficiente manda a transcribir + chat.
        """
        loop = asyncio.get_event_loop()
        audio_buffer   = []   # frames mientras hay voz
        silence_chunks = 0
        speaking       = False
        speech_chunks  = 0

        silence_limit = int(VAD_SILENCE_DURATION / VAD_CHUNK_DURATION)
        speech_min    = int(VAD_MIN_SPEECH_DURATION / VAD_CHUNK_DURATION)

        mic_queue: asyncio.Queue = asyncio.Queue()

        def mic_callback(indata, frames, time_info, status):
            # No capturar mientras Jarvis habla
            with self._speaking_lock:
                if self._is_speaking:
                    return
            loop.call_soon_threadsafe(mic_queue.put_nowait, indata.copy())

        stream = sd.InputStream(
    samplerate=SEND_SAMPLE_RATE,
    channels=CHANNELS,
    dtype="float32",  # era int16
    blocksize=VAD_CHUNK_SIZE,
    callback=mic_callback,
    device=1
)

        print("[JARVIS] 🎤 Mic started")
        stream.start()

        silence_limit_tentative  = int(SILENCE_TENTATIVE  / VAD_CHUNK_DURATION)
        silence_limit_definitive = int(SILENCE_DEFINITIVE / VAD_CHUNK_DURATION)

        try:
            while True:
                chunk = await mic_queue.get()
                rms = float(np.sqrt(np.mean(chunk ** 2)))

                if rms > VAD_SILENCE_THRESHOLD:
                    if not speaking:
                        speaking       = True
                        speech_chunks  = 0
                        audio_buffer   = []
                        self.ui.set_state("LISTENING")
                    audio_buffer.append(chunk)
                    speech_chunks  += 1
                    silence_chunks  = 0   # reset — volvió a hablar

                elif speaking:
                    audio_buffer.append(chunk)
                    silence_chunks += 1

                    if silence_chunks >= silence_limit_definitive:
                        # Silencio largo — definitivamente terminó
                        speaking = False
                        if speech_chunks >= int(VAD_MIN_SPEECH_DURATION / VAD_CHUNK_DURATION):
                            frames = list(audio_buffer)
                            audio_buffer = []
                            asyncio.ensure_future(self._process_voice(frames))
                        else:
                            audio_buffer = []

                    elif silence_chunks == silence_limit_tentative:
                        # Silencio corto — puede estar pensando
                        # No procesamos todavía, solo mostramos estado
                        self.ui.set_state("THINKING")

        finally:
            stream.stop()
            stream.close()

    async def _process_voice(self, frames: list):
        self.ui.set_state("THINKING")
        text = await asyncio.to_thread(_transcribe_audio, frames)
        if not text:
            self.ui.set_state("LISTENING")
            return

        print(f"[STT] 🗣️  {text}")

        import re
        normalized = text.lower().strip()
        WAKE_WORDS = ["asistente"]

    # Verificar si el timeout de conversación expiró
        now = asyncio.get_event_loop().time()
        if self._in_conversation:
            if now - self._last_interaction > self._conversation_timeout:
                self._in_conversation = False
                print("[JARVIS] 💤 Conversación expirada — wake word requerido")

        if not self._in_conversation:
            if not any(w in normalized for w in WAKE_WORDS):
                self.ui.set_state("LISTENING")
                return
        # limpiar wake word del texto
            clean = re.sub(
                r"^(" + "|".join(WAKE_WORDS) + r")[,\.\s]*",
                "", text, flags=re.IGNORECASE
            ).strip() or text.strip()
        else:
            # en conversación — usar el texto completo
            clean = text.strip()

        if not clean:
            self.ui.set_state("LISTENING")
            return

    # actualizar timestamp
        self._last_interaction = asyncio.get_event_loop().time()

        self.ui.write_log(f"You: {clean}")
        await self._respond(clean)

    # ── Texto desde UI ────────────────────────────────────────────────────────

        if not self._in_conversation:
            now = asyncio.get_event_loop().time()
            if now - self._last_proactive > self._proactive_cooldown:
                await self._proactive_check()

        self.ui.write_log(f"You: {clean}")
        await self._respond(clean)

    async def _watch_text_queue(self):
        """Procesa comandos de texto escritos desde la UI."""
        while True:
            text = await self._text_queue.get()
            self.ui.write_log(f"You: {text}")
            await self._respond(text)

    # ── Respuesta común ───────────────────────────────────────────────────────

    async def _respond(self, user_text: str):
        self.ui.set_state("THINKING")
        try:
            reply = await self._chat(user_text)
            if reply:
                self._in_conversation = True
                self._last_interaction = asyncio.get_event_loop().time()
                await self._speak_async(reply)
        except Exception as e:
            print(f"[JARVIS] ❌ _respond error: {e}")
            traceback.print_exc()
            self.ui.set_state("LISTENING")

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self.ui.set_state("LISTENING")
        print("[JARVIS] ✅ Ready — Groq backend (STT + chat + TTS)")

        await asyncio.gather(
            self._listen_and_process(),
            self._watch_text_queue(),
            self._proactive_loop(),
        )


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()