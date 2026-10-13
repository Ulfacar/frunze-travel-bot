"""Явно выбранные версии календаря; без данных года не считаем по обычной неделе."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib

from .deadline_schema import CALENDARS
from .review import canonical
from .validation import InvalidDocument, check_tree, schema_errors


class CalendarError(ValueError):
    def __init__(self, code, year=None):
        self.code, self.year = code, year
        super().__init__(code)


class WorkCalendars:
    def __init__(self, document):
        try:
            check_tree(document)
        except InvalidDocument:
            raise CalendarError("invalid_calendar_document") from None
        if schema_errors(document, CALENDARS):
            raise CalendarError("invalid_calendar_document")
        calendars = deepcopy(document["calendars"])
        self._years = {}
        for calendar in calendars:
            year = calendar["year"] = int(calendar["year"])
            calendar["version"] = int(calendar["version"])
            calendar["week_rest_days"] = sorted(int(v) for v in calendar["week_rest_days"])
            if year in self._years:
                raise CalendarError("duplicate_calendar_year")
            if (calendar["completeness"] == "provisional") != (calendar["provisional_note"] is not None):
                raise CalendarError("invalid_provisional_note")
            days = {}
            for row in calendar["days"]:
                day = date.fromisoformat(row["date"])
                if day.year != year:
                    raise CalendarError("override_outside_calendar_year")
                if row["date"] in days:
                    raise CalendarError("duplicate_calendar_day")
                if (row["kind"] == "transfer_working" and row["is_working"] is not True) or (
                        row["kind"] in {"public_holiday", "floating_holiday", "transfer_rest"} and row["is_working"] is not False):
                    raise CalendarError("calendar_day_kind_conflict")
                days[row["date"]] = row
            calendar["days"].sort(key=lambda r: r["date"])
            fingerprint = hashlib.sha256(canonical(calendar).encode("utf-8")).hexdigest()
            self._years[year] = (calendar, days, fingerprint)
        self._hash = hashlib.sha256(canonical({"format": "kg-work-calendars/1",
            "calendars": [self._years[y][0] for y in sorted(self._years)]}).encode("utf-8")).hexdigest()

    @property
    def content_hash(self):
        return self._hash

    def describe(self):
        return [{"year": y, "version": c["version"], "status": c["status"],
                 "completeness": c["completeness"], "source_ref": c["source_ref"], "hash": h}
                for y, (c, _, h) in sorted(self._years.items())]

    def export(self):
        """Owned, canonical document for immutable storage and later replay."""
        return {"format": "kg-work-calendars/1",
                "calendars": [deepcopy(self._years[y][0]) for y in sorted(self._years)]}

    def day(self, value: date):
        if type(value) is not date:
            raise CalendarError("invalid_calendar_date")
        if value.year not in self._years:
            raise CalendarError("calendar_missing", value.year)
        calendar, days, fingerprint = self._years[value.year]
        if calendar["completeness"] != "complete":
            raise CalendarError("calendar_provisional", value.year)
        override = days.get(value.isoformat())
        return {"date": value.isoformat(), "is_working": override["is_working"] if override else
                value.isoweekday() not in calendar["week_rest_days"],
                "basis": override["kind"] if override else "explicit_week_pattern",
                "source_ref": override["source_ref"] if override else calendar["source_ref"],
                "calendar_year": value.year, "calendar_version": calendar["version"], "calendar_hash": fingerprint}
