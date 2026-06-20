# super-hype: Design Document

Human-in-the-loop employee advocacy for LinkedIn. One organization, many employees, real people approving real posts, with an LLM doing the writing and an orchestrator doing the timing.

This document is written to be handed to Claude Code for implementation. It specifies architecture, data model, contracts, and conventions. Build to it; do not improvise structure. Where a decision is genuinely open it is called out under "Open decisions."

---

## Table of contents

1. Goals and non-goals
2. Scope
3. Core concepts
4. System architecture
5. Tech stack
6. Repository layout
7. Data model
8. Backend design
9. LinkedIn integration
10. Generation and the skill swapper
11. Campaign lifecycle and orchestration
12. Slack approval flow
13. Frontend design
14. Design system (the look)
15. Security
16. Configuration
17. Deployment
18. Testing
19. Implementation phases
20. Open decisions

---

## 1. Goals and non-goals

### Goal
Make it effortless for a 100-person team to amplify a company announcement on LinkedIn with genuine, varied, well-written engagement concentrated in the first 60 to 90 minutes, without anyone hand-writing posts or coordinating manually.

The flow in one line: an admin drops in a raw announcement, picks a writing style, the system drafts a hero post plus a distinct variant and comment for each person, the admin approves, each person gets a one-tap approval in Slack or the web app, and the system publishes through LinkedIn's official API on a staggered schedule.

### Non-goals
- No browser automation, scraping, or credential capture. Every LinkedIn action goes through the official API with the member's own OAuth consent. The human approval step is what keeps engagement genuine and within LinkedIn's API terms; it is load-bearing, not decorative.
- No company-page automation in v1 (that needs the Community Management API and a separate review; see section 9).
- No X/Twitter in v1 (deferred; the provider layer leaves room for it).
- No engagement-analytics scraping. Reading members' post metrics needs the closed `r_member_social` permission, which we do not have. The dashboard reports what the tool did, not the resulting reach. See section 7.

---

## 2. Scope

In scope for v1:
- Google OAuth login (via fastapi-sso) restricted to the company domain, with admin, editor, and viewer roles. New users default to viewer.
- Per-user LinkedIn connection via the Share on LinkedIn product (`w_member_social`).
- Writing skills: CRUD-managed LLM generation profiles, swappable per campaign.
- Campaign composer: brief in, drafts out, per-person editing, approval.
- Orchestrated publishing: staggered, retried, audited; original posts, reshares with comment, comments, and likes.
- Slack approval and reconnect flow, with a web fallback for both.
- A dashboard of what the tool did (who approved, what published, when).

Deferred (build seams, do not implement): X provider, company-page posting, programmatic engagement analytics, multi-org tenancy.

---

## 3. Core concepts

- **User**: a company employee. Authenticates with Google. Has a role.
- **Role**: `viewer` (the default for every new user: connect their own LinkedIn and approve, edit, or skip only their own posts), `editor` (everything a viewer can do, plus create and edit campaigns, generate drafts, and manage writing skills), `admin` (everything an editor can do, plus manage users and assign roles, and launch campaigns). New users are always `viewer`; only an admin can raise a user to `editor` or `admin`. See BACKEND.md for the full permission matrix and role management. In practice the roles map to teams: founder's office and GTM leads are admins, the GTM team are editors, and everyone else (developers and the wider team) stays a viewer.
- **Social account**: a user's connected LinkedIn identity, holding encrypted OAuth tokens.
- **Writing skill** (retired): originally a named, editable set of generation instructions. Removed in the interaction-first reframe; generation now uses lightweight per-campaign hints (tone, length, language). See CHECKLIST.md.
- **Campaign**: one announcement and the set of posts generated from it.
- **Post**: one unit of work for one person on one platform, with an action type (`post`, `repost_comment`, `comment`, `like`) and a lifecycle status.

---

## 4. System architecture

```
                         +-------------------------+
   Browser (React SPA) --+--> FastAPI (REST + OAuth callbacks)
                         |        |        |
   Slack (DMs, buttons) -+--------+        |
                                  |        |
                          +-------v---+ +--v--------+
                          | Postgres  | |  Redis    |
                          | (state)   | | (queue +  |
                          +-----------+ |  cache)   |
                                  ^     +--+--------+
                                  |        |
                          +-------+--------v---------+
                          |  ARQ worker (jobs)       |
                          |  generate / fan-out /    |
                          |  publish / remind /      |
                          |  reconnect               |
                          +-----------+--------------+
                                      |
                  +-------------------+------------------+
                  |                   |                  |
            LLM gateway        LinkedIn API         Slack API
            (generation)       (publish/engage)     (DMs/buttons)
```

The web API never performs slow or external work inline. Generation, publishing, fan-out, and reminders all run as ARQ jobs on the worker. The API enqueues and returns. This keeps request latency low and makes retries and rate-limit handling tractable.

