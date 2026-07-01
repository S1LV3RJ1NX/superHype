# Contributing to super-hype

Thanks for taking the time to contribute. This guide covers how to set up the
project, the conventions we follow, and how to get a change merged.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- Report a bug or request a feature through [Issues](https://github.com/S1LV3RJ1NX/superHype/issues).
- Improve the docs (`README.md`, `docs/`, and the per-package READMEs).
- Fix a bug or build a feature and open a pull request.

For anything large, please open an issue to discuss the approach before you write
a lot of code, so we can agree on direction first.

## Project layout

A monorepo with two deployables:

- `backend/` - FastAPI API and ARQ worker, managed with [`uv`](https://docs.astral.sh/uv/).
- `frontend/` - Vite + React + TypeScript SPA.
- `docs/` - architecture, setup, and testing guides.

Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system overview and
[`agents.md`](agents.md) for the backend operating manual (layering, patterns,
and the rules the code must follow).

## Local setup

Prerequisites: `uv` with Python 3.13+, Node 20+, and reachable Postgres and Redis.

```bash
# Backend
cd backend
cp .env.example .env          # fill in the values (see docs/SETUP.md)
uv sync
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
uv run arq app.workers.arq_app.WorkerSettings   # in a second shell

# Frontend
cd frontend
npm install
npm run dev
```

The `backend/Makefile` wraps the common commands (`make server`, `make worker`,
`make seed`, `make migrate`, `make test`, `make lint`, `make format`). See
[`docs/SETUP.md`](docs/SETUP.md) for full setup including the external app
registration, and [`docs/TESTING.md`](docs/TESTING.md) for end-to-end testing.

## Development workflow

1. Fork the repo and create a branch from `main` (`git checkout -b feature/short-name`).
2. Make your change. Keep it focused; one logical change per pull request.
3. Follow the conventions below and make sure all checks pass locally.
4. Push and open a pull request against `main`, filling in the template.

## Conventions

### Backend (Python)

- Everything is `async` and I/O is awaited. Keep the strict layering:
  `view -> controller -> service -> repository -> model`. A layer only calls the
  one directly below it. See `agents.md` for the load-bearing patterns.
- Lint and format with ruff, and format with black; types with mypy. Install the
  pre-commit hooks so this runs automatically:

  ```bash
  uv run --project backend pre-commit install
  ```

- Run the checks before pushing:

  ```bash
  cd backend
  uv run ruff check . && uv run ruff format --check .
  uv run mypy app
  uv run pytest
  ```

- Add or update tests for any behavior change. Tests are hermetic (in-memory
  SQLite, all outbound HTTP mocked), so they need no live Postgres, Redis, or
  network. Never make a real external call in a test.
- Do not put secrets in code and never commit a `.env`.

### Frontend (TypeScript)

- Type-check and build cleanly:

  ```bash
  cd frontend
  npm run build
  ```

### Commits and copy

- Write clear commit messages that explain the why, not just the what.
- Do not use em dashes in code, comments, docs, or user-facing copy.

## Pull request checklist

- [ ] The change is focused and described in the PR body.
- [ ] Backend: `ruff`, `mypy`, and `pytest` all pass.
- [ ] Frontend: `npm run build` passes.
- [ ] Tests added or updated for the change.
- [ ] Docs updated if behavior or setup changed.

CI runs the same checks on every pull request. A green CI run is required before
review.

## Security

Please do not open a public issue for a security vulnerability. See
[SECURITY.md](SECURITY.md) for how to report one privately.
