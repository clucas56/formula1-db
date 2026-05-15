"""
/query — natural-language text-to-SQL over the F1 database.

This is the endpoint from the v1 "Next Steps" doc — moved from a vague future
plan to a concrete, working endpoint. Asks Claude to generate a SELECT
statement against the F1 schema, runs it through a read-only connection,
returns the rows.

Safety, in layers (most important first):
  1. Runs on a READ-ONLY Postgres role (ro_pool) — a generated INSERT/UPDATE/
     DELETE physically cannot succeed because the role lacks the privilege.
  2. Reject anything that isn't a single SELECT (regex check below).
  3. Wrap execution in a transaction that always rolls back — even a SELECT
     with a side-effecting function call leaves nothing behind.
  4. Hard cap on returned rows.
"""
import os
import re

from anthropic import Anthropic
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from db import get_ro_conn
from models import QueryRequest, QueryResponse

router = APIRouter(prefix="/query", tags=["query"])

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MAX_ROWS = 200

# The schema is small enough to inline. For a larger schema you'd load this
# from a file or generate it from information_schema.
SCHEMA_DESCRIPTION = """
Tables in the f1_data PostgreSQL database:

seasons(season_year PK, total_rounds)
circuits(circuit_id PK, name, location, country, lat, lng)
drivers(driver_id PK, code, first_name, last_name, nationality, date_of_birth, permanent_number)
constructors(constructor_id PK, name, nationality)
races(race_id PK, season_year FK->seasons, round, race_name, circuit_id FK->circuits, date, time)
race_results(result_id PK, race_id FK, driver_id FK, constructor_id FK,
             grid_position, finish_position, points, laps_completed, status, fastest_lap)
qualifying_results(qualifying_id PK, race_id FK, driver_id FK, constructor_id FK,
                   position, q1_time, q2_time, q3_time)
sprint_results(sprint_id PK, race_id FK, driver_id FK, constructor_id FK,
               grid_position, finish_position, points, status)
driver_standings(standing_id PK, season_year FK, round, driver_id FK,
                 points, position, wins)
constructor_standings(standing_id PK, season_year FK, round, constructor_id FK,
                      points, position, wins)

Useful views:
  current_standings, last_race_results

Notes:
  - finish_position is NULL for DNFs
  - season_year covers 1950 through the current year
  - Always use joins to get human-readable names (drivers.first_name + last_name,
    constructors.name) instead of returning IDs
"""

SYSTEM_PROMPT = f"""You are a PostgreSQL expert. Generate a single read-only SELECT
query to answer the user's question about Formula 1 data.

{SCHEMA_DESCRIPTION}

Rules:
- Return ONLY the SQL query, no explanation, no markdown fences
- SELECT only — no INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, etc.
- Always LIMIT to {MAX_ROWS} rows or fewer
- Use joins to return readable names (driver name, constructor name) not IDs
- If the question is ambiguous about a season, use the most recent one
"""


def is_safe_select(sql: str) -> bool:
    """
    Defense-in-depth check. The read-only DB role is the primary safeguard —
    this is a second line of defense, not the only one.
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped.lower().startswith("select"):
        return False
    forbidden = r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke)\b"
    if re.search(forbidden, stripped, re.IGNORECASE):
        return False
    if ";" in stripped:  # No statement chaining
        return False
    return True


@router.post("", response_model=QueryResponse)
def text_to_sql(req: QueryRequest):
    # 1. Ask Claude for SQL
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": req.question}],
    )
    sql = response.content[0].text.strip()

    # Strip markdown fences if Claude wrapped it despite instructions
    sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql, flags=re.MULTILINE).strip()

    # 2. Safety check (layer 2 — the read-only role is layer 1)
    if not is_safe_select(sql):
        raise HTTPException(
            status_code=400,
            detail=f"Generated SQL failed safety check: {sql}",
        )

    # 3. Execute on the READ-ONLY pool, with rollback
    with get_ro_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(sql)
                rows = cur.fetchmany(MAX_ROWS)
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Query failed: {e}")
            finally:
                # Roll back even on success — guarantees no side effects
                conn.rollback()

    return QueryResponse(
        question=req.question,
        sql=sql,
        rows=[dict(r) for r in rows],
        row_count=len(rows),
    )
