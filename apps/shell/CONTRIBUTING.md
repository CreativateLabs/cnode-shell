# Contributing — c:node Shell UI (`apps/shell`)

The shell is the chat UI of c:node (Vite + React + TypeScript + Tailwind, wrapped by Tauri v2 for the
desktop app). General rules, setup and the PR process are in the root
[CONTRIBUTING.md](../../CONTRIBUTING.md); this file covers UI specifics.

## Develop locally

```bash
pnpm install
VITE_GATEWAY_URL=http://localhost:8080 pnpm dev     # UI :3010, gateway :8080
pnpm build                                          # tsc + vite — must be green before a PR
pnpm tauri dev                                      # desktop app (needs Tauri prerequisites)
```

- `tsc` is part of `build`; type errors block the merge.
- `VITE_GATEWAY_URL` points at the `bff` gateway (local stack: `http://localhost:8080`).

## Design system

Login, signup and the workspace share **one** visual identity. New UI follows it:

- **Branding is config-driven.** The accent color comes from `tenant.yaml` (`brand.primary`) through the
  CSS variable `--c-primary`. **Don't hard-code hex values** in components — use the Tailwind tokens
  `primary` / `secondary` or `rgb(var(--c-primary))`.
- **Primary CTA = `.cta-grad`.** Exactly **one** primary action per surface (send, upgrade, primary
  overlay button). Secondary actions: solid `bg-primary` or ghost/outline — not the gradient.
- **Typography:** `font-display` = Bricolage Grotesque (headlines), `font-sans` = Inter (body),
  `font-mono` = IBM Plex Mono (small `uppercase tracking-wider` labels).
- **Light background** with a subtle depth glow (in `index.css`) — keep it, don't override per component.
- **Radii and shadows sparingly** and by role (not every box is a card). Inputs: `rounded-xl`.
- **Stay tenant-agnostic:** no tenant-specific code in components — everything brand-dependent comes from
  the tenant context (`brand()` / CSS variables).

New color or CTA tokens belong in `src/index.css` or `tailwind.config.js` so they apply consistently.

## i18n

All user-facing strings live in `src/i18n/catalog/*.ts` with entries for `de`, `en` and `fr`.
Add new keys to all three languages in the same PR.
