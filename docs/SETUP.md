# SETUP.md: getting super-hype running

Step-by-step setup for local development and the external apps you register: Google (login), LinkedIn (posting), X (optional second platform), and Slack (approvals).

---

## 1. Prerequisites

- Python 3.12+ and **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- Node 20+ and **npm** (ships with Node).
- Docker and docker-compose (for Postgres and Redis, or run them natively).
- A LinkedIn Company Page you administer (required to create the LinkedIn app, even though v1 posts to personal profiles only).
- A Google Workspace for your company domain (so login can be restricted to it).
- Optional: an X (Twitter) developer account, if you want X campaigns (section 4). Skip it and super-hype runs LinkedIn-only; the X connector stays hidden.

---

## 2. Google login (fastapi-sso)

1. Go to the Google Cloud Console and create a project (or pick one).
2. Open **APIs and Services -> OAuth consent screen**. Choose **Internal** user type so only your Workspace domain can sign in. Fill in the app name and support email.
3. Open **APIs and Services -> Credentials -> Create credentials -> OAuth client ID**, type **Web application**.
4. Under **Authorized redirect URIs** add your frontend callback (this is where Google sends the user; the frontend then posts the code to the backend):
   ```
   http://localhost:5173/v1/google/callback        # local dev
   https://app.yourcompany.com/v1/google/callback  # production
   ```
