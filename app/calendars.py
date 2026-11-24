import threading
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

from app.config import Settings

SLOT_HOURS = (10, 14, 16)  # UTC
SCOPES = ["https://www.googleapis.com/auth/calendar"]
MEETING_MINUTES = 30


class SlotTakenError(Exception):
    pass


class Calendar(Protocol):
    def free_slots(self, n: int = 3) -> list[str]: ...

    def book(self, slot_iso: str, name: str, email: str) -> str: ...


def _parse_slot(slot_iso: str) -> datetime:
    """Parse to an aware UTC datetime; naive or malformed input -> ValueError."""
    dt = datetime.fromisoformat(slot_iso)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("slot must include a timezone offset")
    return dt.astimezone(timezone.utc)


def _grid(start_day: date) -> Iterator[datetime]:
    """Endless ascending weekday slots (10/14/16 UTC) from start_day."""
    day = start_day
    while True:
        if day.weekday() < 5:
            for h in SLOT_HOURS:
                yield datetime.combine(day, time(h), tzinfo=timezone.utc)
        day += timedelta(days=1)


def _candidates(now: datetime, limit: int) -> list[datetime]:
    first_day = now.astimezone(timezone.utc).date() + timedelta(days=1)
    out = []
    for slot in _grid(first_day):
        out.append(slot)
        if len(out) >= limit:
            return out
    return out  # unreachable


class FakeCalendar:
    HORIZON = 60  # candidate slots considered (~4 weeks)

    def __init__(self, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._now = now
        self._booked: set[str] = set()
        self._lock = threading.Lock()

    def free_slots(self, n: int = 3) -> list[str]:
        with self._lock:
            booked = set(self._booked)
        free = [s.isoformat() for s in _candidates(self._now(), self.HORIZON)]
        return [s for s in free if s not in booked][:n]

    def book(self, slot_iso: str, name: str, email: str) -> str:
        slot = _parse_slot(slot_iso).isoformat()
        with self._lock:
            if slot not in {s.isoformat() for s in _candidates(self._now(), self.HORIZON)}:
                raise ValueError("not an offered slot")
            if slot in self._booked:
                raise SlotTakenError(slot)
            self._booked.add(slot)
        return f"Booked {slot} for {name}"


class GoogleCalendar:
    """Service-account backed calendar. Google libraries are imported lazily."""

    def __init__(self, credentials_file: str, calendar_id: str = "primary"):
        self._credentials_file = credentials_file
        self._calendar_id = calendar_id

    def _service(self):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            self._credentials_file, scopes=SCOPES
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def _busy(self, service, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": self._calendar_id}],
        }
        resp = service.freebusy().query(body=body).execute()
        busy = resp["calendars"][self._calendar_id]["busy"]
        return [
            (_parse_slot(b["start"].replace("Z", "+00:00")), _parse_slot(b["end"].replace("Z", "+00:00")))
            for b in busy
        ]

    @staticmethod
    def _overlaps(slot: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
        end = slot + timedelta(minutes=MEETING_MINUTES)
        return any(slot < b_end and b_start < end for b_start, b_end in busy)

    def free_slots(self, n: int = 3) -> list[str]:
        service = self._service()
        cands = _candidates(datetime.now(timezone.utc), 60)
        busy = self._busy(service, cands[0], cands[-1] + timedelta(minutes=MEETING_MINUTES))
        return [s.isoformat() for s in cands if not self._overlaps(s, busy)][:n]

    def book(self, slot_iso: str, name: str, email: str) -> str:
        slot = _parse_slot(slot_iso)
        service = self._service()
        end = slot + timedelta(minutes=MEETING_MINUTES)
        if self._overlaps(slot, self._busy(service, slot, end)):
            raise SlotTakenError(slot.isoformat())
        event = {
            "summary": f"Intro call with {name}",
            "description": f"Attendee: {name} <{email}>",
            "start": {"dateTime": slot.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        service.events().insert(calendarId=self._calendar_id, body=event).execute()
        return f"Booked {slot.isoformat()} for {name}"


def get_calendar(s: Settings) -> Calendar:
    if s.google_credentials_file:
        return GoogleCalendar(s.google_credentials_file)
    return FakeCalendar()
