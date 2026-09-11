"""Gmail-Connector (input + output). Belegt bereits im BFF (OAuth) — hier als Plugin
registriert, damit er in der Tenant-Bibliothek erscheint und einheitlich adressierbar ist.
"""
from cnode_platform.contracts import Connector, PluginKind, PluginManifest


class GmailConnector:
    manifest = PluginManifest(
        id="google",                      # matcht tenant.connectors.google
        kind=PluginKind.connector,
        name="Gmail / Google Drive",
        description="Mails & Drive-Dokumente als Quellen; Entwürfe/Antworten als Ausgabe (hinter Gate).",
        capabilities=["input", "output", "oauth"],
        provenance_label="gmail",
    )

    def fetch_sources(self, query: str, ctx) -> list[dict]:
        # Delegiert im Betrieb an den BFF-OAuth-Pfad; hier Contract-konform leer.
        return []

    def push_output(self, payload: dict, ctx) -> dict:
        # Ausführung NUR über das Core-Bestätigungs-Gate (action.execute).
        return {"ok": False, "detail": "über Bestätigungs-Gate ausführen"}


PLUGIN: Connector = GmailConnector()
