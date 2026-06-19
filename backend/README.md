# super-hype backend

The super-hype API and worker. FastAPI (async) for the REST API and OAuth
callbacks, an ARQ worker for slow and external work, Postgres for state, and
Redis for the queue and OAuth state. Managed with [`uv`](https://docs.astral.sh/uv/).

See [`../BACKEND.md`](../BACKEND.md) for the authoritative spec and
[`AGENTS.md`](AGENTS.md) for the operating manual.

## Requirements

- `uv` with Python 3.13+
- A reachable PostgreSQL instance
- A reachable Redis instance

## Setup

```bash
cd backend
cp .env.example .env     # then fill in the values below
uv sync                  # create the venv and install deps
```

Set at least these in `.env` (see [`../SETUP.md`](../SETUP.md) for how to obtain
each secret):

| Key | What it is |
| --- | --- |
| `ENV` | `local` for development (enables `/docs`), `production` to lock it down. Defaults to production if unset. |
| `DATABASE_URL` | async Postgres URL, e.g. `postgresql+asyncpg://user:pass@host:5432/super-hype` |
| `REDIS_URL` | Redis URL including the db index, e.g. `redis://:pass@host:6379/3` |
| `JWT_SECRET` | random 50+ char string |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting LinkedIn tokens |
| `COMPANY_EMAIL_DOMAIN` | the domain allowed to sign in |
| `BOOTSTRAP_ADMIN_EMAILS` | comma-separated admin emails seeded as admins |

Generate a Fernet key:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Database

```bash
uv run alembic upgrade head             # apply migrations
uv run python -m app.seed               # default writing skill + bootstrap admins
```

To create a new migration after changing models:

```bash
uv run alembic revision --autogenerate -m "describe the change"
```

## Run

```bash
uv run uvicorn app.main:app --reload    # API at http://localhost:8000
uv run arq app.workers.arq_app.WorkerSettings   # worker (not yet wired)
```

On startup the app pings Postgres and Redis. If either is unreachable it logs a
clear error and aborts startup instead of serving. Health check: `GET /healthz`.
Interactive docs are at `/docs` and `/redoc` in local/dev and disabled when
`ENV` is production.

## Quality checks

```bash
uv run ruff check . && uv run ruff format .   # lint + import sort
uv run black .                                # format
uv run mypy app                               # types
uv run pytest                                 # tests
```

Tests use a hermetic in-memory SQLite database and mock all outbound HTTP, so
they do not need a live Postgres or Redis.

## Layout

```
app/
  config.py        settings (pydantic-settings); all config from env
  logger.py        structlog logger
  main.py          app factory, startup health checks, CORS, routers
  core/            security (JWT), deps (auth), crypto (Fernet)
  db/              base (DeclarativeBase + naming), session (async engine)
  models/          SQLAlchemy ORM, one module per aggregate
  schemas/         pydantic request/response
  repositories/    all DB access; one singleton per aggregate
  controllers/     per-resource request handling + authorization
  views/           FastAPI routers (thin)
  providers/       LinkedIn provider
  integrations/    LLM gateway, Slack
  workers/         ARQ app + jobs
migrations/        Alembic (async)
tests/             pytest + pytest-asyncio
```
