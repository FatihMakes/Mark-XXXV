import json
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"
RUNTIME_STATE_FILE = CONFIG_DIR / "runtime_state.json"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def ensure_runtime_state_dir() -> None:
    RUNTIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def config_exists() -> bool:
    return CONFIG_FILE.exists()


def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["gemini_api_key"] = gemini_api_key.strip()

    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )


def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}


def get_gemini_key() -> str | None:
    key = str(load_api_keys().get("gemini_api_key", "")).strip()
    return key or None


def require_gemini_key() -> str:
    key = get_gemini_key()
    if not key:
        raise RuntimeError("gemini_api_key is not configured.")
    return key


def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def load_runtime_state() -> dict:
    if not RUNTIME_STATE_FILE.exists():
        return {}
    try:
        return json.loads(RUNTIME_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load runtime_state.json: {e}")
        return {}


def save_runtime_state(data: dict) -> None:
    ensure_runtime_state_dir()
    RUNTIME_STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_runtime_value(key: str, default=None):
    return load_runtime_state().get(key, default)


def set_runtime_value(key: str, value) -> None:
    data = load_runtime_state()
    data[key] = value
    save_runtime_state(data)
