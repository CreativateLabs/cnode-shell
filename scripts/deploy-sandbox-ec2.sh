#!/usr/bin/env bash
# c:node Sandbox → cnode-prod EC2 (kosteneffizient, ~€0 marginal, Gemini, IP-abgeriegelt).
# AUF DER BOX ausführen (nach SSH), aus dem Repo-Root. Kein GPU nötig.
#
# Voraussetzungen auf der Box: docker + compose, caddy (läuft bereits), node+npm (für den Shell-Build),
# eine .env.sandbox (aus .env.sandbox.example, mit GOOGLE_API_KEY), DNS try./api.try. -> Box-IP.
set -euo pipefail
cd "$(dirname "$0")/.."

DIST_DIR="${SANDBOX_DIST_DIR:-/opt/cnode-sandbox/dist}"
API_URL="${SANDBOX_API_URL:-https://api.try.c-node.ai}"
COMPOSE="docker compose \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.tenant.yml \
  -f infra/docker-compose.public.yml \
  -f infra/docker-compose.sandbox-ec2.yml \
  --env-file .env.sandbox"

echo "→ 1/4  Shell statisch bauen (VITE_GATEWAY_URL=$API_URL)"
( cd apps/shell && npm ci && VITE_GATEWAY_URL="$API_URL" npm run build )
sudo mkdir -p "$DIST_DIR"
sudo rsync -a --delete apps/shell/dist/ "$DIST_DIR/"

echo "→ 2/4  Sandbox-Backend starten (lean: graph-db graph-core postgres engine assets bff)"
TENANT=cnode $COMPOSE up -d --build graph-db graph-core postgres engine assets bff

echo "→ 3/5  NENA-Ebenen seeden (Markt/Mesh = bezahlt · Vorschau = Free-Sandbox-Teaser)"
sleep 4  # Engine hochfahren lassen
for layer in market mesh preview; do
  if curl -fsS -X POST "http://127.0.0.1:18091/${layer}/seed" >/dev/null 2>&1; then
    echo "   ${layer}-Ebene geseedet."
  else
    echo "   (${layer}-seed übersprungen — Engine noch nicht bereit; später: curl -X POST 127.0.0.1:18091/${layer}/seed)"
  fi
done

echo "→ 4/5  Caddy-Vhosts (einmalig anhängen, dann reload)"
if ! grep -q "api.try.c-node.ai" /etc/caddy/Caddyfile 2>/dev/null; then
  sudo tee -a /etc/caddy/Caddyfile < infra/caddy/sandbox.Caddyfile >/dev/null
  echo "   Vhosts angehängt."
fi
sudo systemctl reload caddy || sudo caddy reload --config /etc/caddy/Caddyfile

echo "→ 5/5  Smoke-Test"
sleep 3
curl -fsS http://127.0.0.1:18090/tenant/context | sed 's/{/\n{/' | head -1 || echo "   (bff noch nicht bereit — kurz warten)"
echo "✓ Sandbox deployed:  https://try.c-node.ai   (API: $API_URL)"
echo "  Stoppen:  TENANT=cnode $COMPOSE down"