### Data flow for one campaign
1. Editor creates a campaign (brief, image, link, hero account, writing skill).
2. Editor triggers generation. The API enqueues `generate_drafts`. The worker calls the LLM gateway with the skill instructions plus the roster, parses the structured JSON, and writes `posts` rows. Campaign status moves `generating` then `review`.
3. Editor reviews and edits drafts in the composer, optionally swaps the skill and regenerates.
4. Admin approves the campaign. The API enqueues `launch_campaign`, status moves to `publishing`.
5. `launch_campaign` schedules one `notify_person` job per post with a randomized delay inside the campaign's stagger window.
6. Each `notify_person` sends the person a Slack DM (and surfaces the same item in the web app) with Approve, Edit, and Skip.
7. On Approve (Slack interaction or web call), the API enqueues `publish_post`.
8. `publish_post` calls the LinkedIn provider, stores the resulting URN, and for an original post adds the link as the first comment. On a 401 it marks the account stale and enqueues `request_reconnect` for that one person. Other failures retry with backoff.
9. When all posts reach a terminal state, campaign status moves to `completed`.

---

## 5. Tech stack

Backend:
- Python 3.12+, managed with **uv** (uv for dependency resolution, locking, and running).
- **FastAPI** (async) for the API.
- **SQLAlchemy 2.0** async ORM, **Alembic** for migrations.
- **Pydantic v2** and **pydantic-settings** for schemas and config.
- **asyncpg** Postgres driver.
- **ARQ** for the Redis-backed job queue and cron.
- **httpx** (async) for LinkedIn and Slack calls.
- **openai** SDK for generation, pointed at an OpenAI-compatible LLM gateway via `base_url`. The gateway URL, key, and model name come from `LLM_GATEWAY_URL`, `LLM_API_KEY`, and `LLM_MODEL_NAME`.
- **cryptography** (Fernet) for token-at-rest encryption.
- **structlog** for structured logging; optional **sentry-sdk**.
- Tooling: **ruff** (lint and format), **mypy** (types), **pytest** with **pytest-asyncio** and **httpx** test client.

Frontend:
- **React 18** + **TypeScript**, built with **Vite**.
- **Tailwind CSS** + **shadcn/ui** (Radix primitives), themed to the warm palette in section 14.
- **TanStack Query** for server state, **React Router** for routing.
- **TipTap** (ProseMirror) for the composer editor.
- **lucide-react** icons, **sonner** for toasts, **react-hook-form** + **zod** for forms.

Infra:
- PostgreSQL 16, Redis 7.
- Docker and docker-compose; Caddy or nginx for TLS and reverse proxy in production.

---

## 6. Repository layout

A monorepo with two deployable apps. Each app has its own `agents.md` giving Claude Code the conventions and commands for that surface. The backend tree below is the high-level view; BACKEND.md holds the authoritative layered module structure (config, models, schemas, repositories, services, controllers, views) and takes precedence where the two differ.

```
super-hype/
├── DESIGN.md                  # this document
├── docker-compose.yml         # dev: postgres, redis, api, worker, web
├── docker-compose.prod.yml    # prod override: Caddy, gunicorn-style serving
├── .env.example
├── backend/
│   ├── agents.md
│   ├── pyproject.toml         # uv-managed
│   ├── uv.lock
│   ├── alembic.ini
│   ├── Dockerfile
│   ├── src/superhype/
│   │   ├── main.py            # app factory, router registration, middleware
│   │   ├── config.py          # Settings (pydantic-settings)
│   │   ├── db.py              # async engine, session dependency
│   │   ├── logging.py         # structlog setup
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # pydantic request/response models
│   │   ├── api/
│   │   │   ├── deps.py        # current_user, require_role, db session
│   │   │   ├── auth.py        # Google OAuth login/callback, session
│   │   │   ├── connections.py # LinkedIn connect/callback/reconnect
│   │   │   ├── skills.py
│   │   │   ├── campaigns.py
│   │   │   ├── posts.py
│   │   │   ├── slack.py       # events + interactions webhooks
│   │   │   └── users.py       # admin user management
│   │   ├── services/
│   │   │   ├── generation.py  # build prompt, call the LLM gateway, parse JSON
│   │   │   ├── campaigns.py   # lifecycle transitions
│   │   │   └── crypto.py      # Fernet encrypt/decrypt of tokens
│   │   ├── providers/
│   │   │   ├── base.py        # Provider protocol
│   │   │   └── linkedin.py    # OAuth, publish, comment, like, refresh
│   │   ├── integrations/
│   │   │   ├── llm.py         # OpenAI-compatible gateway client
│   │   │   └── slack.py       # Block Kit builders, DM send
│   │   └── workers/
│   │       ├── arq_app.py     # ARQ WorkerSettings, on_startup pools
│   │       └── jobs.py        # generate, fan-out, publish, remind, reconnect
│   ├── migrations/            # alembic versions
│   └── tests/
└── frontend/
    ├── agents.md
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.ts
    ├── components.json        # shadcn config
    ├── .env.example
    └── src/
        ├── main.tsx
        ├── App.tsx            # router + providers
        ├── lib/               # api client, query client, auth, utils
        ├── components/ui/     # shadcn components
        ├── components/        # Composer, SkillSwapper, PostCard, PreviewPane, ...
        ├── pages/             # Login, Dashboard, CampaignCompose, CampaignDetail,
        │                      #   Skills, Connections, Users, Settings
        ├── hooks/
        └── styles/globals.css # theme tokens
```

