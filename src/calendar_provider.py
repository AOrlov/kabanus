from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import tzlocal
from src.config import GOOGLE_CALENDAR_ID, GOOGLE_CREDENTIALS_PATH

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

class CalendarProvider:
    def __init__(self):
        self.service = None
        self._authenticate()

    def _authenticate(self):
        try:
            credentials = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
            )
            self.service = build('calendar', 'v3', credentials=credentials)
        except Exception as e:
            raise Exception(f"Failed to authenticate with Google Calendar: {str(e)}")

    def create_event(self, title, start_time, end_time=None, location=None, description=None):
        if not end_time:
            end_time = start_time + timedelta(hours=1)

        # Get system's local timezone
        local_tz = tzlocal.get_localzone()
        
        # If the datetime is naive (no timezone info), replace its timezone
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=local_tz)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=local_tz)

        event = {
            'summary': title,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': str(local_tz),
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': str(local_tz),
            },
        }

        if location:
            event['location'] = location
        if description:
            event['description'] = description

        try:
            event = self.service.events().insert(
                calendarId=GOOGLE_CALENDAR_ID,
                body=event
            ).execute()
            return event
        except Exception as e:
            raise Exception(f"Failed to create calendar event: {str(e)}") 