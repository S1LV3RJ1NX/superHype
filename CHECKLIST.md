# super-hype build checklist

A living checklist of everything to build, derived from `DESIGN.md` and `BACKEND.md`. Keep this updated as work lands: flip the box and add a short note.

Status legend:

- `[ ]` not started
- `[~]` in progress
- `[x]` done
- `[-]` deferred or intentionally out of v1 scope

Cross-cutting decisions (apply everywhere): package root `app/`; `/v1` prefix (health is unprefixed `GET /healthz`); strict layering view -> controller -> service -> repository -> model; everything async; every list endpoint paginated; every externally triggered mutation writes an `audit_log` row; tokens Fernet-encrypted at rest and never logged.

---

## Scaffold and data model (done)

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
- [-] `app/models/writing_skill.py` (removed in the interaction-first reframe; see "Campaign lifecycle and worker")
- [x] `app/models/campaign.py` (reshaped: `type` amplify|distribute, `seed_url`/`seed_urn`/`seed_content`, hints `tone`/`length`/`language`/`extra_instructions`, `launched_by`/`launched_at`; dropped `writing_skill_id`/`hero_account_id`/`approved_*`; index `created_by`, `status`, `created_at`)
- [x] `app/models/post.py` (added `target_post_id` self-FK and per-variation `image_asset_id`/`image_url`/`image_alt`; index `campaign_id`, `user_id`, `target_post_id`; composites `(campaign_id, status)`, `(user_id, status)`; index `external_id`; unique `idempotency_key`)
- [x] `app/models/asset.py` (uploaded image bytes in a dedicated `assets` table; bytes never selected except to serve/publish)
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
- [x] `app/seed.py` idempotent: bootstrap admin users (the default-skill seed was removed with the writing-skill feature)

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
- [x] Themed marketing landing at `/` (hero, signature post preview, how-it-works, features, footer) with `GoogleSignInButton` (redirect to `/v1/google/login`)
- [x] `vite` pinned to stable `^5.4.11` (was incorrectly `^8`, invalid peer with `@vitejs/plugin-react@4`)

Scaffold tests (pytest + pytest-asyncio):

- [x] config loads from env and parses `bootstrap_admin_emails`
- [x] `core/crypto` encrypt/decrypt round-trips and ciphertext is not plaintext
- [x] keyset pagination: `Page` envelope, `limit` capped at 100, `next_cursor` fetches next page with no overlap or gap (now auth-gated)
- [x] `GET /healthz` returns ok
- [x] `app.seed` is idempotent (re-run inserts no duplicates)
- [x] models metadata imports and the partial unique default-skill index exists
- [x] docs disabled in production, enabled outside production

---

## Auth and users (done)

- [x] `app/views/auth.py` `/v1/google/login` (returns `authorization_url` JSON), `/v1/google/callback` (fastapi-sso, code in body)
- [x] `app/schemas/auth.py` `GoogleCallbackBody`, `TokenResponse`
- [x] `app/controllers/auth_controller.py` `complete_google_login` (company-domain check, bootstrap admin vs viewer, upsert, no duplicate user, updates name/avatar/google_sub on returning user)
- [x] `app/core/security.py` real JWT create/decode (PyJWT, HS256) carrying `user_id`, `email`, `role`; 12h default lifetime via `ACCESS_TOKEN_EXPIRE_MINUTES`
- [x] `app/core/deps.py` real `get_current_user` (HTTPBearer), `require_role(*roles)` (403 on mismatch)
- [x] `app/repositories/user_repo.py` `get_by_email`, `get_by_google_sub`, `set_role`, `count_admins`, inherited `paginate`
- [x] `app/schemas/user.py` `UserOut`, `RoleUpdate`
- [x] `app/controllers/user_controller.py` `list_users`, `get_me`, `change_role` (last-admin guard -> 409, audit row)
- [x] `app/views/users.py` `GET /v1/users/me` (any authed), `GET /v1/users` (admin), `PATCH /v1/users/{id}` (admin) with last-admin demotion guard + audit
- [x] `app/repositories/audit_repo.py` `record(...)` (used by role change)
- [x] Frontend: `GoogleSignInButton` fetches `/v1/google/login` and redirects to Google; `AuthCallback` at `/v1/google/callback` exchanges code and stores JWT; `AuthContext` (localStorage + `GET /v1/users/me`); `ProtectedRoute` gates `/app`; `AppShell` shows user avatar/name + sign out; nav links with active state; admin-only Users nav item
- [x] Frontend: Users admin page (`/app/users`) with role select and last-admin 409 error handling
- [x] Config: `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` added; `ENV` defaults to production
- [x] `audit_log.detail` uses `JSONB().with_variant(JSON(), "sqlite")` so AuditLog works in test SQLite
- [x] Tests (38 passing): JWT create/decode round-trip, expired/tampered -> 401; `require_role` admits and rejects; auth controller domain rejection, bootstrap admin, viewer default, existing user reused, inactive rejected; non-admin 403 on `GET /v1/users` and `PATCH /v1/users/{id}`; admin role change succeeds + writes audit; last-admin guard -> 409; `GET /v1/users/me`; user_repo `get_by_email`, `count_admins`, `set_role`
- [x] No migration needed (JSONB variant is Postgres-identical; autogenerate confirmed empty)

