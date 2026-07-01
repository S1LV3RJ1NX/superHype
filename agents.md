# agents.md: backend

Operating manual for `backend/`. Read this and `../BACKEND.md` before writing code. `../DESIGN.md` is the system overview; `../BACKEND.md` is the authoritative backend spec and wins on structure, roles, auth, and connections.

## What this is
The super-hype API and worker. FastAPI (async) for the REST API and OAuth callbacks, an ARQ worker for all slow and external work, Postgres for state, Redis for the queue and OAuth state. Managed with uv. Package root is `app/`.

## Stack
Python 3.12+, FastAPI, fastapi-sso (Google login), SQLAlchemy 2.0 async, Alembic, Pydantic v2 + pydantic-settings, asyncpg, ARQ, httpx (LinkedIn and Slack), the openai SDK (generation, pointed at the LLM gateway), cryptography (Fernet), structlog. Lint and format with ruff, types with mypy, tests with pytest + pytest-asyncio.

## Commands (use uv, not pip or poetry)
```
uv sync
uv add <pkg>
uv run uvicorn app.main:app --reload
uv run arq app.workers.arq_app.WorkerSettings
uv run alembic revision --autogenerate -m "msg"
uv run alembic upgrade head
uv run python -m scripts.seed
uv run pytest
uv run ruff check . && uv run ruff format .
uv run mypy app
```

## Layering (strict; one job per layer)
Request flow: view -> controller -> service -> repository -> model. A layer only calls the layer directly below it.
```
app/
  config.py        Settings (pydantic-settings); all config from env
  logger.py        structlog get_logger
  core/            security.py (JWT), deps.py (get_current_user, require_role), crypto.py (Fernet)
  db/              base.py (DeclarativeBase + naming convention), session.py (engine, get_db)
  models/          SQLAlchemy ORM, one module per aggregate; declare indexes here
  schemas/         pydantic request/response (the API boundary speaks schemas, not ORM)
  repositories/    all DB access; one singleton repo per aggregate; methods take db first
  services/        business logic + external side effects; own multi-step transactions
  controllers/     per-resource request handling; enforce fine-grained authorization
  views/           FastAPI routers; thin; declare deps, parse schema, call controller
  providers/       base.py (Protocol) + linkedin.py
  integrations/    llm.py (OpenAI SDK against the gateway), slack.py
  workers/         arq_app.py (WorkerSettings) + jobs.py
```

