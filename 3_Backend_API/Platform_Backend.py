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
SUPER_ADMIN_KEY = os.environ.get("FLASK_SUPER_ADMIN_KEY", "f47ac10b-58cc-4372-a567-0e02b2c3d479")


def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
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
            cur.execute(
                '''CREATE TABLE IF NOT EXISTS agencies (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, api_key TEXT NOT NULL UNIQUE, created_at TIMESTAMPTZ DEFAULT NOW());''')
            cur.execute(
                '''CREATE TABLE IF NOT EXISTS settings (id SERIAL PRIMARY KEY, agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE, total_licenses INTEGER NOT NULL DEFAULT 25, UNIQUE(agency_id));''')
            cur.execute(
                '''CREATE TABLE IF NOT EXISTS versions (id SERIAL PRIMARY KEY, agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE, version_number TEXT NOT NULL, release_date TIMESTAMPTZ DEFAULT NOW(), download_url TEXT NOT NULL, is_latest BOOLEAN NOT NULL DEFAULT FALSE, UNIQUE(agency_id, version_number));''')
            cur.execute(
                '''CREATE TABLE IF NOT EXISTS licenses (id SERIAL PRIMARY KEY, agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE, device_id TEXT NOT NULL, username TEXT NOT NULL, hostname TEXT, location TEXT, operating_system TEXT, activated_at TIMESTAMPTZ DEFAULT NOW(), status TEXT NOT NULL DEFAULT 'active', UNIQUE(agency_id, device_id));''')
        conn.commit()
        print("Database setup for PostgreSQL support is complete.")
    except Exception as e:
        print(f"Error during database setup: {e}")
    finally:
        conn.close()


with app.app_context():
    setup_database()


# --- Helper Functions ---
def is_super_admin():
    """Checks for the super admin key in the request headers."""
    return request.headers.get('X-Admin-Key') == SUPER_ADMIN_KEY


def get_agency_id_from_api_key(cur):
    """Gets agency ID from the API key in the request header."""
    api_key = request.headers.get('X-Agency-Api-Key')
    if not api_key:
        return None
    cur.execute("SELECT id FROM agencies WHERE api_key = %s;", (api_key,))
    agency = cur.fetchone()
    return agency['id'] if agency else None


# --- Root Route ---
@app.route('/')
def index():
    return jsonify({"status": "online", "message": "Timesheet Platform API is running."}), 200


