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
lets you like, comment on, and reshare your own posts. The plan builder is a
participant picker: you choose people or whole teams and the backend expands each
into the concrete actions. With one user that participant is just you, so every
action is assigned to you automatically. Cross-person engagement (liking and
commenting on other people's posts) only appears once there is more than one
participant, so solo testing covers your own post, reshare, and self-comment but
not the cross-engagement mesh (see section B for that).

### A.0 Make actions fire fast

The authenticity guardrails throttle a single account hard (90 seconds between
actions, 10 per day). For local testing, set these in `backend/.env` and restart
the API and worker:

```bash
MIN_SECONDS_BETWEEN_ACCOUNT_ACTIONS=0
MAX_ACTIONS_PER_ACCOUNT_PER_DAY=100
```

Restore them to `90` and `10` when you are done.

Comments, likes, and self-comments run assisted-manual by default (the Community
Management API scope is not self-serve). When the target post is live the card
turns into an "open your post, paste this, mark done" step with a deep link; do
the action in your own browser, then press **Mark done**. Posts and reshares are
fully automated. To automate comments and likes through the API instead, set
`COMMUNITY_MANAGEMENT_ENABLED=true` (only works once your app holds
`w_member_social_feed`).

The assisted like and comment on the same post are merged into one "like +
comment" card: one Approve, then one **Mark done** opens the post, likes it, and
pastes the comment in a single pass (both settle together via the batch endpoint).
When `COMMUNITY_MANAGEMENT_ENABLED=true` the two run as separate automated cards.

### A.1 Amplify an existing post (the cleanest full test)

1. Connect your LinkedIn on the Connectors page if you have not.
2. Copy the link of any post (the LinkedIn "Copy link to post" button works; the
   share, embed, feed, and lnkd.in short-link forms all resolve). For a reshare
   the URL must resolve to a share or ugcPost URN, not an activity URN; the form
   warns you if it looks like an activity URN.
3. New campaign, choose Amplify, paste the link into "Post URL to amplify", paste
   the post's text (used to write relevant comments), give it a title, Create.
4. Step 2 is the participant picker: select yourself (or your team). The backend
   plans a like, a comment, and a reshare for each participant. Press Generate to
   draft the comment and reshare text; edit any card if you want.
5. Save, then Launch.
6. Approve each card. Watch the worker publish the reshare; the like and comment
   are merged into one assisted "like + comment" card that turns into a single
   "mark done" step once the target is live. Refresh LinkedIn to see the
   interactions and the campaign progress bar fill.

Exercises: URL parsing, participant expansion, LLM generation, per-post approval,
worker publish, the assisted-manual flow, the stagger, guardrails, and audit log.

### A.2 Distribute (variations and self-comment)

1. New campaign, choose Distribute (needs the editor role). Add seed text
   (required), optionally tone, a Link, an image, and a **Self-comment** (for
   example "For more details: <link>").
2. Step 2 is the participant picker: select yourself (or your team). Each
   participant is planned a post of their own (in their team voice), and, with more
   than one participant, a like and a comment on every other participant's post
   (merged into one assisted "like + comment" card per target). A self-comment, if
   set, is planned as its own tracked card per authored post.
3. Press Generate to draft each variation, then Save and Launch. Approve your post
   card.
4. The worker publishes your post. The self-comment waits until that post is live,
   then becomes an assisted "mark done" step (you cannot comment on a post that
   does not exist yet). If you set a Link, confirm it lands as the first comment on
   the post.

Exercises: per-persona variation generation, publishing a new post, dependency
ordering (self-comment after its parent), and link-in-first-comment placement.

### A.2.1 Re-run a campaign locally

Instead of creating a new campaign each time, reset an existing one back to review
so you can launch it again:

```bash
cd backend
make reset                       # lists recent campaigns and their ids
make reset CAMPAIGN=<id>         # rewind that campaign and its posts to review/pending
make reset CAMPAIGN=<id> REGEN=1 # also rebuild the plan (re-runs generation)
```

Use `make flush` to clear the worker queue if a stuck job keeps re-firing.

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
- Automated likes and comments through the API. By default these run
  assisted-manual, so you can test the full flow with `w_member_social` alone.
  Only if you set `COMMUNITY_MANAGEMENT_ENABLED=true` without holding
  `w_member_social_feed` will they `403`. See section B for the scope note.

---

## B. Pilot over 3 to 5 users (deployed)

This is the real test: several people, each with their own LinkedIn, running a
coordinated push with per-person consent.

### B.0 Prerequisites

- Deploy the API, worker, and web app, and run the migrate job. See the production
  notes in [`SETUP.md`](SETUP.md).
- Complete the post-deploy steps: set `APP_URL` and `FRONTEND_URL`, and register
  the real Google and LinkedIn redirect URLs for the production domain.
- `COMPANY_EMAIL_DOMAIN` is set to your company domain (only those emails can sign
  in), and your own email plus any co-admins are in `BOOTSTRAP_ADMIN_EMAILS`.
- LinkedIn app scopes: `w_member_social openid profile` cover login, own-post
  publishing, and reshares. For like and comment actions you need
  `w_member_social_feed` via the Community Management API, which requires LinkedIn's
  application and vetting. Plan the pilot around what your current scopes allow (see
  "Scope reality" below).

### B.1 Onboard the pilot group

1. Each of the 3 to 5 people signs in with their company Google account. The first
   sign-in runs onboarding (agree to participate, pick a team) and creates their
   user as a viewer (or admin if bootstrapped; some teams auto-grant editor).
2. Each person opens Connectors and connects their own LinkedIn (consenting with
   their own account). Nothing can publish on their behalf until they do.
3. As an admin, open the Users page and confirm each person shows a green
   "Connected" dot. Promote one or two people to editor if they will create
   distribute campaigns. Only admins change roles.

### B.2 Run an amplify campaign across the group

1. One person publishes a real seed post on LinkedIn (or pick an existing one).
2. An editor or admin creates an Amplify campaign with that post's link and text.
3. In the participant picker, select the pilot people (or their teams). Every
   participant is planned a like, a comment, and a reshare. Generate the text.
4. Save and Launch.
5. Each participant approves their own cards (in the portal for now; Slack approval
   comes later). Confirm a person can only act on their own posts.
6. Watch the reshares publish and the likes and comments settle (automated if you
   hold `w_member_social_feed`, otherwise a single assisted "like + comment" card
   per target) over the stagger window, not all at once.

### B.3 Run a distribute campaign

1. An editor creates a Distribute campaign from one seed idea, optionally with a
   Link, an image, and a self-comment.
2. In the participant picker, select the authors (or their teams). Each is planned
   a post of their own, plus a merged like + comment on everyone else's post, plus
   a self-comment on their own post if the campaign has one.
3. Generate, let authors edit and approve their own posts, then watch each person's
   post publish and the cross-interactions and self-comments follow once each post
   is live.

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
