from __future__ import annotations

from typing import TypedDict


class EstimateStep(TypedDict):
    step_name: str
    hours: float


DEFAULT_ESTIMATE_TEMPLATE: list[EstimateStep] = [
    {"step_name": "情報収集", "hours": 1.0},
    {"step_name": "構図", "hours": 2.0},
    {"step_name": "ラフ", "hours": 4.0},
    {"step_name": "仕上げ", "hours": 3.0},
]


ESTIMATE_TEMPLATES: dict[str, list[EstimateStep]] = {
    "グッズ": [
        {"step_name": "情報収集", "hours": 1.0},
        {"step_name": "構図", "hours": 2.0},
        {"step_name": "ラフ", "hours": 4.0},
        {"step_name": "線画", "hours": 4.0},
        {"step_name": "着色", "hours": 5.0},
        {"step_name": "仕上げ", "hours": 2.0},
        {"step_name": "入稿準備", "hours": 1.5},
    ],
    "同人誌": [
        {"step_name": "構成", "hours": 2.0},
        {"step_name": "プロット", "hours": 3.0},
        {"step_name": "下書き", "hours": 6.0},
        {"step_name": "清書", "hours": 8.0},
        {"step_name": "仕上げ", "hours": 3.0},
        {"step_name": "表紙", "hours": 4.0},
        {"step_name": "入稿準備", "hours": 2.0},
    ],
    "ノベルティ": [
        {"step_name": "情報収集", "hours": 1.0},
        {"step_name": "構図", "hours": 1.5},
        {"step_name": "ラフ", "hours": 3.0},
        {"step_name": "線画", "hours": 3.0},
        {"step_name": "着色", "hours": 4.0},
        {"step_name": "仕上げ", "hours": 2.0},
        {"step_name": "入稿準備", "hours": 1.0},
    ],
    "ディスプレイ": [
        {"step_name": "情報収集", "hours": 1.5},
        {"step_name": "構図", "hours": 2.5},
        {"step_name": "ラフ", "hours": 4.0},
        {"step_name": "線画", "hours": 4.0},
        {"step_name": "着色", "hours": 5.0},
        {"step_name": "文字入れ", "hours": 2.0},
        {"step_name": "仕上げ", "hours": 2.0},
        {"step_name": "入稿準備", "hours": 1.5},
    ],
    "立ち絵": [
        {"step_name": "情報収集", "hours": 1.0},
        {"step_name": "構図", "hours": 2.0},
        {"step_name": "ラフ", "hours": 3.0},
        {"step_name": "線画", "hours": 4.0},
        {"step_name": "着色", "hours": 5.0},
        {"step_name": "仕上げ", "hours": 2.0},
    ],
    "1枚絵": [
        {"step_name": "情報収集", "hours": 1.5},
        {"step_name": "構図", "hours": 2.5},
        {"step_name": "ラフ", "hours": 4.0},
        {"step_name": "線画", "hours": 5.0},
        {"step_name": "着色", "hours": 6.0},
        {"step_name": "仕上げ", "hours": 3.0},
    ],
    "SD": [
        {"step_name": "情報収集", "hours": 0.5},
        {"step_name": "構図", "hours": 1.0},
        {"step_name": "ラフ", "hours": 2.0},
        {"step_name": "線画", "hours": 2.0},
        {"step_name": "着色", "hours": 2.5},
        {"step_name": "仕上げ", "hours": 1.0},
    ],
    "その他": DEFAULT_ESTIMATE_TEMPLATE,
}
