"""
Writer — escribe texto o traducciones donde está el cursor.
Requiere: pip install pyautogui
"""

import time
import pyautogui

pyautogui.PAUSE = 0.05


def writer(parameters: dict, player=None, speak=None) -> str:
    text        = (parameters.get("text") or "").strip()
    translate   = (parameters.get("translate") or "").strip()
    target_lang = (parameters.get("target_lang") or "").strip()
    delay       = float(parameters.get("delay", 1.0))  # segundos antes de escribir

    if not text:
        return "No hay texto para escribir, sir."

    # Si hay que traducir, el texto ya viene traducido desde el LLM
    # (el modelo traduce antes de llamar la tool)
    # delay para que el usuario ponga el cursor donde quiere
    if delay > 0:
        time.sleep(delay)

    try:
        # pyautogui.write no soporta unicode — usar pyperclip + paste
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except ImportError:
        # fallback: escribir caracter por caracter (más lento, problemas con acentos)
        pyautogui.write(text, interval=0.03)

    if player:
        lang_tag = f" ({target_lang})" if target_lang else ""
        player.write_log(f"[writer] Escrito{lang_tag}: {text[:60]}...")

    return f"Listo, sir."