---

## 7. Data model

Postgres. UUID primary keys, `created_at` and `updated_at` on every table, soft-delete only where noted. All timestamps are `timestamptz`. Token columns are encrypted bytes, never plaintext.

```sql
-- users
id              uuid pk
email           text unique not null      -- enforced company domain
name            text
avatar_url      text
google_sub      text unique               -- Google OAuth subject
role            text not null default 'viewer'  -- admin | editor | viewer
lang_pref       text not null default 'en'
is_active       boolean not null default true
created_at, updated_at

-- social_accounts (one LinkedIn identity per user in v1)
id                uuid pk
user_id           uuid not null references users
platform          text not null default 'linkedin'
external_urn      text                    -- urn:li:person:xxxx
display_name      text
access_token_enc  bytea not null          -- Fernet
refresh_token_enc bytea                    -- nullable; may not be issued
scopes            text[]
expires_at        timestamptz
status            text not null default 'active'  -- active | stale | revoked
connected_at, updated_at
unique (user_id, platform)

-- writing_skills (the swappable generation profiles)
id           uuid pk
name         text not null
description  text
instructions text not null               -- the system prompt body
model        text                       -- optional per-skill override; defaults to LLM_MODEL_NAME
is_default   boolean not null default false
is_archived  boolean not null default false
created_by   uuid references users
created_at, updated_at

-- campaigns
id                  uuid pk
title               text not null
raw_brief           text not null
image_url           text                         -- shared campaign image (source)
image_alt           text                         -- alt text for the image
link                text
link_placement      text not null default 'first_comment'  -- body | first_comment
hero_account_id     uuid references social_accounts  -- who posts the hero
writing_skill_id    uuid references writing_skills
status              text not null default 'draft'
                    -- draft | generating | review | approved | publishing | completed | failed
stagger_min_seconds int not null default 600    -- 10 min
stagger_max_seconds int not null default 1800   -- 30 min
created_by          uuid references users
approved_by         uuid references users
approved_at         timestamptz
created_at, updated_at

-- posts (one action for one person)
id                 uuid pk
campaign_id        uuid not null references campaigns
user_id            uuid not null references users
social_account_id  uuid references social_accounts
platform           text not null default 'linkedin'
action             text not null    -- post | repost_comment | comment | like
target_external_id text             -- hero post URN, for comment/like/repost
angle              text             -- the per-person angle, for display
body               text             -- English text
body_native        text             -- localized text, nullable
lang               text
link               text
first_comment      text             -- link-in-first-comment content
image_asset_urn    text             -- per-author uploaded image URN, set at publish (null until then)
status             text not null default 'pending'
                   -- pending | approved | skipped | scheduled | publishing | published | failed
idempotency_key    text unique      -- guards against double-publish on retry
scheduled_at       timestamptz
published_at       timestamptz
external_id        text             -- resulting post/comment URN
error              text
retries            int not null default 0
created_at, updated_at

-- audit_log (append-only)
id           uuid pk
campaign_id  uuid references campaigns
post_id      uuid references posts
actor_id     uuid references users    -- null for system actions
action       text not null
             -- generated | approved | edited | skipped | published | failed
             --  | reconnect_requested | campaign_approved | ...
detail       jsonb
created_at

-- slack_identities (map app users to Slack)
user_id          uuid pk references users
slack_user_id    text not null
slack_dm_channel text
```

### Indexes
Index every foreign key, and every column used in a `WHERE` or `ORDER BY` on a list endpoint. Define these in the models (SQLAlchemy `index=True`, `Index(...)`, `UniqueConstraint`) so Alembic autogenerates them.
- `users`: unique on `email` and on `google_sub` (both already produce indexes).
- `social_accounts`: unique `(user_id, platform)` (also serves per-user lookups); index `status` (find stale accounts) and `expires_at` (the expiry sweep).
- `writing_skills`: a partial unique index on `is_default` where it is true (at most one default skill); index `is_archived`.
- `campaigns`: index `created_by`, `status`, and `created_at` (the last for keyset pagination).
- `posts`: index `campaign_id` and `user_id`; composites `(campaign_id, status)` for campaign progress and `(user_id, status)` for a person's pending posts; index `external_id` for the already-published check (`idempotency_key` is already unique).
- `audit_log`: composite `(campaign_id, created_at)` for the campaign timeline, and index `created_at`.
- `slack_identities`: index `slack_user_id` to resolve inbound Slack interactions to a user.

