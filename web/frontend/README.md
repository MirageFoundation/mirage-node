# Mirage Frontend

## Quick Start (one command)

    ./run_frontend_local.sh

Run from `web/frontend`. On first run it asks which node to connect to,
installs dependencies, and opens http://localhost:3000 in your browser.

Note: this frontend currently relies on `legacy-peer-deps` because
`react-helmet-async` has a stale React peer range while the app uses React 19.
A project-local `.npmrc` is included so plain `npm install` works.
If you install manually and hit peer resolution errors, run:

    npm install --legacy-peer-deps

## Configuration

Edit `REACT_APP_API_BASE` in `deploy/templates/env/frontend.env` to point at
a node (e.g. `https://mirage.vote`). Leave empty for full-stack local mode.

## Scripts

- `npm start` -- CRA dev server
- `npm run build` -- production build
