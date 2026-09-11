"""CSV-Format-Handler → Text + Spalten-Metadaten (Basis für die Ontology-Pipeline)."""
import csv
import io

from cnode_platform.contracts import FormatHandler, PluginKind, PluginManifest


class CsvFormat:
    manifest = PluginManifest(
        id="csv",
        kind=PluginKind.format,
        name="CSV / TSV",
        description="Tabellen → Zeilen-Text + Spaltenkopf-Metadaten für Ingest & Ontologie.",
        capabilities=["tables"],
        tenant_scoped=False,   # Ingest-Basis, immer verfügbar
    )

    def can_handle(self, filename: str, mime: str) -> bool:
        f = (filename or "").lower()
        return f.endswith((".csv", ".tsv")) or "csv" in (mime or "")

    def extract(self, data: bytes, filename: str) -> dict:
        text = data.decode("utf-8", errors="replace")
        delim = "\t" if filename.lower().endswith(".tsv") else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        header = rows[0] if rows else []
        body = "\n".join(delim.join(r) for r in rows[1:2000])
        return {"text": body, "meta": {"columns": header, "rows": max(0, len(rows) - 1)}}


PLUGIN: FormatHandler = CsvFormat()
