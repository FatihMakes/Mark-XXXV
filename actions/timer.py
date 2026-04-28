"""
Timer y alarmas — asyncio based, no bloquea el hilo principal.
"""

import asyncio
import threading
import time
from datetime import datetime, timedelta
import re

_active_timers: dict[str, threading.Timer] = {}


def _parse_duration(text: str) -> int | None:
    """Convierte '5 minutos', '30 segundos', '1 hora' a segundos."""
    text = text.lower().strip()
    total = 0
    patterns = [
        (r"(\d+)\s*hora", 3600),
        (r"(\d+)\s*min",  60),
        (r"(\d+)\s*seg",  1),
        (r"(\d+)\s*h",    3600),
        (r"(\d+)\s*m",    60),
        (r"(\d+)\s*s",    1),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            total += int(match.group(1)) * multiplier
    return total if total > 0 else None


def _parse_alarm_time(text: str) -> datetime | None:
    """Convierte '14:30', '3:30pm', '8 de la mañana' a datetime."""
    text = text.lower().strip()

    # HH:MM
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if "pm" in text and h < 12:
            h += 12
        if "am" in text and h == 12:
            h = 0
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    # "8 de la mañana" → 8:00
    match = re.search(r"(\d{1,2})\s*de la mañana", text)
    if match:
        h = int(match.group(1))
        now = datetime.now()
        target = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    return None


def timer(parameters: dict, player=None, speak=None) -> str:
    action   = parameters.get("action", "set").lower()
    label    = parameters.get("label", "Timer").strip()
    duration = parameters.get("duration", "").strip()
    alarm_at = parameters.get("alarm_at", "").strip()
    timer_id = parameters.get("timer_id", label).strip()

    # ── CANCELAR ──────────────────────────────────────────────
    if action == "cancel":
        if timer_id in _active_timers:
            _active_timers[timer_id].cancel()
            del _active_timers[timer_id]
            return f"Timer '{timer_id}' cancelado, sir."
        return f"No hay timer activo con nombre '{timer_id}'."

    # ── LISTAR ────────────────────────────────────────────────
    if action == "list":
        if not _active_timers:
            return "No hay timers activos, sir."
        return "Timers activos: " + ", ".join(_active_timers.keys())

    # ── SETEAR TIMER (duración) ────────────────────────────────
    if action == "set" and duration:
        seconds = _parse_duration(duration)
        if not seconds:
            return f"No entendí la duración '{duration}'. Decí algo como '5 minutos' o '30 segundos'."

        def _fire():
            msg = f"Sir, el timer '{label}' terminó."
            print(f"[Timer] ⏰ {msg}")
            if player:
                player.write_log(f"[Timer] {label} terminó")
            if speak:
                speak(msg)
            if label in _active_timers:
                del _active_timers[label]

        t = threading.Timer(seconds, _fire)
        t.daemon = True
        t.start()
        _active_timers[label] = t

        mins = seconds // 60
        secs = seconds % 60
        if mins > 0:
            dur_str = f"{mins}m {secs}s" if secs else f"{mins} minutos"
        else:
            dur_str = f"{secs} segundos"

        return f"Timer '{label}' seteado por {dur_str}, sir."

    # ── ALARMA (hora específica) ───────────────────────────────
    if action in ("alarm", "set") and alarm_at:
        target = _parse_alarm_time(alarm_at)
        if not target:
            return f"No entendí la hora '{alarm_at}'. Decí algo como '14:30' o '8 de la mañana'."

        seconds = (target - datetime.now()).total_seconds()

        def _fire_alarm():
            msg = f"Sir, son las {target.strftime('%H:%M')}. Alarma: '{label}'."
            print(f"[Timer] ⏰ {msg}")
            if player:
                player.write_log(f"[Alarma] {label}")
            if speak:
                speak(msg)
            if label in _active_timers:
                del _active_timers[label]

        t = threading.Timer(seconds, _fire_alarm)
        t.daemon = True
        t.start()
        _active_timers[label] = t

        return f"Alarma '{label}' seteada para las {target.strftime('%H:%M')}, sir."

    return "Especificá una duración ('5 minutos') o una hora ('14:30')."