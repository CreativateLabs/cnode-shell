# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Community files: `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md`, issue templates
  (bug, feature, connector request), pull-request template, this changelog.
- CI workflow: UI type-check + build, Python compile check, Compose config validation.

### Changed
- README rewritten for first-time users: working two-step quickstart (backend via Docker Compose, UI via
  pnpm), feature overview, Mermaid architecture diagram, configuration table, open-core comparison,
  roadmap, privacy/telemetry note.
- `CONTRIBUTING.md` expanded with contribution areas, local checks and PR flow; UI guide translated to
  English.
- `.env.example` cleaned up and documented; default model aligned with the README (`qwen2.5:7b`).
- Product naming in docs and UI strings unified to **c:node Graph**.

### Fixed
- `SUPERADMIN_EMAIL` no longer defaults to a maintainer address in `infra/docker-compose.yml`.

## [0.1.0] - 2026-09-24

First public release of the open-core shell.

### Added
- Open-core c:node Shell: grounded chat UI (React + Vite + Tailwind), gateway (`bff`), retrieval and
  synthesis engine, pgvector knowledge-graph memory (`graph-core`), CPU embedder, asset ingest, voice
  (local STT), MCP server, reference domain services and plugin framework (`platform/`).
- Config-driven tenants and themes under `tenants/`.
- One-command `docker compose up --build` from the repo root (`compose.yaml` bundles the `infra/` overlays).
- Native desktop release workflow (Tauri v2): macOS `.dmg`, Windows `.msi`/`.exe`, Linux `.AppImage`/`.deb`,
  built on tag push as a draft GitHub Release.
- App icons using the c:node bracket-C mark.
- Dual licensing: AGPL-3.0 plus a commercial license; contributor license agreement.

[Unreleased]: https://github.com/CreativateLabs/cnode-shell/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CreativateLabs/cnode-shell/releases/tag/v0.1.0
