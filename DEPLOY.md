# DEPLOY.md: deploying super-hype on TrueFoundry

This covers the application workloads only. It assumes you already have a TrueFoundry workspace, a Docker registry integrated with the cluster, and the PostgreSQL and Redis you installed via Helm. Those are reused as-is; nothing here deploys a database.

## What gets deployed

super-hype is one backend image run as three workloads, plus a static frontend:

| Workload | TrueFoundry type | Port | Command |
| --- | --- | --- | --- |
| api | Service | 8000 | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| worker | Service (no port) | none | `arq app.workers.arq_app.WorkerSettings` |
| migrate | Job (manual trigger) | none | `sh -c "alembic upgrade head && python -m app.seed"` |
| web | Service | 8080 | nginx serving the built `dist/` |

api, worker, and migrate run the same backend image and differ only by command, so build that image once and reference it from all three. web is a separate image.

## Connecting to your existing Postgres and Redis

Since super-hype runs in the same cluster, point it at the in-cluster service DNS of your Helm releases. No public exposure is needed. Use your actual release names and namespace:

```
DATABASE_URL=postgresql+asyncpg://superhype:<pw>@<pg-release>-postgresql.<ns>.svc.cluster.local:5432/superhype
REDIS_URL=redis://:<pw>@<redis-release>-master.<ns>.svc.cluster.local:6379/0
```

If super-hype deploys into the same namespace as the databases, the short service name works; across namespaces use the full `*.svc.cluster.local` form. Include the Redis password (and switch to `rediss://` if you enabled TLS). Both URLs carry credentials, so store them as secrets (below), not as plain env.

## Secrets

Put every sensitive value in a TrueFoundry secret group and reference it by FQN in the deployment env. The FQN form is `tfy-secret://<user-or-tenant>:<group>:<key>`, and TrueFoundry injects the real value at runtime so the spec never contains the secret itself.

Store as secrets: `SECRET_KEY` (JWT signing), `FERNET_KEY` (token encryption), `DATABASE_URL`, `REDIS_URL`, `GOOGLE_CLIENT_SECRET`, `LINKEDIN_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN`, and `LLM_API_KEY`.

Keep as plain env (not sensitive): `GOOGLE_CLIENT_ID`, `LINKEDIN_CLIENT_ID`, `COMPANY_EMAIL_DOMAIN`, `BOOTSTRAP_ADMIN_EMAILS`, `APP_URL`, `FRONTEND_URL`, `LLM_GATEWAY_URL`, `LLM_MODEL_NAME`, `LINKEDIN_VERSION`, and the stagger defaults.

api and worker take the same env set. The migrate Job needs only `DATABASE_URL` (and `REDIS_URL` if your seed touches it).

## LLM gateway

You are already on TrueFoundry, so the gateway is internal. Set `LLM_GATEWAY_URL` to your TrueFoundry AI Gateway endpoint and `LLM_API_KEY` to a gateway virtual-account key stored as a secret. The backend's OpenAI client uses `base_url=LLM_GATEWAY_URL`, so nothing in the code changes between local and cluster, only the env.

## Build the backend image once

Build and push `superhype-backend` to your integrated registry (in CI, or with a `tfy` build from the backend Dockerfile). The three backend workloads then reference that one image URI and override the command. The Dockerfile is the uv multi-stage build from SETUP.md; its default CMD can be the uvicorn line, which api inherits and worker and migrate override.

## Service specs (Python SDK)

Install the CLI and SDK with `pip install -U "truefoundry"` (Python 3.9 to 3.14), log in, then put this in `deploy.py` and run `python deploy.py`. TrueFoundry's own recommendation is to configure a service once in the UI and copy the generated Python or YAML; the spec below is the shape to expect. Replace the image URI, workspace FQN, host, and secret FQNs.

```python
import logging
from truefoundry.deploy import Service, Job, Image, Port, Resources, NodeSelector

logging.basicConfig(level=logging.INFO)

IMAGE = "<registry>/superhype-backend:<tag>"
WORKSPACE = "<your-workspace-fqn>"

# shared env for api + worker
env = {
    "DATABASE_URL": "tfy-secret://<tenant>:superhype:DATABASE_URL",
    "REDIS_URL": "tfy-secret://<tenant>:superhype:REDIS_URL",
    "SECRET_KEY": "tfy-secret://<tenant>:superhype:SECRET_KEY",
    "FERNET_KEY": "tfy-secret://<tenant>:superhype:FERNET_KEY",
    "GOOGLE_CLIENT_SECRET": "tfy-secret://<tenant>:superhype:GOOGLE_CLIENT_SECRET",
    "LINKEDIN_CLIENT_SECRET": "tfy-secret://<tenant>:superhype:LINKEDIN_CLIENT_SECRET",
    "SLACK_SIGNING_SECRET": "tfy-secret://<tenant>:superhype:SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN": "tfy-secret://<tenant>:superhype:SLACK_BOT_TOKEN",
    "LLM_API_KEY": "tfy-secret://<tenant>:superhype:LLM_API_KEY",
    "GOOGLE_CLIENT_ID": "<id>",
    "LINKEDIN_CLIENT_ID": "<id>",
    "COMPANY_EMAIL_DOMAIN": "truefoundry.com",
    "BOOTSTRAP_ADMIN_EMAILS": "you@truefoundry.com",
    "APP_URL": "https://<api-host>",
    "FRONTEND_URL": "https://<web-host>",
    "LLM_GATEWAY_URL": "https://<org>.truefoundry.cloud/api/llm",
    "LLM_MODEL_NAME": "<model>",
    "LINKEDIN_VERSION": "202606",
}

api = Service(
    name="superhype-api",
    image=Image(image_uri=IMAGE, command="uvicorn app.main:app --host 0.0.0.0 --port 8000"),
    ports=[Port(port=8000, protocol="TCP", expose=True, app_protocol="http", host="<api-host>")],
    env=env,
    resources=Resources(
        cpu_request=0.5, cpu_limit=1,
        memory_request=512, memory_limit=1024,
        node=NodeSelector(capacity_type="spot_fallback_on_demand"),
    ),
    replicas=2,
)

worker = Service(
    name="superhype-worker",
    image=Image(image_uri=IMAGE, command="arq app.workers.arq_app.WorkerSettings"),
    ports=[],            # no port: background worker, no endpoint
    env=env,
    resources=Resources(
        cpu_request=0.5, cpu_limit=1,
        memory_request=512, memory_limit=1024,
        node=NodeSelector(capacity_type="spot_fallback_on_demand"),
    ),
    replicas=1,
)

api.deploy(workspace_fqn=WORKSPACE, wait=False)
worker.deploy(workspace_fqn=WORKSPACE, wait=False)
```