5. Copy the **Client ID** and **Client secret** into `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
6. Set `COMPANY_EMAIL_DOMAIN` to your domain (for example `yourcompany.com`). The backend rejects any login whose email is not on this domain, in addition to the Internal consent screen.

---

## 3. LinkedIn app

super-hype uses LinkedIn only to act on a member's behalf (connect, then post,
reshare, comment, like). It does not use LinkedIn to log people into the app;
that is Google (section 2). Which LinkedIn product you need depends on which
actions you want.

**Two paths:**

- **Posts and reshares only (self-serve, quick):** request the **Share on
  LinkedIn** product. It grants `w_member_social` (publish and reshare) plus
  basic profile. This is enough to test the full reconnect-then-act flow.
  Comments and likes will fail with a 403, because they use a different scope.
- **Comments and likes too (vetted):** you need the **Community Management API**,
  which adds `w_member_social_feed`. It is review-gated, must be the **only**
  product on a dedicated app, and requires organization and Page verification.
  Its scope set (`w_member_social` + `w_member_social_feed` + `r_basicprofile`)
  is a superset of the Share path, so one Community-Management-only app can
  replace the Share app entirely once approved, with just a client id and secret
  swap. The full application process, eligibility, and AI-policy notes are in
  [`LINKEDIN_COMMUNITY_MANAGEMENT.md`](LINKEDIN_COMMUNITY_MANAGEMENT.md).

**Set up the app:**

1. Go to the LinkedIn Developer Portal and create an app. Associate it with your
   Company Page, then have a Page **super admin** approve the verification (only
   the super admin role can approve the app-to-Page association).
2. Under **Products**, add **Share on LinkedIn** for the posts-only path, or the
   **Community Management API** on a dedicated app for the full path. Do not put
   the Community Management API on the same app as other products; the portal
   blocks it ("must be the only product"), so create a separate app for it.
3. Under **Auth**, add the redirect URL (it points at the frontend, matching the
   Google pattern). It must equal `FRONTEND_URL` + `/connections/linkedin/callback`:
   ```
   http://localhost:5173/connections/linkedin/callback
   https://app.yourcompany.com/connections/linkedin/callback
   ```
4. Confirm the requested scopes: `w_member_social` and `r_basicprofile` for the
   Share path, plus `w_member_social_feed` once you are on the Community
   Management API. Adding scopes later forces every connected user to re-consent,
   so set them once.
5. Copy the **Client ID** and **Client Secret** into `LINKEDIN_CLIENT_ID` and
   `LINKEDIN_CLIENT_SECRET`.
6. Set `LINKEDIN_API_VERSION` to the current version header in `YYYYMM` form (for
   example `202606`). The publish call sends this as `LinkedIn-Version`.
7. In the portal's **Token Inspector**, generate a token and check whether a
   `refresh_token` is returned. If it is, the backend refreshes silently; if not,
   the Slack reconnect flow is the refresh path. Either way the code handles it.

---

## 4. X (Twitter) app (optional second platform)

X is an optional second platform. A campaign targets one platform (LinkedIn or
X); there is no cross-posting. Leave `X_CLIENT_ID` empty and the X connector is
hidden, X campaigns cannot be created, and everything else runs unchanged. When
configured, X differs from LinkedIn in two ways worth knowing up front: every
action (tweet, quote post, reply, like, bookmark) is fully automated through the
API with no assisted-manual step, and access tokens are short-lived (~2 hours)
but auto-refreshed by the worker, so members rarely re-consent.

**Set up the app:**

1. Go to the X Developer Portal (`console.x.com`), join the Developer Program,
   and create a Project, then an App inside it. The free tier allows writes but
   is heavily rate-limited; Basic is the tier that fits real campaign volume.
2. Open the app's **User authentication settings** and set it up:
   - **App type: Web App, Automated App or Bot** (a confidential client, so you
     get a Client Secret). Do not pick a native/public client type; it has no
     secret and the code expects one.
   - **App permissions: Read and write** (plus the like and bookmark scopes;
     see step 4).
   - **Type of App: OAuth 2.0.**
3. Add the **Callback URI / Redirect URL**. It must equal `FRONTEND_URL` +
   `/connections/x/callback`:
   ```
   http://localhost:5173/connections/x/callback
   https://app.yourcompany.com/connections/x/callback
   ```
   Set a Website URL too (any valid URL, for example your repo or site).
4. The app requests these OAuth 2.0 scopes (set in code, no portal action beyond
   enabling read and write): `tweet.read`, `tweet.write`, `users.read`,
   `like.write`, `bookmark.write`, `media.write`, and `offline.access`.
   `offline.access` is what grants the rotating refresh token the worker uses to
   keep the short-lived access token alive.
5. Copy the **OAuth 2.0 Client ID** and **Client Secret** (not the OAuth 1.0a
   API Key / Secret and not the Bearer Token, which this flow does not use) into
   `X_CLIENT_ID` and `X_CLIENT_SECRET`, then restart the API.

Because Slack cannot reach `localhost`, X's callback goes to the frontend (like
Google and LinkedIn), so a tunnel is not required for the connect flow itself;
you only need one for Slack interactivity (section 5).

---

## 5. Slack app (approvals and reconnect)

1. Go to the Slack API site, **Create New App -> From scratch**, name it and pick your workspace.
2. **OAuth and Permissions -> Bot Token Scopes**, add: `chat:write`, `im:write`, `users:read`, `users:read.email` (to map company emails to Slack user ids), and `commands` if you add slash commands later.
3. **Interactivity and Shortcuts**: turn on Interactivity and set the Request URL to:
   ```
   https://app.yourcompany.com/v1/slack/interactions
   ```
   For local testing, expose your backend with a tunnel (for example ngrok or `cloudflared`) and use that public HTTPS URL: Slack cannot reach `localhost`. The endpoint must respond within 3 seconds, so `POST /v1/slack/interactions` verifies the signature, acks with an empty 200, and updates the original message out of band via the interaction's `response_url`.
4. **Event Subscriptions** (only if you subscribe to events): enable and set the Request URL to `https://app.yourcompany.com/v1/slack/events`.
5. **Install to Workspace**. Copy the **Bot User OAuth Token** into `SLACK_BOT_TOKEN` and the **Signing Secret** (from Basic Information) into `SLACK_SIGNING_SECRET`. Every inbound Slack request is verified against the signing secret (HMAC-SHA256 over the raw body, with a five-minute replay window); a bad or missing signature returns 401.
6. User mapping: the first time the system needs to DM a person, it resolves their Slack id from their company email via `users.lookupByEmail` (this needs `users:read.email`) and caches it, plus the DM channel, in `slack_identities`.

How it works: when a campaign launches, each participant gets one DM bundling every action they own in that campaign (self post, reshare, comment, like, self-comment) behind **Approve all** / **Skip all**. A click runs the same approval path the web portal uses, then replaces the card with the result. If a self post or reshare needs a fresh LinkedIn token, the card answers with a reconnect link instead of publishing.

Approving does not do the manual like or comment for someone, so as those become actionable (once the target post is live) a second DM bundles them behind **Mark all done** / **Skip all**, each with a deep link to the post and the suggested comment text. A deferred reminder re-DMs anyone still not approved or not done (`REMINDER_DELAY_SECONDS`, a few hours by default; drop it for a quick local check), and a stale token triggers a reconnect DM. For local testing, `ENGAGEMENT_BUNDLE_DELAY_SECONDS` sets how long the worker waits to coalesce a person's like and comment into one card.

