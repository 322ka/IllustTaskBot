from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from src.models.estimate_templates import EstimateStep


BASE_DIR = Path(__file__).resolve().parents[2]
ESTIMATE_PROMPT_PATH = BASE_DIR / "prompts" / "estimate_prompt.md"


class AIEstimateResult(TypedDict):
    adjusted_steps: list[EstimateStep]
    total_hours: float
    commentary: str
    buffer_comment: str
    schedule_plan: list[str]


def _load_estimate_prompt() -> str:
    return ESTIMATE_PROMPT_PATH.read_text(encoding="utf-8")


def _strip_code_fences(text: str) -> str:
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text.strip()


def apply_ai_estimate_adjustment(
    *,
    openai_client: Any | None,
    event_name: str,
    work_title: str,
    work_category: str,
    work_type: str,
    difficulty: str | None,
    due_date: str,
    template_steps: list[EstimateStep],
) -> AIEstimateResult | None:
    if openai_client is None:
        print("AI estimate fallback: OpenAI client が未設定です。")
        return None

    prompt_template = _load_estimate_prompt()
    prompt = prompt_template.format(
        event_name=event_name,
        work_title=work_title,
        work_category=work_category,
        work_type=work_type,
        difficulty=difficulty or "未指定",
        due_date=due_date,
        template_steps_json=json.dumps(template_steps, ensure_ascii=False, indent=2),
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        response_text = response.choices[0].message.content
        print(f"AI estimate raw response repr: {response_text!r}")

        if not response_text or not response_text.strip():
            print("AI estimate fallback: 応答が空です。")
            return None

        cleaned = _strip_code_fences(response_text)
        print(f"AI estimate cleaned response preview: {cleaned[:400]!r}")
        parsed = json.loads(cleaned)

        adjusted_steps_raw = parsed.get("adjusted_steps")
        schedule_plan_raw = parsed.get("schedule_plan")
        if not isinstance(adjusted_steps_raw, list) or not isinstance(schedule_plan_raw, list):
            print("AI estimate fallback: adjusted_steps または schedule_plan の形式が不正です。")
            return None

        adjusted_steps: list[EstimateStep] = []
        for step in adjusted_steps_raw:
            step_name = step.get("step_name")
            hours = step.get("hours")
            if not isinstance(step_name, str) or not isinstance(hours, (int, float)):
                print(f"AI estimate fallback: step 形式が不正です。 step={step!r}")
                return None
            adjusted_steps.append({"step_name": step_name, "hours": float(hours)})

        commentary = parsed.get("commentary")
        buffer_comment = parsed.get("buffer_comment")
        if not isinstance(commentary, str) or not isinstance(buffer_comment, str):
            print("AI estimate fallback: commentary または buffer_comment が不正です。")
            return None

        schedule_plan = [line for line in schedule_plan_raw if isinstance(line, str)]
        if not schedule_plan:
            print("AI estimate fallback: schedule_plan に文字列がありません。")
            return None

        total_hours = parsed.get("total_hours")
        if not isinstance(total_hours, (int, float)):
            total_hours = sum(step["hours"] for step in adjusted_steps)

        return {
            "adjusted_steps": adjusted_steps,
            "total_hours": float(total_hours),
            "commentary": commentary,
            "buffer_comment": buffer_comment,
            "schedule_plan": schedule_plan,
        }
    except json.JSONDecodeError as exc:
        preview = response_text[:500] if "response_text" in locals() else ""
        print(f"AI estimate JSON parse error: {exc}")
        print(f"AI estimate response preview on parse error: {preview!r}")
        return None
    except Exception as exc:
        print(f"AI estimate fallback: {type(exc).__name__}: {exc}")
        return None
