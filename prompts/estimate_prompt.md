You are assisting with illustration production estimation.
Use the template steps as the base estimate, then adjust them carefully.

Inputs:
- event_name: {event_name}
- work_title: {work_title}
- work_category: {work_category}
- work_type: {work_type}
- difficulty: {difficulty}
- due_date: {due_date}

Template steps:
{template_steps_json}

Google Calendar context:
{calendar_context_json}

Rules:
- Keep the same step structure, but you may adjust hours realistically.
- Return `adjusted_steps`.
- Return `total_hours`.
- `buffer_comment` must be natural Japanese.
- `commentary` must be natural Japanese.
- `schedule_plan` must be a natural Japanese schedule suggestion with 3 to 8 lines.
- Use the Google Calendar context as supporting information for commentary and schedule naturalness.
- Treat all-day and semi-all-day days as normal schedule pressure.
- Do not weaken their importance because the calendar is shared.
- Do not output explanations outside JSON.
- Do not use code fences.
- Output must be valid JSON only.

Output format:
{
  "adjusted_steps": [
    {"step_name": "情報収集", "hours": 1.5}
  ],
  "total_hours": 18.5,
  "buffer_comment": "修正対応も見込んで余裕を少し加えました。",
  "commentary": "ややタイトですが、カレンダー上の予定も考慮すると前半でラフまで進めたいです。",
  "schedule_plan": [
    "2026-04-10 - 情報収集と構図",
    "2026-04-11 - ラフ",
    "2026-04-12 - 線画"
  ]
}
