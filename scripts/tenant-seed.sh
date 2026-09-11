#!/usr/bin/env bash
# Lädt tenants/<slug>/seed.json in die eigene Graph-Group des Tenants (graph-core).
# Jeder Tenant = anderer Kunde → eigene Seed-Daten, isoliert per group_id.
#   ./scripts/tenant-seed.sh <slug> [graph-core-url]
set -euo pipefail
SLUG="${1:-}"
URL="${2:-http://localhost:8010}"
[ -z "$SLUG" ] && { echo "Usage: $0 <slug>" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SEED="$ROOT/tenants/$SLUG/seed.json"
YAML="$ROOT/tenants/$SLUG/tenant.yaml"
[ -f "$SEED" ] || { echo "kein Seed: $SEED" >&2; exit 1; }

# group_id aus tenant.yaml lesen (Fallback: slug)
GROUP="$(grep -E '^[[:space:]]*group_id:' "$YAML" 2>/dev/null | head -1 | sed -E 's/.*group_id:[[:space:]]*//; s/[[:space:]]*#.*//; s/[[:space:]]*$//')"
[ -z "$GROUP" ] && GROUP="$SLUG"

# seed.json + group in EIN JSON-Objekt gießen und posten
python3 - "$SEED" "$GROUP" <<'PY' | curl -s -X POST "$URL/seed" -H 'content-type: application/json' --data-binary @-
import json,sys
d=json.load(open(sys.argv[1])); d["group"]=sys.argv[2]; d["replace"]=True
print(json.dumps(d))
PY
echo "  → Seed für Tenant '$SLUG' in group '$GROUP' geladen."
