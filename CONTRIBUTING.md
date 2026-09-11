# Contributing to c:node

Thanks for your interest! c:node is open-core (AGPL-3.0).

## Setup
```bash
cp .env.example .env
TENANT=cnode docker compose -f infra/docker-compose.yml \
  -f infra/docker-compose.tenant.yml -f infra/docker-compose.oss.yml up --build
```
Shell on :3010, API on :8080.

## Ground rules
- **Extend via plugins, don't fork.** New connectors/formats/agents/systems go through
  `platform/` or tenant extensions — no ad-hoc special cases in the core.
- **Evidence stays mandatory.** Answers bind claims to sources; no guessing.
- **Tenant isolation is hard** (no cross-tenant reads).
- **Never commit secrets** — only `.env` references (`.env` is gitignored).
- **No tenant- or customer-specific data** in commits.

## Pull requests
Feature branch → PR against `main`. Keep diffs small and focused; explain the *why*.
Python must pass `python -m py_compile`; the frontend must build (`npm run build`).

## Security
Please report vulnerabilities privately (not via a public issue) — email the maintainers
(see the repo contact), so we can fix before disclosure.
