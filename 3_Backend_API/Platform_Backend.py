import os
import datetime
import psycopg2
import psycopg2.extras
import uuid
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables from .env file for local testing
load_dotenv()

app = Flask(__name__)

# --- Configuration ---
# This will be set via Environment Variables on Render
SUPER_ADMIN_KEY = os.environ.get("FLASK_SUPER_ADMIN_KEY", "q/9^}H=W:HJ;%}t>$YR$g1[")

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    # On Render, this single DATABASE_URL is provided in the environment
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("FATAL ERROR: DATABASE_URL environment variable is not set.")
    conn = psycopg2.connect(db_url)
    return conn

def setup_database():
    """Initializes the database schema for PostgreSQL."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS agencies (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    api_key TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id SERIAL PRIMARY KEY,
                    agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
                    total_licenses INTEGER NOT NULL DEFAULT 25,
                    UNIQUE(agency_id)
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS versions (
                    id SERIAL PRIMARY KEY,
                    agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
                    version_number TEXT NOT NULL,
                    release_date TIMESTAMPTZ DEFAULT NOW(),
                    download_url TEXT NOT NULL,
                    is_latest BOOLEAN NOT NULL DEFAULT FALSE,
                    UNIQUE(agency_id, version_number)
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS licenses (
                    id SERIAL PRIMARY KEY,
                    agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
                    device_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    hostname TEXT,
                    location TEXT,
                    operating_system TEXT,
                    activated_at TIMESTAMPTZ DEFAULT NOW(),
                    status TEXT NOT NULL DEFAULT 'active',
                    UNIQUE(agency_id, device_id)
                );
            ''')
        conn.commit()
        print("Database setup for PostgreSQL support is complete.")
    finally:
        conn.close()

# This will run automatically when the web app starts on Render
setup_database()

# --- All API routes are the same and will work correctly ---
# ... (all the @app.route functions from before) ...

@app.route('/admin/create_agency', methods=['POST'])
def create_agency():
    data = request.get_json()
    if data.get('super_admin_key') != SUPER_ADMIN_KEY:
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    agency_name = data.get('agency_name')
    if not agency_name:
        return jsonify({"success": False, "message": "Agency name is required."}), 400

    new_api_key = str(uuid.uuid4())
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("INSERT INTO agencies (name, api_key) VALUES (%s, %s) RETURNING *;", (agency_name, new_api_key))
        agency = cur.fetchone()
        cur.execute("INSERT INTO settings (agency_id, total_licenses) VALUES (%s, %s);", (agency['id'], 25))
        conn.commit()
        return jsonify({"success": True, "message": f"Agency '{agency_name}' created.", "agency": agency}), 201
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"success": False, "message": "An agency with this name already exists."}), 409
    except Exception as e:
        conn.rollback()
        print(f"ERROR in /admin/create_agency: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close()
        conn.close()

# ... include all other @app.route functions here ...

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
