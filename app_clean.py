import os
import sqlite3
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import mysql.connector as mysql_connector
except ModuleNotFoundError:
    mysql_connector = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "h2s_guard_secret_key_2026")

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "deep",
    "database": "h2s_monitoring_system",
}

SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h2s_guard.db")
USE_SQLITE = os.getenv("USE_SQLITE", "1") == "1"


class SQLiteRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class SQLiteCompatCursor:
    def __init__(self, connection):
        self._cursor = connection.cursor()
        self._cursor.row_factory = sqlite3.Row

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def execute(self, query, params=()):
        if params:
            return self._cursor.execute(query.replace("%s", "?"), params)
        return self._cursor.execute(query)

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return SQLiteRow({key: row[key] for key in row.keys()})

    def fetchall(self):
        return [SQLiteRow({key: item[key] for key in item.keys()}) for item in self._cursor.fetchall()]


class SQLiteCompatConnection:
    def __init__(self, path):
        self._conn = sqlite3.connect(path)

    def cursor(self, dictionary=False):
        return SQLiteCompatCursor(self._conn)

    def execute(self, query, params=()):
        if params:
            return self._conn.execute(query.replace("%s", "?"), params)
        return self._conn.execute(query)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def normalize_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
        ):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def normalize_row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return {
            key: normalize_datetime(value) if key in {"recorded_at", "last_seen", "created_at", "date_of_birth"} else value
            for key, value in zip(row.keys(), row)
        }
    return row


def ensure_sqlite_schema(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            mobile TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            worker_id TEXT UNIQUE,
            wristband_id TEXT,
            department TEXT DEFAULT 'Operations',
            designation TEXT DEFAULT 'Field Technician',
            site TEXT DEFAULT 'MRPL - Refinery',
            shift TEXT DEFAULT 'Day (6:00 AM - 2:00 PM)',
            date_of_birth TEXT,
            height TEXT,
            profile_photo TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS exposure_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            h2s_level REAL NOT NULL,
            exposure_ppm_hr REAL DEFAULT 0,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            wristband_id TEXT NOT NULL,
            status TEXT DEFAULT 'Active',
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    connection.commit()


def get_db():
    if USE_SQLITE:
        connection = SQLiteCompatConnection(SQLITE_DB_PATH)
        ensure_sqlite_schema(connection)
        return connection

    if mysql_connector is not None:
        try:
            connection = mysql_connector.connect(
                host=DB_CONFIG["host"],
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                database=DB_CONFIG["database"],
            )
            if connection is not None:
                return connection
        except Exception as exc:
            print("MySQL unavailable, falling back to SQLite:", exc)

    connection = SQLiteCompatConnection(SQLITE_DB_PATH)
    ensure_sqlite_schema(connection)
    return connection


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    connection = get_db()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                id,
                full_name,
                email,
                mobile,
                worker_id,
                wristband_id,
                department,
                designation,
                site,
                shift,
                date_of_birth,
                height,
                profile_photo
            FROM users
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        user = normalize_row(cursor.fetchone())
        return user or None
    except Exception as exc:
        print("GET USER ERROR:", exc)
        return "DATABASE_ERROR"
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/")
def index():
    if "user_id" in session and get_current_user() is not None:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        current_user = get_current_user()
        if current_user not in (None, "DATABASE_ERROR"):
            return redirect(url_for("home"))
        session.clear()

    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip()
        password = request.form.get("password", "")

        if not login_id or not password:
            flash("Please enter your email/mobile number and password.", "error")
            return render_template("login.html")

        connection = get_db()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    full_name,
                    email,
                    mobile,
                    password_hash,
                    worker_id,
                    wristband_id
                FROM users
                WHERE email = %s OR mobile = %s
                LIMIT 1
                """,
                (login_id, login_id),
            )
            user = normalize_row(cursor.fetchone())

            if user is None or not check_password_hash(user.get("password_hash", ""), password):
                flash("Invalid email/mobile number or password.", "error")
                return render_template("login.html")

            session.clear()
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["worker_id"] = user.get("worker_id")
            session["wristband_id"] = user.get("wristband_id")
            return redirect(url_for("home"))
        except Exception as exc:
            print("LOGIN DATABASE ERROR:", exc)
            flash("Database error occurred during login.", "error")
            return render_template("login.html")
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name:
            flash("Please enter your full name.", "error")
            return render_template("register.html")
        if not email:
            flash("Please enter your email.", "error")
            return render_template("register.html")
        if not mobile:
            flash("Please enter your mobile number.", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return render_template("register.html")
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        connection = get_db()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM users WHERE email = %s OR mobile = %s LIMIT 1",
                (email, mobile),
            )
            if cursor.fetchone():
                flash("Email or mobile number is already registered.", "error")
                return render_template("register.html")

            cursor.execute("SELECT COUNT(*) AS total FROM users")
            result = cursor.fetchone()
            count = int((result["total"] if result else 0) or 0)
            worker_id = f"WKR-{10001 + count}"

            password_hash = generate_password_hash(password)
            cursor.execute(
                """
                INSERT INTO users (
                    full_name,
                    email,
                    mobile,
                    password_hash,
                    worker_id,
                    department,
                    designation,
                    site,
                    shift
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    full_name,
                    email,
                    mobile,
                    password_hash,
                    worker_id,
                    "Operations",
                    "Field Technician",
                    "MRPL - Refinery",
                    "Day (6:00 AM - 2:00 PM)",
                ),
            )
            connection.commit()
            flash("Account created successfully. Please login.", "success")
            return redirect(url_for("login"))
        except Exception as exc:
            print("REGISTER ERROR:", exc)
            try:
                connection.rollback()
            except Exception:
                pass
            flash("Unable to create account.", "error")
            return render_template("register.html")
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    return render_template("register.html")


