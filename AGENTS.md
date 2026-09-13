# H2S Guard — Base44 Dev Environment

## What this app is
Flask web app for H2S (hydrogen sulfide) exposure monitoring. Users register/log in, view a dashboard with exposure charts, scan H2S strip images (analyzed by an ML model), and view reports/history.

## Stack
- **Python 3.12** Flask app (`app.py` is the entry point)
- **SQLite** — file-based DB at `h2s_guard.db` (repo root). Schema auto-created on first request via `ensure_sqlite_schema()`. No external database service needed.
- **ML** — `opencv-python-headless` + `scikit-learn` + `joblib` model at `h2sapp/h2s_rf_model.pkl` for strip image analysis
- Templates in `templates/`, static assets in `static/`

## Running locally (Base44)
```
docker compose -f docker-compose.base44.yml up -d
```
- App served on **port 3000** (mapped from container port 3000)
- Flask dev server with `--reload` (hot reload on file changes)
- Dependencies installed at container startup via `pip install -r requirements.txt`
- System libs `libgl1` and `libglib2.0-0` installed for OpenCV

## Notes
- `database.sql` is a MySQL schema — NOT used at runtime. The app uses SQLite exclusively via the compat layer in `app.py`.
- `api/index.py` is the Vercel serverless entry point — not used in the Docker dev setup.
- No external credentials required. `SECRET_KEY` has a built-in default.
- The SQLite DB starts empty; the first user must register via `/register`.