---

## LinkedIn connection and provider (done)

### Connection flow (done)
- [x] `app/views/connections.py` list, `linkedin/authorize`, `linkedin/callback`, `linkedin/reconnect`, `DELETE linkedin` (all require current user); authorize/reconnect take an optional `resume_post_id` query param
- [x] `app/schemas/connection.py` `LinkedInCallbackBody`, `ConnectionOut` (with optional `resumed_post_id`/`resumed_campaign_id`), `AuthorizeUrlOut`
- [x] `app/controllers/connection_controller.py` authorize/complete/disconnect with Redis-bound CSRF state
- [x] `app/services/linkedin_oauth_service.py` `authorize_url`, `exchange_code`, `fetch_identity`, `revoke`
- [x] `app/repositories/social_account_repo.py` `get_by_user`, `upsert`, `mark_stale`, `delete`
- [x] `app/core/redis.py` shared async Redis client; wired into lifespan shutdown
- [x] `app/providers/base.py` `Provider` Protocol (runtime_checkable stub)
- [x] `SocialAccount.scopes` ARRAY->JSON SQLite variant for test compatibility
- [x] Frontend: Connections page with Connect/Reconnect/Disconnect and stale banner
- [x] Frontend: LinkedIn OAuth callback page (`/connections/linkedin/callback`)
- [x] Tests (49 passing): authorize stores state in Redis; callback rejects missing/foreign state; callback returns 400 on LinkedIn HTTP error; stored token is ciphertext; disconnect deletes + audit; reconnect returns authorize URL; list connections empty and after connect; unauthenticated 401; Provider Protocol structural test
- [x] Pre-existing mypy false positive on pydantic-settings constructor fixed with `type: ignore[call-arg]`
- [x] Config test hardened with required env var fixture
- [x] Redis keys namespaced with `super-hype:` prefix to avoid collisions on a shared DB
- [x] Scopes: `w_member_social openid profile`. The spec named `r_basicprofile`, but LinkedIn deprecated it (apps after 2023-08-01 get `unauthorized_scope_error`). Identity now comes from OpenID Connect, so the member URN is read from `/v2/userinfo` (`sub` -> `urn:li:person:{sub}`). `email` is intentionally omitted.
- [x] Live verified against the real LinkedIn API: full authorize -> consent -> callback -> token exchange -> identity -> connected, with both products (Share on LinkedIn, Sign In with LinkedIn using OpenID Connect) enabled

### Reconnect-then-act (expiry-aware approve; portal done, Slack later)
- [x] `LINKEDIN_RECONNECT_BUFFER_HOURS` (default 24) and `SocialAccount.needs_reconnect(now, buffer_hours)` (stale, null/expired, or within the buffer)
- [x] `approve_post` pre-checks the post owner's account and returns `409 {"code": "linkedin_reconnect_required", "post_id": ...}` when re-consent is needed (the reactive 401 path stays as the safety net)
- [x] Authorize binds an optional `resume_post_id` into the Redis OAuth state (JSON, owner-bound, legacy bare-id tolerated); `complete_linkedin` resumes the approve on callback (owner-checked, idempotent, no-op if terminal) and enqueues `publish_post`, returning `resumed_post_id`/`resumed_campaign_id`
- [x] Frontend: `CampaignDetail` approve catches the 409 and redirects to authorize-with-`resume_post_id`; `LinkedInCallback` returns to the campaign when an action resumed; `ApiError` now carries the structured `detail`
- [x] Tests: `needs_reconnect` unit cases; approve 409 when missing/stale; callback resume happy path + owner mismatch + terminal no-op
- [-] Slack reconnect button deep-linking to authorize-with-resume (deferred to the Slack phase; reuses this primitive)