Slack is optional and strictly additive. The web app exposes the same approve, edit, and skip actions, so the system runs unchanged without it; when Slack is unconfigured, launch still schedules everyone's posts and only the DM is skipped.

---

## 6. Environment

Generation runs through the OpenAI SDK pointed at your LLM gateway, so there is no separate provider account to create: set `LLM_GATEWAY_URL` to the gateway's OpenAI-compatible base URL, `LLM_API_KEY` to its key, and `LLM_MODEL_NAME` to the model the gateway should route to.

Copy `backend/.env.example` to `backend/.env` and fill it in:
```
APP_URL=http://localhost:8000
FRONTEND_URL=http://localhost:5173
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/superhype
REDIS_URL=redis://localhost:6379/0

JWT_SECRET=<random 50+ chars>
TOKEN_ENCRYPTION_KEY=<Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
OAUTHLIB_INSECURE_TRANSPORT=1        # local dev only; ignored in production

COMPANY_EMAIL_DOMAIN=yourcompany.com
BOOTSTRAP_ADMIN_EMAILS=you@yourcompany.com,cofounder@yourcompany.com

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_API_VERSION=202606

X_CLIENT_ID=                         # OAuth 2.0 Client ID; leave empty to hide the X connector
X_CLIENT_SECRET=                     # OAuth 2.0 Client Secret

LLM_GATEWAY_URL=                     # OpenAI-compatible base URL of your LLM gateway
LLM_API_KEY=
LLM_MODEL_NAME=                      # the model the gateway should route to

SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=

SENTRY_DSN=                          # optional
```
The frontend needs only `frontend/.env` with `VITE_API_BASE_URL=http://localhost:8000`.

---

## 7. Run it locally

The fast path is docker-compose for Postgres and Redis, then the app and worker with uv and the frontend with pnpm.

```
# Postgres + Redis
docker compose up -d postgres redis

# Backend
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.seed              # bootstrap admin users + default teams
uv run uvicorn app.main:app --reload   # API on :8000
# in a second terminal:
uv run arq app.workers.arq_app.WorkerSettings   # the worker

# Frontend
cd ../frontend
npm install
npm run dev                             # SPA on :5173
```

The `backend/Makefile` wraps the common commands (`make server`, `make worker`,
`make seed`, `make migrate`, `make test`, `make flush`, `make reset`).

---

## 8. First run

1. Open the frontend and choose **Continue with Google**. Sign in with an email listed in `BOOTSTRAP_ADMIN_EMAILS`; you are created as an admin.
2. Have teammates sign in once with their company Google accounts. First sign-in runs a short onboarding (agree to participate, pick a team); each person is created as a viewer, though members of certain teams (for example Founders, GTM) are auto-granted the editor role.
3. As an admin, open **Users** and raise anyone else who will run campaigns to editor (search, then change their role). Roles are cumulative: viewer, editor, admin.
4. Every participant opens **Connectors** and connects their LinkedIn (the one-time consent), and their X account too if you configured X and plan to run X campaigns. After that LinkedIn members only reconnect if a token goes stale between campaigns; X refreshes itself in the background and only needs a reconnect if the refresh token is revoked.
5. An editor creates a campaign, picks the participants (people or whole teams), generates drafts, and an admin (or the editor, for their own campaign) launches it. Each person then approves, edits, or skips their own actions, either in the web app or from the bundled Slack DM (Approve all / Skip all) if Slack is configured. When the like and comment step comes due, they do it on LinkedIn and mark it done from the portal card or the Slack Mark all done DM.

---

## 9. Production notes

- Run four processes: the API (uvicorn workers), the ARQ worker, Postgres, and Redis, with a reverse proxy in front for TLS.
- `OAUTHLIB_INSECURE_TRANSPORT` must be unset or false in production; the code refuses insecure OAuth there regardless.
- Set the real `APP_URL` and `FRONTEND_URL`, and update the Google, LinkedIn, X, and Slack redirect and request URLs to the production domain.
- Run `uv run alembic upgrade head` on deploy before the API starts. Build the frontend with `npm run build` and serve the static assets behind the proxy.
- The API and worker are the two deployables; run migrations as a one-off job before the API starts, and supply all secrets (`JWT_SECRET`, `TOKEN_ENCRYPTION_KEY`, OAuth and LLM keys) through your platform's secret store rather than committing them.
