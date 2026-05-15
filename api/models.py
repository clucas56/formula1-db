"""
Pydantic models — request/response shapes for the API.

These do three things automatically:
  1. Validate data (FastAPI returns 422 if a request doesn't match)
  2. Generate OpenAPI/Swagger docs at /docs
  3. Serialize DB rows to JSON
"""
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


class QueryRequest(BaseModel):
    """Natural-language question for the text-to-SQL endpoint."""
    question: str


class QueryResponse(BaseModel):
    question: str
    sql: str
    rows: list[dict]
    row_count: int
