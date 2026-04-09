import argparse
import asyncio
import threading
import traceback
from pathlib import Path

from core.action_registry import execute_action, get_live_function_declarations
from core.bootstrap_check import format_report, run_checks
from memory.config_manager import require_gemini_key
from memory.memory_manager import (
    extract_memory,
    format_memory_for_prompt,
    load_memory,
    should_extract_memory,
    update_memory,
)


PROMPT_PATH = Path(__file__).resolve().parent / "core" / "prompt.txt"
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
_last_memory_input = ""


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )


def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    global _last_memory_input

    user_text = (user_text or "").strip()
    jarvis_text = (jarvis_text or "").strip()
    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    try:
        api_key = require_gemini_key()
        if not should_extract_memory(user_text, jarvis_text, api_key):
            return
        data = extract_memory(user_text, jarvis_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ {list(data.keys())}")
    except Exception as exc:
        if "429" not in str(exc):
            print(f"[Memory] ⚠️ {exc}")


class JarvisLive:
    def __init__(self, ui):
        self.ui = ui
        self.session = None
        self.audio_in_queue = None
        self.out_queue = None
        self._loop = None
        self._is_speaking = False
        self._speaking_lock = threading.Lock()
        self.ui.on_text_command = self._on_text_command

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(turns={"parts": [{"text": text}]}, turn_complete=True),
            self._loop,
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(turns={"parts": [{"text": text}]}, turn_complete=True),
            self._loop,
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self):
        from datetime import datetime
        from google.genai import types

        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            "[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            "Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": get_live_function_declarations()}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
                )
            ),
        )

    async def _execute_tool(self, fc):
        from google.genai import types

        name = fc.name
        args = dict(fc.args or {})
        print(f"[JARVIS] 🔧 {name} {args}")
        self.ui.set_state("THINKING")

        result = execute_action(name, args, player=self.ui, speak=self.speak, target="live")
        if not result.ok:
            self.speak_error(name, result.message)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {result.message[:80]}")
        return types.FunctionResponse(id=fc.id, name=name, response={"result": result.message, **result.to_response_payload()})

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        import sounddevice as sd

        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"},
                )

        with sd.InputStream(
            samplerate=SEND_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
            callback=callback,
        ):
            print("[JARVIS] 🎤 Mic stream open")
            while True:
                await asyncio.sleep(0.1)

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        async for response in self.session.receive():
            if response.data:
                self.audio_in_queue.put_nowait(response.data)

            if response.server_content:
                server_content = response.server_content
                if server_content.output_transcription and server_content.output_transcription.text:
                    self.set_speaking(True)
                    text = server_content.output_transcription.text.strip()
                    if text:
                        out_buf.append(text)

                if server_content.input_transcription and server_content.input_transcription.text:
                    text = server_content.input_transcription.text.strip()
                    if text:
                        in_buf.append(text)

                if server_content.turn_complete:
                    self.set_speaking(False)
                    full_in = " ".join(in_buf).strip()
                    if full_in:
                        self.ui.write_log(f"You: {full_in}")
                    in_buf = []

                    full_out = " ".join(out_buf).strip()
                    if full_out:
                        self.ui.write_log(f"Jarvis: {full_out}")
                    out_buf = []

                    if full_in and len(full_in) > 5:
                        threading.Thread(
                            target=_update_memory_async,
                            args=(full_in, full_out),
                            daemon=True,
                            name="MemoryUpdateThread",
                        ).start()

            if response.tool_call:
                function_responses = []
                for function_call in response.tool_call.function_calls:
                    print(f"[JARVIS] 📞 {function_call.name}")
                    function_responses.append(await self._execute_tool(function_call))
                await self.session.send_tool_response(function_responses=function_responses)

    async def _play_audio(self):
        import sounddevice as sd

        print("[JARVIS] 🔊 Play started")
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        from google import genai

        client = genai.Client(api_key=require_gemini_key(), http_options={"api_version": "v1beta"})

        while True:
            try:
                print("[JARVIS] 🔌 Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    self.session = session
                    self._loop = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=10)

                    print("[JARVIS] ✅ Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")

                    async with asyncio.TaskGroup() as group:
                        group.create_task(self._send_realtime())
                        group.create_task(self._listen_audio())
                        group.create_task(self._receive_audio())
                        group.create_task(self._play_audio())

            except Exception as exc:
                print(f"[JARVIS] ⚠️ {exc}")
                traceback.print_exc()

            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[JARVIS] 🔄 Reconnecting in 3s...")
            await asyncio.sleep(3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Validate the local environment and configuration.")
    args = parser.parse_args()

    if args.check:
        report = run_checks()
        print(format_report(report))
        return 0 if report["ok"] else 1

    from ui import JarvisUI

    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True, name="JarvisMainThread").start()
    ui.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
