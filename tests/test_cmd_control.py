import unittest

from actions.cmd_control import cmd_control


class CmdControlTests(unittest.TestCase):
    def test_blocked_command_is_rejected(self):
        result = cmd_control({"command": "taskkill /f /im chrome.exe", "visible": False})
        self.assertIn("Blocked for safety", result)

    def test_model_fallback_is_disabled_by_default(self):
        result = cmd_control({"task": "show system uptime", "visible": False})
        self.assertIn("explicit safe command", result)


if __name__ == "__main__":
    unittest.main()
