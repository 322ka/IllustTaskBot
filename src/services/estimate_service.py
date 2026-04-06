from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.models.estimate_definitions import (
    DEFAULT_ESTIMATE_TEMPLATE,
    ESTIMATE_TEMPLATES,
    EstimateStep,
)
from src.services.db_service import get_current_event


ESTIMATE_EVENT_REQUIRED_MESSAGE = (
    "\u30a4\u30d9\u30f3\u30c8\u540d\u304c\u6307\u5b9a\u3055\u308c\u3066\u3044\u307e\u305b\u3093\u3002"
    "\u5148\u306b /event \u3067\u8a2d\u5b9a\u3059\u308b\u304b\u3001"
    "/estimate \u306b \u30a4\u30d9\u30f3\u30c8\u540d \u3092\u6307\u5b9a\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
)


@dataclass
class SimpleEstimateResult:
    steps: list[EstimateStep]
    total_hours: float
    days_until_due: int
    commentary: str
    schedule_lines: list[str]


def resolve_estimate_event_name(
    explicit_event_name: str | None,
    user_id: str,
) -> str | None:
    if explicit_event_name:
        return explicit_event_name
    return get_current_event(user_id)


def get_estimate_template(work_type: str) -> list[EstimateStep]:
    template = ESTIMATE_TEMPLATES.get(work_type, DEFAULT_ESTIMATE_TEMPLATE)
    return [dict(step) for step in template]


def build_simple_commentary(total_hours: float, days_until_due: int) -> str:
    if days_until_due < 0:
        return "\u7de0\u5207\u3092\u904e\u304e\u3066\u3044\u307e\u3059\u3002\u5225\u6848\u306e\u691c\u8a0e\u304c\u5fc5\u8981\u3067\u3059\u3002"
    if days_until_due <= 3 or total_hours / max(days_until_due, 1) >= 4:
        return "\u53b3\u3057\u3081\u3067\u3059\u3002\u512a\u5148\u9806\u4f4d\u306e\u6574\u7406\u3068\u30d0\u30c3\u30d5\u30a1\u78ba\u4fdd\u3092\u304a\u3059\u3059\u3081\u3057\u307e\u3059\u3002"
    if days_until_due <= 7 or total_hours / max(days_until_due, 1) >= 2:
        return "\u3084\u3084\u30bf\u30a4\u30c8\u3067\u3059\u304c\u8abf\u6574\u53ef\u80fd\u3067\u3059\u3002"
    return "\u4f59\u88d5\u3042\u308a\u3067\u3059\u3002\u30d0\u30c3\u30d5\u30a1\u3092\u53d6\u308a\u3084\u3059\u3044\u898b\u7a4d\u3067\u3059\u3002"


def build_simple_schedule_lines(
    due_date: date,
    steps: list[EstimateStep],
) -> list[str]:
    schedule_lines: list[str] = []
    current_date = due_date

    for step in reversed(steps):
        schedule_lines.append(
            f"{current_date.strftime('%Y-%m-%d')} : {step['step_name']} ({step['hours']:.1f}h)"
        )
        current_date -= timedelta(days=1)

    return list(reversed(schedule_lines))


def build_simple_estimate(
    *,
    due_date: date,
    work_type: str,
    today: date | None = None,
) -> SimpleEstimateResult:
    base_date = today or datetime.now().date()
    steps = get_estimate_template(work_type)
    total_hours = sum(step["hours"] for step in steps)
    days_until_due = (due_date - base_date).days
    commentary = build_simple_commentary(total_hours, days_until_due)
    schedule_lines = build_simple_schedule_lines(due_date, steps)

    return SimpleEstimateResult(
        steps=steps,
        total_hours=total_hours,
        days_until_due=days_until_due,
        commentary=commentary,
        schedule_lines=schedule_lines,
    )
