import os
import hmac
import hashlib
import subprocess
import psycopg2
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

    cursor.close()
    conn.close()

    return render_template('index.html', 
                           standings=standings, 
                           last_race=last_race,
                           constructor_standings=constructor_standings)

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
