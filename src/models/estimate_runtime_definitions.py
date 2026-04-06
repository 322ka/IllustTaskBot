from __future__ import annotations

from typing import TypedDict


class EstimateStep(TypedDict):
    step_name: str
    hours: float


DEFAULT_ESTIMATE_TEMPLATE: list[EstimateStep] = [
    {"step_name": "\u60c5\u5831\u53ce\u96c6", "hours": 1.0},
    {"step_name": "\u69cb\u56f3", "hours": 2.0},
    {"step_name": "\u30e9\u30d5", "hours": 4.0},
    {"step_name": "\u4ed5\u4e0a\u3052", "hours": 3.0},
]


ESTIMATE_TEMPLATES: dict[str, list[EstimateStep]] = {
    "\u30b0\u30c3\u30ba": [
        {"step_name": "\u60c5\u5831\u53ce\u96c6", "hours": 1.0},
        {"step_name": "\u69cb\u56f3", "hours": 2.0},
        {"step_name": "\u30e9\u30d5", "hours": 4.0},
        {"step_name": "\u7dda\u753b", "hours": 4.0},
        {"step_name": "\u7740\u8272", "hours": 5.0},
        {"step_name": "\u4ed5\u4e0a\u3052", "hours": 2.0},
        {"step_name": "\u5165\u7a3f\u6e96\u5099", "hours": 1.5},
    ],
    "\u540c\u4eba\u8a8c": [
        {"step_name": "\u69cb\u6210", "hours": 2.0},
        {"step_name": "\u30d7\u30ed\u30c3\u30c8", "hours": 3.0},
        {"step_name": "\u4e0b\u66f8\u304d", "hours": 6.0},
        {"step_name": "\u6e05\u66f8", "hours": 8.0},
        {"step_name": "\u4ed5\u4e0a\u3052", "hours": 3.0},
        {"step_name": "\u8868\u7d19", "hours": 4.0},
        {"step_name": "\u5165\u7a3f\u6e96\u5099", "hours": 2.0},
    ],
    "\u30ce\u30d9\u30eb\u30c6\u30a3": [
        {"step_name": "\u60c5\u5831\u53ce\u96c6", "hours": 1.0},
        {"step_name": "\u69cb\u56f3", "hours": 1.5},
        {"step_name": "\u30e9\u30d5", "hours": 3.0},
        {"step_name": "\u7dda\u753b", "hours": 3.0},
        {"step_name": "\u7740\u8272", "hours": 4.0},
        {"step_name": "\u4ed5\u4e0a\u3052", "hours": 2.0},
        {"step_name": "\u5165\u7a3f\u6e96\u5099", "hours": 1.0},
    ],
    "\u30c7\u30a3\u30b9\u30d7\u30ec\u30a4": [
        {"step_name": "\u60c5\u5831\u53ce\u96c6", "hours": 1.5},
        {"step_name": "\u69cb\u56f3", "hours": 2.5},
        {"step_name": "\u30e9\u30d5", "hours": 4.0},
        {"step_name": "\u7dda\u753b", "hours": 4.0},
        {"step_name": "\u7740\u8272", "hours": 5.0},
        {"step_name": "\u6587\u5b57\u5165\u308c", "hours": 2.0},
        {"step_name": "\u4ed5\u4e0a\u3052", "hours": 2.0},
        {"step_name": "\u5165\u7a3f\u6e96\u5099", "hours": 1.5},
    ],
    "\u7acb\u3061\u7d75": [
        {"step_name": "\u60c5\u5831\u53ce\u96c6", "hours": 1.0},
        {"step_name": "\u69cb\u56f3", "hours": 2.0},
        {"step_name": "\u30e9\u30d5", "hours": 3.0},
        {"step_name": "\u7dda\u753b", "hours": 4.0},
        {"step_name": "\u7740\u8272", "hours": 5.0},
        {"step_name": "\u4ed5\u4e0a\u3052", "hours": 2.0},
    ],
    "1\u679a\u7d75": [
        {"step_name": "\u60c5\u5831\u53ce\u96c6", "hours": 1.5},
        {"step_name": "\u69cb\u56f3", "hours": 2.5},
        {"step_name": "\u30e9\u30d5", "hours": 4.0},
        {"step_name": "\u7dda\u753b", "hours": 5.0},
        {"step_name": "\u7740\u8272", "hours": 6.0},
        {"step_name": "\u4ed5\u4e0a\u3052", "hours": 3.0},
    ],
    "SD": [
        {"step_name": "\u60c5\u5831\u53ce\u96c6", "hours": 0.5},
        {"step_name": "\u69cb\u56f3", "hours": 1.0},
        {"step_name": "\u30e9\u30d5", "hours": 2.0},
        {"step_name": "\u7dda\u753b", "hours": 2.0},
        {"step_name": "\u7740\u8272", "hours": 2.5},
        {"step_name": "\u4ed5\u4e0a\u3052", "hours": 1.0},
    ],
    "\u305d\u306e\u4ed6": DEFAULT_ESTIMATE_TEMPLATE,
}


WORK_TYPE_WEIGHTS: dict[str, float] = {
    "1\u679a\u7d75": 1.0,
    "\u30b0\u30c3\u30ba": 1.1,
    "\u540c\u4eba\u8a8c": 1.15,
    "\u30ce\u30d9\u30eb\u30c6\u30a3": 0.95,
    "\u30c7\u30a3\u30b9\u30d7\u30ec\u30a4": 1.2,
    "\u305d\u306e\u4ed6": 1.0,
}