### Provider implementation (done)
- [x] `app/providers/linkedin.py` publish (versioned `/rest/posts`, `LinkedIn-Version` + `X-Restli-Protocol-Version` headers), `comment`, `like`, reshare-with-comment (via `reshareContext`), three-step image upload (`initializeUpload` -> PUT -> `urn:li:image`), `refresh`; injectable transport for tests
- [x] Typed errors: `LinkedInAuthError` (401, non-retryable), `LinkedInRateLimitError` (429, `retry_after`), `LinkedInAPIError` (other)
- [x] Wired in the worker: 401 -> mark account stale + enqueue `request_reconnect`; 429 -> deferred retry by `retry_after`; bounded exponential backoff to a cap on other errors; idempotent publish (no-op if `external_id` set); image uploaded under the post's own author and `image_asset_urn` reused on retry; `link_placement == "body"` routes the link into the commentary
- [x] `provider.delete_post(acct, urn)` (versioned `DELETE /rest/posts/{urn}`), used only to roll back a partial first-comment publish
- [x] Link-in-first-comment sequence: `link_placement == "first_comment"` publishes the body without the link, persists `external_id`, then places the link as the first comment. All-or-nothing and resumable via `posts.first_comment_external_id` (body committed before the comment so a retry never double-posts; resume picks up at the comment; on permanent comment failure the post is rolled back with `delete_post` then marked failed)
- [x] Tests (9 passing, mocked httpx): correct headers, link-in-body, three-step image upload, comment URN, 401 -> AuthError, 429 -> RateLimitError with `retry_after`, reshare uses `reshareContext`, `delete_post` issues versioned DELETE

---

## Skills and generation (skills retired in the interaction-first reframe)

> Reframe: the writing-skill feature was removed. People draft posts in ChatGPT/Claude; the product is an interaction orchestrator. The LLM is now repurposed to (a) generate M variations from a seed and (b) generate varied interaction text (comments / reshare commentary), governed by lightweight per-campaign tone/length/language hints. See "Campaign lifecycle and worker".

### Skills CRUD (removed)
- [-] `app/repositories/writing_skill_repo.py`, `app/schemas/skill.py`, `app/controllers/skill_controller.py`, `app/views/skills.py`, `app/models/writing_skill.py` deleted; skills router dropped from `app/views/__init__.py`; `Skills.tsx` page/route/nav removed

### LLM integration and generation service (done, rewritten)
- [x] `openai` package added (`uv add openai`)
- [x] `app/integrations/llm.py` `get_llm_client()` returning `AsyncOpenAI` pointed at `LLM_GATEWAY_URL`
- [x] `app/schemas/generation.py` rewritten to two small contracts: `VariationSet` (`{"variations": [...]}`), `InteractionTexts` (`{"texts": [...]}`); old hero/variant/comment/brief schemas deleted
- [x] `app/services/generation_service.py` rewritten: `generate_variations(seed, n, *, tone, length, language, extra)` and `generate_interactions(target_text, items, *, hints)`; `response_format=json_object`, strip fences, `json.loads`, validate, `_safe_exc` redaction, count normalization, `like` items skip the LLM; raises `GenerationError` on any failure
- [x] `app/prompts/` package: `generation.py` builders (`variations_system`, `interactions_system`, `_hint_block`) plus `BANNED_PHRASES`/`BANNED_COMMENT_OPENERS`; prompt text lives here, the service owns orchestration. Craft rules salvaged from the retired SKILL.md (hook-first, opinion over announcement, specificity, human voice, a reason to engage, no buzzwords)
- [x] Comment-quality floor: generated non-like interactions must clear `MIN_COMMENT_WORDS` and avoid generic praise / banned buzzwords; the service regenerates once, then raises `GenerationError`
- [-] `scripts/smoke_generation.py` removed with the skill-based flow

### Users LinkedIn-status column (done)
- [x] `social_account_repo.map_status_for_users(db, user_ids)` batch helper (avoids N+1)
- [x] `UserOut.linkedin_status` field (`active` | `stale` | `None`)
- [x] `user_controller.list_users` and `get_me` populate the field from batch query

### Frontend (done)
- [x] `Skills.tsx` page: left skill list (default badged with star), editor pane with name/description/monospace instructions textarea/model override, Save/Create, Set as default toggle, Archive button, 409 handling
- [x] `App.tsx` `/app/skills` route wired to `Skills` (was `Placeholder`)
- [x] `Users.tsx` LinkedIn column: green dot "Connected" for active, amber dot "Stale" for stale, muted "Not connected" for null

