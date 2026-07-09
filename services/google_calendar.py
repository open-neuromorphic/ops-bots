import logging
from typing import Optional, Dict, Any
import asyncio
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import config
from utils import google_api_utils

logger = logging.getLogger(__name__)


def create_calendar_event(
    title: str,
    description: str,
    start_time_iso: str,
    end_time_iso: str,
    location: Optional[str] = None
) -> Dict[str, Any]:
    """Creates an event on Google Calendar and returns the created event metadata."""
    creds = google_api_utils.get_credentials(config.CALENDAR_TOKEN_FILE, config.CALENDAR_SCOPES)
    if not creds or not creds.valid:
        raise RuntimeError("Google Calendar credentials missing or invalid. Please run 'python interactive_setup.py' option 3.")

    service = build("calendar", "v3", credentials=creds)

    event_body = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": start_time_iso,
        },
        "end": {
            "dateTime": end_time_iso,
        },
    }
    if location:
        event_body["location"] = location

    try:
        created_event = service.events().insert(
            calendarId=config.CALENDAR_ID,
            body=event_body
        ).execute()
        logger.info(f"Successfully created Google Calendar event: {created_event.get('htmlLink')}")
        return created_event
    except HttpError as err:
        logger.error(f"Google Calendar API error: {err}")
        raise err