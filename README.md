<p align="center">
  <img src="assets/banner-compressed.jpg" alt="super-hype" width="100%" />
</p>

<h1 align="center">super-hype</h1>

<p align="center">
  <strong>Turn one announcement into a wave of posts that read as real.</strong>
</p>

<p align="center">
  Human-in-the-loop employee advocacy platform for LinkedIn and X. Amplify an
  existing post with genuine interactions, or distribute distinct, on-voice
  variations across your team, each approved by a real person and published on a
  stagger through the platform's official API. A campaign targets one platform.
</p>

<p align="center">
  <a href="#quickstart"><img src="https://img.shields.io/badge/Quickstart-C0613F?style=for-the-badge" alt="Quickstart" /></a>
  <a href="backend/README.md"><img src="https://img.shields.io/badge/Backend_setup-2B2B2B?style=for-the-badge" alt="Backend setup" /></a>
  <a href="frontend/README.md"><img src="https://img.shields.io/badge/Frontend_setup-2B2B2B?style=for-the-badge" alt="Frontend setup" /></a>
</p>

<p align="center">
  <a href="https://github.com/S1LV3RJ1NX/superHype/actions/workflows/ci.yml"><img src="https://github.com/S1LV3RJ1NX/superHype/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT" />
  <img src="https://img.shields.io/badge/python-3.13+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.13+" />
  <img src="https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black" alt="React 18" />
  <img src="https://img.shields.io/badge/Postgres-4169E1.svg?logo=postgresql&logoColor=white" alt="Postgres" />
  <img src="https://img.shields.io/badge/Redis-DC382D.svg?logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/code%20style-ruff%20%2B%20black-000000.svg" alt="ruff + black" />
</p>

---

## Features

- **Two advocacy workflows.** Amplify points a roster at one existing post (each
  does a like, a comment, and a reshare). Distribute turns a seed into a distinct
  on-voice post per participant, then has everyone like and comment on everyone
  else's post, with an optional author self-comment ("link in the comments").
- **Per-persona AI generation.** Drafts distinct post variations and varied
  interaction text tuned to each participant's team voice, with a comment-quality
  floor and a hard ban on buzzwords, generic praise, and em dashes.
- **Content rules.** An admin-editable global rules document (Markdown) is
  injected into every campaign's generation; campaign creators can add
  campaign-specific rules and toggle whether the global rules apply.
- **Human-in-the-loop approval.** Everyone approves, edits, or skips their own
  actions, from the web app or a bundled Slack DM (one approve/skip for everything
  they owe a campaign). Nothing publishes without them.
- **Slack loop.** Bundled approve/skip at launch, a bundled mark-all-done for the
  assisted like and comment step, deferred reminders, and a reconnect prompt on a
  stale token.
- **Two platforms, one per campaign.** Pick LinkedIn or X when you create a
  campaign; generation, connections, and the action vocabulary adapt (a comment
  is a reply on X, a reshare is a quote post, a like carries a bookmark). No
  cross-posting: a campaign runs on exactly one platform.
- **Official API only.** Every action runs on each member's own consented
  account (LinkedIn `w_member_social`, or X OAuth 2.0 with `tweet.write`,
  `like.write`, and `bookmark.write`); tokens are Fernet-encrypted at rest. On
  X every action is fully automated through the API. On LinkedIn comments and
  likes run assisted-manual until the Community Management API is enabled.
- **Authentic pacing.** Approved posts publish on a randomized stagger with
  per-account spacing and daily caps, so a coordinated push never reads as a bot
  pod. Publishing is idempotent and never double-posts on retry.
- **Campaign controls.** Pause and resume a launched campaign, reset it to re-run,
  and (admins) delete; queued jobs are flushed so nothing stale fires.
- **Onboarding and roles.** Google login (company domain only), team selection,
  and a connect step: LinkedIn is required, X is optional (offered only when the
  deployment has X configured). Cumulative roles (viewer, editor, admin) with
  fine-grained ownership; participants see and edit only their own posts.
- **Leaderboard.** Ranks members by a weighted contribution score over an optional
  date window.
- **Audit trail.** Every externally triggered mutation writes an append-only audit
  row.

## Why I built this

Startups do not lose because the product is bad. They lose because nobody hears
about it. You ship something you are proud of, you hit post, and it lands to
crickets, because the LinkedIn feed rewards a wave of real people talking, not
one lonely company update.

So the founder does what every founder does: drops the link in the team channel
and asks everyone to "please like and comment." It half works. Some people miss
it. Some paste the same canned line five minutes apart, which the algorithm reads
as a pod and the audience reads as fake. Some forget. The launch that deserved a
week of momentum gets a Tuesday afternoon and then goes quiet.

The tools that claim to fix this are built for enterprise marketing teams: they
scrape, they ask for your password, they auto-generate the same soulless post for
everyone, and they treat your teammates as broadcast bots rather than people with
their own voice and their own consent. That is exactly the thing that makes
advocacy feel gross.

I wanted the opposite. super-hype turns one announcement into genuine, varied
advocacy from the people who actually built the thing:

- Every action runs on each person's own consented account through the official
  API. No scraping, no shared logins, no credential capture.
