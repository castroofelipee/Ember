from datetime import date

import httpx
from sqlalchemy import func, select

from ember.models import Calendar, Event, Workspace
from ember.services import holidays
from ember.services.holidays import HolidayRecord, disable_holidays, sync_holidays


async def test_calendarific_parses_holidays(monkeypatch) -> None:
    monkeypatch.setitem(holidays.env, "CALENDARIFIC_API_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["country"] == "BR"
        assert request.url.params["location"] == "br-ce"
        return httpx.Response(
            200,
            json={
                "response": {
                    "holidays": [
                        {
                            "uuid": "holiday-1",
                            "name": "Independência do Brasil",
                            "description": "Feriado nacional",
                            "date": {"iso": "2026-09-07"},
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        records = await holidays._calendarific_holidays(client, 2026, "BR", "CE")

    assert records == [
        HolidayRecord(
            external_id="calendarific:holiday-1",
            name="Independência do Brasil",
            day=date(2026, 9, 7),
            description="Feriado nacional",
        )
    ]


async def test_openholidays_parses_holidays() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["countryIsoCode"] == "BR"
        assert request.url.params["subdivisionCode"] == "BR-CE"
        assert request.url.params["validFrom"] == "2026-01-01"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "holiday-2",
                    "name": [
                        {"language": "EN", "text": "Saint Joseph's Day"},
                        {"language": "PT", "text": "Dia de São José"},
                    ],
                    "startDate": "2026-03-19",
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        records = await holidays._openholidays_holidays(client, 2026, "BR", "CE")

    assert records[0].external_id == "openholidays:holiday-2"
    assert records[0].name == "Dia de São José"
    assert records[0].day == date(2026, 3, 19)


async def test_openholidays_falls_back_to_nager() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "openholidaysapi.org":
            return httpx.Response(200, json=[])
        assert request.url.path == "/api/v3/PublicHolidays/2026/BR"
        return httpx.Response(
            200,
            json=[
                {
                    "date": "2026-09-07",
                    "localName": "Dia da Independência",
                    "name": "Independence Day",
                    "global": True,
                    "counties": None,
                },
                {
                    "date": "2026-07-09",
                    "localName": "Revolução Constitucionalista",
                    "name": "Constitutionalist Revolution",
                    "global": False,
                    "counties": ["BR-SP"],
                },
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        records = await holidays._openholidays_holidays(client, 2026, "BR", "CE")

    assert len(records) == 1
    assert records[0].external_id.startswith("nager:")
    assert records[0].name == "Dia da Independência"
    assert records[0].day == date(2026, 9, 7)


async def test_sync_holidays_is_idempotent(db_session, monkeypatch) -> None:
    workspace = Workspace(
        name="Home",
        holiday_enabled=True,
        holiday_provider="openholidays",
        holiday_country="BR",
        holiday_region="CE",
        holiday_city="Fortaleza",
    )
    db_session.add(workspace)
    await db_session.flush()

    async def fake_holidays(client, year, country, region):
        return [
            HolidayRecord(
                external_id=f"openholidays:{year}",
                name=f"Holiday {year}",
                day=date(year, 1, 1),
                description=None,
            )
        ]

    monkeypatch.setattr(holidays, "_openholidays_holidays", fake_holidays)
    calendar, count = await sync_holidays(db_session, workspace, "America/Fortaleza")
    await sync_holidays(db_session, workspace, "America/Fortaleza")

    event_count = (
        await db_session.execute(
            select(func.count(Event.id)).where(Event.calendar_id == calendar.id)
        )
    ).scalar_one()
    events = (
        (await db_session.execute(select(Event).where(Event.calendar_id == calendar.id)))
        .scalars()
        .all()
    )
    assert count == 2
    assert event_count == 2
    assert all(event.all_day for event in events)
    assert calendar.color == "#16a34a"

    await disable_holidays(db_session, workspace)
    remaining = await db_session.scalar(
        select(func.count(Calendar.id)).where(Calendar.workspace_id == workspace.id)
    )
    assert remaining == 0
