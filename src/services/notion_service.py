from __future__ import annotations

from typing import Any


EVENT_PROPERTY_NAME = "イベント名(進捗管理用)"


def get_select_options(
    notion: Any,
    database_id: str,
    property_name: str,
) -> list[str]:
    database = notion.databases.retrieve(database_id=database_id)
    properties = database.get("properties", {})
    prop = properties.get(property_name)

    if not prop:
        raise ValueError(f"Notion プロパティが見つかりません: {property_name}")

    if prop.get("type") != "select":
        raise ValueError(f"Notion プロパティが select ではありません: {property_name}")

    return [
        option.get("name")
        for option in prop.get("select", {}).get("options", [])
        if option.get("name")
    ]


def has_select_option(
    notion: Any,
    database_id: str,
    property_name: str,
    option_name: str,
) -> bool:
    return option_name in get_select_options(notion, database_id, property_name)


def ensure_select_option(
    notion: Any,
    database_id: str,
    property_name: str,
    option_name: str,
) -> str:
    database = notion.databases.retrieve(database_id=database_id)
    properties = database.get("properties", {})
    prop = properties.get(property_name)

    if not prop:
        raise ValueError(f"Notion プロパティが見つかりません: {property_name}")

    if prop.get("type") != "select":
        raise ValueError(f"Notion プロパティが select ではありません: {property_name}")

    options = prop.get("select", {}).get("options", [])
    if any(option.get("name") == option_name for option in options):
        return "exists"

    new_options = list(options) + [{"name": option_name}]
    notion.databases.update(
        database_id=database_id,
        properties={
            property_name: {
                "select": {
                    "options": new_options,
                }
            }
        },
    )
    return "added"
