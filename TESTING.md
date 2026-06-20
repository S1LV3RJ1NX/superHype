# Testing super-hype from the UI

How to exercise the product end to end through the web app: first by yourself on
a local build (section A), then as a small pilot of 3 to 5 real people once it is
deployed (section B).

For one-time local setup (Postgres, Redis, env, migrations) see
`backend/README.md`. This doc assumes the stack is already installed and focuses
on the workflows.

## Processes that must be running

A campaign only moves if the worker is up. Run these in separate terminals:

```bash
cd backend && uv run uvicorn app.main:app --reload         # API on :8000
cd backend && uv run arq app.workers.arq_app.WorkerSettings # worker (generation + publishing)
cd frontend && npm run dev                                   # SPA on :5173
```

If a campaign sits in `generating` or `publishing` forever, the worker is not
running. Keep the worker terminal visible: every job logs there.

---

## A. Single-user testing (local)

With one connected account you can drive almost every workflow, because LinkedIn
lets you like, comment on, and reshare your own posts. The plan builder picks
participants from your team roster, which with one user is just you, so you assign
all the actions to yourself.

### A.0 Make actions fire fast

The authenticity guardrails throttle a single account hard (90 seconds between
actions, 10 per day). For local testing, set these in `backend/.env` and restart
the API and worker:

```bash
MIN_SECONDS_BETWEEN_ACCOUNT_ACTIONS=0
MAX_ACTIONS_PER_ACCOUNT_PER_DAY=100
```

Restore them to `90` and `10` when you are done.

### A.1 Amplify an existing post (the cleanest full test)

1. Connect your LinkedIn on the Connections page if you have not.
2. Copy the link of any post (the LinkedIn "Copy link to post" button works; the
   share, embed, and feed URL forms all parse).
3. New campaign, choose Amplify, paste the link into "Post URL to amplify", give
   it a title, Create.
4. In the Plan panel add rows, all assigned to you: `+ like`, `+ comment`,
   `+ repost comment`. For comment and repost, type text, or as an editor leave it
   blank and press Generate.
5. Save plan, then Launch.
6. Watch the worker publish the like, comment, and reshare. Refresh LinkedIn to
   see the real interactions and the campaign progress bar fill.

Exercises: campaign create, plan, LLM generation, per-post approval, worker
publish, the stagger, the guardrails, and the audit log.

### A.2 Distribute (variations)

1. New campaign, choose Distribute (needs the editor role). Optionally add seed
   text, tone, a Link, and a default image URL.
2. In the Plan panel press `+ Variation` (assigned to you), then add `+ comment`
   or `+ repost comment` rows that target "Variation #1", also assigned to you.
3. Press Generate to draft the variation and the interaction text. Edit if you
   want, then Approve the variation post first.
4. The worker publishes a new post from your account. The interactions are
   dependency-aware: they wait until that post is live, then fire on it. If you set
   a Link, confirm it lands as the first comment.

Exercises: variation generation, publishing a new post, dependency ordering, and
link-in-first-comment placement.

### A.3 Per-post controls

On any pending post card: Edit the body and save, Skip a post (confirm it never
publishes and the campaign still reaches a terminal state), and Approve.

### A.4 Reconnect-then-act

Force the expiry gate, then approve:

- Set `LINKEDIN_RECONNECT_BUFFER_HOURS=100000` in `backend/.env` and restart the
  API, or run `UPDATE social_accounts SET status='stale' WHERE user_id='<you>';`.
- Approve a pending post. You are redirected to LinkedIn consent, and after
  consenting you land back on the campaign with the queued action publishing.
- Restore the buffer to `24` afterward.

### A.5 Roles (RBAC)

Check the viewer, editor, and admin differences without a second login by flipping
your own role in the database and reloading, for example
`UPDATE users SET role='viewer' WHERE email='<you>';`. As a viewer the Distribute
toggle and editor-only generation are blocked.

### A.6 What you cannot fully test solo

