from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
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


@dataclass
class GoogleCalendarEventSummary:
    all_day_dates: list[str]
    semi_all_day_dates: list[str]
    light_dates: list[str]

    @property
    def all_day_count(self) -> int:
        return len(self.all_day_dates)

    @property
    def semi_all_day_count(self) -> int:
        return len(self.semi_all_day_dates)

    @property
    def light_count(self) -> int:
        return len(self.light_dates)


JST = timezone(timedelta(hours=9))
DAY_START_HOUR = 9
DAY_END_HOUR = 24
DAY_CAPACITY_HOURS = DAY_END_HOUR - DAY_START_HOUR


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


def is_all_day_event(event: GoogleCalendarEvent) -> bool:
    return event.is_all_day


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized_value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized_value)
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def get_event_duration_hours(event: GoogleCalendarEvent) -> float | None:
    if event.is_all_day:
        start_date = _parse_date(event.start)
        end_date = _parse_date(event.end)
        if not start_date or not end_date:
            return None
        return max((end_date - start_date).days * 24.0, 24.0)

    start_dt = _parse_datetime(event.start)
    end_dt = _parse_datetime(event.end)
    if not start_dt or not end_dt:
        return None
    duration_hours = (end_dt - start_dt).total_seconds() / 3600
    return max(duration_hours, 0.0)


def is_semi_all_day_event(event: GoogleCalendarEvent) -> bool:
    if event.is_all_day:
        return False
    duration_hours = get_event_duration_hours(event)
    return duration_hours is not None and duration_hours >= 8.0


def _enumerate_event_dates(event: GoogleCalendarEvent) -> list[str]:
    if event.is_all_day:
        start_date = _parse_date(event.start)
        end_date = _parse_date(event.end)
        if not start_date:
            return []
        if not end_date or end_date <= start_date:
            return [start_date.isoformat()]
        dates: list[str] = []
        current_date = start_date
        while current_date < end_date:
            dates.append(current_date.isoformat())
            current_date += timedelta(days=1)
        return dates

    start_dt = _parse_datetime(event.start)
    end_dt = _parse_datetime(event.end)
    if not start_dt:
        return []
    if not end_dt or end_dt <= start_dt:
        return [start_dt.date().isoformat()]

    adjusted_end = end_dt - timedelta(microseconds=1)
    current_date = start_dt.date()
    final_date = adjusted_end.date()
    dates: list[str] = []
    while current_date <= final_date:
        dates.append(current_date.isoformat())
        current_date += timedelta(days=1)
    return dates


def summarize_events(events: list[GoogleCalendarEvent]) -> GoogleCalendarEventSummary:
    all_day_dates: set[str] = set()
    semi_all_day_dates: set[str] = set()
    light_dates: set[str] = set()

    for event in events:
        event_dates = _enumerate_event_dates(event)
        if not event_dates:
            continue
        if is_all_day_event(event):
            all_day_dates.update(event_dates)
            continue
        if is_semi_all_day_event(event):
            semi_all_day_dates.update(event_dates)
            continue
        light_dates.update(event_dates)

    normalized_all_day = sorted(all_day_dates)
    normalized_semi_all_day = sorted(semi_all_day_dates - all_day_dates)
    normalized_light = sorted(light_dates - all_day_dates - semi_all_day_dates)
    return GoogleCalendarEventSummary(
        all_day_dates=normalized_all_day,
        semi_all_day_dates=normalized_semi_all_day,
        light_dates=normalized_light,
    )


def build_daily_blocked_hours(
    events: list[GoogleCalendarEvent],
    *,
    day_start_hour: int = DAY_START_HOUR,
    day_end_hour: int = DAY_END_HOUR,
) -> dict[str, float]:
    blocked_hours: dict[str, float] = {}

    for event in events:
        event_dates = _enumerate_event_dates(event)
        if not event_dates:
            continue

        if event.is_all_day:
            for event_date in event_dates:
                blocked_hours[event_date] = float(day_end_hour - day_start_hour)
            continue

        start_dt = _parse_datetime(event.start)
        end_dt = _parse_datetime(event.end)
        if not start_dt or not end_dt or end_dt <= start_dt:
            continue

        local_start = start_dt.astimezone(JST)
        local_end = end_dt.astimezone(JST)
        current_date = local_start.date()
        final_date = (local_end - timedelta(microseconds=1)).date()

        while current_date <= final_date:
            window_start = datetime.combine(current_date, time(hour=day_start_hour, tzinfo=JST))
            if day_end_hour >= 24:
                window_end = datetime.combine(current_date + timedelta(days=1), time.min, tzinfo=JST)
            else:
                window_end = datetime.combine(current_date, time(hour=day_end_hour, tzinfo=JST))

            overlap_start = max(local_start, window_start)
            overlap_end = min(local_end, window_end)
            if overlap_end > overlap_start:
                overlap_hours = (overlap_end - overlap_start).total_seconds() / 3600
                date_key = current_date.isoformat()
                blocked_hours[date_key] = min(
                    float(day_end_hour - day_start_hour),
                    round(blocked_hours.get(date_key, 0.0) + overlap_hours, 2),
                )
            current_date += timedelta(days=1)

    return blocked_hours


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
