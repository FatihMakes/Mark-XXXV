import unittest
from unittest.mock import patch

from core.action_result import success
from core.bootstrap_check import run_checks
from agent.executor import AgentExecutor


class ExecutorAndBootstrapTests(unittest.TestCase):
    def test_agent_executor_runs_with_mocked_action_registry(self):
        plan = {
            "goal": "open notepad",
            "steps": [
                {
                    "step": 1,
                    "tool": "open_app",
                    "description": "Open Notepad",
                    "parameters": {"app_name": "Notepad"},
                    "critical": True,
                }
            ],
        }
        with patch("agent.executor.create_plan", return_value=plan), \
             patch("agent.executor.execute_action", return_value=success("Opened Notepad.")), \
             patch.object(AgentExecutor, "_summarize", return_value="Opened Notepad, sir."):
            result = AgentExecutor().execute("open notepad")
        self.assertEqual(result, "Opened Notepad, sir.")

    def test_bootstrap_check_success_path(self):
        with patch("core.bootstrap_check._read_requirements", return_value=[]), \
             patch("core.bootstrap_check._check_playwright", return_value=(True, "ok")), \
             patch("core.bootstrap_check.load_api_keys", return_value={"gemini_api_key": "x" * 20}), \
             patch("core.bootstrap_check.sys.version_info", (3, 11, 0)):
            report = run_checks()
        self.assertTrue(report["ok"])


if __name__ == "__main__":
    unittest.main()
