import threading
import time
from typing import Callable

from agent.error_handler import ErrorDecision, analyze_error
from agent.planner import create_plan, replan
from core.action_registry import execute_action
from memory.config_manager import require_gemini_key


def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                value
                for value in step_results.values()
                if value and len(value) > 100 and value not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                params["content"] = _translate_to_goal_language(combined, goal)
                print("[Executor] Injected contextual content")

    return params


def _detect_language(text: str) -> str:
    import google.generativeai as genai

    genai.configure(api_key=require_gemini_key())
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    try:
        response = model.generate_content(
            "What language is this text written in? Reply with ONLY the language name in English.\n\n"
            f"Text: {text[:200]}"
        )
        return response.text.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content

    try:
        import google.generativeai as genai

        genai.configure(api_key=require_gemini_key())
        model = genai.GenerativeModel("gemini-2.5-flash")
        target_lang = _detect_language(goal)
        response = model.generate_content(
            "Translate the following text into "
            f"{target_lang}. Keep all facts, numbers, and formatting. Output ONLY the translated text.\n\n"
            f"{content[:4000]}"
        )
        print(f"[Executor] Translated content to {target_lang}")
        return response.text.strip()
    except Exception as exc:
        print(f"[Executor] Translation failed: {exc}")
        return content


class AgentExecutor:
    MAX_REPLAN_ATTEMPTS = 2

    def execute(
        self,
        goal: str,
        speak: Callable | None = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        print(f"\n[Executor] Goal: {goal}")

        replan_attempts = 0
        completed_steps = []
        step_results: dict[int | str, str] = {}
        plan = create_plan(goal)

        while True:
            steps = plan.get("steps", [])
            if not steps:
                message = "I couldn't create a valid plan for this task, sir."
                if speak:
                    speak(message)
                return message

            success_run = True
            failed_step = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak:
                        speak("Task cancelled, sir.")
                    return "Task cancelled."

                step_num = step.get("step", "?")
                tool = step.get("tool", "web_search")
                desc = step.get("description", "")
                params = _inject_context(step.get("parameters", {}), tool, step_results, goal=goal)

                print(f"\n[Executor] Step {step_num}: [{tool}] {desc}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    result = execute_action(tool, params, speak=speak, target="agent")
                    if result.ok:
                        step_results[step_num] = result.message
                        completed_steps.append(step)
                        print(f"[Executor] Step {step_num} done: {result.message[:100]}")
                        step_ok = True
                        break

                    print(f"[Executor] Step {step_num} attempt {attempt} failed: {result.message}")
                    recovery = analyze_error(
                        step,
                        result.message,
                        attempt=attempt,
                        error_code=result.error_code,
                        retryable=result.retryable,
                    )
                    decision = recovery["decision"]
                    user_message = recovery.get("user_message", "")
                    if speak and user_message:
                        speak(user_message)

                    if decision == ErrorDecision.RETRY:
                        attempt += 1
                        time.sleep(2)
                        continue

                    if decision == ErrorDecision.SKIP:
                        print(f"[Executor] Skipping step {step_num}")
                        completed_steps.append(step)
                        step_ok = True
                        break

                    if decision == ErrorDecision.ABORT:
                        message = f"Task aborted, sir. {recovery.get('reason', '')}".strip()
                        if speak:
                            speak(message)
                        return message

                    failed_step = step
                    failed_error = result.message
                    success_run = False
                    break

                if not step_ok and not failed_step:
                    failed_step = step
                    failed_error = "Max retries exceeded"
                    success_run = False

                if not success_run:
                    break

            if success_run:
                return self._summarize(goal, completed_steps, speak)

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                message = f"Task failed after {replan_attempts} replan attempts, sir."
                if speak:
                    speak(message)
                return message

            if speak:
                speak("Adjusting my approach, sir.")
            replan_attempts += 1
            plan = replan(goal, completed_steps, failed_step, failed_error)

    def _summarize(self, goal: str, completed_steps: list, speak: Callable | None) -> str:
        fallback = f"All done, sir. Completed {len(completed_steps)} steps for: {goal[:60]}."
        try:
            import google.generativeai as genai

            genai.configure(api_key=require_gemini_key())
            model = genai.GenerativeModel(model_name="gemini-2.5-flash-lite")
            steps_str = "\n".join(f"- {step.get('description', '')}" for step in completed_steps)
            prompt = (
                f'User goal: "{goal}"\n'
                f"Completed steps:\n{steps_str}\n\n"
                "Write a single natural sentence summarizing what was accomplished. "
                "Address the user as 'sir'. Be direct and positive."
            )
            response = model.generate_content(prompt)
            summary = response.text.strip()
            if speak:
                speak(summary)
            return summary
        except Exception:
            if speak:
                speak(fallback)
            return fallback