### Tests
- [-] `test_writing_skill_repo.py`, `test_skills.py`, `test_skill_test.py`, `test_generate_instructions.py` removed with the skills feature
- [x] `test_generation.py` (10): variations count enforced, padded when too few, fenced JSON parses, non-JSON raises GenerationError, interaction texts indexed to items with `like` empty, all-likes skips the LLM, bad contract raises GenerationError, comment-floor fails after retry on short/banned text, regenerates once then succeeds
- [x] `test_users.py` extended (2): list_users returns linkedin_status=active for connected user, None for unconnected
- [x] `test_config.py` env fixture extended with `LLM_GATEWAY_URL`, `LLM_API_KEY`, `LLM_MODEL_NAME`

---

## Campaign lifecycle and worker (done, interaction-first reframe)

> Two campaign types share one `posts` table and one publish job. **Amplify** (1 x N): interactions on an existing external post. **Distribute** (M x N): generate or hand-write M variations, publish them, then run interactions across all of them (interactions link to the local variation via `target_post_id`). RBAC: amplify create/launch/generate = any role; distribute create/generate = editor+. Launch is per-participant gated (each person approves their own post), so there is no `approved` state and no admin campaign sign-off.

### Model and storage (done)
- [x] `app/models/asset.py` + `app/storage/base.py` (`AssetStore` Protocol) + `app/storage/db_store.py` (Postgres `bytea` backend, swappable to object storage later)
- [x] `app/core/linkedin_urn.py` `parse_post_urn(url)` for pasted LinkedIn URLs (share/copy-link, embed, and feed forms; preserves the activity/share/ugcPost namespace)
- [x] Migration `7f3a9c2b1d04`: drop `writing_skills`, drop campaign hero/skill/approval columns, add campaign type/seed/hints + `launched_*`, add `posts.target_post_id`/`image_asset_id`/`image_url`/`image_alt`, create `assets`
- [x] Migration `8a1c4e7d9b20`: add `posts.first_comment_external_id` (URN of the link-in-first-comment; doubles as the resume/idempotency marker)

### Service (done)
- [x] `app/services/campaign_service.py` state machine `draft -> generating | review`, `generating -> review | failed`, `review -> generating | publishing`, `publishing -> completed | failed` (no `approved` state); `transition` (validate + audit), `build_plan` (manual or LLM fill; variation `post` rows + interaction rows; unique idempotency keys `{cid}:{action}:{user}:{seq}`; rebuild preserves approved/published work), `check_completion`
- [x] `app/repositories/campaign_repo.py` `set_status`, `count_by_status`, `paginate_for_user` (creator/participant/admin visibility)
- [x] `app/repositories/post_repo.py` `paginate_for_campaign`, `list_for_campaign`, `list_pending_for_user`, `mark_published`, `mark_failed`, `bulk_create`, `delete_unlocked_for_campaign`, `all_terminal`

### API (done)
- [x] `app/views/campaigns.py` list, `POST` create (controller gates distribute to editor+), `GET /{id}` (creator/admin/participant), `PATCH /{id}` (creator/admin, draft/review only), `POST /{id}/plan` (manual assignments), `POST /{id}/generate` (LLM; amplify any role, distribute editor+; enqueues `generate_drafts`), `POST /{id}/launch` (creator/admin; enqueues `launch_campaign`)
- [x] `app/views/posts.py` `GET /v1/campaigns/{id}/posts`, `PATCH /v1/posts/{id}`, `POST /v1/posts/{id}/approve` (enqueues `publish_post`), `POST /v1/posts/{id}/skip`; owner-or-admin enforced in `post_controller`
- [x] `app/views/assets.py` `POST /v1/assets` (multipart, editor+, image + 8 MB validation), `GET /v1/assets/{id}` (serve with cache headers); `python-multipart` added
- [x] `app/views/users.py` `GET /v1/users/roster` (any authed) for participant selection

