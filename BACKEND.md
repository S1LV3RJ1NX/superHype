# BACKEND.md: backend implementation spec

The authoritative spec for `backend/`. This refines sections 6 to 9 of `DESIGN.md`; where they differ, this document wins. The conventions here match the patterns from the sample project (the `app/` package, the repository pattern, fastapi-sso, JWT bearer auth, and the `/v1` prefix). The private `setu-backend` repo could not be read directly, so this is derived from the pasted example; if anything conflicts with that repo's real conventions, prefer the repo.

---

## 1. Layered architecture

Strict layering. A request flows: **view -> controller -> service -> repository -> model**. Each layer has one job and may only call the layer directly below it.

- **config** (`app/config.py`): a pydantic-settings `Settings` object, all values from environment, plus an `is_production` flag and parsed lists (for example bootstrap admin emails).
- **models** (`app/models/`): SQLAlchemy 2.0 ORM, one module per aggregate. No logic beyond simple properties.
- **schemas** (`app/schemas/`): pydantic request and response models. Views speak schemas, never ORM objects, at the boundary.
- **repositories** (`app/repositories/`): all database access. One repository per aggregate, each a singleton instance with async methods that take `db` as the first argument. No business logic; just queries and persistence.
- **services** (`app/services/`): business logic and external side effects (token creation, OAuth exchange, generation, lifecycle). Services own multi-step transaction boundaries and call repositories and providers.
- **controllers** (`app/controllers/`): per-resource request handling. Controllers enforce authorization rules that go beyond a route-level role check (for example "only the owner or an admin may act on this post"), call services and repositories, and return schema objects. Controllers do not touch the request or response directly.
- **views** (`app/views/`): FastAPI routers. Thin. They declare the route and its dependencies (auth, role), parse the body into a schema, call a controller, and return a schema. No business logic, no database, no external calls.

Cross-cutting modules:
- **core** (`app/core/`): `security.py` (JWT create and decode), `deps.py` (auth and RBAC dependencies), `crypto.py` (Fernet token encryption).
- **db** (`app/db/`): the async engine and the `get_db` session dependency.
- **logger** (`app/logger.py`): structlog `get_logger`.
- **providers** (`app/providers/`): the platform abstraction; `linkedin.py` in v1, including image upload (see DESIGN.md section 9).
- **integrations** (`app/integrations/`): thin clients, `llm.py` (the OpenAI SDK pointed at the LLM gateway) and `slack.py`.
- **workers** (`app/workers/`): the ARQ app and jobs (see DESIGN.md section 11).

### Module tree
```
app/
├── config.py
├── logger.py
├── main.py                  # app factory; include all routers from views/
├── core/
│   ├── security.py          # create_access_token, decode_access_token
│   ├── deps.py              # get_current_user, require_role
│   └── crypto.py            # Fernet encrypt/decrypt
├── db/
│   ├── base.py              # DeclarativeBase + naming convention
│   └── session.py           # async engine, async_sessionmaker, get_db
├── models/
│   ├── user.py
│   ├── social_account.py
│   ├── writing_skill.py
│   ├── campaign.py
│   ├── post.py
│   ├── audit_log.py
│   └── slack_identity.py
├── schemas/
│   ├── auth.py              # GoogleCallbackBody, TokenResponse
│   ├── user.py              # UserOut, RoleUpdate
│   ├── connection.py        # LinkedInCallbackBody, ConnectionOut, AuthorizeUrlOut
│   ├── skill.py
│   ├── campaign.py
│   └── post.py
├── repositories/
│   ├── base.py              # BaseRepository[Model]
│   ├── user_repo.py
│   ├── social_account_repo.py
│   ├── writing_skill_repo.py
│   ├── campaign_repo.py
│   ├── post_repo.py
│   └── audit_repo.py
├── services/
│   ├── auth_service.py
│   ├── linkedin_oauth_service.py
│   ├── generation_service.py
│   └── campaign_service.py
├── controllers/
│   ├── auth_controller.py
│   ├── connection_controller.py
│   ├── user_controller.py
│   ├── skill_controller.py
│   ├── campaign_controller.py
│   ├── post_controller.py
│   └── slack_controller.py
├── views/
│   ├── __init__.py          # api_router that includes every router below
│   ├── auth.py              # /v1/google/*
│   ├── connections.py       # /v1/connections/*
│   ├── users.py             # /v1/users/*
│   ├── skills.py            # /v1/skills/*
│   ├── campaigns.py         # /v1/campaigns/*
│   ├── posts.py             # /v1/posts/*
│   └── slack.py             # /v1/slack/*
├── providers/
│   ├── base.py
│   └── linkedin.py
├── integrations/
│   ├── llm.py               # OpenAI SDK against the LLM gateway
│   └── slack.py
└── workers/
    ├── arq_app.py
    └── jobs.py
migrations/                  # alembic
tests/
```

