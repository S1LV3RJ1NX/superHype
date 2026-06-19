<p align="center">
  <img src="assets/banner-compressed.jpg" alt="super-hype" width="100%" />
</p>

<h1 align="center">super-hype</h1>

<p align="center">
  <strong>Turn one announcement into a wave of posts that read as real.</strong>
</p>

<p align="center">
  Human-in-the-loop employee advocacy for LinkedIn. One announcement becomes a
  hero post plus a distinct, on-voice variant for every teammate, each approved
  by a real person and published on a stagger through LinkedIn's official API.
</p>

<p align="center">
  <a href="#quickstart"><img src="https://img.shields.io/badge/Quickstart-C0613F?style=for-the-badge" alt="Quickstart" /></a>
  <a href="backend/README.md"><img src="https://img.shields.io/badge/Backend_setup-2B2B2B?style=for-the-badge" alt="Backend setup" /></a>
  <a href="frontend/README.md"><img src="https://img.shields.io/badge/Frontend_setup-2B2B2B?style=for-the-badge" alt="Frontend setup" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT" />
  <img src="https://img.shields.io/badge/python-3.13+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.13+" />
  <img src="https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black" alt="React 18" />
  <img src="https://img.shields.io/badge/Postgres-4169E1.svg?logo=postgresql&logoColor=white" alt="Postgres" />
  <img src="https://img.shields.io/badge/Redis-DC382D.svg?logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/code%20style-ruff%20%2B%20black-000000.svg" alt="ruff + black" />
</p>

---

## Why super-hype

Most teams ship something and post "excited to announce." It reads like a press
release and the algorithm treats it like one. super-hype does the opposite: it
turns a single internal announcement into genuine, varied advocacy from the
people who actually built the thing, without the spam.

- **Genuine variety.** Every teammate gets a different angle drawn from their
  role, not one post reworded six ways.
- **Real approval.** Each person approves, edits, or skips their own post in one
  tap from Slack or the web app. Nothing publishes without them.
- **Official API only.** No scraping and no credential capture. Every action
  runs on each member's own LinkedIn consent (`w_member_social`, `r_basicprofile`).
- **Concentrated reach.** Approved posts publish on a randomized stagger,
  clustered in the first ninety minutes, never all at once.

## How it works

1. **Draft.** Drop in a raw announcement and pick a writing style. The model
   writes a hero post plus a distinct variant and first comment for everyone.
2. **Approve.** Each person gets a one-tap approve, edit, or skip in Slack or the
   web app.
3. **Publish on a stagger.** Approved posts go out through LinkedIn's official
   `/rest/posts` API on a randomized schedule, with the link placed in the first
   comment for reach.

## Architecture

A monorepo with two deployables and remote managed datastores.

| Part | Stack |
| --- | --- |
| `backend/` | Python 3.13, FastAPI (async), SQLAlchemy 2.0 + asyncpg, Alembic, Pydantic v2, ARQ worker, structlog, managed with `uv` |
| `frontend/` | Vite, React 18, TypeScript, Tailwind CSS, shadcn/ui |
| Data | PostgreSQL (state), Redis (queue + OAuth state) |
| External | LinkedIn API, Google OAuth, an OpenAI-compatible LLM gateway, Slack |

The backend follows strict layering: `view -> controller -> service -> repository
-> model`. Everything is async, every list endpoint is paginated, slow and
external work runs in the ARQ worker, and every externally triggered mutation
writes an `audit_log` row. See [`DESIGN.md`](DESIGN.md) and
[`BACKEND.md`](BACKEND.md) for the authoritative specs.

## Quickstart

Prerequisites: [`uv`](https://docs.astral.sh/uv/) with Python 3.13+, Node.js 20+,
and reachable Postgres and Redis instances.

```bash
# Backend
cd backend
cp .env.example .env          # fill in DATABASE_URL, REDIS_URL, etc.
uv sync
uv run alembic upgrade head   # create the schema
uv run python -m app.seed     # default skill + bootstrap admins
uv run uvicorn app.main:app --reload   # http://localhost:8000

# Frontend (in a second shell)
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

The API serves `GET /healthz`. Interactive docs live at `/docs` and `/redoc` in
local/dev (disabled when `ENV` is production). Detailed setup, including external
app registration, is in [`backend/README.md`](backend/README.md),
[`frontend/README.md`](frontend/README.md), and [`SETUP.md`](SETUP.md).

## Project status

Built in phases (see [`CHECKLIST.md`](CHECKLIST.md)):

- [x] **Phase 0** Scaffold, full data model, migrations, seed, reference API, themed UI shell, landing page
- [ ] **Phase 1** Google auth and users
- [ ] **Phase 2** LinkedIn connection and provider
- [ ] **Phase 3** Skills and generation
- [ ] **Phase 4** Campaign lifecycle and worker
- [ ] **Phase 5** Slack approval
- [ ] **Phase 6** Dashboard and polish

## License

[MIT](LICENSE).