#
# --- ADMIN CONSOLE ROUTES ---
#
@app.route('/admin/agencies', methods=['GET'])
def get_agencies():
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT id, name, api_key, created_at FROM agencies ORDER BY name;")
        agencies = cur.fetchall() or []
        return jsonify({"success": True, "agencies": agencies})
    except Exception as e:
        print(f"ERROR in /admin/agencies: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


@app.route('/admin/create_agency', methods=['POST'])
def create_agency():
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    agency_name = request.get_json().get('agency_name')
    if not agency_name: return jsonify({"success": False, "message": "Agency name is required."}), 400
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        new_api_key = str(uuid.uuid4())
        cur.execute("INSERT INTO agencies (name, api_key) VALUES (%s, %s) RETURNING *;", (agency_name, new_api_key))
        agency = cur.fetchone()
        cur.execute("INSERT INTO settings (agency_id, total_licenses) VALUES (%s, %s);", (agency['id'], 25))
        conn.commit()
        return jsonify({"success": True, "message": f"Agency '{agency_name}' created.", "agency": agency}), 201
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"success": False, "message": "An agency with this name already exists."}), 409
    except Exception as e:
        conn.rollback();
        print(f"ERROR in /admin/create_agency: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


@app.route('/admin/agencies/<int:agency_id>', methods=['DELETE'])
def delete_agency(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM agencies WHERE id = %s;", (agency_id,))
        conn.commit()
        if cur.rowcount == 0: return jsonify({"success": False, "message": "Agency not found."}), 404
        return jsonify({"success": True, "message": "Agency deleted successfully."})
    except Exception as e:
        conn.rollback();
        print(f"ERROR in /admin/agencies/delete: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


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
        cur.execute(
            "SELECT device_id, username, hostname, location, operating_system, status, activated_at FROM licenses WHERE agency_id = %s ORDER BY activated_at DESC;",
            (agency_id,))
        devices = cur.fetchall() or []
        return jsonify({"success": True, "total_licenses": total_licenses, "activated_count": activated_count,
                        "licenses_remaining": total_licenses - activated_count, "activated_devices": devices})
    except Exception as e:
        print(f"ERROR in /admin/agencies/.../status: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


@app.route('/admin/agencies/<int:agency_id>/set_total_licenses', methods=['POST'])
def set_total_licenses(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    new_total = request.get_json().get('new_total_licenses')
    if not isinstance(new_total, int) or new_total < 0: return jsonify(
        {"success": False, "message": "Invalid number of licenses."}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO settings (agency_id, total_licenses) VALUES (%s, %s) ON CONFLICT (agency_id) DO UPDATE SET total_licenses = EXCLUDED.total_licenses;",
            (agency_id, new_total))
        conn.commit()
        return jsonify({"success": True, "message": f"Total licenses for agency set to {new_total}."})
    except Exception as e:
        conn.rollback();
        print(f"ERROR in /admin/agencies/.../set_total_licenses: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


@app.route('/admin/agencies/<int:agency_id>/versions', methods=['GET'])
def get_versions(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            "SELECT version_number, release_date, download_url, is_latest FROM versions WHERE agency_id = %s ORDER BY release_date DESC;",
            (agency_id,))
        versions = cur.fetchall() or []
        return jsonify({"success": True, "versions": versions})
    except Exception as e:
        print(f"ERROR in /admin/agencies/.../versions: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


@app.route('/admin/agencies/<int:agency_id>/set_latest_version', methods=['POST'])
def set_latest_version(agency_id):
    if not is_super_admin(): return jsonify({"success": False, "message": "Unauthorized"}), 403
    data = request.get_json()
    version_number, download_url = data.get('version_number'), data.get('download_url')
    if not version_number or not download_url: return jsonify(
        {"success": False, "message": "Version number and download URL are required."}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE versions SET is_latest = FALSE WHERE agency_id = %s;", (agency_id,))
        cur.execute(
            "INSERT INTO versions (agency_id, version_number, download_url, is_latest) VALUES (%s, %s, %s, TRUE) ON CONFLICT (agency_id, version_number) DO UPDATE SET download_url = EXCLUDED.download_url, is_latest = TRUE, release_date = NOW();",
            (agency_id, version_number, download_url))
        conn.commit()
        return jsonify(
            {"success": True, "message": f"Version {version_number} is now set as the latest for the agency."})
    except Exception as e:
        conn.rollback();
        print(f"ERROR in /admin/agencies/.../set_latest_version: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


#
# --- CLIENT APPLICATION API V1 ROUTES ---
#
@app.route('/api/v1/license/activate', methods=['POST'])
def api_activate_license():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        agency_id = get_agency_id_from_api_key(cur)
        if not agency_id:
            return jsonify({"success": False, "message": "Invalid Agency API Key."}), 403

        cur.execute("SELECT total_licenses FROM settings WHERE agency_id = %s;", (agency_id,))
        total_licenses = (cur.fetchone() or {}).get('total_licenses', 0)
        cur.execute("SELECT COUNT(*) FROM licenses WHERE agency_id = %s AND status = 'active';", (agency_id,))
        activated_count = cur.fetchone()['count']

        data = request.get_json()
        device_id = data.get('device_id')
        if not device_id: return jsonify({"success": False, "message": "Device ID is required."}), 400

        cur.execute("SELECT id FROM licenses WHERE agency_id = %s AND device_id = %s AND status = 'active';",
                    (agency_id, device_id))
        is_already_active = cur.fetchone() is not None

        if not is_already_active and activated_count >= total_licenses:
            return jsonify(
                {"success": False, "message": "All licenses are currently in use. Please contact your manager."}), 429

        cur.execute("""
            INSERT INTO licenses (agency_id, device_id, username, hostname, location, operating_system)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (agency_id, device_id) DO UPDATE SET
                status = 'active',
                username = EXCLUDED.username,
                hostname = EXCLUDED.hostname,
                location = EXCLUDED.location,
                operating_system = EXCLUDED.operating_system,
                activated_at = NOW();
        """, (agency_id, device_id, data.get('username'), data.get('hostname'), data.get('location'),
              data.get('operating_system')))

        conn.commit()
        return jsonify({"success": True, "message": "License activated successfully!"})

    except Exception as e:
        conn.rollback();
        print(f"ERROR in /api/v1/license/activate: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


@app.route('/api/v1/license/check', methods=['POST'])
def api_check_license():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        agency_id = get_agency_id_from_api_key(cur)
        if not agency_id:
            return jsonify({"success": False, "message": "Invalid Agency API Key."}), 403

        device_id = request.get_json().get('device_id')
        if not device_id: return jsonify({"success": False, "message": "Device ID is required."}), 400

        cur.execute("SELECT status FROM licenses WHERE agency_id = %s AND device_id = %s;", (agency_id, device_id))
        license_record = cur.fetchone()

        if license_record and license_record['status'] == 'active':
            return jsonify({"success": True, "message": "License is active."})
        elif license_record:
            return jsonify({"success": False, "message": "This license has been deactivated by an administrator."})
        else:
            return jsonify({"success": False, "message": "This device has not been licensed."})

    except Exception as e:
        conn.rollback();
        print(f"ERROR in /api/v1/license/check: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


@app.route('/api/v1/version/latest', methods=['GET'])
def api_get_latest_version():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        agency_id = get_agency_id_from_api_key(cur)
        if not agency_id:
            return jsonify({"success": False, "message": "Invalid Agency API Key."}), 403

        cur.execute("SELECT version_number, download_url FROM versions WHERE agency_id = %s AND is_latest = TRUE;",
                    (agency_id,))
        version_record = cur.fetchone()

        if version_record:
            return jsonify({"success": True, "latest_version": version_record['version_number'],
                            "download_url": version_record['download_url']})
        else:
            return jsonify({"success": True, "latest_version": "99.0.0", "download_url": ""})

    except Exception as e:
        print(f"ERROR in /api/v1/version/latest: {e}")
        return jsonify({"success": False, "message": "An internal server error occurred."}), 500
    finally:
        cur.close();
        conn.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
