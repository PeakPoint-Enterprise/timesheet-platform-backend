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
SUPER_ADMIN_KEY = os.environ.get("FLASK_SUPER_ADMIN_KEY", "q/9^}H=W:HJ;%}t>$`YR$g1[")

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("FATAL ERROR: DATABASE_URL environment variable is not set.")
    conn = psycopg2.connect(db_url)
    return conn

def setup_database():
    """Initializes the database schema for PostgreSQL."""
    # This function is safe to run multiple times.
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS agencies (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, api_key TEXT NOT NULL UNIQUE, created_at TIMESTAMPTZ DEFAULT NOW());''')
            cur.execute('''CREATE TABLE IF NOT EXISTS settings (id SERIAL PRIMARY KEY, agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE, total_licenses INTEGER NOT NULL DEFAULT 25, UNIQUE(agency_id));''')
            cur.execute('''CREATE TABLE IF NOT EXISTS versions (id SERIAL PRIMARY KEY, agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE, version_number TEXT NOT NULL, release_date TIMESTAMPTZ DEFAULT NOW(), download_url TEXT NOT NULL, is_latest BOOLEAN NOT NULL DEFAULT FALSE, UNIQUE(agency_id, version_number));''')
            cur.execute('''CREATE TABLE IF NOT EXISTS licenses (id SERIAL PRIMARY KEY, agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE, device_id TEXT NOT NULL, username TEXT NOT NULL, hostname TEXT, location TEXT, operating_system TEXT, activated_at TIMESTAMPTZ DEFAULT NOW(), status TEXT NOT NULL DEFAULT 'active', UNIQUE(agency_id, device_id));''')
        conn.commit()
        print("Database setup for PostgreSQL support is complete.")
    except Exception as e:
        print(f"Error during database setup: {e}")
    finally:
        conn.close()

with app.app_context():
    setup_database()

# --- Helper & Root Route ---
def is_super_admin():
    """Checks for the super admin key in the request headers."""
    return request.headers.get('X-Admin-Key') == SUPER_ADMIN_KEY

@app.route('/')
def index():
    """Welcome route to confirm the server is running."""
    return jsonify({"status": "online", "message": "Timesheet Platform API is running."}), 200

# --- Super Admin Routes ---
@app.route('/admin/agencies', methods=['GET'])
def get_agencies():
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT id, name, api_key, created_at FROM agencies ORDER BY name;")
        agencies = cur.fetchall()
        return jsonify({"success": True, "agencies": agencies})
    except Exception as e:
        print(f"ERROR in /admin/agencies: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close(); conn.close()

@app.route('/admin/create_agency', methods=['POST'])
def create_agency():
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    agency_name = request.get_json().get('agency_name')
    if not agency_name: return jsonify({"success": False, "message": "Agency name is required."}), 400
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
        conn.rollback(); print(f"ERROR in /admin/create_agency: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close(); conn.close()

# --- Agency-Specific Admin Routes ---
@app.route('/admin/agencies/<int:agency_id>/status', methods=['GET'])
def get_agency_status(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT total_licenses FROM settings WHERE agency_id = %s;", (agency_id,))
        total_licenses = (cur.fetchone() or {}).get('total_licenses', 0)
        cur.execute("SELECT COUNT(*) FROM licenses WHERE agency_id = %s AND status = 'active';", (agency_id,))
        activated_count = cur.fetchone()['count']
        cur.execute("SELECT device_id, username, hostname, location, operating_system, status, activated_at FROM licenses WHERE agency_id = %s ORDER BY activated_at DESC;", (agency_id,))
        devices = cur.fetchall()
        return jsonify({"success": True, "total_licenses": total_licenses, "activated_count": activated_count, "licenses_remaining": total_licenses - activated_count, "activated_devices": devices})
    except Exception as e:
        print(f"ERROR in /admin/agencies/.../status: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close(); conn.close()

@app.route('/admin/agencies/<int:agency_id>/set_total_licenses', methods=['POST'])
def set_total_licenses(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    new_total = request.get_json().get('new_total_licenses')
    if not isinstance(new_total, int) or new_total < 0: return jsonify({"success": False, "message": "Invalid number of licenses."}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO settings (agency_id, total_licenses) VALUES (%s, %s) ON CONFLICT (agency_id) DO UPDATE SET total_licenses = EXCLUDED.total_licenses;", (agency_id, new_total))
        conn.commit()
        return jsonify({"success": True, "message": f"Total licenses for agency set to {new_total}."})
    except Exception as e:
        conn.rollback(); print(f"ERROR in /admin/agencies/.../set_total_licenses: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close(); conn.close()

def bulk_update_device_status(agency_id, device_ids, status):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = "UPDATE licenses SET status = %s WHERE agency_id = %s AND device_id = ANY(%s);"
        cur.execute(query, (status, agency_id, device_ids))
        conn.commit()
        return {"success": True, "message": f"{cur.rowcount} device(s) updated to '{status}'."}
    except Exception as e:
        conn.rollback(); print(f"ERROR during bulk status update: {e}")
        return {"success": False, "message": "Database error during update."}
    finally:
        cur.close(); conn.close()

@app.route('/admin/agencies/<int:agency_id>/bulk_activate_devices', methods=['POST'])
def bulk_activate(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    result = bulk_update_device_status(agency_id, request.get_json().get('device_ids', []), 'active')
    return jsonify(result)

@app.route('/admin/agencies/<int:agency_id>/bulk_deactivate_devices', methods=['POST'])
def bulk_deactivate(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    result = bulk_update_device_status(agency_id, request.get_json().get('device_ids', []), 'inactive')
    return jsonify(result)

@app.route('/admin/agencies/<int:agency_id>/bulk_delete_devices', methods=['POST'])
def bulk_delete(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = "DELETE FROM licenses WHERE agency_id = %s AND device_id = ANY(%s) AND status = 'inactive';"
        cur.execute(query, (agency_id, request.get_json().get('device_ids', [])))
        conn.commit()
        return jsonify({"success": True, "message": f"{cur.rowcount} inactive device record(s) deleted."})
    except Exception as e:
        conn.rollback(); print(f"ERROR during bulk delete: {e}")
        return jsonify({"success": False, "message": "Database error during deletion."}), 500
    finally:
        cur.close(); conn.close()

@app.route('/admin/agencies/<int:agency_id>/versions', methods=['GET'])
def get_versions(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT version_number, release_date, download_url, is_latest FROM versions WHERE agency_id = %s ORDER BY release_date DESC;", (agency_id,))
        versions = cur.fetchall()
        return jsonify({"success": True, "versions": versions})
    except Exception as e:
        print(f"ERROR in /admin/agencies/.../versions: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close(); conn.close()

@app.route('/admin/agencies/<int:agency_id>/set_latest_version', methods=['POST'])
def set_latest_version(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    data = request.get_json()
    version_number, download_url = data.get('version_number'), data.get('download_url')
    if not version_number or not download_url: return jsonify({"success": False, "message": "Version number and download URL are required."}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE versions SET is_latest = FALSE WHERE agency_id = %s;", (agency_id,))
        cur.execute("INSERT INTO versions (agency_id, version_number, download_url, is_latest) VALUES (%s, %s, %s, TRUE) ON CONFLICT (agency_id, version_number) DO UPDATE SET download_url = EXCLUDED.download_url, is_latest = TRUE, release_date = NOW();", (agency_id, version_number, download_url))
        conn.commit()
        return jsonify({"success": True, "message": f"Version {version_number} is now set as the latest for the agency."})
    except Exception as e:
        conn.rollback(); print(f"ERROR in /admin/agencies/.../set_latest_version: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close(); conn.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
