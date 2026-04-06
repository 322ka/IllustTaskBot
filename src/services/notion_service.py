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


def get_title_property_name(notion: Any, database_id: str) -> str:
    database = notion.databases.retrieve(database_id=database_id)
    properties = database.get("properties", {})

    for prop_name, prop in properties.items():
        if prop.get("type") == "title":
            return prop_name

    raise ValueError("Notion database に title プロパティが見つかりません。")


def find_page_by_title(
    notion: Any,
    database_id: str,
    title_property_name: str,
    page_title: str,
) -> dict | None:
    response = notion.databases.query(
        database_id=database_id,
        filter={
            "property": title_property_name,
            "title": {
                "equals": page_title,
            },
        },
        page_size=1,
    )

    results = response.get("results", [])
    if results:
        return results[0]

    return None


def ensure_event_page(
    notion: Any,
    database_id: str,
    event_name: str,
) -> str:
    title_property_name = get_title_property_name(notion, database_id)
    existing_page = find_page_by_title(
        notion=notion,
        database_id=database_id,
        title_property_name=title_property_name,
        page_title=event_name,
    )
    if existing_page:
        return "exists"

    notion.pages.create(
        parent={"database_id": database_id},
        properties={
            title_property_name: {
                "title": [
                    {
                        "text": {
                            "content": event_name,
                        }
                    }
                ]
            }
        },
    )
    return "created"