---

## 2. Roles and permissions

Three roles on `users.role`: `viewer`, `editor`, `admin`. Every new user is `viewer`. Roles are cumulative: editor includes everything a viewer can do, admin includes everything an editor can do. In practice these map to teams: founder's office and GTM leads hold admin, the GTM team holds editor, and the wider team (developers and others) stays viewer. The web app is therefore primarily a GTM and founder's-office tool; viewers mostly act through the Slack approval card.

| Capability | viewer | editor | admin |
| --- | --- | --- | --- |
| Log in, view own profile | yes | yes | yes |
| Connect, reconnect, disconnect own LinkedIn | yes | yes | yes |
| View and approve, edit, or skip own posts | yes | yes | yes |
| View campaigns they are part of | yes | yes | yes |
| View all campaigns | no | yes | yes |
| Create and edit campaigns, generate and regenerate | no | yes | yes |
| Manage writing skills | no | yes | yes |
| Launch a campaign | no | own only | any |
| Manage users and assign roles | no | no | yes |

Enforcement is two-layered. The route declares a coarse gate with `require_role(...)`. The controller enforces the fine-grained rule, for example that a viewer may act only on a post where `post.user_id == current_user.id`, or that an editor may launch only a campaign they created. Never rely on the UI for this.

### Role management
- `GET  /v1/users` (admin): list users with roles and connection status.
- `PATCH /v1/users/{id}` (admin), body `{ "role": "admin" | "editor" | "viewer" }`: change a user's role. An admin cannot demote themselves if they are the last admin (guard against lockout). Writes an audit row.

### Bootstrapping the first admin
There is a chicken-and-egg problem: only an admin can promote, but the first user has no admin to promote them. Solve it with `BOOTSTRAP_ADMIN_EMAILS` (a comma-separated env list). On first login, if the user's email is in that list they are created as `admin`; everyone else is created as `viewer`. The list is consulted only at user creation, so changing it later does not re-grant; use the API after that.

---

## 3. Authentication

Google login via fastapi-sso, then a JWT bearer token for every API call. The flow mirrors the sample: fastapi-sso redirects to the frontend, and the frontend posts the authorization code to the backend in the request body so it never lands in logs or Referer headers.

### View (`app/views/auth.py`)
```python
google_sso = GoogleSSO(
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    redirect_uri=f"{settings.FRONTEND_URL.rstrip('/')}/v1/google/callback",
    allow_insecure_http=bool(settings.OAUTHLIB_INSECURE_TRANSPORT) and not settings.is_production,
)
router = APIRouter(prefix="/v1/google", tags=["auth"])

@router.get("/login")
async def google_login():
    async with google_sso:
        return await google_sso.get_login_redirect(
            params={"prompt": "consent", "access_type": "offline"}
        )

@router.post("/callback")
async def google_callback(body: GoogleCallbackBody, request: Request,
                          db: AsyncSession = Depends(get_db)):
    async with google_sso:
        sso_user = await google_sso.process_login(body.code, request)
    return await auth_controller.complete_google_login(db, sso_user)
```

### Controller (`app/controllers/auth_controller.py`)
The differences from the sample: drop the trial and subscription logic (this is an internal tool, no billing), add the company-domain check, and assign a role instead of an `is_admin` boolean.
```python
async def complete_google_login(db, sso_user) -> TokenResponse:
    domain = sso_user.email.split("@")[-1].lower()
    if domain != settings.COMPANY_EMAIL_DOMAIN.lower():
        raise HTTPException(403, "Use your company account to sign in.")

    user = await user_repo.get_by_email_and_provider(
        db, email=sso_user.email, provider=sso_user.provider
    )
    if user is None:
        role = "admin" if sso_user.email.lower() in settings.bootstrap_admin_emails else "viewer"
        user = await user_repo.create(
            db, email=sso_user.email, first_name=sso_user.first_name,
            last_name=sso_user.last_name, provider=sso_user.provider, role=role,
        )
        await db.commit()
        await db.refresh(user)
    if not user.is_active:
        raise HTTPException(403, "This account is disabled.")

    token = await create_access_token(user_id=user.id, email=user.email, role=user.role)
    return TokenResponse(access_token=token, token_type="bearer")
```

