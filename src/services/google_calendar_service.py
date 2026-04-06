from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


GOOGLE_CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


@dataclass
class GoogleCalendarEvent:
    summary: str
    start: str
    end: str | None
    is_all_day: bool


@dataclass
class GoogleCalendarClientResult:
    client: Any | None
    calendar_id: str
    error: str | None = None


def _import_google_dependencies() -> tuple[Any, Any, Any] | tuple[None, None, None]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        return Request, Credentials, build
    except ImportError:
        return None, None, None


def build_google_calendar_client(
    *,
    calendar_id: str | None = None,
    token_file: str | None = None,
) -> GoogleCalendarClientResult:
    request_cls, credentials_cls, build_fn = _import_google_dependencies()
    resolved_calendar_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")
    resolved_token_file = token_file or os.getenv("GOOGLE_TOKEN_FILE", "google_token.json")

    if request_cls is None or credentials_cls is None or build_fn is None:
        return GoogleCalendarClientResult(
            client=None,
            calendar_id=resolved_calendar_id,
            error="Google Calendar dependencies are not installed.",
        )

    if not os.path.exists(resolved_token_file):
        return GoogleCalendarClientResult(
            client=None,
            calendar_id=resolved_calendar_id,
            error=(
                "Google OAuth token file was not found. "
                "Set GOOGLE_TOKEN_FILE and prepare an authorized user token."
            ),
        )

    try:
        credentials = credentials_cls.from_authorized_user_file(
            resolved_token_file,
            [GOOGLE_CALENDAR_READONLY_SCOPE],
        )
    except Exception as exc:
        return GoogleCalendarClientResult(
            client=None,
            calendar_id=resolved_calendar_id,
            error=f"Failed to load Google OAuth token: {type(exc).__name__}: {exc}",
        )

    try:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(request_cls())
            with open(resolved_token_file, "w", encoding="utf-8") as token_handle:
                token_handle.write(credentials.to_json())
    except Exception as exc:
        return GoogleCalendarClientResult(
            client=None,
            calendar_id=resolved_calendar_id,
            error=f"Failed to refresh Google OAuth token: {type(exc).__name__}: {exc}",
        )

    if not credentials or not credentials.valid:
        return GoogleCalendarClientResult(
            client=None,
            calendar_id=resolved_calendar_id,
            error="Google OAuth token is invalid. Re-authorize and try again.",
        )

    try:
        client = build_fn("calendar", "v3", credentials=credentials)
    except Exception as exc:
        return GoogleCalendarClientResult(
            client=None,
            calendar_id=resolved_calendar_id,
            error=f"Failed to build Google Calendar client: {type(exc).__name__}: {exc}",
        )

    return GoogleCalendarClientResult(client=client, calendar_id=resolved_calendar_id)


def list_events(
    *,
    calendar_id: str = "primary",
    time_min: datetime,
    time_max: datetime,
    max_results: int = 20,
) -> tuple[list[GoogleCalendarEvent], str | None]:
    client_result = build_google_calendar_client(calendar_id=calendar_id)
    if client_result.client is None:
        return [], client_result.error

    normalized_time_min = time_min.astimezone(timezone.utc) if time_min.tzinfo else time_min.replace(tzinfo=timezone.utc)
    normalized_time_max = time_max.astimezone(timezone.utc) if time_max.tzinfo else time_max.replace(tzinfo=timezone.utc)

    try:
        response = (
            client_result.client.events()
            .list(
                calendarId=client_result.calendar_id,
                timeMin=normalized_time_min.isoformat().replace("+00:00", "Z"),
                timeMax=normalized_time_max.isoformat().replace("+00:00", "Z"),
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )
    except Exception as exc:
        return [], f"Failed to list Google Calendar events: {type(exc).__name__}: {exc}"

    events: list[GoogleCalendarEvent] = []
    for item in response.get("items", []):
        start_info = item.get("start", {})
        end_info = item.get("end", {})
        start_date = start_info.get("date")
        start_datetime = start_info.get("dateTime")
        end_date = end_info.get("date")
        end_datetime = end_info.get("dateTime")
        is_all_day = bool(start_date and not start_datetime)
        start_value = start_date or start_datetime or ""
        end_value = end_date or end_datetime
        events.append(
            GoogleCalendarEvent(
                summary=item.get("summary") or "(no title)",
                start=start_value,
                end=end_value,
                is_all_day=is_all_day,
            )
        )

    return events, None
