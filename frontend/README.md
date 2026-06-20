# super-hype frontend

The super-hype web app. Vite + React 18 + TypeScript, styled with Tailwind CSS
and shadcn/ui on the section 14 design tokens (warm paper and clay palette,
Fraunces for the wordmark, Inter for UI).

## Requirements

- Node.js 20+
- npm (a `package-lock.json` is committed)

## Setup

```bash
cd frontend
cp .env.example .env     # set VITE_API_BASE_URL
npm install
```

Environment:

| Key | What it is |
| --- | --- |
| `VITE_API_BASE_URL` | base URL of the backend API, e.g. `http://localhost:8000` |

## Run

```bash
npm run dev       # dev server at http://localhost:5173
npm run build     # typecheck (tsc --noEmit) + production build to dist/
npm run preview   # serve the production build locally
npm run lint      # typecheck only
```

## Routes

| Path | Page |
| --- | --- |
| `/` | Marketing landing page with the Continue with Google call to action |
| `/app` | Authenticated app shell |
| `/app/campaigns` | Campaigns list with per-row View, Edit, and Delete actions |
| `/app/campaigns/new` | Create a campaign (two-step wizard: details, then assign people) |
| `/app/campaigns/:id` | Campaign view (read-only): info, posts, and interactions |
| `/app/campaigns/:id/edit` | Edit a campaign (same two-step wizard, preloaded) |
| `/app/connections` | LinkedIn connection management |
| `/app/users` | Admin user management |

The Continue with Google button redirects to `${VITE_API_BASE_URL}/v1/google/login`.

## Layout

```
src/
  main.tsx                entry, BrowserRouter
  App.tsx                 routes
  auth/AuthContext.tsx    current user + token, login/logout
  components/
    Wordmark.tsx          Fraunces wordmark
    AppShell.tsx          sidebar + header shell
    GoogleSignInButton.tsx
    ProtectedRoute.tsx    auth gate for /app routes
    CampaignFields.tsx    wizard step 1: campaign config fields
    PlanBuilder.tsx       wizard step 2: people matrix (search, select, like/comment/repost)
    CampaignWizard.tsx    shared two-step wizard (create + edit)
    DeleteCampaignDialog.tsx  type-to-confirm delete modal
  pages/
    Landing.tsx           public marketing + sign-in
    Dashboard.tsx         placeholder app home
    Campaigns.tsx         campaigns list + View/Edit/Delete actions
    CampaignEditor.tsx    create/edit wizard host (/new and /:id/edit)
    CampaignDetail.tsx    read-only view: info, posts, approve/skip, launch
    Connections.tsx       LinkedIn connect/reconnect/disconnect
    Users.tsx             admin user + role management
    AuthCallback.tsx      Google OAuth code exchange
    LinkedInCallback.tsx  LinkedIn OAuth code exchange (resumes paused actions)
  lib/
    api.ts                apiFetch wrapper + ApiError
    utils.ts              cn() helper
  styles/globals.css      design tokens as HSL CSS variables
tailwind.config.ts      token aliases (paper, sand, ink, clay, ok/pending/fail)
components.json         shadcn/ui config
```
