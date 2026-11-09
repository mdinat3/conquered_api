# Conquered API

FastAPI + MySQL backend for guest accounts, email signup/login, and match history.

## 1) Setup

```bash
cd /home/matt/projects/games/conquered_api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`dev.env` is loaded automatically. It should include:

```env
mysql_host=localhost
mysql_username=root
mysql_pass=...
mysql_port=3306
mysql_db=conquered
jwt_secret=change-me
```

`mysql_db` is optional; default is `conquered`.

## 2) Run migrations

```bash
alembic upgrade head
```

## 3) Run API

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Endpoints

- `POST /auth/guest` create or refresh a guest session.
- `POST /auth/signup` upgrade guest to email account (or create a new account).
- `POST /auth/login` sign in and merge current guest match history.
- `GET /me` fetch profile and win/loss/draw record.
- `POST /matches` add one PC match result (`client_match_id` is idempotent).
- `GET /matches?limit=20` recent history.
- `GET /stats/usage?days=30` usage rollup by OS, browser, and platform.

## Telemetry tracked for stats

Auth and match events now record:
- request IP address
- user-agent string
- parsed OS name
- parsed browser name
- client app platform / OS / app version (when provided by the game client)

Use `Authorization: Bearer <token>` for authenticated routes.
