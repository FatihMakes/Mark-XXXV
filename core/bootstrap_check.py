from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from memory.config_manager import (
    RUNTIME_STATE_FILE,
    ensure_config_dir,
    ensure_runtime_state_dir,
    load_api_keys,
)


BASE_DIR = Path(__file__).resolve().parent.parent
REQUIREMENTS_FILE = BASE_DIR / "requirements.txt"


def _read_requirements() -> list[str]:
    if not REQUIREMENTS_FILE.exists():
        return []
    packages: list[str] = []
    for raw_line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        packages.append(line.split("==")[0].split(">=")[0].split("<=")[0].strip())
    return packages


def _module_name(package: str) -> str:
    mapping = {
        "beautifulsoup4": "bs4",
        "duckduckgo-search": "duckduckgo_search",
        "google-genai": "google.genai",
        "google-generativeai": "google.generativeai",
        "opencv-python": "cv2",
        "pillow": "PIL",
        "send2trash": "send2trash",
        "sounddevice": "sounddevice",
        "youtube-transcript-api": "youtube_transcript_api",
        "win10toast": "win10toast",
    }
    return mapping.get(package, package.replace("-", "_"))


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _check_playwright() -> tuple[bool, str]:
    if not _module_available("playwright.sync_api"):
        return False, "playwright package not installed"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = playwright.chromium.executable_path
        if executable and Path(executable).exists():
            return True, executable
        return False, "Chromium browser not installed. Run 'playwright install'."
    except Exception as exc:
        return False, str(exc)


def run_checks() -> dict[str, object]:
    report: dict[str, object] = {"ok": True, "checks": []}

    py_ok = sys.version_info[:2] in {(3, 11), (3, 12)}
    report["checks"].append(
        {
            "name": "python_version",
            "ok": py_ok,
            "message": f"Python {sys.version.split()[0]} detected; expected 3.11 or 3.12.",
        }
    )

    missing = []
    for package in _read_requirements():
        if not _module_available(_module_name(package)):
            missing.append(package)
    report["checks"].append(
        {
            "name": "dependencies",
            "ok": not missing,
            "message": "All required packages installed." if not missing else f"Missing packages: {', '.join(missing)}",
        }
    )

    playwright_ok, playwright_message = _check_playwright()
    report["checks"].append(
        {
            "name": "playwright",
            "ok": playwright_ok,
            "message": playwright_message,
        }
    )

    ensure_config_dir()
    ensure_runtime_state_dir()

    config = load_api_keys()
    gemini_key = str(config.get("gemini_api_key", "")).strip()
    config_ok = bool(gemini_key)
    try:
        json.dumps(config)
        config_message = "Config file is present and valid." if config_ok else "Config file is valid but missing gemini_api_key."
    except Exception as exc:
        config_ok = False
        config_message = f"Config file is invalid JSON: {exc}"
    report["checks"].append(
        {
            "name": "config",
            "ok": config_ok,
            "message": config_message,
        }
    )

    runtime_ok = True
    runtime_messages: list[str] = []
    for path in (BASE_DIR / "memory", RUNTIME_STATE_FILE.parent):
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            runtime_messages.append(f"{path} writable")
        except Exception as exc:
            runtime_ok = False
            runtime_messages.append(f"{path} not writable: {exc}")
    report["checks"].append(
        {
            "name": "runtime_dirs",
            "ok": runtime_ok,
            "message": "; ".join(runtime_messages),
        }
    )

    report["ok"] = all(check["ok"] for check in report["checks"])
    return report


def format_report(report: dict[str, object]) -> str:
    lines = ["MARK-XXXV bootstrap check"]
    for check in report["checks"]:
        status = "PASS" if check["ok"] else "FAIL"
        lines.append(f"[{status}] {check['name']}: {check['message']}")
    lines.append("Overall: PASS" if report["ok"] else "Overall: FAIL")
    return "\n".join(lines)


if __name__ == "__main__":
    result = run_checks()
    print(format_report(result))
    raise SystemExit(0 if result["ok"] else 1)
