import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import config_manager


class ConfigManagerTests(unittest.TestCase):
    def test_runtime_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_file = Path(tmp) / "runtime_state.json"
            with patch.object(config_manager, "RUNTIME_STATE_FILE", runtime_file):
                config_manager.set_runtime_value("camera_index", 2)
                self.assertEqual(config_manager.get_runtime_value("camera_index"), 2)

    def test_require_gemini_key_raises_when_missing(self):
        with patch.object(config_manager, "load_api_keys", return_value={}):
            with self.assertRaises(RuntimeError):
                config_manager.require_gemini_key()


if __name__ == "__main__":
    unittest.main()
