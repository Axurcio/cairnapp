# Cairn mobile (placeholder)

A minimal Expo (React Native) shell that checks the API's `/health` endpoint.
The backend is the focus of the scaffold; this directory reserves the app's place
in the monorepo and its boundary:

- The app is a **thin client**. It posts participant messages to
  `POST /v1/journeys/{id}/messages` and renders Cairn's reply.
- It never decides what to ask next, never stores AI context, and never talks to
  Graphiti, Neo4j or an LLM directly.
- Offline capture may set `occurred_at` on messages; the server records it.

```bash
cd apps/mobile
npm install
npx expo start
```

Set `expo.extra.apiUrl` in `app.json` to reach your API (from a phone, use your
machine's LAN address rather than `localhost`).