- The words are theirs. Drafts are tuned to each person's team voice, and nobody
  publishes anything they did not approve, edit, or skip.
- It reads as real. Posts and interactions go out on a randomized stagger with
  spacing and daily caps, so a coordinated push never looks like a bot pod.

It started as a way to make our own launches actually travel without nagging the
team or faking engagement. LinkedIn is the first channel because that is where
B2B distribution lives, and the design generalizes to more channels next.

## Why super-hype

Most teams ship something and post "excited to announce." It reads like a press
release and the algorithm treats it like one. super-hype does the opposite: it
turns a single internal announcement into genuine, varied advocacy from the
people who actually built the thing, without the spam.

- **Two real workflows.** Amplify points a roster of people at one existing post
  (each does a like, a comment, and a reshare). Distribute turns a seed into a
  distinct on-voice post for every participant, then has everyone like and
  comment on everyone else's post, with an optional author self-comment ("link
  in the comments").
- **Genuine variety.** The model drafts distinct variations and varied
  interaction text, tuned to each participant's team voice (persona), not one
  post reworded six ways. People still approve, edit, or skip their own.
- **Real approval.** Each person approves, edits, or skips their own actions in one
  tap, from the web app or a bundled Slack DM (one Approve all / Skip all for
  everything they owe a campaign). Nothing publishes without them.
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

1. **Choose a workflow.** Amplify an existing post by pasting its URL (plus the
   post text), or distribute a seed idea (pasted text, optional link and image).
2. **Pick participants and generate.** Choose the people or teams; the backend
   expands each into the concrete actions for that workflow (no manual row
   assignment) and the model drafts the on-voice variations and interaction
   text, applying your global and per-campaign content rules. Every draft stays
   editable.
3. **Approve and publish on a stagger.** Each person approves, edits, or skips
   their own post; approved work goes out through the platform's official API
   (LinkedIn `/rest/posts` or the X v2 endpoints) on a randomized schedule.

## Architecture

A monorepo with two deployables and remote managed datastores.

| Part | Stack |
| --- | --- |
| `backend/` | Python 3.13, FastAPI (async), SQLAlchemy 2.0 + asyncpg, Alembic, Pydantic v2, ARQ worker, structlog, managed with `uv` |
| `frontend/` | Vite, React 18, TypeScript, Tailwind CSS, shadcn/ui |
| Data | PostgreSQL (state), Redis (queue + OAuth state) |
| External | LinkedIn API, X (Twitter) API v2, Google OAuth, an OpenAI-compatible LLM gateway, Slack |

The backend follows strict layering: `view -> controller -> service -> repository
-> model`. Everything is async, every list endpoint is paginated, slow and
external work runs in the ARQ worker, and every externally triggered mutation
writes an `audit_log` row. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for
the authoritative reference on topology, data model, auth, and the publishing
pipeline.

## Quickstart

Prerequisites: [`uv`](https://docs.astral.sh/uv/) with Python 3.13+, Node.js 20+,
and reachable Postgres and Redis instances.

```bash
# Backend
cd backend
cp .env.example .env          # fill in DATABASE_URL, REDIS_URL, etc.
uv sync
uv run alembic upgrade head            # create the schema
uv run python -m app.seed              # bootstrap admin users + default teams
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
[`frontend/README.md`](frontend/README.md), and [`docs/SETUP.md`](docs/SETUP.md).
For enabling comments and likes (LinkedIn's vetted Community Management API), see
[`docs/LINKEDIN_COMMUNITY_MANAGEMENT.md`](docs/LINKEDIN_COMMUNITY_MANAGEMENT.md).

## Project status

Development is essentially complete. The full Slack loop is live: bundled
approve/skip at launch, a bundled mark-all-done for the assisted like and comment
step, a deferred reminder for anyone still outstanding, and a reconnect DM on a
stale token. The one remaining nice-to-have is a recurring scheduler so reminders
fire on a cadence rather than once per launch.

- [x] Scaffold, full data model, migrations, seed, reference API, themed UI shell, landing page
- [x] Google auth, onboarding, users, teams and personas
- [x] LinkedIn connection and provider (posts, reshares, images, video)
- [x] X (Twitter) connection and provider (tweets, quote posts, replies, likes, bookmarks, media; OAuth 2.0 PKCE with worker-side token refresh)
- [x] Generation (per-persona post variations and interaction text)
- [x] Content rules (admin-editable global rules + per-campaign rules and toggle)
- [x] Campaign lifecycle and worker (amplify + distribute, ARQ jobs)
- [x] Campaign controls (pause/resume, reset to re-run, admin delete, queue flush)
- [x] Self-comment ("link in the comments") as a tracked, assisted step
- [x] Assisted-manual comments and likes (until Community Management API access lands)
- [x] Leaderboard
- [x] Slack bundled approval (one Approve all / Skip all DM per participant)
- [x] Slack assisted engagement bundle (one Mark all done DM for like and comment)
- [x] Slack reminders (deferred re-nudge) and reconnect prompts
- [ ] Recurring reminder scheduler (cron cadence)

## License

[MIT](LICENSE).