Note on analytics: there is deliberately no table for post engagement metrics. With `w_member_social` only, we cannot read members' post analytics. The dashboard derives everything from `posts` and `audit_log`. If the company later obtains the Community Management API, add an `engagement_snapshots` table and a polling job; the seam is the optional `Provider.insights` method.

---

## 8. Backend design

### Conventions
- Routers in `api/` are thin: validate input, check role, call a service or enqueue a job, return a pydantic response. No business logic or external calls in routers.
- Services in `services/` hold business logic and own the database transaction boundary.
- All I/O is async. Database sessions come from a FastAPI dependency that opens a session per request and rolls back on error.
- Every externally triggered mutation writes an `audit_log` row.

### Pagination
Every list endpoint is paginated; none returns an unbounded set. Use a shared `PageParams` dependency (`limit: int = 20`, bounded 1 to 100, plus a `cursor`) and a generic `Page[T]` response of `{ items, next_cursor }`. Prefer keyset (cursor) pagination on `(created_at, id)` for the high-volume lists (`posts`, `audit_log`, `campaigns`), since deep offsets get slow; the cursor encodes the last `(created_at, id)` seen, and the supporting indexes are listed in section 7. Small bounded lists (`skills`, `users`) may use simple `limit` and `offset`. Repository list methods take the page params and return the page plus the next cursor. The campaign detail endpoint does not embed all posts; it links to the paginated `GET /v1/campaigns/{id}/posts`.

### API surface

BACKEND.md is authoritative for the endpoint list, including the fastapi-sso login flow, the connect, reconnect, and disconnect routes, and role management. The sketch below uses an `/api` prefix for illustration; the implementation uses the `/v1` prefix from BACKEND.md.

Auth and session:
```
GET    /api/auth/google/login        -> 302 to Google consent
GET    /api/auth/google/callback     -> sets session cookie, 302 to app
POST   /api/auth/logout
GET    /api/me                        -> current user + connection status
```

LinkedIn connections:
```
GET    /api/connections                       -> list current user's accounts
GET    /api/connections/linkedin/connect      -> 302 to LinkedIn consent
GET    /api/connections/linkedin/callback     -> store tokens, 302 to app
POST   /api/connections/linkedin/reconnect    -> 302 to LinkedIn consent (re-auth)
DELETE /api/connections/{id}
```

Writing skills (editor or admin):
```
GET    /api/skills
POST   /api/skills
GET    /api/skills/{id}
PATCH  /api/skills/{id}
DELETE /api/skills/{id}        -> archive, not hard delete
```

Campaigns:
```
GET    /api/campaigns
POST   /api/campaigns
GET    /api/campaigns/{id}                 -> campaign + posts
POST   /api/campaigns/{id}/generate        -> enqueue generate_drafts
POST   /api/campaigns/{id}/regenerate      -> body: { skill_id } ; re-runs generation
PATCH  /api/campaigns/{id}                 -> edit brief, stagger, hero
POST   /api/campaigns/{id}/approve         -> admin only; enqueue launch_campaign
```

Posts (the approval actions, shared by Slack and web):
```
GET    /api/campaigns/{id}/posts
PATCH  /api/posts/{id}        -> edit body / body_native / first_comment
POST   /api/posts/{id}/approve  -> enqueue publish_post (must be owner or admin)
POST   /api/posts/{id}/skip
```

Slack and health:
```
POST   /api/slack/events         -> URL verification + events
POST   /api/slack/interactions   -> button clicks, modal submits
GET    /api/health
```

### Auth and RBAC
Authentication uses fastapi-sso for Google login and a JWT bearer token for the API. The full flow, the role model, the permission matrix, and role management are in BACKEND.md; the essentials:
- Login: the frontend opens `GET /v1/google/login` (fastapi-sso builds the consent redirect). Google redirects to a frontend route, which POSTs the authorization code to `POST /v1/google/callback` with the code in the request body, not the query string, so it cannot leak into access logs or Referer headers. The backend exchanges it, verifies the email is on the company domain, upserts the user (new users get the viewer role, or admin if their email is in the bootstrap-admin list), and returns a signed JWT.
- The JWT carries `user_id`, `email`, and `role`. `core.deps.get_current_user` decodes the bearer token and loads the active user; `core.deps.require_role(...)` returns 403 on insufficient role. A viewer may act only on posts where `post.user_id == current_user.id`.

