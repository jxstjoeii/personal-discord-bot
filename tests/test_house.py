from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.house import FeedError, brief_report, calendar_report, direct_kind, weather_report
from assistant.ics import events_from_ics, events_from_local, merge_events

# A real setting on this PC must not change what the tests expect.
os.environ.pop("WEATHER_LOCATION", None)

PACIFIC = ZoneInfo("America/Los_Angeles")
THURSDAY = datetime(2026, 11, 5, 15, 4, tzinfo=PACIFIC)


WEEKLY = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Studio
DTSTART:20261102T180000
DTEND:20261102T190000
RRULE:FREQ=WEEKLY;BYDAY=MO,TH
END:VEVENT
END:VCALENDAR
"""

TIMED = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Ship
DTSTART:20261105T230000Z
DTEND:20261106T000000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Nope
STATUS:CANCELLED
DTSTART:20261105T150000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Trip
DTSTART;VALUE=DATE:20261105
DTEND;VALUE=DATE:20261107
END:VEVENT
BEGIN:VEVENT
SUMMARY:Skipped Thursday
DTSTART:20261102T180000
RRULE:FREQ=WEEKLY;BYDAY=TH
EXDATE:20261105T180000
END:VEVENT
END:VCALENDAR
"""


class IcsTests(unittest.TestCase):
    def test_timed_weekly_all_day_and_cancelled(self) -> None:
        thursday = events_from_ics(TIMED, THURSDAY.date(), PACIFIC)
        titles = sorted(event.title for event in thursday)
        self.assertEqual(titles, ["Ship", "Trip"])
        ship = next(event for event in thursday if event.title == "Ship")
        self.assertEqual(ship.spoken, "3 PM")
        self.assertTrue(next(event for event in thursday if event.title == "Trip").all_day)

        friday = events_from_ics(TIMED, THURSDAY.date().replace(day=6), PACIFIC)
        self.assertEqual([event.title for event in friday], ["Trip"])
        saturday = events_from_ics(TIMED, THURSDAY.date().replace(day=7), PACIFIC)
        self.assertEqual(saturday, [])

        studio = events_from_ics(WEEKLY, THURSDAY.date(), PACIFIC)
        self.assertEqual(studio[0].spoken, "6 PM")
        self.assertEqual(events_from_ics(WEEKLY, THURSDAY.date().replace(day=6), PACIFIC), [])
        monday = events_from_ics(WEEKLY, THURSDAY.date().replace(day=9), PACIFIC)
        self.assertEqual(monday[0].title, "Studio")

    def test_local_events_and_duplicates(self) -> None:
        data = {
            "events": [
                {"title": "Oil change", "date": "2026-11-05", "time": "15:30"},
                {"title": "Gym", "weekdays": ["Thursday"], "time": "18:00"},
                {"title": "Mom's birthday", "date": "2026-12-03", "allDay": True},
            ]
        }
        local = events_from_local(data, THURSDAY.date())
        self.assertEqual([event.title for event in local], ["Oil change", "Gym"])
        self.assertEqual(local[0].spoken, "3:30 PM")
        repeated = events_from_ics(
            "BEGIN:VEVENT\nSUMMARY:Oil change\nDTSTART:20261105T153000\nEND:VEVENT\n",
            THURSDAY.date(),
            PACIFIC,
        )
        merged = merge_events([local, repeated])
        self.assertEqual([event.title for event in merged], ["Oil change", "Gym"])


