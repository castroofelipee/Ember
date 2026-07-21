import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.config import env
from ember.models import Calendar, Event, Workspace


HOLIDAY_CALENDAR_SOURCE = "holidays"
HOLIDAY_CALENDAR_COLOR = "#16a34a"


class HolidaySyncError(Exception):
    pass


@dataclass(frozen=True)
class HolidayRecord:
    external_id: str
    name: str
    day: date
    description: str | None


def _external_id(provider: str, item: dict, day: date, name: str) -> str:
    identifier = item.get("id") or item.get("uuid")
    if identifier:
        return f"{provider}:{identifier}"
    digest = hashlib.sha256(f"{provider}:{day.isoformat()}:{name}".encode()).hexdigest()[:32]
    return f"{provider}:{digest}"


async def _calendarific_holidays(
    client: httpx.AsyncClient,
    year: int,
    country: str,
    region: str,
) -> list[HolidayRecord]:
    api_key = env["CALENDARIFIC_API_KEY"]
    if not api_key:
        raise HolidaySyncError("CALENDARIFIC_API_KEY is not configured")
    params = {
        "api_key": api_key,
        "country": country,
        "year": year,
        "type": "national,local",
    }
    if region:
        params["location"] = f"{country}-{region}".lower()
    response = await client.get("https://calendarific.com/api/v2/holidays", params=params)
    if response.status_code != 200:
        raise HolidaySyncError(f"Calendarific returned HTTP {response.status_code}")
    body = response.json()
    items = body.get("response", {}).get("holidays", [])
    records: list[HolidayRecord] = []
    for item in items:
        name = item.get("name")
        iso = item.get("date", {}).get("iso", "")[:10]
        if not isinstance(name, str) or not iso:
            continue
        holiday_day = date.fromisoformat(iso)
        records.append(
            HolidayRecord(
                external_id=_external_id("calendarific", item, holiday_day, name),
                name=name,
                day=holiday_day,
                description=item.get("description"),
            )
        )
    return records


def _localized_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    names = [item for item in value if isinstance(item, dict)]
    for language in ("PT", "EN"):
        match = next(
            (item for item in names if str(item.get("language", "")).upper() == language),
            None,
        )
        if match and isinstance(match.get("text"), str):
            return match["text"]
    if names and isinstance(names[0].get("text"), str):
        return names[0]["text"]
    return None


async def _openholidays_holidays(
    client: httpx.AsyncClient,
    year: int,
    country: str,
    region: str,
) -> list[HolidayRecord]:
    params = {
        "countryIsoCode": country,
        "languageIsoCode": "PT" if country == "BR" else "EN",
        "validFrom": f"{year}-01-01",
        "validTo": f"{year}-12-31",
    }
    if region:
        params["subdivisionCode"] = (
            region if region.startswith(f"{country}-") else f"{country}-{region}"
        )
    response = await client.get(
        "https://openholidaysapi.org/PublicHolidays",
        params=params,
        headers={"Accept": "application/json"},
    )
    if response.status_code != 200:
        raise HolidaySyncError(f"OpenHolidays returned HTTP {response.status_code}")
    items = response.json()
    if not isinstance(items, list):
        raise HolidaySyncError("OpenHolidays returned an invalid response")
    records: list[HolidayRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _localized_name(item.get("name"))
        iso = str(item.get("startDate") or item.get("date") or "")[:10]
        if not name or not iso:
            continue
        holiday_day = date.fromisoformat(iso)
        records.append(
            HolidayRecord(
                external_id=_external_id("openholidays", item, holiday_day, name),
                name=name,
                day=holiday_day,
                description=None,
            )
        )
    if records:
        return records
    return await _nager_holidays(client, year, country, region)


async def _nager_holidays(
    client: httpx.AsyncClient,
    year: int,
    country: str,
    region: str,
) -> list[HolidayRecord]:
    response = await client.get(
        f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}",
        headers={"Accept": "application/json"},
    )
    if response.status_code != 200:
        raise HolidaySyncError(f"Nager.Date returned HTTP {response.status_code}")
    items = response.json()
    if not isinstance(items, list):
        raise HolidaySyncError("Nager.Date returned an invalid response")
    subdivision = region if region.startswith(f"{country}-") else f"{country}-{region}"
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        counties = item.get("counties")
        if not item.get("global") and (not region or subdivision not in (counties or [])):
            continue
        name = item.get("localName") or item.get("name")
        iso = str(item.get("date") or "")[:10]
        if not isinstance(name, str) or not iso:
            continue
        holiday_day = date.fromisoformat(iso)
        records.append(
            HolidayRecord(
                external_id=_external_id("nager", item, holiday_day, name),
                name=name,
                day=holiday_day,
                description=None,
            )
        )
    return records


