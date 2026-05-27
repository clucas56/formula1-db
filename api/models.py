from datetime import date
from decimal import Decimal
from pydantic import BaseModel


class DriverStanding(BaseModel):
    position: int
    driver_name: str
    constructor_name: str | None = None
    points: Decimal
    wins: int


class RaceResult(BaseModel):
    finish_position: int | None
    driver_name: str
    constructor_name: str
    grid_position: int | None
    points: Decimal | None
    status: str | None


class LastRaceSummary(BaseModel):
    race_name: str
    season_year: int
    round: int
    date: date | None
    results: list[RaceResult]
