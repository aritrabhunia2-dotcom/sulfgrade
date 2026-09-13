import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

PROJECT_SITE_PACKAGES = Path(__file__).resolve().parent / ".venv" / "Lib" / "site-packages"
if PROJECT_SITE_PACKAGES.exists() and str(PROJECT_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(PROJECT_SITE_PACKAGES))

try:
    import cv2
    CV2_IMPORT_ERROR = None
except ImportError as exc:
    cv2 = None
    CV2_IMPORT_ERROR = str(exc)

try:
    import joblib
    JOBLIB_IMPORT_ERROR = None
except ImportError as exc:
    joblib = None
    JOBLIB_IMPORT_ERROR = str(exc)

try:
    import numpy as np
    NUMPY_IMPORT_ERROR = None
except ImportError as exc:
    np = None
    NUMPY_IMPORT_ERROR = str(exc)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "h2s_guard_secret_key_2026")

DEFAULT_SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h2s_guard.db")
SQLITE_DB_PATH = os.environ.get(
    "SQLITE_DB_PATH",
    "/tmp/h2s_guard.db" if os.environ.get("VERCEL") else DEFAULT_SQLITE_DB_PATH,
)
MODEL_PATH = Path(__file__).resolve().parent / "h2sapp" / "h2s_rf_model.pkl"
ALLOWED_SCAN_EXTENSIONS = {"jpg", "jpeg", "png", "bmp", "webp"}


def analyze_strip_image(image_bytes):
    if cv2 is None or joblib is None or np is None:
        failures = "; ".join(
            message
            for message in (CV2_IMPORT_ERROR, JOBLIB_IMPORT_ERROR, NUMPY_IMPORT_ERROR)
            if message
        )
        raise RuntimeError(f"ML dependency import failed: {failures}")
    if not MODEL_PATH.exists():
        raise RuntimeError("The H2S model file is missing.")

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The uploaded file is not a valid image.")

    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    corrected_image = normalize_lighting(rgb_image)
    height, width, _ = corrected_image.shape
    roi = corrected_image[int(height * 0.4):int(height * 0.6), int(width * 0.4):int(width * 0.6)]
    if roi.size == 0:
        raise ValueError("The uploaded image is too small to analyze.")

    mean_r, mean_g, mean_b = np.mean(roi, axis=(0, 1))
    model = joblib.load(MODEL_PATH)
    predicted_dose = max(0.0, float(model.predict([[mean_r, mean_g, mean_b]])[0]))
    return {
        "predicted_dose": predicted_dose,
        "mean_r": float(mean_r),
        "mean_g": float(mean_g),
        "mean_b": float(mean_b),
    }


