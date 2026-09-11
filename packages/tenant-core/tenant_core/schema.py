"""Getyptes Schema eines cNode-Tenants (pydantic v2).

Dieselbe Struktur beschreibt einen Tenant, egal ob die Werte aus einer
`tenant.yaml` (dedicated/on-prem) oder aus einer DB-Zeile (shared/SaaS) kommen.
Der Core liest ausschließlich diesen validierten Kontext — nie Marke/Kunde direkt.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Brand(BaseModel):
    wordmark: str = "cNode"
    assistant_name: str = ""       # Name des Assistenten in der Copy (leer → name/wordmark)
    assistant_role: str = ""       # kontextueller Intro: „dein Assistent für <role>"
    logo: str = ""
    primary: str = "#4B6EF5"      # Primärfarbe (Logo-Bracket, CTAs, Highlights)
    secondary: str = ""            # Sekundärfarbe (Akzent-Punkt); leer → nutzt accent
    accent: str = "#36C399"        # Alias/Fallback für secondary
    favicon: str = "🕸️"


class Modules(BaseModel):
    # Voller Scope = alle an. Hier wird nur abgeschaltet, was ein Tenant NICHT bekommt.
    scouts: list[str] = Field(default_factory=lambda: ["lead", "startup", "trend", "competitor", "regulatorik"])
    agents: list[str] = Field(default_factory=lambda: ["recherche", "memo", "outreach", "funding", "governance"])
    ontology_studio: bool = True
    verifiable_reasoning: bool = True


class LLM(BaseModel):
    provider: Literal["ollama", "api"] = "ollama"
    model: str = "qwen2.5:7b"
    api_base: str = ""
    rationale: bool = True


class Graph(BaseModel):
    backend: Literal["nen", "neo4j-local"] = "nen"
    url: str = "http://nen:8001"
    group_id: str = ""  # default = tenant.id (siehe TenantContext)


class Storage(BaseModel):
    driver: Literal["local", "s3"] = "local"
    bucket: str = ""


class DB(BaseModel):
    driver: Literal["sqlite", "postgres"] = "sqlite"
    url: str = ""


class Connector(BaseModel):
    enabled: bool = False
    secret_ref: str = ""  # nur Referenz: env:NAME | ssm:/path | vault:/path — NIE inline


class Auth(BaseModel):
    mode: Literal["magic-link", "password", "sso"] = "magic-link"
    admin_emails: list[str] = Field(default_factory=list)


class Extension(BaseModel):
    name: str
    path: str = ""  # relativer Pfad im Tenant-Repo, oder leer für installiertes Paket


class Domain(BaseModel):
    """Ein Domänen-Microservice (funding/sales/legal …), der den cNode-Domain-Contract
    erfüllt (GET /ontology, POST /enrich, GET /health). Zustandsloser Producer: er liefert
    getypte Graph-Fragmente — persistiert wird ausschließlich über den Engine-Graph-Adapter
    (Provenienz + Layer erzwungen). Aktivierung je Tenant."""
    id: str                                  # eindeutig, kebab-case (z.B. "funding")
    base_url: str                            # http://<service>:<port> im Compose-Netz
    layer: Literal["client", "market", "mesh"] = "client"  # Ziel-Ebene der Fragmente
    enabled: bool = True


class TenantMeta(BaseModel):
    id: str
    name: str
    mode: Literal["dedicated", "shared"] = "dedicated"
    locale: Literal["de", "en", "fr"] = "de"


class TenantSpec(BaseModel):
    """Die vollständige, validierte Definition eines Tenants."""
    tenant: TenantMeta
    brand: Brand = Field(default_factory=Brand)
    modules: Modules = Field(default_factory=Modules)
    llm: LLM = Field(default_factory=LLM)
    graph: Graph = Field(default_factory=Graph)
    storage: Storage = Field(default_factory=Storage)
    db: DB = Field(default_factory=DB)
    connectors: dict[str, Connector] = Field(default_factory=dict)
    auth: Auth = Field(default_factory=Auth)
    extensions: list[Extension] = Field(default_factory=list)
    domains: list[Domain] = Field(default_factory=list)
    secrets: dict = Field(default_factory=lambda: {"source": "env"})
