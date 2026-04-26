"""
Screenshot action — captura pantalla completa o ventana activa y la guarda.
Requiere: pip install pillow mss
"""

import os
import re
from datetime import datetime
from pathlib import Path


def _default_path() -> Path:
    return Path.home() / "Pictures" / "Screenshots"


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def screenshot(parameters: dict, player=None) -> str:
    import mss
    import mss.tools

    try:
        from PIL import Image
        _PIL = True
    except ImportError:
        _PIL = False

    dest     = (parameters.get("destination") or "").strip()
    filename = (parameters.get("filename") or "").strip()
    monitor  = parameters.get("monitor", 1)  # 1 = monitor principal

    # Resolver carpeta destino
    if dest:
        folder = Path(dest).expanduser()
    else:
        folder = _default_path()

    folder.mkdir(parents=True, exist_ok=True)

    # Resolver nombre de archivo
    if filename:
        filename = _sanitize_filename(filename)
        if not filename.lower().endswith((".png", ".jpg")):
            filename += ".png"
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename  = f"screenshot_{timestamp}.png"

    output_path = folder / filename

    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor >= len(monitors):
                monitor = 1
            shot = sct.grab(monitors[monitor])

            if _PIL:
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                img.save(str(output_path))
            else:
                mss.tools.to_png(shot.rgb, shot.size, output=str(output_path))

        if player:
            player.write_log(f"[screenshot] Guardada en {output_path}")

        return f"Screenshot guardada en {output_path}, sir."

    except Exception as e:
        return f"Error al tomar screenshot: {e}"