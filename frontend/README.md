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
| `/app/users` | Admin user management |
| `/app/connections` | LinkedIn connection management |
| `/app/skills` | Writing skill management |

The Continue with Google button redirects to `${VITE_API_BASE_URL}/v1/google/login`.

## Layout

```
src/
  main.tsx              entry, BrowserRouter
  App.tsx               routes
  components/
    Wordmark.tsx        Fraunces wordmark
    AppShell.tsx        sidebar + header shell
    GoogleSignInButton.tsx
  pages/
    Landing.tsx         public marketing + sign-in
    Dashboard.tsx       placeholder app home
  lib/utils.ts          cn() helper
  styles/globals.css    design tokens as HSL CSS variables
tailwind.config.ts      token aliases (paper, sand, ink, clay, ok/pending/fail)
components.json         shadcn/ui config
```
