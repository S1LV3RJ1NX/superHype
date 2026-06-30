<p align="center">
  <img src="assets/banner-compressed.jpg" alt="super-hype" width="100%" />
</p>

<h1 align="center">super-hype</h1>

<p align="center">
  <strong>Turn one announcement into a wave of posts that read as real.</strong>
</p>

<p align="center">
  Human-in-the-loop employee advocacy for LinkedIn. Amplify an existing post
  with genuine interactions, or distribute distinct, on-voice variations across
  your team, each approved by a real person and published on a stagger through
  LinkedIn's official API.
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

- **Two real workflows.** Amplify points a roster of people at one existing post
  (like, comment, reshare). Distribute turns a seed into M variations your
  teammates publish, then runs interactions across all of them.
- **Genuine variety.** When the model helps, it drafts distinct variations and
  varied interaction text from lightweight tone and length hints, not one post
  reworded six ways. People can also hand-write everything.
- **Real approval.** Each person approves, edits, or skips their own post in one
  tap from the web app (Slack coming next). Nothing publishes without them.
- **Official API only.** No scraping and no credential capture. Posts and
  reshares run on each member's own LinkedIn consent (`w_member_social`).
  Comments and likes need `w_member_social_feed` (LinkedIn's Community
  Management API); until that access lands they run assisted-manual: super-hype
  deep-links the person to the post with the suggested text and they comment or
  like in their own browser, then mark it done. Flip
  `COMMUNITY_MANAGEMENT_ENABLED` to automate them through the API.
- **Concentrated reach.** Approved posts publish on a randomized stagger,
  clustered in the first ninety minutes, never all at once.

## How it works

1. **Choose a workflow.** Amplify an existing post by pasting its URL, or
   distribute a seed (URL and/or pasted text) into variations.
2. **Plan and generate.** Assign people and actions (post, comment, like,
   reshare). Optionally let the model draft variations and interaction text, or
   write them yourself.
3. **Approve and publish on a stagger.** Each person approves, edits, or skips
   their own post; approved work goes out through LinkedIn's official
   `/rest/posts` API on a randomized schedule.

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
uv run alembic upgrade head            # create the schema
uv run python -m scripts.seed          # insert the default writing skill
uv run uvicorn app.main:app --reload   # API on http://localhost:8000

# Worker (in a second shell): runs generation and publishing
cd backend
uv run arq app.workers.arq_app.WorkerSettings

# Frontend (in a third shell)
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

The worker is required: generation, launch fan-out, and publishing all run as
ARQ jobs, so drafts and published posts only appear once it is running.

The API serves `GET /healthz`. Interactive docs live at `/docs` and `/redoc` in
local/dev (disabled when `ENV` is production). Detailed setup, including external
app registration, is in [`backend/README.md`](backend/README.md),
[`frontend/README.md`](frontend/README.md), and [`SETUP.md`](SETUP.md). For
enabling comments and likes (LinkedIn's vetted Community Management API), see
[`LINKEDIN_COMMUNITY_MANAGEMENT.md`](LINKEDIN_COMMUNITY_MANAGEMENT.md).

## Project status

See [`CHECKLIST.md`](CHECKLIST.md) for the full breakdown.

- [x] Scaffold, full data model, migrations, seed, reference API, themed UI shell, landing page
- [x] Google auth and users
- [x] LinkedIn connection and provider
- [x] Generation (post variations and interaction text)
- [x] Campaign lifecycle and worker (amplify + distribute, ARQ jobs)
- [ ] Slack approval
- [ ] Dashboard and polish

## License

[MIT](LICENSE).
