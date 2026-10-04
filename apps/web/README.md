# Cairn website

React + Vite + TypeScript. Participants, facilitators and tenant admins sign in and use
Cairn from the browser: journeys, the conversation, observations, the descriptive report,
evidence upload and consent withdrawal.

The site holds no business logic. Every decision and every authorization check happens in
the API; what a user sees is whatever `/v1` returns for their session.

## Run it

```bash
make api          # API on :8000 (repo root, Dev Container)
make seed         # synthetic demo data and sign-in accounts
make web          # this site on http://localhost:5173 with hot reload
```

`/v1` is proxied to `CAIRN_API_URL` (default `http://localhost:8000`), so the site and the
API share one origin and the session cookie works without CORS. In Docker Compose the
`web` service serves the production build with nginx on http://localhost:3000 and proxies
`/v1` to the `api` service ([nginx.conf](nginx.conf)).

The sign-in page lists the synthetic demo accounts from `make seed` (password
`cairn-demo-only`, local only) and signs in with one click. They are shown in the dev
server and in builds made with `VITE_DEMO_ACCOUNTS=true` (Compose sets it; override with
`CAIRN_WEB_DEMO_ACCOUNTS=false`). [src/demoAccounts.ts](src/demoAccounts.ts) holds the
list; a plain production build tree-shakes it away.

## How sign-in works

- `POST /v1/auth/login` sets an HttpOnly session cookie and returns a CSRF token.
- [src/api/client.ts](src/api/client.ts) keeps that token in memory and sends it as
  `X-CSRF-Token` on every POST. Page scripts never see the session token itself.
- After a reload, `GET /v1/auth/session` restores the account and CSRF token.
- Any 401 (expired, revoked or signed out elsewhere) returns the user to the sign-in page,
  and after signing in they go back to the page they asked for (same-site paths only).

## Checks

```bash
npm run typecheck
npm test          # vitest: API client (CSRF, 401 handling) and formatting helpers
npm run build
```

`make web-check` runs all three; CI runs them in the `web` job.

## Layout

```
src/api/          fetch client + types mirroring cairn/api/schemas.py
src/auth/         AuthProvider: session restore, login, logout, expiry
src/pages/        LoginPage, JourneysPage, JourneyPage
src/components/   Layout, Conversation, side panels (observations, report, evidence, consent)
```
