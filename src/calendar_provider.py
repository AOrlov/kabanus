from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import tzlocal
from src.config import GOOGLE_CALENDAR_ID, GOOGLE_CREDENTIALS_PATH, GOOGLE_CREDENTIALS_JSON
import os
import json

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

class CalendarProvider:
    def __init__(self):
        self.service = None
        self._authenticate()

    def _authenticate(self):
        try:
            if os.getenv('GOOGLE_CREDENTIALS_PATH'):
                credentials = service_account.Credentials.from_service_account_file(
                    GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
                )
            elif os.getenv('GOOGLE_CREDENTIALS_JSON'):
                credentials_info = json.loads(GOOGLE_CREDENTIALS_JSON)
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_info, scopes=SCOPES
                )
            self.service = build('calendar', 'v3', credentials=credentials)
        except Exception as e:
            raise Exception(f"Failed to authenticate with Google Calendar: {str(e)}")

    def create_event(self, title, is_all_day, start_time, end_time=None, location=None, description=None):
        event = {
            'summary': title,
        }

        try:
            print(f"Debug - Input parameters:")
            print(f"title: {title}")
            print(f"is_all_day: {is_all_day}")
            print(f"start_time: {start_time} (type: {type(start_time)})")
            print(f"end_time: {end_time} (type: {type(end_time) if end_time else None})")
            print(f"location: {location}")
            print(f"description: {description}")

            if is_all_day:
                # For all-day events, ensure we have a date object
                if isinstance(start_time, datetime):
                    start_date = start_time.date()
                else:
                    start_date = start_time
                
                # Format the date as YYYY-MM-DD
                event['start'] = {
                    'date': start_date.strftime('%Y-%m-%d'),
                }
                event['end'] = {
                    'date': start_date.strftime('%Y-%m-%d'),
                }
            else:
                if not end_time:
                    end_time = start_time + timedelta(hours=1)
                
                # Get system's local timezone
                local_tz = tzlocal.get_localzone()
                
                # If the datetime is naive (no timezone info), replace its timezone
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=local_tz)
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=local_tz)

                # Convert to UTC for Google Calendar API
                start_time_utc = start_time.astimezone(tz=timezone.utc)
                end_time_utc = end_time.astimezone(tz=timezone.utc)

                event['start'] = {
                    'dateTime': start_time_utc.isoformat(),
                    'timeZone': str(tzlocal.get_localzone())
                }
                event['end'] = {
                    'dateTime': end_time_utc.isoformat(),
                    'timeZone': str(tzlocal.get_localzone())
                }

            if location:
                event['location'] = location
            if description:
                event['description'] = description

            # Log the event data for debugging
            print(f"Debug - Final event data being sent to Google Calendar:")
            print(json.dumps(event, indent=2))

            event = self.service.events().insert(
                calendarId=GOOGLE_CALENDAR_ID,
                body=event
            ).execute()
            return event
        except Exception as e:
            error_msg = f"Failed to create calendar event: {str(e)}"
            if hasattr(e, 'content'):
                error_msg += f"\nError details: {e.content}"
            raise Exception(error_msg) 