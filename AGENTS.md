# Repository Guidelines

## Project Structure & Module Organization
- `app/`: Flask application package (views, models, forms, importers, utils).
- `app/templates/` and `app/static/`: Jinja templates and frontend assets.
- `migrations/`: Alembic migration scripts and config.
- `data/`: local SQLite database files (default path in `dev.sh`).
- `imports/`, `reports/`, `app/uploads/`: raw inputs/exports and uploaded CSVs.
- Entry points: `pod_accounting.py` (Flask app + CLI), `app.py` (legacy/alt entry).

## Build, Test, and Development Commands
- `pip install -r requirements.txt` — install Python dependencies.
- `./dev.sh` — load `.env`, set `FLASK_APP`, and start the dev server.
- `python pod_accounting.py` — run Flask directly (debug enabled).
- `flask create-db` — create database tables (uses `DATABASE_URL`).
- `docker compose -f docker-compose.dev.yml up` — local dev with Docker.
- `./deploy.sh` — pull latest image and restart Docker services.

## Coding Style & Naming Conventions
- Python: 4-space indentation, PEP 8 style, `snake_case` for functions/vars, `CamelCase` for classes.
- Templates: keep business logic in views; use templates for formatting only.
- Typing: `mypy.ini` exists; if adding annotations, keep them compatible with current settings.

## Testing Guidelines
- Tests live in `tests/` (currently placeholders).
- No test runner or coverage target is enforced yet.
- Ad hoc integration checks: `python test_printify_api.py` (requires `.env` tokens).

## Commit & Pull Request Guidelines
- Recent commits use short, imperative summaries (e.g., "Add ...", "Update ...").
- Keep commits focused; mention schema changes or data migrations in the message.
- PRs should include a clear description, relevant screenshots for UI changes, and any required `.env` variables.

## Security & Configuration Tips
- Store secrets in `.env` (`PRINTIFY_API_TOKEN`, `PRINTIFY_SHOP_ID`, `OPEN_EXCHANGE_API`).
- Do not expose the app publicly; there is no authentication layer.
- Verify financial outputs manually; the app is not hardened for correctness.