### core/security and core/deps
```python
# core/security.py
async def create_access_token(*, user_id, email, role,
                              expires_delta: timedelta | None = None) -> str: ...
def decode_access_token(token: str) -> TokenPayload: ...   # raises 401 on bad/expired

# core/deps.py
async def get_current_user(token: str = Depends(oauth2_scheme),
                           db: AsyncSession = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    user = await user_repo.get(db, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Invalid or inactive user.")
    return user

def require_role(*roles: str):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have access to this action.")
        return user
    return _dep
```
The JWT payload carries `user_id`, `email`, and `role`. Keep the lifetime short.

---

## 4. LinkedIn connection

A user connects, reconnects, or disconnects their own LinkedIn account. The flow mirrors the Google pattern: the LinkedIn redirect URI points to the frontend, and the frontend posts the code (and state) back to the backend. Because auth is a stateless JWT and there is no cookie session, the CSRF state is stored in Redis and bound to the user.

### Endpoints (`app/views/connections.py`)
```
GET    /v1/connections                      # list current user's connections
GET    /v1/connections/linkedin/authorize   # -> { authorize_url }; stores state in Redis
POST   /v1/connections/linkedin/callback    # body { code, state }; exchange + store tokens
POST   /v1/connections/linkedin/reconnect   # -> { authorize_url }; same flow, for stale accounts
DELETE /v1/connections/linkedin             # revoke (best effort) + delete the row
```
All five require `get_current_user`. None require a role beyond viewer; a user manages only their own connection.

### Controller (`app/controllers/connection_controller.py`)
```python
async def authorize_linkedin(user) -> AuthorizeUrlOut:
    state = secrets.token_urlsafe(32)
    await redis.setex(f"li:state:{state}", 600, str(user.id))   # 10 min, bound to user
    return AuthorizeUrlOut(authorize_url=linkedin_oauth_service.authorize_url(state))

async def complete_linkedin(db, user, code: str, state: str) -> ConnectionOut:
    owner = await redis.get(f"li:state:{state}")
    if owner is None or owner != str(user.id):
        raise HTTPException(400, "Invalid or expired connection request.")
    await redis.delete(f"li:state:{state}")

    tokens = await linkedin_oauth_service.exchange_code(code)      # access, refresh, expires_at
    urn, display_name = await linkedin_oauth_service.fetch_identity(tokens.access_token)
    account = await social_account_repo.upsert(
        db, user_id=user.id, platform="linkedin", external_urn=urn,
        display_name=display_name,
        access_token_enc=crypto.encrypt(tokens.access_token),
        refresh_token_enc=crypto.encrypt(tokens.refresh_token) if tokens.refresh_token else None,
        scopes=tokens.scopes, expires_at=tokens.expires_at, status="active",
    )
    await audit_repo.record(db, actor_id=user.id, action="linkedin_connected", detail={"urn": urn})
    await db.commit()
    return ConnectionOut.model_validate(account)

async def disconnect_linkedin(db, user) -> None:
    account = await social_account_repo.get_by_user(db, user.id, platform="linkedin")
    if account is None:
        return
    await linkedin_oauth_service.revoke(account)                  # best effort, ignore failure
    await social_account_repo.delete(db, account)
    await audit_repo.record(db, actor_id=user.id, action="linkedin_disconnected")
    await db.commit()
```
Reconnect calls the same `authorize_linkedin`; on the callback `upsert` updates the existing row and resets `status` to `active`. This is also the recovery path when a token goes stale (a 401 during publishing sets `status = 'stale'` and the Slack bot sends a reconnect link, per DESIGN.md sections 9 and 11).

### Service (`app/services/linkedin_oauth_service.py`)
- `authorize_url(state)`: builds `https://www.linkedin.com/oauth/v2/authorization` with `response_type=code`, the client id, `redirect_uri = {FRONTEND_URL}/connections/linkedin/callback`, the scope string `w_member_social r_basicprofile`, and `state`.
- `exchange_code(code)`: posts to `https://www.linkedin.com/oauth/v2/accessToken`, returns access token (60-day), refresh token if issued (up to 365-day), expiry, and granted scopes.
- `fetch_identity(access_token)`: fetches the member person URN and a display name.
- `refresh(account)`: refreshes when a refresh token exists; otherwise the account goes stale and the reconnect flow takes over.
- `revoke(account)`: best-effort token revocation on disconnect.

Tokens are encrypted with Fernet (`core/crypto.py`) before they ever reach the database. They never appear in logs.

---

## 5. Repositories

A small generic base, then one repository per aggregate, each exported as a singleton (matching `user_repo` in the sample). Every method takes `db` first and returns model instances; repositories never commit (the controller or service owns the transaction), except where a single-call helper is clearer, in which case it is explicit. Any method that backs a list endpoint is paginated: it takes `PageParams` and returns a `Page[Model]` (`items` plus `next_cursor`), using keyset pagination on `(created_at, id)` for the large tables; see DESIGN.md section 8.