@app.route("/home")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = get_current_user()
    if user == "DATABASE_ERROR":
        return "Unable to load dashboard due to a database problem.", 500
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    user_id = user["id"]
    connection = get_db()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT id, wristband_id, status, last_seen FROM badges WHERE user_id = %s ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        badge = normalize_row(cursor.fetchone())
        if badge is None:
            badge = {
                "id": None,
                "wristband_id": user.get("wristband_id") or "Not Assigned",
                "status": "Inactive",
                "last_seen": None,
            }

        cursor.execute(
            "SELECT id, h2s_level, exposure_ppm_hr, recorded_at FROM exposure_records WHERE user_id = %s ORDER BY recorded_at DESC LIMIT 1",
            (user_id,),
        )
        latest = normalize_row(cursor.fetchone())
        if latest is None:
            latest = {"id": None, "h2s_level": 0, "exposure_ppm_hr": 0, "recorded_at": None}

        cursor.execute(
            "SELECT h2s_level, exposure_ppm_hr, recorded_at FROM exposure_records WHERE user_id = %s ORDER BY recorded_at ASC LIMIT 24",
            (user_id,),
        )
        exposure_history = [normalize_row(row) for row in cursor.fetchall()]

        cursor.execute(
            "SELECT COALESCE(SUM(exposure_ppm_hr), 0) AS total_exposure FROM exposure_records WHERE user_id = %s",
            (user_id,),
        )
        total_result = cursor.fetchone()
        total_exposure = float((total_result["total_exposure"] if total_result else 0) or 0)

        safe_limit = 8.0
        exposure_percent = max(0, min((total_exposure / safe_limit) * 100, 100))
        exposure_percent = round(exposure_percent)

        current_level = float((latest.get("h2s_level") if latest else 0) or 0)
        if current_level < 5:
            safety_status = "Safe"
        elif current_level < 10:
            safety_status = "Caution"
        else:
            safety_status = "Danger"

        graph_labels = []
        graph_values = []
        for record in exposure_history:
            recorded_at = record.get("recorded_at")
            if recorded_at:
                graph_labels.append(recorded_at.strftime("%H:%M"))
            graph_values.append(float(record.get("h2s_level") or 0))

        return render_template(
            "home.html",
            user=user,
            badge=badge,
            latest=latest,
            exposure_percent=exposure_percent,
            current_level=current_level,
            safety_status=safety_status,
            graph_labels=graph_labels,
            graph_values=graph_values,
            safe_limit=safe_limit,
        )
    except Exception as exc:
        print("HOME DATABASE ERROR:", exc)
        return "Unable to load dashboard because of a database error.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = get_current_user()
    if user == "DATABASE_ERROR":
        return "Unable to load profile due to a database problem.", 500
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    return render_template("profile.html", user=user)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not login_id:
            flash("Please enter your email or mobile number.", "error")
            return render_template("forgot_password.html")
        if len(new_password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return render_template("forgot_password.html")
        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("forgot_password.html")

        connection = get_db()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM users WHERE email = %s OR mobile = %s LIMIT 1",
                (login_id, login_id),
            )
            user = cursor.fetchone()
            if user is None:
                flash("Account not found.", "error")
                return render_template("forgot_password.html")

            password_hash = generate_password_hash(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (password_hash, user["id"]),
            )
            connection.commit()
            flash("Password changed successfully.", "success")
            return redirect(url_for("login"))
        except Exception as exc:
            print("FORGOT PASSWORD ERROR:", exc)
            try:
                connection.rollback()
            except Exception:
                pass
            flash("Unable to change password.", "error")
            return render_template("forgot_password.html")
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    return render_template("forgot_password.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