async def get_holiday_calendar(session: AsyncSession, workspace_id: uuid.UUID) -> Calendar | None:
    return (
        await session.execute(
            select(Calendar).where(
                Calendar.workspace_id == workspace_id,
                Calendar.source == HOLIDAY_CALENDAR_SOURCE,
            )
        )
    ).scalar_one_or_none()


async def disable_holidays(session: AsyncSession, workspace: Workspace) -> None:
    calendar = await get_holiday_calendar(session, workspace.id)
    if calendar is not None:
        await session.delete(calendar)
    workspace.holiday_enabled = False
    await session.flush()


async def sync_holidays(
    session: AsyncSession,
    workspace: Workspace,
    timezone: str,
) -> tuple[Calendar, int]:
    provider = workspace.holiday_provider or "openholidays"
    country = workspace.holiday_country or "BR"
    region = workspace.holiday_region or ""
    city = workspace.holiday_city or ""
    current_year = datetime.now(ZoneInfo(timezone)).year
    timeout = env["HOLIDAY_HTTP_TIMEOUT_SECONDS"]
    async with httpx.AsyncClient(timeout=timeout) as client:
        records: list[HolidayRecord] = []
        for year in (current_year, current_year + 1):
            if provider == "calendarific":
                records.extend(await _calendarific_holidays(client, year, country, region))
            else:
                records.extend(await _openholidays_holidays(client, year, country, region))

    calendar = await get_holiday_calendar(session, workspace.id)
    location = ", ".join(part for part in (city, region, country) if part)
    if calendar is None:
        calendar = Calendar(
            workspace_id=workspace.id,
            name=f"Holidays — {location}",
            color=HOLIDAY_CALENDAR_COLOR,
            source=HOLIDAY_CALENDAR_SOURCE,
        )
        session.add(calendar)
        await session.flush()
    else:
        calendar.name = f"Holidays — {location}"

    zone = ZoneInfo(timezone)
    start_bound = datetime(current_year, 1, 1, tzinfo=zone)
    end_bound = datetime(current_year + 2, 1, 1, tzinfo=zone)
    existing = (
        (
            await session.execute(
                select(Event).where(
                    Event.calendar_id == calendar.id,
                    Event.start_at >= start_bound,
                    Event.start_at < end_bound,
                )
            )
        )
        .scalars()
        .all()
    )
    existing_by_id = {event.external_id: event for event in existing if event.external_id}
    incoming_ids: set[str] = set()
    for record in records:
        incoming_ids.add(record.external_id)
        start_at = datetime.combine(record.day, time.min, tzinfo=zone)
        end_at = datetime.combine(record.day + timedelta(days=1), time.min, tzinfo=zone)
        event = existing_by_id.get(record.external_id)
        if event is None:
            session.add(
                Event(
                    calendar_id=calendar.id,
                    title=record.name,
                    description=record.description,
                    start_at=start_at,
                    end_at=end_at,
                    all_day=True,
                    external_id=record.external_id,
                )
            )
        else:
            event.title = record.name
            event.description = record.description
            event.start_at = start_at
            event.end_at = end_at
            event.all_day = True
    stale_ids = [event.id for event in existing if event.external_id not in incoming_ids]
    if stale_ids:
        await session.execute(delete(Event).where(Event.id.in_(stale_ids)))
    await session.flush()
    return calendar, len(records)