## Patterns that are load-bearing
- **Thin views.** A view declares the route and its dependencies (auth, role), parses the body into a schema, calls a controller, returns a schema. No logic, no DB, no external calls in views.
- **Controllers enforce ownership.** Route-level `require_role(...)` is the coarse gate; the controller enforces the fine rule (a viewer acts only on their own post, an editor launches only their own campaign). Never trust the UI for this.
- **Services own transactions and side effects.** Generation, OAuth exchange, lifecycle. Repositories do not commit; the controller or service does.
- **Repositories are the only DB layer.** One singleton per aggregate (`user_repo`, `social_account_repo`, ...), async methods with `db` first, returning models.
- **Auth is JWT bearer via fastapi-sso.** Login flow in `views/auth.py` and `controllers/auth_controller.py`: fastapi-sso redirects to the frontend, the frontend posts the code in the body to `POST /v1/google/callback`, the backend verifies the company domain, assigns a role (viewer, or admin if the email is in `BOOTSTRAP_ADMIN_EMAILS`), and returns a JWT carrying `user_id`, `email`, `role`. Drop any trial or subscription logic from the sample; this is an internal tool.
- **Three roles.** viewer (default), editor, admin; cumulative. Only admins change roles via `PATCH /v1/users/{id}`; guard against demoting the last admin. One exception: self-service team selection (`PATCH /v1/users/me`) auto-grants editor when a viewer joins a company-acting team (Founder's Office, GTM, Marketing and Sales). This only ever elevates viewer to editor, never demotes, and writes a `role_change` audit row. It is an intentional onboarding convenience, so any viewer can self-elevate to editor by picking one of those teams; keep this in mind when tightening role controls.
- **Generation via the LLM gateway.** Use the openai SDK in `integrations/llm.py`: `AsyncOpenAI(base_url=settings.LLM_GATEWAY_URL, api_key=settings.LLM_API_KEY)`. Call `chat.completions.create` with a system message holding the skill's `instructions` and a user message holding the JSON brief. Model is the skill's `model` if set, otherwise `settings.LLM_MODEL_NAME`. Request `response_format={"type": "json_object"}`, but parse defensively (strip fences, validate against a pydantic schema, fail the job on malformed output). Do not import or use the anthropic SDK.
- **Pagination and indexes.** Every list endpoint is paginated through a shared `PageParams` dependency returning a `Page[T]` (`items`, `next_cursor`); prefer keyset pagination on `(created_at, id)` for `posts`, `audit_log`, and `campaigns`. Declare all indexes on the models (see DESIGN.md section 7), including the partial unique index for the single default skill and the composites that back pagination, so Alembic emits them.
- **Everything async.** `async def` and await all I/O. httpx async clients for LinkedIn and Slack; the async openai client for the gateway.
- **No slow work in requests.** Generation, publishing, fan-out, reminders are ARQ jobs. The API enqueues and returns.
- **Idempotent publishing.** Every `posts` row has an `idempotency_key`; `publish_post` is a no-op if `external_id` is already set. A retry must never double-post.
- **Token encryption.** LinkedIn tokens are Fernet-encrypted via `core/crypto.py` before they touch the database. Never log a token. Never store plaintext.
- **Audit everything.** Every externally triggered mutation writes an `audit_log` row.
- **`/v1` prefix** on all routes.

## LinkedIn connection and provider rules
- Connect, reconnect, disconnect live in `views/connections.py` and `controllers/connection_controller.py`. The LinkedIn redirect URI points at the frontend; the frontend posts `{ code, state }` back. CSRF state is stored in Redis bound to the user (no cookie session), validated on callback.
- Disconnect revokes (best effort) then deletes the row and audits it. Reconnect reuses the authorize flow and resets the account to active.
- Publish via `POST /rest/posts` with headers `LinkedIn-Version` (from `LINKEDIN_API_VERSION`) and `X-Restli-Protocol-Version: 2.0.0`. Do not use the deprecated `/v2/ugcPosts`.
- Link placement is set by `link_placement`: `first_comment` (default) publishes the text and adds the link as the first comment for reach; `body` puts the URL in the commentary for the auto preview card. Keep both URNs when using the first comment.
- Images upload via `POST /rest/images?action=initializeUpload` (owner is the post's author), then PUT the bytes, then reference `content.media.id`. The image owner must match the post author, so in the publish job upload the campaign image under each participant's own token, store `image_asset_urn`, and skip re-upload on retry. Carousels are 2 to 20 images.
- 401 is non-retryable: mark the account `stale` and enqueue `request_reconnect`. 429 is retryable-with-delay. Other 5xx use bounded exponential backoff.
- Scopes are `w_member_social` and `r_basicprofile` only. Do not add scopes; it forces every member to re-consent.

## Don't
- Do not call external APIs from inside a view; go through a controller and service, and push slow work to a job.
- Do not introduce a second ORM, a sync DB driver, or a Celery/RQ queue; the stack is ARQ + SQLAlchemy async.
- Do not use the anthropic SDK or hardcode a model name; generation goes through the openai client against the gateway, with the model from settings.
- Do not return an unbounded list from any endpoint; paginate.
- Do not put secrets in code or commit `.env`.
- Do not copy the trial or subscription logic from the sample auth flow.
- Do not use em dashes in any user-facing copy, comments, or docs.

## Tests
Dedicated test Postgres, transaction-rollback per test, all outbound HTTP mocked (respx or a stub transport; mock the gateway through the openai client). Fixtures: `db`, `client`, `as_role(role)` (overrides `get_current_user`), `auth_headers(user)` (mints a real JWT). Cover RBAC (viewer 403 on campaign create, non-admin 403 on role change, viewer only acts on own post, last-admin guard), the auth callback (domain rejection, bootstrap admin, no duplicate user), the connection flow (state validation, ciphertext at rest, disconnect deletes), `create_access_token`/`decode_access_token` round-trip and `require_role`, repository CRUD and domain queries, pagination (page envelope, limit capped at 100, next_cursor with no overlap or gap), and the provider order plus idempotency from `../DESIGN.md` section 18.
