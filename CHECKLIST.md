# super-hype build checklist

A living checklist of everything to build, derived from `DESIGN.md` (section 19 phases) and `BACKEND.md`. Keep this updated as work lands: flip the box and add a short note. Phases after 0 are scoped now but built later.

Status legend:

- `[ ]` not started
- `[~]` in progress
- `[x]` done
- `[-]` deferred or intentionally out of v1 scope

Cross-cutting decisions (apply everywhere): package root `app/`; `/v1` prefix (health is unprefixed `GET /healthz`); strict layering view -> controller -> service -> repository -> model; everything async; every list endpoint paginated; every externally triggered mutation writes an `audit_log` row; tokens Fernet-encrypted at rest and never logged.

---

## Phase 0: Scaffold and data model (CURRENT)

Goal: a runnable skeleton plus the full data model. No auth, LinkedIn, generation, worker, or Slack logic. Auth-adjacent modules are stubbed just enough for imports to resolve.

Backend scaffold:

- [x] uv project `pyproject.toml` (requires-python >=3.13; deps via `uv add`; ruff/mypy/black config)
- [x] `app/config.py` pydantic-settings reading `backend/.env`, all SETUP.md keys optional, `is_production`, parsed `bootstrap_admin_emails` (no `lang_pref`, per decision)
- [x] `app/logger.py` structlog `get_logger`
- [x] `app/db/base.py` DeclarativeBase + naming convention + UUID pk and timestamp mixins
- [x] `app/db/session.py` async engine (pool size/overflow from settings, 10s connect timeout), `async_sessionmaker`, `get_db`
- [x] `app/main.py` app factory, structlog init, router registration, CORS to `FRONTEND_URL`
- [x] `app/main.py` `lifespan`: ping Postgres (`SELECT 1`) and Redis (`PING`, 10s timeouts) on startup; abort startup with a clear error if either is unreachable (graceful fail-fast), dispose engine on shutdown

Data model (DESIGN.md section 7; all indexes declared on the models):

- [x] `app/models/user.py` (unique `email`, unique `google_sub`; `lang_pref` dropped)
- [x] `app/models/social_account.py` (unique `(user_id, platform)`, index `status`, index `expires_at`)
- [x] `app/models/writing_skill.py` (partial unique index on `is_default` where true, index `is_archived`)
- [x] `app/models/campaign.py` (index `created_by`, `status`, `created_at`)
- [x] `app/models/post.py` (index `campaign_id`, `user_id`; composites `(campaign_id, status)`, `(user_id, status)`; index `external_id`; unique `idempotency_key`)
- [x] `app/models/audit_log.py` (composite `(campaign_id, created_at)`, index `created_at`)
- [x] `app/models/slack_identity.py` (index `slack_user_id`)

Core (stubs unless noted):

- [x] `app/core/crypto.py` real Fernet encrypt/decrypt from `TOKEN_ENCRYPTION_KEY`
- [x] `app/core/security.py` stub `create_access_token` / `decode_access_token` (signatures only)
- [x] `app/core/deps.py` stub `get_current_user` / `require_role` so the campaigns route resolves

Reference slice wired end to end (campaigns, keyset on `(created_at, id)`):

- [x] `app/schemas/common.py` `PageParams` dep (limit default 20, bounded 1-100, `cursor`) and generic `Page[T]`
- [x] `app/schemas/campaign.py` `CampaignOut`
- [x] `app/repositories/base.py` `BaseRepository[ModelT]` with keyset `paginate`
- [x] `app/repositories/campaign_repo.py` singleton `campaign_repo.paginate`
- [x] `app/controllers/campaign_controller.py` `list_campaigns`
- [x] `app/views/health.py` `GET /healthz` returns ok
- [x] `app/views/campaigns.py` `GET /v1/campaigns` (thin)
- [x] `app/views/__init__.py` `api_router`

Migrations and seed:

- [x] Async Alembic: `alembic.ini`, `migrations/env.py` importing `Base.metadata` with asyncpg + naming convention
- [x] Initial migration creating the full schema with every index (reviewed; applied to remote `super-hype` DB)
- [x] `app/seed.py` idempotent: default `Super-Hype Post Writer` skill (instructions = `SKILL.md` body) + bootstrap admin users

Infra:

- [x] `backend/Dockerfile` uv multi-stage (+ `.dockerignore`)
- [x] `backend/.env.example` full SETUP.md key set
- [-] `docker-compose.yml` (skipped: DB and Redis are remote, run via CLI)

