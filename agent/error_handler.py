import json
import re
from enum import Enum

from memory.config_manager import require_gemini_key


class ErrorDecision(Enum):
    RETRY = "retry"
    SKIP = "skip"
    REPLAN = "replan"
    ABORT = "abort"


ERROR_ANALYST_PROMPT = """You are the error recovery module of MARK XXXV AI assistant.

A task step has failed. Analyze the failure and decide what to do.

DECISIONS:
- retry: transient failure that may work on the next attempt.
- skip: the failed step is non-critical and can be skipped.
- replan: the current tool or method is wrong; choose a different approach.
- abort: the task is unsafe or fundamentally impossible.

Return ONLY valid JSON:
{
  "decision": "retry|skip|replan|abort",
  "reason": "short reason",
  "max_retries": 1,
  "user_message": "Short message to tell the user"
}
"""


def analyze_error(
    step: dict,
    error: str,
    attempt: int = 1,
    max_attempts: int = 2,
    *,
    error_code: str | None = None,
    retryable: bool | None = None,
) -> dict:
    import google.generativeai as genai

    if retryable is True and attempt < max_attempts:
        return {
            "decision": ErrorDecision.RETRY,
            "reason": error[:120],
            "max_retries": max_attempts - attempt,
            "user_message": "Retrying the step, sir.",
        }

    if error_code in {"validation_error", "unknown_action", "unsupported_action"}:
        return {
            "decision": ErrorDecision.REPLAN,
            "reason": error[:120],
            "max_retries": 0,
            "user_message": "Adjusting the approach, sir.",
        }

    if attempt >= max_attempts:
        print(f"[ErrorHandler] ⚠️ Max attempts reached for step {step.get('step')} — forcing replan")
        return {
            "decision": ErrorDecision.REPLAN,
            "reason": f"Failed {attempt} times: {error[:100]}",
            "max_retries": 0,
            "user_message": "Trying a different approach, sir.",
        }

    genai.configure(api_key=require_gemini_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=ERROR_ANALYST_PROMPT,
    )

    prompt = f"""Failed step:
Tool: {step.get('tool')}
Description: {step.get('description')}
Parameters: {json.dumps(step.get('parameters', {}), indent=2)}
Critical: {step.get('critical', False)}
Error code: {error_code or 'none'}
Retryable hint: {retryable}

Error:
{error[:500]}

Attempt number: {attempt}"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        result = json.loads(text)
        decision_str = str(result.get("decision", "replan")).lower()
        decision_map = {
            "retry": ErrorDecision.RETRY,
            "skip": ErrorDecision.SKIP,
            "replan": ErrorDecision.REPLAN,
            "abort": ErrorDecision.ABORT,
        }
        result["decision"] = decision_map.get(decision_str, ErrorDecision.REPLAN)

        if step.get("critical") and result["decision"] == ErrorDecision.SKIP:
            result["decision"] = ErrorDecision.REPLAN
            result["user_message"] = "This step is critical — finding another approach, sir."

        print(f"[ErrorHandler] Decision: {result['decision'].value} — {result.get('reason', '')}")
        return result

    except Exception as exc:
        print(f"[ErrorHandler] ⚠️ Analysis failed: {exc} — defaulting to replan")
        return {
            "decision": ErrorDecision.REPLAN,
            "reason": str(exc),
            "max_retries": 0,
            "user_message": "Encountered an issue, adjusting approach, sir.",
        }
