"""Generischer REST-System-Connector: bindet eine externe JSON-API als Quelle an.
Wird per Tenant-Extension konfiguriert (Basis-URL, Auth-Header via secret_ref).
"""
from cnode_platform.contracts import PluginKind, PluginManifest, SystemConnector


class RestSystem:
    manifest = PluginManifest(
        id="rest-system",
        kind=PluginKind.system,
        name="REST-API-System",
        description="Externe JSON-API als abfragbare Quelle (Basis-URL + Auth via secret_ref).",
        capabilities=["query"],
        config_schema={"base_url": "string", "auth_ref": "string"},
    )

    def __init__(self) -> None:
        self._cfg: dict = {}

    def connect(self, config: dict, ctx) -> None:
        self._cfg = dict(config or {})

    def query(self, q: str, ctx) -> list[dict]:
        # Betrieb: httpx GET base_url mit q; Contract-konformer Fallback:
        return []


PLUGIN: SystemConnector = RestSystem()