### Idempotency and retries
- Every `posts` row gets an `idempotency_key` at creation. The LinkedIn publish call passes it so that a retried job cannot create a duplicate post. The worker treats an already-published row (non-null `external_id`) as a no-op.
- Publish failures other than auth use exponential backoff with a small retry cap. Auth failures (401) do not retry; they mark the account stale and trigger reconnect.

---

## 9. LinkedIn integration

### Product and scopes (decided)
Use the **Share on LinkedIn** product, which grants `w_member_social` (post, comment, and like on the member's own behalf) and is self-serve with no partner review. Request scopes `w_member_social` and `r_basicprofile`. Do not request more; adding scopes later forces every member to re-consent. The company page and member analytics are out of scope (they need the Community Management API, which is review-gated and mutually exclusive with Share on LinkedIn on the same app).

### OAuth flow
- Authorize at `https://www.linkedin.com/oauth/v2/authorization` with `response_type=code`, the client id, the redirect URI `{APP_URL}/api/connections/linkedin/callback`, a CSRF `state` stored in the session, and the scope string.
- Exchange the code at `https://www.linkedin.com/oauth/v2/accessToken` for an access token (60-day lifetime) and, if issued, a refresh token (up to 365 days). Verify in the LinkedIn Token Inspector whether a refresh token is actually returned for this app; do not assume it.
- Fetch the member's person URN (basic profile) and store it. Encrypt both tokens with Fernet before persisting.

### Token lifecycle and reconnect
- Before any call, if `expires_at` is near and a refresh token exists, refresh silently.
- If no refresh token is issued, or a call returns 401, set `social_accounts.status = 'stale'` and enqueue `request_reconnect(user_id)`, which DMs that one person a reconnect link. Tokens last 60 days, so within a single campaign window nobody re-auths mid-flight; reconnect only matters between campaigns and is surgical, never a mass re-auth.

### Provider interface
```python
class Provider(Protocol):
    async def publish(self, acct: SocialAccount, text: str, *,
                      link: str | None = None,
                      link_in_body: bool = False,
                      image_urn: str | None = None,
                      reshare_of: str | None = None) -> str: ...   # returns post URN
    async def upload_image(self, acct: SocialAccount, data: bytes, *,
                      alt: str | None = None) -> str: ...   # returns urn:li:image owned by acct
    async def comment(self, acct: SocialAccount, target_urn: str, text: str) -> str: ...
    async def like(self, acct: SocialAccount, target_urn: str) -> None: ...
    async def refresh(self, acct: SocialAccount) -> Tokens: ...
    async def insights(self, acct: SocialAccount, urn: str) -> dict: ...  # not implemented in v1
```

### LinkedIn specifics for `linkedin.py`
- Publish through the versioned Posts API: `POST https://api.linkedin.com/rest/posts`. Always send headers `LinkedIn-Version: <YYYYMM>` (for example `202606`) and `X-Restli-Protocol-Version: 2.0.0`. The author is the member person URN. The legacy `/v2/ugcPosts` endpoint is deprecated for new apps; do not use it.
- Link placement: `link_placement` decides where the link goes. With `first_comment` (the default), publish the text without the link, then add the link as a comment on the returned URN, and store both URNs; this protects reach. With `body`, include the URL in the commentary and LinkedIn auto-generates the preview card, at some cost to reach. The composer toggles this per campaign.
- Reshare with comment (`repost_comment`): create a post that references the hero post URN via the reshare field, with the person's comment as the commentary.
- Comment (`comment`) and like (`like`): act on `target_external_id` (the hero URN) through the social actions endpoints, under `w_member_social`.
- Respect the rate ceiling of roughly 100 calls per member per day; track per-account call counts and surface 429s as retryable-with-delay.
- Images (in v1): a three-step upload. Call `POST /rest/images?action=initializeUpload` with `{ initializeUploadRequest: { owner: <author person URN> } }`, which returns an `uploadUrl` and an `urn:li:image:...`; PUT the raw bytes to that URL; then create the post with `content: { media: { id: <that urn>, altText: <alt> } }`. Carousels of 2 to 20 images upload each one first. The catch: the image asset is owned by whoever initialized the upload, and a post can only reference an image its own author owns, so each participant's image must be uploaded under that participant's own token. See the publish job in section 11.

---

## 10. Generation and the skill swapper

### The skill is the system prompt
A writing skill's `instructions` field is a complete generation brief. The default skill is the "Super-Hype Post Writer" already authored for this system. Editors can create others (for example an SEO or thought-leadership style) entirely through the UI; no code change is needed to add a style. That is the whole point of the swapper.

### Generation call (`services/generation.py`)
Generation goes through the OpenAI SDK pointed at the company LLM gateway. Construct an `AsyncOpenAI(base_url=LLM_GATEWAY_URL, api_key=LLM_API_KEY)` client (wrapped in `integrations/llm.py`) and call `chat.completions.create`:
- messages: a `system` message holding the selected skill's `instructions`, and a `user` message holding a JSON brief assembled from the campaign and roster (the raw announcement, image caption, link, the hero account, and each person's name, role, language, and platform).
- model: the skill's `model` if set, otherwise `LLM_MODEL_NAME`. The per-skill field is an optional override so a style can pin a specific gateway model; most skills leave it blank and inherit the env default.
- response_format: request `{"type": "json_object"}` so the gateway returns JSON. Support varies across gateway-routed models, so still parse defensively.
- Instruct the model to return only the structured JSON contract below, no prose.

