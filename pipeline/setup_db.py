import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def setup_database():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

    cursor = conn.cursor()

    # Read and execute schema
    with open("database/schema.sql", "r") as f:
        cursor.execute(f.read())

    conn.commit()
    cursor.close()
    conn.close()
    print("Database schema created successfully!")

if __name__ == "__main__":
    setup_database()