### Worker (done)
- [x] `arq` added; `app/workers/queue.py` enqueue helper + pool; `app/core/redis.py` `get_arq_redis_settings()`
- [x] `app/workers/arq_app.py` `WorkerSettings` (functions, redis, startup/shutdown engine dispose)
- [x] `app/workers/jobs.py` `generate_drafts` (build_plan with LLM; on `GenerationError` -> `failed`), `launch_campaign` (transition `publishing`, stagger fan-out of `notify_person`, enqueue `send_reminders`), `notify_person` (mark scheduled), `publish_post` (idempotent, dependency-aware self-defer until target post is live, per-author image upload, action dispatch, first-comment placement + rollback, 401 -> stale + `request_reconnect`, 429 -> delayed retry, bounded backoff, `check_completion`), `send_reminders`/`request_reconnect` stubs
- [x] Authenticity guardrails in `publish_post`: per-account daily action cap (`MAX_ACTIONS_PER_ACCOUNT_PER_DAY`) and minimum spacing between actions (`MIN_SECONDS_BETWEEN_ACCOUNT_ACTIONS`), enforced by deferral (re-enqueue) before the outbound call so a coordinated push does not read as a pod; the first-comment resume step is exempt. Backed by `post_repo.published_times_for_account`
- [x] Stagger delay drawn from `[stagger_min_seconds, stagger_max_seconds]`
- [x] Idempotency-key on every post; publish is a no-op once `external_id` is set
- [x] Audit row on create, plan, status change, launch, edit, approve, skip, publish, first-comment placed, rollback
- [-] Daily expiry-sweep cron (deferred; not needed until token-expiry handling lands)

### Frontend (done)
- [x] `Campaigns.tsx` list with status badges + pagination + amplify/distribute create form (distribute gated to editors); nav + routes wired in `App.tsx`/`AppShell.tsx`
- [x] `CampaignDetail.tsx` two-pane: seed + plan builder (Save plan / Generate) + Launch on the left; posts grouped with inline edit and per-post Approve/Skip + publish progress bar on the right
- [x] Reusable `.input` component class added to `globals.css`

### Tests (128 backend passing; frontend `tsc` + `vite build` clean)
- [x] `test_linkedin_urn.py` (4): feed + posts URL forms, bare URN passthrough, junk -> None
- [x] `test_campaign_service.py` (7): legal/illegal transitions; amplify targets seed URN; distribute links `target_post_id`; unique idempotency keys; rebuild keeps published; `check_completion` (and no-op when pending)
- [x] `test_campaigns_api.py` (7): viewer creates amplify, viewer 403 on distribute, editor creates distribute, detail counts, generate enqueues + `generating`, launch requires review + enqueues, list shows only own
- [x] `test_posts_api.py` (5): owner edit+approve enqueues publish, non-owner 403, skip, double-approve 409, missing 404
- [x] `test_assets_api.py` (4): upload+serve round-trip, viewer 403, non-image 415, oversize 413
- [x] `test_worker_jobs.py` (15): generate happy/fail, launch stagger range + enqueue, publish idempotent no-op, like completes campaign, distribute interaction defers until target live, 401 -> stale + reconnect, 429 re-enqueues with `retry_after`, generic backoff then fail, first-comment places link, first-comment resumes after body, body placement skips comment, first-comment permanent failure rolls back, defers on min-gap, defers on daily cap
- [x] Migrations are hand-written (deterministic) rather than `--autogenerate`; `7f3a9c2b1d04` and `8a1c4e7d9b20` applied via `alembic upgrade head`

---

## Slack approval

- [ ] `app/integrations/slack.py` Block Kit builders, DM send, `users.lookupByEmail`
- [ ] `app/views/slack.py` `/v1/slack/events`, `/v1/slack/interactions`; `app/controllers/slack_controller.py`
- [ ] `slack_identities` mapping populated on first DM
- [ ] Slack request signature verification on every inbound call; ack within 3s, work in a job
- [ ] Approve/Edit/Skip route to the same approval API; reconnect DM
- [ ] Reminders sweep; full web fallback for all actions
- [ ] Tests: signature verification; interaction routing to approve/skip; Edit modal updates post

---

## Dashboard and polish

- [ ] Dashboard: campaigns list with status + current user's pending approvals on top
- [ ] Campaign detail: per-post status, audit timeline, "what published" summary
- [ ] Empty and error states as direction
- [ ] Mobile responsiveness
- [ ] Accessibility: visible `--clay` focus ring, reduced-motion respected
- [ ] Frontend component tests: composer, skill swapper, preview renders exact published text

---

## Cross-cutting tooling

- [x] Pre-commit (`.pre-commit-config.yaml`): black (format) + ruff (lint, with `--fix`) + basic hygiene hooks. ruff runs lint and import-sorting only; black owns formatting; line-length aligned at 88.
- [x] ruff + mypy + black config in `pyproject.toml` (ruff allows `Depends`/`Query` defaults, keeps `Generic[T]`)
- [x] pytest + pytest-asyncio harness; `tests/conftest.py` fixtures `db`, `client` (SQLite, hermetic), `as_role`, `auth_headers`
- [ ] CI: `ruff check .`, `black --check .`, `mypy app`, `pytest`; frontend typecheck, lint, build
- [-] DEPLOY.md / TrueFoundry deployment (deferred to a deployment pass)
