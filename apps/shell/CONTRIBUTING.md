# Contributing — c:node Shell (`apps/shell`)

Die Shell ist die Chat-UI der c:node-Plattform (Vite + React + TypeScript + Tailwind).
Diese Regeln gelten für Beiträge zu `apps/shell`; plattformweite Grundregeln stehen in der
Repo-Root-`CLAUDE.md`.

## Git-Workflow (verbindlich)

- **Kein Direkt-Commit/-Push auf `main`.** Immer: Branch → PR → Merge.
  - Branch-Namen: `feature/<was>`, `fix/<was>`, `chore/<was>`.
  - Aus frischem `main` branchen, gezielt stagen (**nie** `git add -A` / `git add .`).
  - PR öffnen; Merge nach `main` erst nach Freigabe, `git merge --no-ff`.
- **Pre-push-Guard aktivieren** (blockt versehentliche `main`-Pushes lokal):
  ```bash
  git config core.hooksPath .githooks
  ```
  Serverseitige Branch-Protection ist auf dem privaten Repo planbedingt nicht aktiv —
  der Hook ist der clientseitige Ersatz. Notfall-Override: `git push --no-verify`.
- **Commits:** Conventional-Commits-Stil, wie im Repo etabliert:
  `feat(scope): …`, `fix(scope): …`, `chore(scope): …`, `docs(scope): …`.
  Signierte Commits (CreativateLabs-Org-Policy).

## Lokal entwickeln

```bash
npm install
VITE_GATEWAY_URL=http://localhost:8080 npm run dev      # Shell :3010, API-Gateway :8080
npm run build                                            # tsc + vite — MUSS grün sein vor dem PR
```

- `tsc` ist Teil von `build`; Type-Errors blocken den Merge.
- `VITE_GATEWAY_URL` zeigt auf das bff-Gateway (Sandbox: `https://api.try.c-node.ai`).

## Design-System (nicht verhandelbar)

Login, Signup und Dashboard teilen **eine** visuelle Identität. Neue UI folgt ihr:

- **Marke ist config-driven.** Akzentfarbe kommt aus `tenant.yaml` (`brand.primary`) über
  die CSS-Var `--c-primary`. In Komponenten **kein Hex hardcoden** — `primary` / `secondary`
  (Tailwind-Tokens) bzw. `rgb(var(--c-primary))` nutzen. Aktueller c:node-Akzent: Violett
  `#7C3AED`.
- **Hero-CTA = `.cta-grad`** (Violett→Indigo-Verlauf, weicher Schatten, `hover:brightness`).
  Genau **eine** primäre Aktion pro Fläche (Senden, Upgrade, primärer Overlay-Button).
  Sekundäre Aktionen: solide `bg-primary` oder Ghost/Outline — nicht der Verlauf.
- **Typografie:** `font-display` = Bricolage Grotesque (Headlines), `font-sans` = Inter
  (Fließtext), `font-mono` = IBM Plex Mono (Labels: `uppercase tracking-wider`, klein).
- **Heller Grund** `#F5F6FB` mit dezentem violett/indigo Tiefe-Glow (in `index.css`) —
  beibehalten, nicht pro Komponente überschreiben.
- **Radien/Shadows sparsam** und rollenbasiert (nicht jede Box ist eine Card). Inputs:
  `rounded-xl`, `focus:border-violet-400`.
- **Tenant-agnostisch bleiben:** kein tenant-spezifischer Code in Komponenten — alles
  Markenabhängige kommt aus dem Tenant-Context (`brand()` / CSS-Vars).

Neue Farb-/CTA-Tokens gehören zentral in `src/index.css` bzw. `tailwind.config.js`, damit
sie über die ganze Shell konsistent greifen.

## Deploy (Sandbox)

Die Shell ist ein statischer Build; Backend läuft getrennt.

```bash
VITE_GATEWAY_URL=https://api.try.c-node.ai npm run build
rsync -a --delete dist/ <box>:/opt/cnode-sandbox/dist/     # von Caddy serviert
```

`bff`/`engine` etc. laufen als ECR-Images (`build-push-ecr.sh` → `pull` + `up -d` auf der
Box) und sind vom Shell-Deploy unabhängig.