Frontend:

- [x] Vite + React 18 + TS scaffold, npm (`package-lock.json`)
- [x] Tailwind + shadcn (`components.json`), `frontend/.env` `VITE_API_BASE_URL`
- [x] Section 14 design tokens in `tailwind.config.ts` + `globals.css` (incl. `--ok`/`--pending`/`--fail`), shadcn CSS vars, radius 10-12px
- [x] Fraunces wordmark, Inter UI
- [x] Static `AppShell` (`--sand` sidebar, header wordmark) at `/app`
- [x] Themed marketing landing at `/` (hero, signature post preview, how-it-works, features, footer) with `GoogleSignInButton` (visual + redirect to `/v1/google/login`; OAuth wired in Phase 1)
- [x] `vite` pinned to stable `^5.4.11` (was incorrectly `^8`, invalid peer with `@vitejs/plugin-react@4`)

Phase 0 tests (pytest + pytest-asyncio), 12 passing:

- [x] config loads from env and parses `bootstrap_admin_emails`
- [x] `core/crypto` encrypt/decrypt round-trips and ciphertext is not plaintext
- [x] keyset pagination: `Page` envelope, `limit` capped at 100, `next_cursor` fetches next page with no overlap or gap
- [x] `GET /healthz` returns ok
- [x] `app.seed` is idempotent (re-run inserts no duplicates)
- [x] models metadata imports and the partial unique default-skill index exists

---

## Phase 1: Auth and users

- [ ] `app/views/auth.py` `/v1/google/login`, `/v1/google/callback` (fastapi-sso, code in body)
- [ ] `app/schemas/auth.py` `GoogleCallbackBody`, `TokenResponse`
- [ ] `app/controllers/auth_controller.py` `complete_google_login` (company-domain check, bootstrap admin vs viewer, upsert, no duplicate user, drop trial/subscription logic)
- [ ] `app/core/security.py` real JWT create/decode carrying `user_id`, `email`, `role`; short lifetime
- [ ] `app/core/deps.py` real `get_current_user`, `require_role(*roles)`
- [ ] `app/repositories/user_repo.py` `get_by_email_and_provider`, `set_role`, `list_all`, `count_admins`
- [ ] `app/schemas/user.py` `UserOut`, `RoleUpdate`
- [ ] `app/controllers/user_controller.py`
- [ ] `app/views/users.py` `GET /v1/users` (admin), `PATCH /v1/users/{id}` (admin) with last-admin demotion guard + audit
- [ ] `app/repositories/audit_repo.py` `record(...)` (used by role change)
- [ ] Frontend: wire `GoogleSignInButton` to the real OAuth handoff + callback handling (landing page already built in Phase 0), Users admin page, auth context, JWT storage, protected routes
- [ ] Tests: viewer 403 on `POST /v1/campaigns`; non-admin 403 on `PATCH /v1/users/{id}`; last-admin guard; callback rejects non-company domain; bootstrap email -> admin, normal -> viewer; existing user reused; `create_access_token`/`decode_access_token` round-trip, expired/tampered -> 401; `require_role` admits and rejects

---

## Phase 2: LinkedIn connection and provider

- [ ] `app/views/connections.py` list, `linkedin/authorize`, `linkedin/callback`, `linkedin/reconnect`, `DELETE linkedin` (all require current user)
- [ ] `app/schemas/connection.py` `LinkedInCallbackBody`, `ConnectionOut`, `AuthorizeUrlOut`
- [ ] `app/controllers/connection_controller.py` authorize/complete/disconnect with Redis-bound CSRF state
- [ ] `app/services/linkedin_oauth_service.py` `authorize_url`, `exchange_code`, `fetch_identity`, `refresh`, `revoke`
- [ ] `app/repositories/social_account_repo.py` `get_by_user`, `upsert`, `mark_stale`, `delete`
- [ ] Redis client/util for state and queue
- [ ] `app/providers/base.py` `Provider` Protocol
- [ ] `app/providers/linkedin.py` publish (versioned `/rest/posts`, headers), link-in-first-comment sequence, `comment`, `like`, reshare-with-comment, three-step image upload, `refresh`
- [ ] 401 -> mark stale -> `request_reconnect` path; 429 retryable-with-delay; bounded backoff on other 5xx
- [ ] Frontend: Connections page with Connect/Reconnect and stale banner
- [ ] Tests: `authorize` stores state in Redis; callback rejects missing/foreign state; stored token is ciphertext; disconnect deletes row + audit; provider publish-then-first-comment order and headers; idempotent publish (no double post); image uploaded under post's own author and `image_asset_urn` reused on retry; `link_placement` routes link to body vs first comment

