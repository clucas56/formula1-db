import os
import hmac
import hashlib
import subprocess
import psycopg2
import markdown
from flask import Flask, render_template, request, abort
from dotenv import load_dotenv
from pathlib import Path

# ------------------------------------------------
# Configuration
# ------------------------------------------------

load_dotenv(Path(__file__).parent / '.env')

app = Flask(__name__)

# ------------------------------------------------
# Database connection
# ------------------------------------------------

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

# ------------------------------------------------
# Routes
# ------------------------------------------------

@app.route('/')
def index():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM current_standings;")
    standings = cursor.fetchall()

    cursor.execute("SELECT * FROM last_race_results;")
    last_race = cursor.fetchall()

    cursor.execute("SELECT * FROM current_constructor_standings;")
    constructor_standings = cursor.fetchall()

    cursor.execute("SELECT * FROM season_races ORDER BY round;")
    season_races = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('index.html',
                           standings=standings,
                           last_race=last_race,
                           constructor_standings=constructor_standings,
                           season_races=season_races)
    
@app.route('/race/<int:season>/<int:round_num>')
def race(season, round_num):
    conn = get_connection()
    cursor = conn.cursor()

    # Get race details and results
    cursor.execute("""
        SELECT * FROM race_results_detail
        WHERE season_year = %s AND round = %s
        ORDER BY finish_position;
    """, (season, round_num))
    results = cursor.fetchall()

    # Get all races in the season for the navigation selector
    cursor.execute("""
        SELECT * FROM season_races
        ORDER BY round;
    """)
    season_races = cursor.fetchall()

    cursor.close()
    conn.close()

    if not results:
        return "Race not found", 404

    return render_template('race.html', 
                           results=results, 
                           season_races=season_races,
                           season=season,
                           round_num=round_num)    
    
@app.route('/seasons')
def seasons():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT season_year, total_rounds FROM seasons ORDER BY season_year DESC;")
    seasons_list = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('seasons.html', seasons=seasons_list)

@app.route('/seasons/<int:year>')
def season_detail(year):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT round, race_name, date
        FROM races
        WHERE season_year = %s
        ORDER BY round;
    """, (year,))
    races = cursor.fetchall()
    cursor.close()
    conn.close()
    if not races:
        return "Season not found", 404
    return render_template('season_detail.html', races=races, year=year)

@app.route('/drivers')
def drivers():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT driver_id, first_name, last_name, nationality
        FROM drivers
        ORDER BY last_name, first_name;
    """)
    drivers_list = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('drivers.html', drivers=drivers_list)

@app.route('/drivers/<driver_id>')
def driver_detail(driver_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT driver_id, first_name, last_name, nationality
        FROM drivers WHERE driver_id = %s;
    """, (driver_id,))
    driver = cursor.fetchone()

    if not driver:
        cursor.close()
        conn.close()
        return "Driver not found", 404

    cursor.execute("""
        SELECT
            COUNT(*) as races,
            SUM(CASE WHEN finish_position = 1 THEN 1 ELSE 0 END) as wins,
            COALESCE(SUM(points), 0) as total_points
        FROM race_results
        WHERE driver_id = %s;
    """, (driver_id,))
    stats = cursor.fetchone()

    cursor.execute("""
        SELECT DISTINCT r.season_year
        FROM race_results rr
        JOIN races r ON rr.race_id = r.race_id
        WHERE rr.driver_id = %s
        ORDER BY r.season_year DESC;
    """, (driver_id,))
    active_seasons = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()
    return render_template('driver_detail.html', driver=driver, stats=stats, active_seasons=active_seasons)

@app.route('/circuits')
def circuits():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT circuit_id, name, country, lat, lng
        FROM circuits
        ORDER BY country, name;
    """)
    circuits_list = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('circuits.html', circuits=circuits_list)

@app.route('/docs')
def docs():
    doc_path = Path(__file__).parent.parent / 'DOCUMENTATION.md'
    with open(doc_path, 'r') as f:
        content = f.read()
    html_content = markdown.markdown(content, extensions=['tables', 'fenced_code'])
    return render_template('docs.html', content=html_content)

@app.route('/webhook', methods=['POST'])
def webhook():
    # Verify the request is from GitHub
    secret = os.getenv("WEBHOOK_SECRET").encode()
    signature = request.headers.get("X-Hub-Signature-256", "")
    body = request.get_data()

    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, signature):
        abort(403)

    # Pull latest code
    subprocess.run(["/usr/bin/git", "-C", "/var/www/formula1-db", "pull"], check=True)

    # Restart service in background so we can return response first
    subprocess.Popen(["/usr/bin/sudo", "/bin/systemctl", "restart", "f1-app"])

    return "Deployed", 200


# ------------------------------------------------
# Entry point
# ------------------------------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
