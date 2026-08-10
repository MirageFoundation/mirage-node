# Mirage Frontend

## Quick Start (one command)

    ./run_frontend_local.sh

Run from `web/frontend`. On first run it asks which node to connect to,
installs dependencies, and opens http://localhost:3000 in your browser.

Note: this frontend currently relies on `legacy-peer-deps` because
`react-helmet-async` has a stale React peer range while the app uses React 19.
If you install manually and hit peer resolution errors, run:

    npm install --legacy-peer-deps

## Configuration

Edit `VITE_API_BASE` in `deploy/templates/env/frontend.env` to point at
a node (e.g. `https://mirage.vote`). Leave empty for full-stack local mode.
`VITE_*` values are bake-time (dev server / Docker build), not runtime.

`REACT_APP_GIPHY_API_KEY` remains a **backend** env var returned via `get_node_config`.

## Scripts

- `npm run dev` — Vite dev server
- `npm run build` — production build into `build/` (CRA-compatible `/static/` paths)
- `npm run preview` — serve the production build
- `npm run lint` — ESLint
- `npm run test` — Vitest unit tests
- `npm run test:e2e` — Playwright mocked browser tests
- `npm run check:pow-assets` — verify vendored Argon2 PoW assets
- `npm run check:bundle-policy` — reject GTM / remote worker scripts in build output

## Security notes

- Plaintext recovery-phrase storage is the intentional default; password/passkey/memory are optional.
- Recovery phrases never travel through React Router `location.state` (in-memory handoff only).
- Remote thumbnails go through the Photon/wsrv image proxies (Photon primary, wsrv for query-string URLs and as fallback); `mediaPolicy` rejects unsafe URLs.
- PoW Argon2 is same-origin under `/pow/`.
