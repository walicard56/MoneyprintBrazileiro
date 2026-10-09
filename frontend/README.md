# MoneyPrint Frontend

React + TypeScript + Vite + Tailwind dashboard for the MoneyPrint platform.

## Run

Requires Node.js 18+.

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
```

API calls to `/api/*` are proxied to the backend at `http://127.0.0.1:8000`
(see `vite.config.ts`). Start the backend first (see `../backend/README.md`).

## Pages

- **Dashboard** — counts, status chart, queue depth, estimated cost.
- **Projects** — create/manage channels (niche, language, style, duration).
- **Videos** — generate one or a batch; open a video to watch its pipeline,
  logs, script, and scenes live; approve manual-mode gates.
- **Providers / APIs** — add any provider from the catalog, store its key
  (encrypted server-side; only a masked hint is ever shown), test connectivity.
- **Agents** — tune each agent's provider, model, temperature, and system prompt.
- **Prompts** — edit, version, and test prompts.
- **Accounts** — publishing accounts per platform.
- **Settings** — local API token and seeding defaults.

## Build

```bash
npm run build     # type-checks and builds to dist/
```
