import unittest
from pathlib import Path
from unittest.mock import patch

from actions.file_controller import delete_file


class FileControllerTests(unittest.TestCase):
    def test_protected_path_delete_is_blocked(self):
        protected = Path.home().resolve()
        with patch.object(Path, "exists", return_value=True):
            result = delete_file(str(protected))
        self.assertIn("Blocked for safety", result)


if __name__ == "__main__":
    unittest.main()