Point the api health probes at `GET /healthz` (configure liveness and readiness in the UI or spec). The worker has no port, so it has no HTTP probe; TrueFoundry treats the process staying up as healthy. If the SDK version is strict about an empty `ports`, omit the field entirely instead of passing `[]`.

## Migration Job

Run schema migrations as a manual-trigger Job that you fire on each release before rolling the app. Manual triggers always start a fresh run, and concurrency policy does not apply to them.

```python
migrate = Job(
    name="superhype-migrate",
    image=Image(
        image_uri=IMAGE,
        command="sh -c 'alembic upgrade head && python -m app.seed'",
    ),
    env={
        "DATABASE_URL": "tfy-secret://<tenant>:superhype:DATABASE_URL",
        "REDIS_URL": "tfy-secret://<tenant>:superhype:REDIS_URL",
    },
    resources=Resources(cpu_request=0.5, cpu_limit=0.5, memory_request=512, memory_limit=512),
)
migrate.deploy(workspace_fqn=WORKSPACE, wait=False)
```

After it deploys it sits idle until triggered. Trigger it from the dashboard (Run Job) or programmatically in CI, wait for success, then deploy api and worker. Do not bake `alembic upgrade` into the api start command: with multiple api replicas that races, and a Job keeps migrations to a single controlled run.

## Frontend (web)

Build the SPA with `pnpm build` and serve the static `dist/` from a small nginx image, deployed as a normal Service on port 8080 with `expose=True` and a host.

The one catch is the API URL. Vite inlines `VITE_API_BASE_URL` at build time, so either:
- serve web and api under one domain (web at `/`, api proxied at `/api`), which is cleanest because it removes the build-time URL problem and CORS entirely; or
- build the frontend with `VITE_API_BASE_URL` set to the api host, which means you must know the api host before building and rebuild if it changes.

Same-origin is the recommended setup. If you split hosts, set the api CORS allowlist to the web origin.

## Order of operations on a release

1. Build and push the backend image (and the web image if the frontend changed).
2. Trigger the migrate Job and wait for it to complete.
3. Deploy api and worker on the new image.
4. Deploy web if it changed.

Migrations always run before the app. Steps 3 and 4 are rolling, so the old version keeps serving until the new pods are healthy.

## After the first deploy (do not skip)

The OAuth and Slack callbacks must point at the real deployed URLs, so once you know the api and web hosts:

1. Set `APP_URL` (api public URL) and `FRONTEND_URL` (web public URL) in the api and worker env, and redeploy if they were placeholders.
2. Update the external apps to the deployed URLs (confirm each path against the routes your app actually mounts, see DESIGN section 9 and BACKEND):
   - Google: authorized redirect URI to your deployed frontend callback (the SPA route that receives the code and POSTs it to the backend `/v1/google/callback`), and add the web origin to authorized JavaScript origins.
   - LinkedIn: OAuth redirect URL to `{APP_URL}/api/connections/linkedin/callback`.
   - Slack: interactivity Request URL to `{APP_URL}/v1/slack/interactions`, and reinstall the app if scopes changed.
3. Confirm `BOOTSTRAP_ADMIN_EMAILS` so the first admins exist, then log in.
4. Smoke test: connect one LinkedIn account on the Connections page, then run a one-person campaign to yourself end to end.

## Scaling the worker (one sharp edge)

The publish path is safe to parallelize: posts are idempotent on `idempotency_key` and keyed per person, so running two or more workers is fine for throughput. ARQ cron is the exception. Scheduled tasks (the daily reconnect sweep) fire once per worker, so with N workers the sweep runs N times. If you scale beyond one worker, either keep a single dedicated cron worker at `replicas=1` separate from the throughput workers, or wrap each scheduled task in a short Redis lock so only one instance runs it.

## GitOps (optional)

To drive this from CI, keep the YAML equivalents of these specs in a `truefoundry/` directory and run `tfy apply -d truefoundry`. That needs TrueFoundry CLI 0.14.2 or newer and two env vars in CI: `TFY_HOST` and `TFY_API_KEY` (use a Virtual Account token for production). Put the image build and the migrate-Job trigger in the pipeline before `tfy apply`.
