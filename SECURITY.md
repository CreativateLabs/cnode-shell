# Security Policy

Thank you for helping keep c:node Shell and its users safe.

## Supported versions

Security fixes land on `main` and in the latest tagged release. Please run the most recent version;
older releases do not receive backports.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues, pull requests or
discussions.**

Instead, email **privacy@creativate.tech** with the subject line `[SECURITY] cnode-shell`.

Please include as much of the following as you can:

- a description of the issue and its impact,
- the affected version / commit and your deployment type (Docker Compose, desktop app, …),
- step-by-step reproduction instructions or a proof of concept,
- any suggested mitigation.

## What to expect

- We acknowledge your report within **5 business days**.
- We keep you informed while we investigate and fix the issue.
- We coordinate a disclosure date with you and credit you in the release notes, unless you prefer to
  stay anonymous.

Please give us a reasonable amount of time to fix the issue before any public disclosure, and avoid
accessing or modifying data that isn't yours while testing.

## Scope

In scope: the code in this repository (UI, services, desktop app, MCP server, compose files).

Out of scope: the public demo at try.c-node.ai under load/DoS testing, social engineering, and issues in
third-party dependencies that are already publicly known (please report those upstream).

## Hardening reminders for self-hosters

- Set your own `AUTH_SECRET` and `SUPERADMIN_EMAIL` before exposing the stack beyond localhost.
- Keep API keys in `.env` (gitignored) — never in `tenant.yaml` or commits.
- Put the gateway behind TLS (e.g. Caddy or nginx) when it is reachable from a network.
