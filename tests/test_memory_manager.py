import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import memory_manager


class MemoryManagerTests(unittest.TestCase):
    def test_load_memory_handles_partial_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_path = Path(tmp) / "long_term.json"
            memory_path.write_text('{"identity":{"name":{"value":"Fatih"}}}', encoding="utf-8")
            with patch.object(memory_manager, "MEMORY_PATH", memory_path):
                data = memory_manager.load_memory()
        self.assertIn("identity", data)
        self.assertIn("preferences", data)
        self.assertEqual(data["identity"]["name"]["value"], "Fatih")

    def test_load_memory_handles_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_path = Path(tmp) / "long_term.json"
            memory_path.write_text("{broken", encoding="utf-8")
            with patch.object(memory_manager, "MEMORY_PATH", memory_path):
                data = memory_manager.load_memory()
        self.assertEqual(data["identity"], {})


if __name__ == "__main__":
    unittest.main()
