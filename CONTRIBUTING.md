# Contributing to c:node Shell

Thanks for your interest! Bug reports, docs fixes, translations, connectors and agent templates are all
welcome. Issues and PRs in English or German are fine.

## Table of contents

- [Where to start](#where-to-start)
- [Development setup](#development-setup)
- [Ground rules](#ground-rules)
- [Pull requests](#pull-requests)
- [CLA](#contributor-license-agreement-cla)
- [Security](#security)

## Where to start

| Contribution | Where it lives | Notes |
|---|---|---|
| 🐛 Bug fixes | anywhere | Open or pick an issue first so we avoid duplicate work |
| 🔌 Connectors | `platform/cnode_platform/plugins/connectors/` | See [platform/README.md](platform/README.md); request one with the *Connector request* template |
| 📄 File formats | `platform/cnode_platform/plugins/formats/` | `FormatHandler` contract |
| 🤖 Agents / domain services | `platform/cnode_platform/plugins/agents/`, `services/domain-example/` | Copy `domain-example` as a template |
| 🌍 Translations | `apps/shell/src/i18n/catalog/` | Every key exists in `de`, `en` and `fr` |
| 🎨 Themes / tenants | `tenants/_template/` | Brand colors via `tenant.yaml` + `brand/theme.css` |
| 📚 Docs | `README.md`, `services/*/README.md` | Always appreciated |

Look for issues labelled
[`good first issue`](https://github.com/CreativateLabs/cnode-shell/labels/good%20first%20issue) or
[`help wanted`](https://github.com/CreativateLabs/cnode-shell/labels/help%20wanted).
For larger features, open an issue first and describe the use case — it saves everyone time.

## Development setup

**Prerequisites:** Docker with Compose v2, Node.js 20+ and pnpm, Python 3.11+, and
[Ollama](https://ollama.com) (or a Gemini/Claude key).

```bash
cp .env.example .env
docker compose up --build -d        # backend from source (gateway :8080)

cd apps/shell
pnpm install
pnpm dev                            # UI on http://localhost:3010
```

Useful targets: `make health`, `make logs`, `make down`, `make shell` (Tauri desktop app),
`make tenant-new NAME=<slug>`.

### Checks before you open a PR

```bash
# frontend: type-check + build must be green
cd apps/shell && pnpm build

# python: at minimum, everything must compile
python3 -m py_compile $(git ls-files '*.py')
```

CI runs the same checks on every pull request.

## Ground rules

- **Extend via plugins, don't fork.** New connectors, formats, agents and systems go through `platform/`
  or tenant extensions — no tenant-specific special cases in the core.
- **Evidence stays mandatory.** Answers bind claims to sources. Don't add code paths that let the model
  answer without grounding and present it as sourced.
- **Tenant isolation is hard.** No cross-tenant reads, ever.
- **Outbound actions stay behind the human-in-the-loop gate.**
- **Never commit secrets or real customer data.** Only `.env` references; `.env` is gitignored.
- **UI:** brand colors come from the tenant config (`--c-primary` / Tailwind `primary`) — no hard-coded
  hex values in components. New user-facing strings go into the i18n catalog in all three languages.
  See [apps/shell/CONTRIBUTING.md](apps/shell/CONTRIBUTING.md) for UI details.

## Pull requests

1. Fork the repo and create a branch from `main`: `feature/<what>`, `fix/<what>`, `docs/<what>`.
2. Keep the diff small and focused; explain the *why* in the description.
3. Use [Conventional Commits](https://www.conventionalcommits.org/) style, e.g.
   `feat(connectors): add Nextcloud connector`, `fix(engine): …`, `docs: …`.
4. Fill in the PR template, link the issue (`Closes #123`), add screenshots for UI changes.
5. A maintainer reviews; please be patient and responsive to feedback.

Maintainers: enable the local guard against accidental pushes to `main` with
`git config core.hooksPath .githooks`.

## Contributor License Agreement (CLA)

c:node Shell is dual-licensed (AGPL-3.0 and a commercial license). To make that possible, contributions
are accepted under the [CLA](CLA.md). In your first PR, add this comment:

> I have read the CLA and I agree to it. My contribution is my own original work.

## Security

Please **do not** report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md).

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating you agree to
uphold it.
