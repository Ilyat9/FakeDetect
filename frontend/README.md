# FakeDetect frontend

Production SPA for the FakeDetect brand-protection platform (React 19 + TypeScript strict + Vite + TanStack stack). Replaces the legacy single-file `index.html` (kept untouched at the repo root for rollback).

## Quick start

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, /api proxied to localhost:8000
```

Environment: copy `.env.example` → `.env.local` and adjust `VITE_API_URL` if needed. Never hardcode API URLs.

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Vite dev server with `/api` proxy |
| `npm run build` | typecheck + production bundle |
| `npm test` | Vitest + RTL + MSW unit/component tests |
| `npm run test:e2e` | Playwright smoke suite |
| `npm run lint` | ESLint incl. FSD layer-boundary rules |
| `npm run generate:api-types` | regenerate TS types from backend OpenAPI |

## Architecture

Feature-Sliced Design with enforced layer boundaries (ESLint fails on violations):

```
src/
  app/        providers, router (route-level code splitting, auth guards)
  pages/      dashboard · analyze · cases · brand-watches · history · whitelist · batch · settings · auth
  widgets/    verdict-card · stats-overview · navigation-sidebar
  features/   cross-entity workflows (form contracts live next to their pages)
  entities/   check · case · brand-watch · whitelist-entry · batch · user
  shared/     api client + typed ApiError · ui primitives · config · lib
```

Key decisions and compromises are documented in the repo-root `docs/architecture-decisions.md`.

### Security notes

- API key is held **in memory** (Zustand), never in localStorage; a sessionStorage mirror exists only to survive dev HMR.
- All requests carry `X-API-Key`; any 401/403 clears the session globally.
- CSP and hardened headers are set by nginx (`frontend/nginx.conf`).

## Deployment

```bash
docker compose up --build   # frontend on :8080, nginx proxies /api/* to FastAPI
```
