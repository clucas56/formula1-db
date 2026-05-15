-- =============================================================================
-- F1 Data Platform — Schema
-- Auto-loaded by the postgres container on first start.
-- =============================================================================

-- Seasons
CREATE TABLE IF NOT EXISTS seasons (
    season_year INT PRIMARY KEY,
    total_rounds INT
);

-- Circuits
CREATE TABLE IF NOT EXISTS circuits (
    circuit_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100),
    location VARCHAR(100),
    country VARCHAR(100),
    lat DECIMAL(9,6),
    lng DECIMAL(9,6)
);

-- Drivers
CREATE TABLE IF NOT EXISTS drivers (
    driver_id VARCHAR(50) PRIMARY KEY,
    code VARCHAR(3),
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    nationality VARCHAR(50),
    date_of_birth DATE,
    permanent_number INT
);

-- Constructors
CREATE TABLE IF NOT EXISTS constructors (
    constructor_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100),
    nationality VARCHAR(50)
);

-- Races
CREATE TABLE IF NOT EXISTS races (
    race_id SERIAL PRIMARY KEY,
    season_year INT REFERENCES seasons(season_year),
    round INT,
    race_name VARCHAR(100),
    circuit_id VARCHAR(50) REFERENCES circuits(circuit_id),
    date DATE,
    time TIME,
    UNIQUE (season_year, round)
);

-- Race Results
-- NOTE: Original schema.sql had `DEFAULT FALSE.` (period instead of comma) on
-- the fastest_lap line — fixed here.
CREATE TABLE IF NOT EXISTS race_results (
    result_id SERIAL PRIMARY KEY,
    race_id INT REFERENCES races(race_id),
    driver_id VARCHAR(50) REFERENCES drivers(driver_id),
    constructor_id VARCHAR(50) REFERENCES constructors(constructor_id),
    grid_position INT,
    finish_position INT,
    points DECIMAL(4,1),
    laps_completed INT,
    status VARCHAR(50),
    fastest_lap BOOLEAN DEFAULT FALSE,
    UNIQUE (race_id, driver_id)
);

-- Qualifying Results
CREATE TABLE IF NOT EXISTS qualifying_results (
    qualifying_id SERIAL PRIMARY KEY,
    race_id INT REFERENCES races(race_id),
    driver_id VARCHAR(50) REFERENCES drivers(driver_id),
    constructor_id VARCHAR(50) REFERENCES constructors(constructor_id),
    position INT,
    q1_time VARCHAR(20),
    q2_time VARCHAR(20),
    q3_time VARCHAR(20),
    UNIQUE (race_id, driver_id)
);

-- Sprint Results
CREATE TABLE IF NOT EXISTS sprint_results (
    sprint_id SERIAL PRIMARY KEY,
    race_id INT REFERENCES races(race_id),
    driver_id VARCHAR(50) REFERENCES drivers(driver_id),
    constructor_id VARCHAR(50) REFERENCES constructors(constructor_id),
    grid_position INT,
    finish_position INT,
    points DECIMAL(4,1),
    status VARCHAR(50),
    UNIQUE (race_id, driver_id)
);

-- Driver Standings
CREATE TABLE IF NOT EXISTS driver_standings (
    standing_id SERIAL PRIMARY KEY,
    season_year INT REFERENCES seasons(season_year),
    round INT,
    driver_id VARCHAR(50) REFERENCES drivers(driver_id),
    points DECIMAL(6,1),
    position INT,
    wins INT,
    UNIQUE (season_year, round, driver_id)
);

-- Constructor Standings
CREATE TABLE IF NOT EXISTS constructor_standings (
    standing_id SERIAL PRIMARY KEY,
    season_year INT REFERENCES seasons(season_year),
    round INT,
    constructor_id VARCHAR(50) REFERENCES constructors(constructor_id),
    points DECIMAL(6,1),
    position INT,
    wins INT,
    UNIQUE (season_year, round, constructor_id)
);

-- Lap Times
CREATE TABLE IF NOT EXISTS lap_times (
    lap_id SERIAL PRIMARY KEY,
    race_id INT REFERENCES races(race_id),
    driver_id VARCHAR(50) REFERENCES drivers(driver_id),
    lap_number INT,
    lap_time VARCHAR(20),
    sector1 VARCHAR(20),
    sector2 VARCHAR(20),
    sector3 VARCHAR(20),
    is_personal_best BOOLEAN DEFAULT FALSE
);

-- Pit Stops
CREATE TABLE IF NOT EXISTS pit_stops (
    pit_id SERIAL PRIMARY KEY,
    race_id INT REFERENCES races(race_id),
    driver_id VARCHAR(50) REFERENCES drivers(driver_id),
    stop_number INT,
    lap INT,
    duration VARCHAR(20)
);

-- =============================================================================
-- Views — used by the API layer
-- (You'll need to recreate `current_standings` and `last_race_results` from
-- the existing DB; pg_dump --schema-only will give you the definitions.)
-- =============================================================================

-- Placeholder: replace with the actual view definitions from your current DB.
-- Run on the old DB to extract them:
--   pg_dump -U f1user -d f1_data --schema-only --table='*standings*' > views.sql
