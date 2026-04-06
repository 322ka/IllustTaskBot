from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.estimate_runtime_definitions import EstimateStep


BASE_DIR = Path(__file__).resolve().parents[2]
ESTIMATE_PROMPT_PATH = BASE_DIR / "prompts" / "estimate_prompt.md"


@dataclass
class AIEstimateResult:
    adjusted_steps: list[EstimateStep]
    total_hours: float
    commentary: str
    buffer_comment: str
    schedule_plan: list[str]


@dataclass
class AIEstimateOutcome:
    result: AIEstimateResult | None
    used_ai: bool
    failure_stage: str | None = None
    failure_reason: str | None = None


def _load_estimate_prompt() -> str:
    return ESTIMATE_PROMPT_PATH.read_text(encoding="utf-8")


def _render_prompt(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _strip_code_fences(text: str) -> str:
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text.strip()


def request_estimate_adjustment(
    *,
    openai_client: Any | None,
    event_name: str,
    work_title: str,
    work_category: str,
    work_type: str,
    difficulty: str | None,
    due_date: str,
    template_steps: list[EstimateStep],
) -> AIEstimateOutcome:
    if openai_client is None:
        print("estimate.ai skipped: OpenAI client is not configured.")
        return AIEstimateOutcome(
            result=None,
            used_ai=False,
            failure_stage="ai_call",
            failure_reason="OpenAI client is not configured.",
        )

    prompt = _render_prompt(
        _load_estimate_prompt(),
        {
            "event_name": event_name,
            "work_title": work_title,
            "work_category": work_category,
            "work_type": work_type,
            "difficulty": difficulty or "unspecified",
            "due_date": due_date,
            "template_steps_json": json.dumps(template_steps, ensure_ascii=False, indent=2),
        },
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        response_text = response.choices[0].message.content
        print(f"estimate.ai raw response repr: {response_text!r}")
    except Exception as exc:
        print(f"estimate.ai call failed: {type(exc).__name__}: {exc}")
        return AIEstimateOutcome(
            result=None,
            used_ai=False,
            failure_stage="ai_call",
            failure_reason=f"{type(exc).__name__}: {exc}",
        )

    if not response_text or not response_text.strip():
        print("estimate.ai empty response")
        return AIEstimateOutcome(
            result=None,
            used_ai=False,
            failure_stage="ai_response",
            failure_reason="AI response was empty.",
        )

    cleaned = _strip_code_fences(response_text)
    print(f"estimate.ai cleaned response preview: {cleaned[:400]!r}")

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(f"estimate.ai json parse error: {exc}")
        print(f"estimate.ai parse preview: {cleaned[:500]!r}")
        return AIEstimateOutcome(
            result=None,
            used_ai=False,
            failure_stage="json_parse",
            failure_reason=f"JSON parse failed: {exc}",
        )

    adjusted_steps_raw = parsed.get("adjusted_steps")
    schedule_plan_raw = parsed.get("schedule_plan")
    commentary = parsed.get("commentary")
    buffer_comment = parsed.get("buffer_comment")

    if not isinstance(adjusted_steps_raw, list):
        return AIEstimateOutcome(None, False, "json_shape", "adjusted_steps shape is invalid.")
    if not isinstance(schedule_plan_raw, list):
        return AIEstimateOutcome(None, False, "json_shape", "schedule_plan shape is invalid.")
    if not isinstance(commentary, str) or not isinstance(buffer_comment, str):
        return AIEstimateOutcome(None, False, "json_shape", "commentary fields are invalid.")

    adjusted_steps: list[EstimateStep] = []
    for step in adjusted_steps_raw:
        step_name = step.get("step_name")
        hours = step.get("hours")
        if not isinstance(step_name, str) or not isinstance(hours, (int, float)):
            return AIEstimateOutcome(None, False, "json_shape", "step data shape is invalid.")
        adjusted_steps.append({"step_name": step_name, "hours": float(hours)})

    schedule_plan = [line for line in schedule_plan_raw if isinstance(line, str)]
    if not schedule_plan:
        return AIEstimateOutcome(None, False, "json_shape", "schedule_plan is empty.")

    total_hours = parsed.get("total_hours")
    if not isinstance(total_hours, (int, float)):
        total_hours = sum(step["hours"] for step in adjusted_steps)

    return AIEstimateOutcome(
        result=AIEstimateResult(
            adjusted_steps=adjusted_steps,
            total_hours=float(total_hours),
            commentary=commentary,
            buffer_comment=buffer_comment,
            schedule_plan=schedule_plan,
        ),
        used_ai=True,
    )