Parse defensively (strip any code fences, validate against a pydantic schema, fail the job with a clear error if it does not parse). Write one `posts` row per hero, variant, and comment. Set `idempotency_key`, `angle`, `body`, `body_native`, `lang`, `link`, `first_comment`, and `action`.

### Output contract (must match the skill)
```json
{
  "campaign": "string",
  "assumptions": "string",
  "hero_post": {
    "account": "string",
    "platform": "linkedin",
    "text": "string",
    "link_placement": "first_comment",
    "first_comment": "string",
    "hashtags": ["string"]
  },
  "variants": [{
    "person": "string", "role": "string", "platform": "linkedin",
    "action": "post | repost_comment",
    "angle": "string", "text_en": "string",
    "text_native": "string", "native_language": "string"
  }],
  "comments": [{
    "person": "string", "on": "hero_post",
    "text_en": "string", "text_native": "string", "native_language": "string"
  }]
}
```

### Regeneration
`POST /campaigns/{id}/regenerate` with a `skill_id` discards non-edited draft posts for that campaign and re-runs generation with the new skill. Posts a user has already approved or published are never touched.

---

## 11. Campaign lifecycle and orchestration

State machine: `draft -> generating -> review -> approved -> publishing -> completed`, with `failed` reachable from `generating` and `publishing`.

ARQ jobs (`workers/jobs.py`):
- `generate_drafts(campaign_id)`: calls generation, writes posts, sets status `review`.
- `launch_campaign(campaign_id)`: for each pending post, compute a delay drawn uniformly from `[stagger_min_seconds, stagger_max_seconds]` and enqueue `notify_person(post_id)` with that defer. Set status `publishing`. Enqueue `send_reminders(campaign_id)` for a follow-up sweep.
- `notify_person(post_id)`: send the Slack DM with Approve, Edit, Skip; mark the post `scheduled`. The same item appears in the web app's pending list.
- `publish_post(post_id)`: idempotent; resolve the provider. If the post carries an image and `image_asset_urn` is not yet set, upload the campaign image under this post's own author first (the owner must match), store the returned URN on the post, and skip this step on a retry. Then publish according to `action`: with `link_placement = first_comment` add the link as the first comment, with `body` include the link in the commentary for the preview card. Store `external_id`, set `published`. On 401 mark account stale and enqueue `request_reconnect`. On other failure increment `retries` and reschedule with backoff up to the cap, then `failed`.
- `send_reminders(campaign_id)`: after a configurable interval, DM anyone whose post is still `scheduled` (not yet acted on).
- `request_reconnect(user_id)`: DM the user a reconnect link; never blocks other users.
- Cron: a daily sweep that flags accounts whose `expires_at` is within a few days and pings those users to reconnect proactively.

The goal of the stagger is genuine engagement clustered in the golden hour, not the appearance of coordination. Keep the defaults at 10 to 30 minutes and make them per-campaign editable.

---

## 12. Slack approval flow

A Slack app with interactivity enabled, pointing at `/api/slack/interactions`, and bot scopes for DMs.

- `notify_person` posts a Block Kit DM: the campaign title, the rendered post text (and the native-language version below it when present), and three buttons: Approve, Edit, Skip. Approve and Skip carry the `post_id` in the action value.
- Approve calls the same logic as `POST /posts/{id}/approve` and enqueues `publish_post`. Skip marks the post `skipped`. Edit opens a Slack modal prefilled with the text; on submit it updates the post and re-renders the DM.
- `request_reconnect` posts a DM with a single button linking to `/api/connections/linkedin/reconnect`.
- Verify the Slack request signature on every inbound call. Respond within 3 seconds; do the real work in a job.

Slack is one client of the approval API, not a hard dependency. The web app exposes the same Approve, Edit, and Skip actions on a per-user "Your pending posts" view, so the system is fully usable without Slack.

---

## 13. Frontend design

A React SPA talking to the API with a JWT bearer token, server state via TanStack Query, forms via react-hook-form and zod.

Who uses it: the people who live in this web app, composing campaigns, reviewing drafts, and managing skills and users, are the GTM team and the founder's office, not engineers. The wider team are viewers whose real touchpoint is the one-tap Slack approval; most of them rarely open the web UI. Design for that primary audience, approachable and polished for non-engineers, with the part they spend the most time in, reading and tweaking post copy, made pleasant.