class HouseReportTests(unittest.TestCase):
    def test_calendar_weather_and_brief_without_network(self) -> None:
        self.assertEqual(direct_kind("Brief."), "brief")
        self.assertIsNone(direct_kind("brief me on the house"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "calendar").mkdir()
            (root / "calendar" / "events.json").write_text(
                json.dumps({"events": [{"title": "Gym", "date": "2026-11-05", "time": "18:00"}]}),
                encoding="utf-8",
            )
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "location": {
                            "name": "Home",
                            "latitude": 47.0,
                            "longitude": -122.0,
                            "timezone": "America/Los_Angeles",
                            "units": "fahrenheit",
                        },
                        "calendar": {
                            "useLocal": True,
                            "localFile": "calendar/events.json",
                            "icsUrls": ["webcal://example.test/good.ics", "https://example.test/bad.ics"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            def fetch(url: str) -> str:
                if url.endswith("bad.ics"):
                    raise OSError("down")
                if "open-meteo" in url:
                    return json.dumps(
                        {
                            "daily": {
                                "time": ["2026-11-05", "2026-11-06"],
                                "weather_code": [2, 61],
                                "temperature_2m_max": [58.2, 55],
                                "temperature_2m_min": [44.4, 42],
                                "precipitation_probability_max": [20, 70],
                            },
                            "hourly": {
                                "time": ["2026-11-05T15:00"],
                                "temperature_2m": [52.2],
                                "weather_code": [1],
                            },
                        }
                    )
                self.assertEqual(url, "https://example.test/good.ics")
                return "BEGIN:VEVENT\nSUMMARY:Ship\nDTSTART:20261105T230000Z\nEND:VEVENT\n"

            calendar = calendar_report(PACIFIC, THURSDAY, "both", briefing=root, fetch_text=fetch)
            self.assertIn("Gym at 6 PM", calendar)
            self.assertIn("Ship at 3 PM", calendar)
            self.assertIn("Friday, November 6", calendar)
            self.assertIn("Nothing scheduled.", calendar)
            self.assertIn("One calendar feed did not answer.", calendar)

            weather = weather_report(PACIFIC, THURSDAY, "today", briefing=root, fetch_text=fetch)
            self.assertIn("Right now in Home: 52 F and mostly clear.", weather)
            self.assertIn("Today: partly cloudy, high 58 F, low 44 F. Rain chance 20%.", weather)

            brief = brief_report(
                PACIFIC,
                THURSDAY,
                ["#4 Fri, Nov 06, 2026 09:00 AM PST — stretch"],
                briefing=root,
                fetch_text=fetch,
            )
            self.assertIn("Thursday, November 5, 2026, 3:04 PM", brief)
            self.assertIn("stretch", brief)
            self.assertIn("Ship at 3 PM", brief)

    def test_icloud_not_found_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text(
                json.dumps({"calendar": {"useLocal": False, "icsUrls": ["https://p163-caldav.icloud.com/secret"]}}),
                encoding="utf-8",
            )

            def fetch(_url: str) -> str:
                raise FeedError("p163-caldav.icloud.com", 404)

            text = calendar_report(PACIFIC, THURSDAY, "today", briefing=root, fetch_text=fetch)
        self.assertIn("The iCloud calendar link returned Not Found.", text)
        self.assertNotIn("secret", text)


class WeatherBackupTests(unittest.TestCase):
    def _place_fetch(self, url: str) -> str:
        return json.dumps(
            {"results": [{"name": "Puyallup", "admin1": "Washington", "admin2": "Pierce",
                          "country_code": "US", "latitude": 47.19, "longitude": -122.29,
                          "timezone": "America/Los_Angeles"}]}
        )

    def test_weather_gov_steps_in_when_open_meteo_is_down(self) -> None:
        def fetch(url: str) -> str:
            if "geocoding-api" in url:
                return self._place_fetch(url)
            if "api.open-meteo.com" in url:
                raise FeedError("api.open-meteo.com", None, "timed out")
            if "/points/" in url:
                return json.dumps({"properties": {
                    "forecast": "https://api.weather.gov/gridpoints/SEW/1,1/forecast",
                    "forecastHourly": "https://api.weather.gov/gridpoints/SEW/1,1/forecast/hourly",
                }})
            if url.endswith("/hourly"):
                hours = []
                for hour, (temp, words, rain) in enumerate(
                    [(51, "Mostly Cloudy", 10), (52, "Light Rain", 60), (50, "Rain", 80),
                     (49, "Rain", 70), (47, "Cloudy", 30), (45, "Cloudy", 20)], start=15):
                    hours.append({"startTime": f"2026-11-05T{hour:02d}:00:00-08:00", "temperature": temp,
                                  "temperatureUnit": "F", "shortForecast": words,
                                  "probabilityOfPrecipitation": {"value": rain}})
                hours.append({"startTime": "2026-11-06T09:00:00-08:00", "temperature": 48,
                              "temperatureUnit": "F", "shortForecast": "Sunny",
                              "probabilityOfPrecipitation": {"value": 0}})
                return json.dumps({"properties": {"periods": hours}})
            if url.endswith("/forecast"):
                return json.dumps({"properties": {"periods": [
                    {"startTime": "2026-11-05T15:00:00-08:00", "isDaytime": True, "temperature": 56,
                     "temperatureUnit": "F", "shortForecast": "Rain Likely"},
                    {"startTime": "2026-11-06T06:00:00-08:00", "isDaytime": True, "temperature": 54,
                     "temperatureUnit": "F", "shortForecast": "Sunny"},
                ]}})
            raise AssertionError(url)

        text = weather_report(PACIFIC, THURSDAY, "both", briefing=Path("/nowhere"), fetch_text=fetch,
                              location="Puyallup, Pierce County, Washington")
        self.assertIn("Right now in Puyallup, Washington: 51 F and overcast.", text)
        self.assertIn("Today: rainy, high 56 F, low 45 F. Rain chance 80%.", text)
        self.assertIn("Friday: clear, high 54 F, low 48 F.", text)

    def test_both_services_down_says_so(self) -> None:
        def fetch(url: str) -> str:
            if "geocoding-api" in url:
                return self._place_fetch(url)
            raise FeedError("x", None, "down")

        text = weather_report(PACIFIC, THURSDAY, "today", briefing=Path("/nowhere"), fetch_text=fetch,
                              location="Puyallup, WA")
        self.assertIn("The weather service didn't answer just now.", text)

    def test_fetch_retries_over_ipv4(self) -> None:
        from unittest import mock

        import assistant.house as house

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return b"ok"

        with mock.patch.object(house.urllib.request, "urlopen", side_effect=TimeoutError("timed out")), \
                mock.patch.object(house._IPV4, "open", return_value=Reply()) as ipv4:
            self.assertEqual(house._fetch_text("https://api.open-meteo.com/v1/forecast"), "ok")
        ipv4.assert_called_once()

        with mock.patch.object(house.urllib.request, "urlopen", side_effect=TimeoutError("timed out")), \
                mock.patch.object(house._IPV4, "open", side_effect=OSError("no route")):
            with self.assertRaises(FeedError) as caught:
                house._fetch_text("https://api.open-meteo.com/v1/forecast")
        self.assertIn("timed out", caught.exception.reason)
        self.assertIn("no route", caught.exception.reason)


if __name__ == "__main__":
    unittest.main()
