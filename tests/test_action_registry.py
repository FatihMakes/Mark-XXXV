import unittest
from unittest.mock import patch

from core.action_registry import build_planner_prompt, execute_action, get_live_function_declarations
from core.action_result import ActionResult


class ActionRegistryTests(unittest.TestCase):
    def test_unknown_action_fails_structured(self):
        result = execute_action("does_not_exist", {}, target="agent")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "unknown_action")

    def test_missing_required_parameter_fails_validation(self):
        result = execute_action("open_app", {}, target="live")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "validation_error")

    def test_save_memory_uses_registry_executor(self):
        with patch("core.action_registry.update_memory") as update_memory:
            result = execute_action(
                "save_memory",
                {"category": "notes", "key": "favorite_game", "value": "chess"},
                target="live",
            )
        self.assertTrue(result.ok)
        update_memory.assert_called_once()

    def test_live_declarations_come_from_registry(self):
        declarations = get_live_function_declarations()
        names = {item["name"] for item in declarations}
        self.assertIn("open_app", names)
        self.assertIn("save_memory", names)

    def test_planner_prompt_excludes_non_agent_actions(self):
        prompt = build_planner_prompt()
        self.assertIn("cmd_control", prompt)
        self.assertNotIn("agent_task\n", prompt)


if __name__ == "__main__":
    unittest.main()
