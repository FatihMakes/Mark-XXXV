import json
import re

from core.action_registry import build_planner_prompt, get_action_spec
from memory.config_manager import require_gemini_key


def _normalize_plan(plan: dict, fallback_query: str) -> dict:
    if "steps" not in plan or not isinstance(plan["steps"], list):
        raise ValueError("Invalid plan structure")

    for step in plan["steps"]:
        spec = get_action_spec(step.get("tool", ""))
        if not spec or not spec.supports_agent:
            print(f"[Planner] ⚠️ Invalid tool in step {step.get('step')}: {step.get('tool')}")
            desc = step.get("description", fallback_query)
            step["tool"] = "web_search"
            step["parameters"] = {"query": desc[:200]}

    return plan


def create_plan(goal: str, context: str = "") -> dict:
    import google.generativeai as genai

    genai.configure(api_key=require_gemini_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=build_planner_prompt(),
    )

    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        response = model.generate_content(user_input)
        text = response.text.strip()
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        plan = _normalize_plan(json.loads(text), goal)

        print(f"[Planner] ✅ Plan: {len(plan['steps'])} steps")
        for step in plan["steps"]:
            print(f"  Step {step['step']}: [{step['tool']}] {step['description']}")
        return plan

    except json.JSONDecodeError as exc:
        print(f"[Planner] ⚠️ JSON parse failed: {exc}")
        return _fallback_plan(goal)
    except Exception as exc:
        print(f"[Planner] ⚠️ Planning failed: {exc}")
        return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    print("[Planner] 🔄 Fallback plan")
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True,
            }
        ],
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=require_gemini_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=build_planner_prompt(),
    )

    completed_summary = "\n".join(
        f"  - Step {step['step']} ({step['tool']}): DONE" for step in completed_steps
    )

    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a revised plan for the remaining work only. Do not repeat completed steps."""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        plan = _normalize_plan(json.loads(text), failed_step.get("description", goal))
        print(f"[Planner] 🔄 Revised plan: {len(plan['steps'])} steps")
        return plan
    except Exception as exc:
        print(f"[Planner] ⚠️ Replan failed: {exc}")
        return _fallback_plan(goal)