Pages:
- **Login**: a single calm screen, "Continue with Google."
- **Dashboard**: campaigns list with status, plus the current user's pending approvals surfaced at the top.
- **Compose** (`/campaigns/new` and `/campaigns/:id`): the heart of the product. A two-pane layout. Left: the brief (title, announcement, an image with alt text, the link plus a body-or-first-comment placement toggle), the hero account selector, and the skill swapper. Right: a live, LinkedIn-accurate preview that updates as drafts arrive and as the user edits, rendering the attached image or carousel and the link as either a preview card (body placement) or a "link in first comment" chip. A "Generate" action fills the right pane with the hero card and one card per person; each card is editable in place and shows the person, their angle, and, for non-English speakers, both language versions. A "Regenerate with this skill" control sits next to the swapper.
- **Campaign detail**: status of every post (pending, approved, published, failed), the audit timeline, and a "what published" summary.
- **Skills**: list and editor. The instructions field uses a monospace, full-height editor (the system prompt body). A "Set as default" toggle.
- **Connections**: the user's LinkedIn status with Connect or Reconnect, and a clear stale-state banner.
- **Users** (admin): roster, roles, and invites.

Editor: TipTap with a deliberately minimal extension set. LinkedIn posts publish as plain text with line breaks (LinkedIn does not render markdown, and unicode-bold tricks hurt readability and accessibility), so the editor's job is comfortable authoring plus an accurate preview and a live character count, not rich formatting that gets published. Support line breaks, emoji, image upload with alt text, link insertion governed by the placement toggle (body or first comment), and a hashtag affordance. The preview renders exactly what will be posted.

Copy follows the writing guidance: name things by what the person controls, use active voice, keep one verb per action through the whole flow (a button that says "Approve" produces a toast that says "Approved"), and treat empty and error states as direction rather than mood.

---

## 14. Design system (the look)

The brief is explicit: the warm, calm Claude aesthetic in beige. Follow it precisely. This is a focused internal work tool, so the direction is quiet and disciplined; spend the one note of warmth on the composer's preview, which is the screen people will live in. Dark mode is a later nice-to-have, not part of v1: the GTM and founder's-office audience does not require it, and the viewers who might are in Slack.

### Palette (named, 4 to 6 values)
```
--paper      #FAF9F5   /* app background, warm near-white */
--surface    #FFFFFF   /* cards, slightly lifted from paper */
--sand       #EFEBE0   /* muted panels, hover fills, the left rail */
--border     #E4DFD3   /* hairline borders, dividers */
--ink        #23211C   /* primary text, warm near-black */
--muted      #6F6B61   /* secondary text */
--clay       #D97757   /* the single accent: primary buttons, active state, focus ring */
--clay-press #C15F3C   /* pressed/hover for clay */
--ok         #2E7D32   /* status: published, a clear readable green */
--pending    #B26A00   /* status: pending, a clear amber */
--fail       #C0392B   /* status: failed, a clear red */
```
Use `--clay` sparingly. It marks the primary action and the current state, nothing else. Everything else is paper, sand, ink, and border. Status is the exception that must read at a glance: `--ok`, `--pending`, and `--fail` are deliberately crisp and clearly different from one another, since a user scanning twenty posts has to tell published from failed instantly. Tone them just enough to sit on the warm surface, but never so muted that two states blur together, and always pair status with an icon, not color alone.

### Typography
Two roles, paired deliberately rather than a single default sans:
- Display and product name: a warm serif used with restraint, for example **Fraunces** or **Newsreader**, only for page titles and the wordmark. Do not build a giant high-contrast serif hero; that is the generic look and the wrong register for a work tool.
- UI and body: a humanist sans, for example **Inter** or **Hanken Grotesk**, for everything functional.
- Data and counts: the same sans with tabular figures.
Set a clear, restrained scale. Sentence case everywhere. Generous line height in the composer.

### Form
Soft, not heavy: border-radius around 10 to 12px on cards and inputs, hairline `--border` instead of drop shadows (a single very soft shadow only on overlays and modals), generous whitespace, a quiet left rail in `--sand`. Theme shadcn/ui by overriding its CSS variables to the tokens above rather than fighting its defaults. Honor a quality floor: responsive to mobile, visible keyboard focus (a `--clay` ring), and reduced-motion respected.

### Signature
The composer's split view is the memorable screen: the brief on the left, and on the right the hero post plus the fan of per-person preview cards rendering exactly as they will appear on LinkedIn, updating live as the model writes and as the user edits. Keep everything around it calm so this one moment carries the product's personality.

Avoid the generic cream-plus-serif-plus-terracotta template by grounding every choice in this tool's job (calm, fast approval of real posts), not in decoration: no numbered eyebrows unless a real sequence exists, no ambient motion, no stat-grid hero.

