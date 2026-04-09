from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from core.action_result import ActionResult, failure, success
from memory.memory_manager import update_memory


Executor = Callable[[dict[str, Any], Any, Callable[[str], None] | None, Any], ActionResult]


@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    executor: Executor
    safety_level: str
    supports_live: bool = True
    supports_agent: bool = True

    def function_declaration(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }


def _normalize_result(
    value: Any,
    *,
    default_message: str = "Done.",
    error_code: str = "action_failed",
) -> ActionResult:
    if isinstance(value, ActionResult):
        return value
    if value is None:
        return success(default_message)

    message = str(value).strip() or default_message
    lowered = message.lower()
    error_markers = (
        "error:",
        "failed",
        "could not",
        "cannot ",
        "can't ",
        "blocked",
        "unknown action",
        "please specify",
        "permission denied",
        "timed out",
    )
    if any(marker in lowered for marker in error_markers):
        return failure(message, error_code=error_code, retryable="timed out" in lowered)
    return success(message)


def _run_import(module_name: str, function_name: str, parameters: dict[str, Any], **kwargs) -> ActionResult:
    module = __import__(module_name, fromlist=[function_name])
    function = getattr(module, function_name)
    return _normalize_result(function(parameters=parameters, response=None, **kwargs))


def _run_open_app(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.open_app", "open_app", parameters, player=player)


def _run_web_search(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.web_search", "web_search", parameters, player=player, session_memory=session_memory)


def _run_weather(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    module = __import__("actions.weather_report", fromlist=["weather_action"])
    return _normalize_result(module.weather_action(parameters=parameters, player=player, session_memory=session_memory))


def _run_send_message(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.send_message", "send_message", parameters, player=player, session_memory=session_memory)


def _run_reminder(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.reminder", "reminder", parameters, player=player, session_memory=session_memory)


def _run_screen_process(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    from actions.screen_processor import screen_process

    threading.Thread(
        target=screen_process,
        kwargs={"parameters": parameters, "response": None, "player": player, "session_memory": session_memory},
        daemon=True,
        name="ScreenProcessAction",
    ).start()
    return success("Vision module activated. Stay completely silent — vision module will speak directly.")


def _run_computer_settings(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.computer_settings", "computer_settings", parameters, player=player, session_memory=session_memory)


def _run_browser_control(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.browser_control", "browser_control", parameters, player=player, session_memory=session_memory)


def _run_file_controller(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.file_controller", "file_controller", parameters, player=player, session_memory=session_memory)


def _run_code_helper(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    module = __import__("actions.code_helper", fromlist=["code_helper"])
    return _normalize_result(module.code_helper(parameters=parameters, player=player, speak=speak))


def _run_dev_agent(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    module = __import__("actions.dev_agent", fromlist=["dev_agent"])
    return _normalize_result(module.dev_agent(parameters=parameters, player=player, speak=speak))


def _run_cmd_control(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.cmd_control", "cmd_control", parameters, player=player, session_memory=session_memory)


def _run_desktop_control(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.desktop", "desktop_control", parameters, player=player, session_memory=session_memory)


def _run_agent_task(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    from agent.task_queue import TaskPriority, get_queue

    priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
    priority = priority_map.get(str(parameters.get("priority", "normal")).lower(), TaskPriority.NORMAL)
    goal = str(parameters.get("goal", "")).strip()
    if not goal:
        return failure("agent_task requires a goal.", error_code="validation_error")

    task_id = get_queue().submit(goal=goal, priority=priority, speak=speak)
    return success(f"Task started (ID: {task_id}).", data={"task_id": task_id})


def _run_computer_control(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    return _run_import("actions.computer_control", "computer_control", parameters, player=player, session_memory=session_memory)


def _run_game_updater(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    module = __import__("actions.game_updater", fromlist=["game_updater"])
    return _normalize_result(module.game_updater(parameters=parameters, player=player, speak=speak))


def _run_flight_finder(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    module = __import__("actions.flight_finder", fromlist=["flight_finder"])
    return _normalize_result(module.flight_finder(parameters=parameters, player=player, speak=speak))


def _run_youtube(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    module = __import__("actions.youtube_video", fromlist=["youtube_video"])
    return _normalize_result(module.youtube_video(parameters=parameters, response=None, player=player, speak=speak))


def _run_save_memory(parameters: dict[str, Any], player=None, speak=None, session_memory=None) -> ActionResult:
    category = str(parameters.get("category", "notes")).strip() or "notes"
    key = str(parameters.get("key", "")).strip()
    value = str(parameters.get("value", "")).strip()
    if not key or not value:
        return failure("save_memory requires category, key, and value.", error_code="validation_error")
    update_memory({category: {key: {"value": value}}})
    return success("ok", data={"silent": True})


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "OBJECT", "properties": properties, "required": required or []}


_ACTION_SPECS = [
    ActionSpec("open_app", "Opens any application on the computer.", _schema({"app_name": {"type": "STRING", "description": "Exact name of the application."}}, ["app_name"]), _run_open_app, "medium"),
    ActionSpec("web_search", "Searches the web for information or compares items.", _schema({"query": {"type": "STRING", "description": "Search query."}, "mode": {"type": "STRING", "description": "search or compare."}, "items": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare."}, "aspect": {"type": "STRING", "description": "Comparison aspect."}}, ["query"]), _run_web_search, "low"),
    ActionSpec("weather_report", "Gets real-time weather information for a city.", _schema({"city": {"type": "STRING", "description": "City name."}}, ["city"]), _run_weather, "low"),
    ActionSpec("send_message", "Sends a text message via a messaging platform.", _schema({"receiver": {"type": "STRING", "description": "Recipient contact name."}, "message_text": {"type": "STRING", "description": "The message to send."}, "platform": {"type": "STRING", "description": "Platform name."}}, ["receiver", "message_text", "platform"]), _run_send_message, "high"),
    ActionSpec("reminder", "Sets a timed reminder using the system scheduler.", _schema({"date": {"type": "STRING", "description": "Date in YYYY-MM-DD format."}, "time": {"type": "STRING", "description": "Time in HH:MM format."}, "message": {"type": "STRING", "description": "Reminder message."}}, ["date", "time", "message"]), _run_reminder, "medium"),
    ActionSpec("youtube_video", "Controls YouTube for play, summarize, get info, or trending workflows.", _schema({"action": {"type": "STRING", "description": "play | summarize | get_info | trending"}, "query": {"type": "STRING", "description": "Search query for play."}, "save": {"type": "BOOLEAN", "description": "Save summary to Notepad."}, "region": {"type": "STRING", "description": "Country code for trending."}, "url": {"type": "STRING", "description": "Video URL for get_info."}}), _run_youtube, "medium"),
    ActionSpec("screen_process", "Captures and analyzes the screen or webcam image.", _schema({"angle": {"type": "STRING", "description": "screen or camera."}, "text": {"type": "STRING", "description": "Question or instruction about the captured image."}}, ["text"]), _run_screen_process, "medium"),
    ActionSpec("computer_settings", "Handles OS and system-level controls such as volume, brightness, lock, restart, shutdown, and Wi-Fi.", _schema({"action": {"type": "STRING", "description": "The action to perform."}, "description": {"type": "STRING", "description": "Natural language description."}, "value": {"type": "STRING", "description": "Optional action value."}}), _run_computer_settings, "high"),
    ActionSpec("browser_control", "Controls the web browser for navigation, search, clicking, typing, scrolling, and text extraction.", _schema({"action": {"type": "STRING", "description": "Browser action name."}, "url": {"type": "STRING", "description": "URL for go_to."}, "query": {"type": "STRING", "description": "Search query."}, "selector": {"type": "STRING", "description": "CSS selector."}, "text": {"type": "STRING", "description": "Text to click or type."}, "description": {"type": "STRING", "description": "Element description."}, "direction": {"type": "STRING", "description": "Scroll direction."}, "key": {"type": "STRING", "description": "Key name."}, "incognito": {"type": "BOOLEAN", "description": "Open in private mode."}}, ["action"]), _run_browser_control, "medium"),
    ActionSpec("file_controller", "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage, organize desktop, and info.", _schema({"action": {"type": "STRING", "description": "File action name."}, "path": {"type": "STRING", "description": "File or folder path or shortcut."}, "destination": {"type": "STRING", "description": "Destination path."}, "new_name": {"type": "STRING", "description": "New name for rename."}, "content": {"type": "STRING", "description": "File content."}, "name": {"type": "STRING", "description": "File name."}, "extension": {"type": "STRING", "description": "Extension for search."}, "count": {"type": "INTEGER", "description": "Number of results for largest."}, "append": {"type": "BOOLEAN", "description": "Append instead of overwrite."}, "max_results": {"type": "INTEGER", "description": "Maximum search results."}}, ["action"]), _run_file_controller, "high"),
    ActionSpec("code_helper", "Assists with writing, editing, explaining, running, and optimizing code.", _schema({"action": {"type": "STRING", "description": "write | edit | run | explain | build | optimize | screen_debug | auto"}, "description": {"type": "STRING", "description": "Task description."}, "language": {"type": "STRING", "description": "Programming language."}, "output_path": {"type": "STRING", "description": "Output file path."}, "file_path": {"type": "STRING", "description": "Target file path."}, "code": {"type": "STRING", "description": "Inline code content."}}), _run_code_helper, "high"),
    ActionSpec("dev_agent", "Creates or repairs small code projects using model assistance.", _schema({"description": {"type": "STRING", "description": "Project or coding task description."}, "language": {"type": "STRING", "description": "Programming language."}}, ["description"]), _run_dev_agent, "high"),
    ActionSpec("cmd_control", "Executes explicit shell commands with strict safety checks.", _schema({"task": {"type": "STRING", "description": "Natural language description for a known safe command."}, "command": {"type": "STRING", "description": "Explicit shell command."}, "visible": {"type": "BOOLEAN", "description": "Whether to open a visible terminal."}, "allow_model_fallback": {"type": "BOOLEAN", "description": "Experimental opt-in model fallback."}}), _run_cmd_control, "high"),
    ActionSpec("desktop_control", "Handles deterministic desktop organization and wallpaper actions.", _schema({"action": {"type": "STRING", "description": "wallpaper | wallpaper_url | current_wallpaper | organize | clean | list | stats"}, "path": {"type": "STRING", "description": "Image path."}, "url": {"type": "STRING", "description": "Image URL."}, "mode": {"type": "STRING", "description": "by_type or by_date."}}), _run_desktop_control, "medium"),
    ActionSpec("agent_task", "Queues a complex multi-step goal for the autonomous agent task queue.", _schema({"goal": {"type": "STRING", "description": "The goal to accomplish."}, "priority": {"type": "STRING", "description": "low | normal | high"}}, ["goal"]), _run_agent_task, "high", supports_agent=False),
    ActionSpec("computer_control", "Provides low-level deterministic input primitives such as click, type, press, scroll, screenshot, and screen find.", _schema({"action": {"type": "STRING", "description": "Primitive action name."}, "text": {"type": "STRING", "description": "Text to type or paste."}, "x": {"type": "INTEGER", "description": "X coordinate."}, "y": {"type": "INTEGER", "description": "Y coordinate."}, "x1": {"type": "INTEGER", "description": "Drag start X."}, "y1": {"type": "INTEGER", "description": "Drag start Y."}, "x2": {"type": "INTEGER", "description": "Drag end X."}, "y2": {"type": "INTEGER", "description": "Drag end Y."}, "keys": {"type": "STRING", "description": "Hotkey string."}, "key": {"type": "STRING", "description": "Key name."}, "direction": {"type": "STRING", "description": "Scroll direction."}, "description": {"type": "STRING", "description": "Element description."}, "image": {"type": "STRING", "description": "Image path for locate-on-screen."}}, ["action"]), _run_computer_control, "high"),
    ActionSpec("game_updater", "Handles Steam and Epic install, update, list, download status, and scheduling tasks.", _schema({"action": {"type": "STRING", "description": "update | install | list | download_status | schedule"}, "platform": {"type": "STRING", "description": "steam | epic | both"}, "game_name": {"type": "STRING", "description": "Game name."}, "app_id": {"type": "STRING", "description": "Steam app id."}, "shutdown_when_done": {"type": "BOOLEAN", "description": "Shutdown when done."}}, ["action"]), _run_game_updater, "high"),
    ActionSpec("flight_finder", "Finds flights between cities and summarizes the results.", _schema({"origin": {"type": "STRING", "description": "Origin city or airport."}, "destination": {"type": "STRING", "description": "Destination city or airport."}, "date": {"type": "STRING", "description": "Travel date."}}, ["origin", "destination", "date"]), _run_flight_finder, "medium"),
    ActionSpec("save_memory", "Saves an important personal fact about the user to long-term memory without announcing it.", _schema({"category": {"type": "STRING", "description": "identity | preferences | projects | relationships | wishes | notes"}, "key": {"type": "STRING", "description": "Short snake_case memory key."}, "value": {"type": "STRING", "description": "Concise English value."}}, ["category", "key", "value"]), _run_save_memory, "low", supports_agent=False),
]

ACTION_REGISTRY = {spec.name: spec for spec in _ACTION_SPECS}


def get_action_spec(name: str) -> ActionSpec | None:
    return ACTION_REGISTRY.get(name)


def list_action_specs(*, supports_live: bool | None = None, supports_agent: bool | None = None) -> list[ActionSpec]:
    specs = list(ACTION_REGISTRY.values())
    if supports_live is not None:
        specs = [spec for spec in specs if spec.supports_live == supports_live]
    if supports_agent is not None:
        specs = [spec for spec in specs if spec.supports_agent == supports_agent]
    return specs


def get_live_function_declarations() -> list[dict[str, Any]]:
    return [spec.function_declaration() for spec in list_action_specs(supports_live=True)]


def _validate_parameters(spec: ActionSpec, parameters: dict[str, Any]) -> ActionResult | None:
    required = spec.parameters_schema.get("required", [])
    missing = [name for name in required if not str(parameters.get(name, "")).strip()]
    if missing:
        return failure(
            f"{spec.name} is missing required parameters: {', '.join(missing)}.",
            error_code="validation_error",
        )
    return None


def execute_action(
    name: str,
    parameters: dict[str, Any] | None,
    *,
    player=None,
    speak: Callable[[str], None] | None = None,
    session_memory=None,
    target: str = "live",
) -> ActionResult:
    spec = get_action_spec(name)
    if not spec:
        return failure(f"Unknown action: {name}", error_code="unknown_action")

    if target == "live" and not spec.supports_live:
        return failure(f"{name} is not supported in live mode.", error_code="unsupported_action")
    if target == "agent" and not spec.supports_agent:
        return failure(f"{name} is not supported in agent mode.", error_code="unsupported_action")

    params = dict(parameters or {})
    validation_error = _validate_parameters(spec, params)
    if validation_error:
        return validation_error

    try:
        return spec.executor(params, player, speak, session_memory)
    except Exception as exc:
        return failure(str(exc), error_code="execution_exception")


def build_planner_prompt() -> str:
    lines = [
        "You are the planning module of MARK XXXV, a personal AI assistant.",
        "Break the user's goal into the minimum sequence of steps using ONLY the tools listed below.",
        "",
        "ABSOLUTE RULES:",
        "- NEVER write Python scripts or invent tools.",
        "- NEVER reference previous step results in parameters. Every step must stand alone.",
        "- Use web_search for information retrieval or current data.",
        "- Use file_controller to save content to disk.",
        "- Use cmd_control only for explicit shell commands or known safe command tasks.",
        "- Max 5 steps.",
        "",
        "AVAILABLE TOOLS:",
    ]
    for spec in list_action_specs(supports_agent=True):
        lines.append(spec.name)
        lines.append(f"  {spec.description}")
        required = set(spec.parameters_schema.get("required", []))
        for key, schema in spec.parameters_schema.get("properties", {}).items():
            label = "required" if key in required else "optional"
            type_name = str(schema.get("type", "STRING")).lower()
            lines.append(f"  - {key}: {type_name} ({label}) — {schema.get('description', '').strip()}")
        lines.append("")
    lines.extend(
        [
            "OUTPUT — return ONLY valid JSON, no markdown, no explanation:",
            "{",
            '  "goal": "...",',
            '  "steps": [',
            "    {",
            '      "step": 1,',
            '      "tool": "tool_name",',
            '      "description": "what this step does",',
            '      "parameters": {},',
            '      "critical": true',
            "    }",
            "  ]",
            "}",
        ]
    )
    return "\n".join(lines)