```python
# app/repositories/base.py
class BaseRepository(Generic[ModelT]):
    model: type[ModelT]
    async def get(self, db, id) -> ModelT | None: ...
    async def list(self, db, **filters) -> list[ModelT]: ...
    async def paginate(self, db, *, params: PageParams, **filters) -> Page[ModelT]: ...
    async def create(self, db, **fields) -> ModelT: ...
    async def update(self, db, obj, **fields) -> ModelT: ...
    async def delete(self, db, obj) -> None: ...
```

Concrete repositories and their notable methods:
- `user_repo`: `get_by_email_and_provider`, `set_role`, `list_all`, `count_admins`.
- `social_account_repo`: `get_by_user(db, user_id, platform)`, `upsert(...)`, `mark_stale(db, id)`, `delete`.
- `writing_skill_repo`: `get_default`, `list_active`, `set_default`.
- `campaign_repo`: `get_with_posts`, `paginate_for_user(params, user)`, `set_status`.
- `post_repo`: `paginate_for_campaign(params, campaign_id)`, `list_pending_for_user`, `mark_published`, `mark_failed`.
- `audit_repo`: `record(db, *, actor_id=None, campaign_id=None, post_id=None, action, detail=None)`, `paginate_for_campaign(params, campaign_id)`.

---

## 6. Migrations (alembic, async)

- Configure `migrations/env.py` for async (`asyncpg`), importing `Base.metadata` from `app/db/base.py` so autogenerate sees every model.
- Set a constraint naming convention on the `MetaData` so autogenerated migrations have stable, named constraints (important for clean downgrades and for Postgres enum and index churn).
- The initial migration creates every table in section 7 of DESIGN.md.
- Indexes (including the partial unique index that keeps at most one default writing skill, and the composites that back keyset pagination) are declared on the models per DESIGN.md section 7, so autogenerate emits them. Review the generated migration to confirm each one is present rather than trusting autogenerate blindly.
- Seed data is a separate idempotent step, not baked into the schema migration: a `scripts/seed.py` (or an `alembic` data migration) that inserts the default writing skill from the project's `SKILL.md` if it does not already exist. Bootstrap admins are handled at login, not in the seed.
- Commands (always through uv):
```
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head
uv run alembic downgrade -1
uv run python -m scripts.seed
```
Migrations run on deploy before the API starts.

---

## 7. Tests

pytest with pytest-asyncio against a dedicated test Postgres (or testcontainers), each test wrapped in a transaction that rolls back. Mock all outbound HTTP (LinkedIn, the LLM gateway, Slack) with respx or a stub httpx transport; never hit a real third party in tests.

Fixtures (`tests/conftest.py`):
- `db`: an async session bound to a rolled-back transaction.
- `client`: an httpx `AsyncClient` wired to the app with `get_db` overridden to the test session.
- `as_role(role)`: overrides `get_current_user` to inject a user of the given role, so endpoint tests do not need a real token.
- `auth_headers(user)`: mints a real JWT, for tests that exercise `core/security` and the token path end to end.

Coverage to write:
- **RBAC**: a viewer gets 403 on `POST /v1/campaigns`; a non-admin gets 403 on `PATCH /v1/users/{id}`; a viewer may act on their own post but gets 403 on someone else's; the last-admin demotion guard returns an error.
- **Auth**: the callback rejects a non-company domain (403); a bootstrap-admin email is created as admin and a normal email as viewer; an existing user is reused, not duplicated.
- **Connection**: `authorize` stores state in Redis; `callback` rejects a state that is missing or bound to a different user; on success the stored token is ciphertext, not plaintext; `disconnect` deletes the row and writes an audit entry.
- **security**: `create_access_token` then `decode_access_token` round-trips the claims; an expired or tampered token raises 401; `require_role` admits the listed roles and rejects others.
- **repositories**: CRUD plus the domain queries (`get_by_email_and_provider`, `get_by_user`, `count_admins`).
- **pagination**: a list endpoint returns the `Page` envelope, caps `limit` at 100, and a `next_cursor` fetches the following page with no overlap or gap.
- **provider and lifecycle**: see DESIGN.md section 18 (publish-then-first-comment order, idempotent publish, state-machine transitions, and the generation parser including malformed output, with the LLM gateway mocked through the OpenAI client). Also test media: an image post uploads under the post's own author and reuses `image_asset_urn` on retry (no double upload), and `link_placement` routes the link to the body or the first comment.

CI runs `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`, and `uv run pytest`.