---

## 15. Security

- LinkedIn tokens encrypted at rest with Fernet; the key comes from the environment (or a secrets manager) and is never committed. Tokens never appear in logs.
- OAuth: CSRF `state` for both Google and LinkedIn, stored in the session and verified on callback. Verify the Google ID token signature and the email domain server-side.
- Sessions: HTTP-only, Secure, SameSite cookies. CORS locked to the known frontend origin. CSRF protection on state-changing API calls if cookie-based auth is used.
- Verify Slack request signatures on every inbound webhook.
- Secrets via environment only, 12-factor. Distinct dev and prod configuration via `config.py`.
- Audit log is append-only and records actor, action, and target for every mutation.

---

## 16. Configuration

All via environment. `backend/.env.example` lists the full set; the essentials:
```
APP_URL=                       # public base URL
DATABASE_URL=                  # postgresql+asyncpg://...
REDIS_URL=
JWT_SECRET=
TOKEN_ENCRYPTION_KEY=          # Fernet key
COMPANY_EMAIL_DOMAIN=          # restrict Google login
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_API_VERSION=202606    # the YYYYMM version header
LLM_GATEWAY_URL=               # OpenAI-compatible base URL for the gateway
LLM_API_KEY=
LLM_MODEL_NAME=
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
SENTRY_DSN=                    # optional
```
Frontend reads only `VITE_API_BASE_URL`.

---

## 17. Deployment

- Four processes: API (uvicorn workers), the ARQ worker, Postgres, and Redis, with Caddy in front for TLS in production.
- `docker-compose.yml` for local development (postgres, redis, api with reload, worker, web with Vite dev server). `docker-compose.prod.yml` overrides to serve the built SPA behind Caddy and run the API without reload.
- Backend image is a multi-stage uv build: install with `uv sync --frozen`, copy the venv, run uvicorn. The worker shares the image and runs `arq superhype.workers.arq_app.WorkerSettings`.
- Migrations run on deploy with `alembic upgrade head` before the API starts.
- The frontend builds to static assets (`vite build`) served by Caddy.

---

## 18. Testing

- Backend: pytest with pytest-asyncio. Unit-test services and the LinkedIn provider against mocked httpx transports (assert correct endpoints, headers, and the link-in-first-comment sequence). Integration-test the API with the httpx test client against a test Postgres. Test the campaign state machine transitions and the idempotency guard (a retried publish does not double-post). Mock the LLM gateway call with a fixed JSON fixture and test the parser, including malformed output.
- Frontend: component tests for the composer and skill swapper; the preview must render the exact published text.
- CI: ruff, mypy, and pytest on the backend; typecheck, lint, and build on the frontend.

---

## 19. Implementation phases

Build in this order; each phase should end runnable.

0. **Scaffold**: monorepo, uv backend, Vite frontend, docker-compose, health check, structlog, the theme tokens from section 14 wired into Tailwind and shadcn.
1. **Auth and users**: Google OAuth login restricted to the company domain, session, RBAC dependencies, the Users admin page.
2. **LinkedIn connection and provider**: OAuth connect and callback, encrypted token storage, the `linkedin.py` provider (publish, first comment, comment, like, image upload, refresh), the Connections page, and the reconnect flow including the 401 to stale to reconnect path.
3. **Skills and generation**: writing-skills CRUD with the instructions editor, the LLM generation service and parser, the composer with the skill swapper, TipTap editor, and the live LinkedIn preview.
4. **Campaign lifecycle and worker**: the state machine, ARQ jobs for generate, launch, notify, publish, remind, and reconnect, staggering, idempotency (including the per-author image upload), and the audit log.
5. **Slack approval**: the Slack app, DMs with Approve, Edit, Skip, the interactions webhook, reminders, and reconnect DMs, with the web fallback for all of it.
6. **Dashboard and polish**: campaign detail with the audit timeline and "what published" summary, empty and error states, mobile responsiveness, and accessibility passes.

---

## 20. Open decisions

- **Session strategy**: decided. JWT bearer tokens issued by fastapi-sso after Google login (see BACKEND.md). No server-side session store; the token carries `user_id`, `email`, and `role`. Keep the token lifetime short.
- **Refresh tokens from Share on LinkedIn**: confirm in the Token Inspector whether a refresh token is issued. If yes, silent refresh is primary and Slack reconnect is the fallback. If no, Slack reconnect is primary. The code supports both; this only changes which path is common.
- **Image posting**: decided. Images are in v1 via the three-step upload, uploaded under each participant's own token at publish time (the image owner must match the post author). Link placement (body or first comment) is also in v1, defaulting to first comment.
- **Package manager (frontend)**: npm, pnpm, or bun. Recommendation: pnpm.
