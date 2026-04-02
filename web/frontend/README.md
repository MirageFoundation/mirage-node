# Mirage Frontend

## Quick Start (one command)

    ./run_frontend_local.sh

Run from `web/frontend`. On first run it asks which node to connect to,
installs dependencies, and opens http://localhost:3000 in your browser.

## Configuration

Edit `REACT_APP_API_BASE` in `deploy/templates/env/frontend.env` to point at
a node (e.g. `https://mirage.vote`). Leave empty for full-stack local mode.

## Scripts

- `npm start` -- CRA dev server
- `npm run build` -- production build