- Multi-person publishing with different people's tokens. You can insert extra
  dummy users so they appear in the roster and you can plan and skip against them,
  but their posts fail at publish with "No connected LinkedIn account" because they
  have no token. Real multi-account behavior needs section B.
- Likes and comments on other people's posts may return `403` if your LinkedIn app
  only holds `w_member_social`. The like and comment social actions map to
  `w_member_social_feed` (the Community Management API). Your own-post publishing
  and reshares work with `w_member_social`. See section B for the scope note.

---

## B. Pilot over 3 to 5 users (deployed)

This is the real test: several people, each with their own LinkedIn, running a
coordinated push with per-person consent.

### B.0 Prerequisites

- Deploy the API, worker, and web app, and run the migrate job. See `DEPLOY.md`.
- Complete the post-deploy steps in `DEPLOY.md` ("After the first deploy"): set
  `APP_URL` and `FRONTEND_URL`, and register the real Google and LinkedIn redirect
  URLs.
- `COMPANY_EMAIL_DOMAIN` is set to your company domain (only those emails can sign
  in), and your own email plus any co-admins are in `BOOTSTRAP_ADMIN_EMAILS`.
- LinkedIn app scopes: `w_member_social openid profile` cover login, own-post
  publishing, and reshares. For like and comment actions you need
  `w_member_social_feed` via the Community Management API, which requires LinkedIn's
  application and vetting. Plan the pilot around what your current scopes allow (see
  "Scope reality" below).

### B.1 Onboard the pilot group

1. Each of the 3 to 5 people signs in with their company Google account. The first
   sign-in creates their user as a viewer (or admin if bootstrapped).
2. Each person opens Connections and connects their own LinkedIn (consenting with
   their own account). Nothing can publish on their behalf until they do.
3. As an admin, open the Users page and confirm each person shows a green
   "Connected" dot. Promote one or two people to editor if they will create
   distribute campaigns. Only admins change roles.

### B.2 Run an amplify campaign across the group

1. One person publishes a real seed post on LinkedIn (or pick an existing one).
2. An editor or admin creates an Amplify campaign with that post's link.
3. In the Plan, add one row per pilot participant: a mix of like, comment, and
   repost comment. Generate or hand-write the comment and reshare text.
4. Save plan and Launch.
5. Each participant approves their own post (in the portal for now; Slack approval
   comes later). Confirm a person can only act on their own row.
6. Watch the interactions land on LinkedIn over the stagger window, not all at
   once.

### B.3 Run a distribute campaign

1. An editor creates a Distribute campaign from one seed idea, optionally with a
   Link.
2. Add a Variation per author and interaction rows that target each variation.
3. Generate, let authors edit and approve their variations, then watch each
   person's post publish and the cross-interactions follow once each post is live.

### B.4 What to verify during the pilot

- Consent and ownership: nothing publishes without the owner approving their own
  post.
- Stagger and guardrails: actions from one account are spaced out and capped, so
  the push does not look like a bot pod. Keep the production guardrail defaults
  (`MIN_SECONDS_BETWEEN_ACCOUNT_ACTIONS=90`, `MAX_ACTIONS_PER_ACCOUNT_PER_DAY=10`).
- Idempotency: a retried job never double-posts.
- Reconnect: when someone's 60-day token has expired, approving prompts them to
  reconnect and then completes the action in one flow.
- Audit: every approve, publish, first-comment, and rollback is recorded.

### B.5 Scope reality for the pilot

- If your LinkedIn app has `w_member_social` only, run the pilot on the workflows
  that work today: publishing variations and reshares. Likes and comments will
  `403` until `w_member_social_feed` is granted.
- Apply for the Community Management API (Development then Standard tier) to unlock
  `w_member_social_feed`. Frame the use case as consented employee advocacy and
  content distribution, since each action runs on the member's own token with their
  explicit approval.

### B.6 Known limits during the pilot

- Slack approval is not built yet, so approvals happen in the web portal. The
  reconnect-then-act primitive is already in place for Slack to reuse.
- Scheduled start times are not implemented; launch is immediate with a per-person
  stagger.
- Insights and analytics are not in this version.
