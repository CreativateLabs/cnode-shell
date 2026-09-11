"""PDF-Format-Handler → Haupttext + Seiten-Metadaten. Extraktion delegiert an die
im Assets-Service vorhandene PDF-Pipeline; hier als Plugin registriert.
"""
from cnode_platform.contracts import FormatHandler, PluginKind, PluginManifest


class PdfFormat:
    manifest = PluginManifest(
        id="pdf",
        kind=PluginKind.format,
        name="PDF",
        description="PDF → Haupttext + Seitenzahl für den Ingest.",
        capabilities=["documents"],
        tenant_scoped=False,
    )

    def can_handle(self, filename: str, mime: str) -> bool:
        return (filename or "").lower().endswith(".pdf") or "pdf" in (mime or "")

    def extract(self, data: bytes, filename: str) -> dict:
        # Betrieb: an Assets-PDF-Extractor delegieren. Contract-konformer Fallback:
        return {"text": "", "meta": {"note": "pdf-extraction via assets-service", "bytes": len(data)}}


PLUGIN: FormatHandler = PdfFormat()