---

## Phase 3: Skills and generation

- [ ] `app/views/skills.py` CRUD (`DELETE` = archive), `app/schemas/skill.py`, `app/controllers/skill_controller.py`
- [ ] `app/repositories/writing_skill_repo.py` `get_default`, `list_active`, `set_default`
- [ ] `app/integrations/llm.py` `AsyncOpenAI(base_url=LLM_GATEWAY_URL, api_key=LLM_API_KEY)`
- [ ] `app/services/generation_service.py` build system+user messages, model from skill or `LLM_MODEL_NAME`, `response_format=json_object`, parse defensively, validate against pydantic output contract, write posts rows
- [ ] Output-contract pydantic schema (hero_post, variants, comments)
- [ ] Regenerate: discard non-edited drafts, never touch approved/published
- [ ] Frontend: Skills page + monospace instructions editor; Compose skill swapper; TipTap editor; live LinkedIn-accurate preview
- [ ] Tests: parser on valid fixture and on malformed output (job fails cleanly), gateway mocked via the OpenAI client

---

## Phase 4: Campaign lifecycle and worker

- [ ] `app/services/campaign_service.py` state machine `draft -> generating -> review -> approved -> publishing -> completed` (+ `failed`)
- [ ] `app/repositories/campaign_repo.py` `get_with_posts`, `paginate_for_user`, `set_status`
- [ ] `app/repositories/post_repo.py` `paginate_for_campaign`, `list_pending_for_user`, `mark_published`, `mark_failed`
- [ ] `app/views/campaigns.py` full (create, get, generate, regenerate, patch, approve) + `app/views/posts.py` (patch, approve, skip) with controller ownership rules
- [ ] `app/workers/arq_app.py` `WorkerSettings`, on_startup pools
- [ ] `app/workers/jobs.py` `generate_drafts`, `launch_campaign`, `notify_person`, `publish_post` (idempotent, per-author image upload), `send_reminders`, `request_reconnect`, daily expiry-sweep cron
- [ ] Stagger delay drawn from `[stagger_min_seconds, stagger_max_seconds]`
- [ ] Idempotency-key guard end to end
- [ ] Audit row on every mutation
- [ ] Frontend: Compose two-pane, Campaign detail
- [ ] Tests: state-machine transitions; idempotent publish does not double-post; stagger scheduling

---

## Phase 5: Slack approval

- [ ] `app/integrations/slack.py` Block Kit builders, DM send, `users.lookupByEmail`
- [ ] `app/views/slack.py` `/v1/slack/events`, `/v1/slack/interactions`; `app/controllers/slack_controller.py`
- [ ] `slack_identities` mapping populated on first DM
- [ ] Slack request signature verification on every inbound call; ack within 3s, work in a job
- [ ] Approve/Edit/Skip route to the same approval API; reconnect DM
- [ ] Reminders sweep; full web fallback for all actions
- [ ] Tests: signature verification; interaction routing to approve/skip; Edit modal updates post

---

## Phase 6: Dashboard and polish

- [ ] Dashboard: campaigns list with status + current user's pending approvals on top
- [ ] Campaign detail: per-post status, audit timeline, "what published" summary
- [ ] Empty and error states as direction
- [ ] Mobile responsiveness
- [ ] Accessibility: visible `--clay` focus ring, reduced-motion respected
- [ ] Frontend component tests: composer, skill swapper, preview renders exact published text

---

## Cross-cutting tooling

- [x] Pre-commit (`.pre-commit-config.yaml`): black (format) + ruff (lint, with `--fix`) + basic hygiene hooks. ruff runs lint and import-sorting only; black owns formatting; line-length aligned at 88.
- [x] ruff + mypy + black config in `pyproject.toml` (Phase 0; ruff allows `Depends`/`Query` defaults, keeps `Generic[T]`)
- [x] pytest + pytest-asyncio harness (Phase 0); `tests/conftest.py` fixtures `db`, `client` (SQLite, hermetic). `as_role`, `auth_headers` grow in Phase 1+
- [ ] CI: `ruff check .`, `black --check .`, `mypy app`, `pytest`; frontend typecheck, lint, build (wired alongside Phase 1)
- [-] DEPLOY.md / TrueFoundry deployment (deferred to a deployment pass)
