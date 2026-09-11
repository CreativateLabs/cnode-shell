#!/usr/bin/env bash
# Scaffold einen neuen lokalen Dev-Tenant aus tenants/_template.
#   ./scripts/tenant-new.sh <name>
# Erzeugt tenants/<name>/ mit tenant.yaml (id/name gesetzt) + brand/.
# Für Produktion: eigenes Repo cnode-tenant-<name> aus dem Template statt lokal.
set -euo pipefail

NAME="${1:-}"
if [[ -z "$NAME" ]]; then
  echo "Usage: $0 <tenant-name>" >&2
  exit 1
fi
if [[ ! "$NAME" =~ ^[a-z0-9][a-z0-9-]{1,30}$ ]]; then
  echo "Ungültiger Name (nur a-z, 0-9, '-'): $NAME" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/tenants/_template"
DST="$ROOT/tenants/$NAME"

if [[ -e "$DST" ]]; then
  echo "Tenant existiert bereits: $DST" >&2
  exit 1
fi

cp -R "$SRC" "$DST"
# id + name in der frischen tenant.yaml setzen (macOS/BSD & GNU sed kompatibel).
TITLE="$(printf '%s' "$NAME" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')"
sed -i.bak -e "s/^  id: .*/  id: $NAME/" \
           -e "s/^  name: .*/  name: \"$TITLE\"/" \
           -e "s/^  group_id: .*/  group_id: $NAME/" "$DST/tenant.yaml"
rm -f "$DST/tenant.yaml.bak"

echo "✓ Tenant angelegt: tenants/$NAME"
echo "  Bearbeite tenants/$NAME/tenant.yaml (Marke, Module, LLM-Mode, Connectoren),"
echo "  dann:  TENANT=$NAME make up"
