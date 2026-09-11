"""Generischer Webhook-Connector (output). HMAC-signiert; sendet Ergebnisse an ein
beliebiges Ziel-System des Kunden. Ausführung nur hinter dem Bestätigungs-Gate.
"""
from cnode_platform.contracts import Connector, PluginKind, PluginManifest


class WebhookConnector:
    manifest = PluginManifest(
        id="webhook",
        kind=PluginKind.connector,
        name="Webhook (generisch)",
        description="Sendet Ergebnisse HMAC-signiert an ein Kunden-Endpoint. Output-only.",
        capabilities=["output", "hmac"],
        config_schema={"url": "string", "secret_ref": "string"},
        provenance_label="webhook",
    )

    def fetch_sources(self, query: str, ctx) -> list[dict]:
        return []

    def push_output(self, payload: dict, ctx) -> dict:
        return {"ok": False, "detail": "über Bestätigungs-Gate ausführen"}


PLUGIN: Connector = WebhookConnector()