def normalize_lighting(image_rgb):
    result = image_rgb.astype(np.float32)
    mean_r, mean_g, mean_b = np.mean(result, axis=(0, 1))
    if mean_r == 0 or mean_g == 0 or mean_b == 0:
        return image_rgb

    mean_gray = (mean_r + mean_g + mean_b) / 3.0
    result[:, :, 0] *= mean_gray / mean_r
    result[:, :, 1] *= mean_gray / mean_g
    result[:, :, 2] *= mean_gray / mean_b
    return np.clip(result, 0, 255).astype(np.uint8)


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
        return {
            key: normalize_datetime(value) if key in {"recorded_at", "last_seen", "created_at", "date_of_birth"} else value
            for key, value in row.items()
        }
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
    except Exception:
        return "DATABASE_ERROR"
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/sw.js")
def service_worker():
    response = send_from_directory(app.static_folder, "sw.js")
    response.headers["Service-Worker-Allowed"] = "/"
    return response


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
        except Exception:
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
        designation = request.form.get("designation", "").strip()
        shift = request.form.get("shift", "").strip()
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
        if not designation:
            flash("Please enter your designation.", "error")
            return render_template("register.html")
        if not shift:
            flash("Please enter your shift.", "error")
            return render_template("register.html")
        allowed_shifts = {
            "Day (6:00 AM - 2:00 PM)",
            "Evening (2:00 PM - 10:00 PM)",
            "Night (10:00 PM - 6:00 AM)",
        }
        if shift not in allowed_shifts:
            flash("Please select a valid eight-hour shift.", "error")
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

            cursor.execute(
                """
                SELECT COALESCE(
                    MAX(CAST(SUBSTR(worker_id, 5) AS INTEGER)),
                    10000
                ) AS highest_worker_number
                FROM users
                WHERE worker_id LIKE 'WKR-%'
                """
            )
            result = cursor.fetchone()
            highest_worker_number = int(
                (result["highest_worker_number"] if result else 10000) or 10000
            )
            worker_id = f"WKR-{highest_worker_number + 1}"

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
                    designation,
                    "MRPL - Refinery",
                    shift,
                ),
            )
            connection.commit()
            flash("Account created successfully. Please login.", "success")
            return redirect(url_for("login"))
        except Exception:
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
            "SELECT id, h2s_level, exposure_ppm_hr, recorded_at FROM exposure_records WHERE user_id = %s ORDER BY recorded_at DESC, id DESC LIMIT 1",
            (user_id,),
        )
        latest = normalize_row(cursor.fetchone())
        if latest is None:
            latest = {"id": None, "h2s_level": 0, "exposure_ppm_hr": 0, "recorded_at": None}

        cursor.execute(
            "SELECT h2s_level, exposure_ppm_hr, recorded_at FROM exposure_records WHERE user_id = %s ORDER BY recorded_at ASC",
            (user_id,),
        )
        all_exposure_history = [normalize_row(row) for row in cursor.fetchall()]

        selected_period = request.args.get("period", "today")
        if selected_period not in {"today", "yesterday", "week"}:
            selected_period = "today"

        today = date.today()
        if selected_period == "yesterday":
            period_start = today - timedelta(days=1)
            period_end = today
            period_label = "Yesterday"
        elif selected_period == "week":
            period_start = today - timedelta(days=6)
            period_end = today + timedelta(days=1)
            period_label = "This Week"
        else:
            period_start = today
            period_end = today + timedelta(days=1)
            period_label = "Today"

        exposure_history = [
            record
            for record in all_exposure_history
            if record.get("recorded_at")
            and period_start <= record["recorded_at"].date() < period_end
        ]

        cursor.execute(
            "SELECT COALESCE(SUM(exposure_ppm_hr), 0) AS total_exposure FROM exposure_records WHERE user_id = %s",
            (user_id,),
        )
        total_result = cursor.fetchone()
        total_exposure = float((total_result["total_exposure"] if total_result else 0) or 0)

        safe_limit = 8.0
        exposure_percent = round(max(0, min((total_exposure / safe_limit) * 100, 100)))
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

        if graph_values:
            point_width = 500 / max(len(graph_values) - 1, 1)
            points = []
            for index, value in enumerate(graph_values):
                x = index * point_width
                y = 215 - (min(max(value, 0), 10) / 10 * 195)
                points.append(f"{x:.1f},{y:.1f}")
            graph_path = "M" + " L".join(points)
            graph_area_path = f"{graph_path} L500,215 L0,215 Z"
        else:
            graph_path = "M0,215 L500,215"
            graph_area_path = "M0,215 L500,215 L500,215 L0,215 Z"

        if selected_period == "week":
            graph_labels = [
                (period_start + timedelta(days=index)).strftime("%a")
                for index in range(7)
            ]
        elif not graph_labels:
            graph_labels = ["12 AM", "4 AM", "8 AM", "12 PM", "4 PM", "8 PM", "12 AM"]

        return render_template(
            "home.html",
            user=user,
            badge=badge,
            latest=latest,
            exposure_percent=exposure_percent,
            total_exposure=total_exposure,
            current_level=current_level,
            safety_status=safety_status,
            graph_labels=graph_labels,
            graph_values=graph_values,
            graph_path=graph_path,
            graph_area_path=graph_area_path,
            selected_period=selected_period,
            period_label=period_label,
            safe_limit=safe_limit,
        )
    except Exception as exc:
        print("HOME DATABASE ERROR:", repr(exc))
        return "Unable to load dashboard because of a database error.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/manual-guidelines")
def manual_guidelines():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("manual_guidelines.html")


@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = get_current_user()
    if user == "DATABASE_ERROR":
        return "Unable to load history due to a database problem.", 500
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    connection = get_db()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        selected_period = request.args.get("period", "today")
        if selected_period not in {"today", "yesterday", "week"}:
            selected_period = "today"

        today = date.today()
        if selected_period == "yesterday":
            period_start = today - timedelta(days=1)
            period_end = today
            period_label = "Yesterday"
        elif selected_period == "week":
            period_start = today - timedelta(days=6)
            period_end = today + timedelta(days=1)
            period_label = "This Week"
        else:
            period_start = today
            period_end = today + timedelta(days=1)
            period_label = "Today"

        cursor.execute(
            """
            SELECT h2s_level, exposure_ppm_hr, recorded_at
            FROM exposure_records
            WHERE user_id = %s
            ORDER BY recorded_at DESC, id DESC
            """,
            (user["id"],),
        )
        readings = [
            normalize_row(row)
            for row in cursor.fetchall()
            if row["recorded_at"]
            and period_start <= normalize_datetime(row["recorded_at"]).date() < period_end
        ]
        return render_template(
            "history.html",
            user=user,
            readings=readings,
            selected_period=selected_period,
            period_label=period_label,
        )
    except Exception as exc:
        print("HISTORY DATABASE ERROR:", repr(exc))
        return "Unable to load reading history because of a database error.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/alerts")
def alerts():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = get_current_user()
    if user == "DATABASE_ERROR":
        return "Unable to load alerts due to a database problem.", 500
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    return render_template("alerts.html", user=user)


