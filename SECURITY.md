# Security Policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in this repository:

- Prefer using the platform's private reporting mechanism (e.g., GitHub Security Advisories) if available.
- If private reporting is not available, open an issue **without** including exploit details, secrets, or sensitive logs. Provide a high-level description and we will follow up.

## Secrets policy (critical)

This project must **never** commit or publish:

- Wallet mnemonics / seed phrases / recovery phrases
- Private keys (validator keys, node keys, SSH keys, TLS keys/certs)
- API tokens (Cloudflare, OpenAI/ChatGPT, etc.)
- Database passwords / connection URLs containing credentials

Notes:

- `.env` and `.env.*` are gitignored. Use example files like `.env.example` and `deploy/templates/*.env.example`.
- For a quick local check, run a secret scanner from the repo root, for example:
  - `gitleaks detect --no-git --source .`


