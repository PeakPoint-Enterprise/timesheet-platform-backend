import os
import datetime
import pymysql
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import uuid

# Load environment variables from .env file for local testing
load_dotenv()

app = Flask(__name__)

# --- Configuration ---
# This will be set via Environment Variables on PythonAnywhere
SUPER_ADMIN_KEY = os.environ.get("FLASK_SUPER_ADMIN_KEY", "q/9^}H=W:HJ;%}t>$YR$g1[")

def get_db_connection():
    """Establishes a connection to the MySQL database."""
    # On PythonAnywhere, connection details are provided via environment variables
    # For local testing, it will use your .env file
    db_host = os.environ.get('DB_HOST')
    db_user = os.environ.get('DB_USER')
    db_password = os.environ.get('DB_PASSWORD')
    db_name = os.environ.get('DB_NAME')

    if not all([db_host, db_user, db_password, db_name]):
        raise ValueError("Database environment variables (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME) are not set.")

    conn = pymysql.connect(
        host=db_host,
        user=db_user,
        password=db_password,
        database=db_name,
        cursorclass=pymysql.cursors.DictCursor # Use DictCursor to get results as dictionaries
    )
    return conn

def setup_database():
    """
    Initializes the database schema for MySQL.
    Note the changes in data types (e.g., TIMESTAMPTZ -> DATETIME).
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS agencies (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    api_key VARCHAR(255) NOT NULL UNIQUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    agency_id INT NOT NULL,
                    total_licenses INT NOT NULL DEFAULT 25,
                    UNIQUE(agency_id),
                    FOREIGN KEY (agency_id) REFERENCES agencies(id) ON DELETE CASCADE
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS versions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    agency_id INT NOT NULL,
                    version_number VARCHAR(255) NOT NULL,
                    release_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    download_url VARCHAR(1024) NOT NULL,
                    is_latest BOOLEAN NOT NULL DEFAULT FALSE,
                    UNIQUE(agency_id, version_number),
                    FOREIGN KEY (agency_id) REFERENCES agencies(id) ON DELETE CASCADE
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS licenses (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    agency_id INT NOT NULL,
                    device_id VARCHAR(255) NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    hostname VARCHAR(255),
                    location VARCHAR(255),
                    operating_system VARCHAR(255),
                    activated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(50) NOT NULL DEFAULT 'active',
                    UNIQUE(agency_id, device_id),
                    FOREIGN KEY (agency_id) REFERENCES agencies(id) ON DELETE CASCADE
                );
            ''')
        conn.commit()
        print("Database setup for MySQL support is complete.")
    finally:
        conn.close()

# This will now run automatically when the web app starts on PythonAnywhere
setup_database()

# --- Helper Function ---
def get_agency_from_key(api_key):
    """Validates an API key and returns the corresponding agency record."""
    if not api_key:
        return None
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM agencies WHERE api_key = %s;", (api_key,))
            agency = cur.fetchone()
            return agency
    finally:
        conn.close()

# --- All API routes remain the same, only the DB connection logic changed ---

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
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO agencies (name, api_key) VALUES (%s, %s);", (agency_name, new_api_key))
            agency_id = cur.lastrowid
            cur.execute("INSERT INTO settings (agency_id, total_licenses) VALUES (%s, %s);", (agency_id, 25))
            cur.execute("SELECT * from agencies WHERE id = %s;", (agency_id,))
            agency = cur.fetchone()
        conn.commit()
        return jsonify({"success": True, "message": f"Agency '{agency_name}' created.", "agency": agency}), 201
    except pymysql.err.IntegrityError:
        conn.rollback()
        return jsonify({"success": False, "message": "An agency with this name already exists."}), 409
    except Exception as e:
        conn.rollback()
        print(f"ERROR in /admin/create_agency: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        conn.close()

# ... (The rest of the API routes: /admin/list_agencies, /app/version, etc. are the same as before)
# They will work correctly with the new get_db_connection() function.

if __name__ == "__main__":
    # This part is for local testing, not for PythonAnywhere
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
