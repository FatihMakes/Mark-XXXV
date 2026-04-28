import psutil
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

def volume_mixer(parameters=None, response=None, player=None, session_memory=None) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()
    level    = (parameters or {}).get("level", None)
    action   = (parameters or {}).get("action", "set").lower()

    if not app_name:
        return "Please specify an application, sir."

    sessions = AudioUtilities.GetAllSessions()
    app_lower = app_name.lower().replace(".exe", "")
    matched = []

    for s in sessions:
        if s.Process and app_lower in s.Process.name().lower().replace(".exe", ""):
            matched.append(s)

    if not matched:
        return f"No active audio session found for {app_name}, sir."

    for s in matched:
        vol = s._ctl.QueryInterface(ISimpleAudioVolume)
        current = vol.GetMasterVolume()

        if action == "mute":
            vol.SetMute(1, None)
        elif action == "unmute":
            vol.SetMute(0, None)
        elif action == "up":
            vol.SetMasterVolume(min(1.0, current + 0.2), None)
        elif action == "down":
            vol.SetMasterVolume(max(0.0, current - 0.2), None)
        elif action == "set" and level is not None:
            vol.SetMasterVolume(max(0.0, min(1.0, float(level) / 100)), None)

    return f"Volume adjusted for {app_name}, sir."