@app.route("/scan", methods=["GET", "POST"])
def scan():
    if "user_id" not in session:
        return redirect(url_for("login"))

    result = None
    if request.method == "POST":
        image_file = request.files.get("strip_image")
        extension = ""
        if image_file and image_file.filename:
            extension = image_file.filename.rsplit(".", 1)[-1].lower()

        if not image_file or not image_file.filename:
            flash("Please upload an H2S strip image.", "error")
        elif extension not in ALLOWED_SCAN_EXTENSIONS:
            flash("Please upload a JPG, JPEG, PNG, BMP, or WEBP image.", "error")
        else:
            try:
                analysis = analyze_strip_image(image_file.read())
                connection = get_db()
                cursor = None
                try:
                    cursor = connection.cursor(dictionary=True)
                    cursor.execute(
                        """
                        INSERT INTO exposure_records (user_id, h2s_level, exposure_ppm_hr)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            session["user_id"],
                            analysis["predicted_dose"],
                            analysis["predicted_dose"],
                        ),
                    )
                    connection.commit()
                finally:
                    if cursor is not None:
                        cursor.close()
                    connection.close()

                result = analysis
                flash("H2S strip analyzed and reading saved.", "success")
                return redirect(url_for("home"))
            except Exception as exc:
                flash(f"Unable to analyze image: {exc}", "error")

    user = get_current_user()
    return render_template("scan.html", user=user, result=result)


@app.route("/daily-report")
def daily_report():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = get_current_user()
    if user == "DATABASE_ERROR":
        return "Unable to load report due to a database problem.", 500
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    connection = get_db()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT h2s_level, exposure_ppm_hr, recorded_at
            FROM exposure_records
            WHERE user_id = %s
              AND DATE(recorded_at) = DATE('now', 'localtime')
            ORDER BY recorded_at DESC
            """,
            (user["id"],),
        )
        readings = [normalize_row(row) for row in cursor.fetchall()]

        total_exposure = sum(float(reading.get("exposure_ppm_hr") or 0) for reading in readings)
        average_level = (
            sum(float(reading.get("h2s_level") or 0) for reading in readings) / len(readings)
            if readings
            else 0
        )
        peak_level = max(
            (float(reading.get("h2s_level") or 0) for reading in readings),
            default=0,
        )
        if peak_level < 5:
            safety_status = "Safe"
        elif peak_level < 10:
            safety_status = "Caution"
        else:
            safety_status = "Danger"

        return render_template(
            "daily_report.html",
            user=user,
            readings=readings,
            total_exposure=total_exposure,
            average_level=average_level,
            peak_level=peak_level,
            safety_status=safety_status,
        )
    except Exception:
        return "Unable to load daily report because of a database error.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/health-guidelines")
def health_guidelines():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("health_guidelines.html")


@app.route("/emergency-contacts")
def emergency_contacts():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("emergency_contacts.html")


@app.route("/download-guidelines")
def download_guidelines():
    if "user_id" not in session:
        return redirect(url_for("login"))

    pdf_directory = os.path.join(app.root_path, "static", "pdf")
    return send_from_directory(
        pdf_directory,
        "user_guidelines.pdf",
        as_attachment=True,
    )


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


@app.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = get_current_user()
    if user == "DATABASE_ERROR":
        return "Unable to load profile due to a database problem.", 500
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        mobile = request.form.get("mobile", "").strip()
        department = request.form.get("department", "").strip()
        designation = request.form.get("designation", "").strip()
        site = request.form.get("site", "").strip()
        shift = request.form.get("shift", "").strip()
        allowed_shifts = {
            "Day (6:00 AM - 2:00 PM)",
            "Evening (2:00 PM - 10:00 PM)",
            "Night (10:00 PM - 6:00 AM)",
        }

        if not all((full_name, email, mobile, department, designation, site)):
            flash("Please complete all profile fields.", "error")
            return render_template("edit_profile.html", user=user)
        if shift not in allowed_shifts:
            flash("Please select a valid eight-hour shift.", "error")
            return render_template("edit_profile.html", user=user)

        connection = get_db()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM users WHERE (email = %s OR mobile = %s) AND id != %s LIMIT 1",
                (email, mobile, user["id"]),
            )
            if cursor.fetchone():
                flash("Email or mobile number is already registered.", "error")
                return render_template("edit_profile.html", user=user)

            cursor.execute(
                """
                UPDATE users
                SET full_name = %s,
                    email = %s,
                    mobile = %s,
                    department = %s,
                    designation = %s,
                    site = %s,
                    shift = %s
                WHERE id = %s
                """,
                (full_name, email, mobile, department, designation, site, shift, user["id"]),
            )
            connection.commit()
            session["full_name"] = full_name
            flash("Profile updated successfully.", "success")
            return redirect(url_for("profile"))
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            flash("Unable to update profile.", "error")
            return render_template("edit_profile.html", user=user)
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    return render_template("edit_profile.html", user=user)


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
        except Exception:
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
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
