"""Connector-Katalog — recherchierte API-Metadaten der EU-/DACH- + globalen Stack-Tools.

Deklarativ statt 25 Einzeldateien: jeder Eintrag beschreibt Base-URL, Auth-Modell,
Read-Endpoint (→ `fetch_sources`) und (optional) einen Output-Endpoint. Ein einziger
generischer Connector (`plugins/connectors/catalog.py`) macht daraus je Tool ein
tenant-aktivierbares Plugin.

Grundregeln der Plattform gelten:
  • **Secrets nur als Ref** (`env:`/`ssm:`/`vault:`), nie inline. Feld: `auth.secret_ref`.
  • **Provenienz erzwungen** — `provenance_label` je Quelle.
  • **Output nur hinter dem Bestätigungs-Gate** (der Connector schreibt nie direkt hinaus).
  • **Kein Tenant-Code** — Aktivierung/Regionen/Instanzen kommen aus tenant.yaml.

Auth-Modelle:
  oauth2            — Authorization-Code-Flow (Token liegt per-Tenant im BFF-OAuth-Store)
  oauth2_cc         — Client-Credentials (server-to-server)
  api_key           — statischer Schlüssel/Token im Header
  basic             — HTTP-Basic (user:pass / key:secret)
  signed            — provider-spezifische Signatur (z.B. OVH) → nur dokumentiert

Wo `search` gesetzt ist, ruft der generische Connector die API real ab, sobald ein
Credential auflösbar ist; sonst liefert er vertragskonform eine leere Liste.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuthSpec:
    kind: str                              # oauth2 | oauth2_cc | api_key | basic | signed
    secret_ref: str = ""                   # env:/ssm:/vault: — Quelle des Credentials
    authorize_url: str = ""                # oauth2: Authorize-Endpoint
    token_url: str = ""                    # oauth2/oauth2_cc: Token-Endpoint
    scopes: list[str] = field(default_factory=list)
    header: str = "Authorization"          # Header-Name für den Key
    header_prefix: str = "Bearer "         # Prefix vor dem Token
    query_param: str = ""                  # alternativ: Key als Query-Param
    extra_headers: dict = field(default_factory=dict)  # z.B. Notion-Version


@dataclass
class SearchSpec:
    method: str = "GET"
    path: str = ""                         # an api_base angehängt
    query_param: str = "q"                 # Such-Parameter (GET)
    body_template: dict = field(default_factory=dict)  # POST-Body ({q} wird ersetzt)
    result_path: str = ""                  # Dotted-Path zur Trefferliste (z.B. "results")
    map_title: str = "name"                # Feld → title
    map_text: str = ""                     # Feld → text (leer = ganzes Objekt)
    map_url: str = "url"                   # Feld → url


@dataclass
class ConnectorSpec:
    id: str
    name: str
    category: str                          # crm|productivity|dev|comms|storage|accounting|hr|cloud|payments|banking
    api_base: str
    docs_url: str
    auth: AuthSpec
    capabilities: list[str] = field(default_factory=lambda: ["input"])
    provenance_label: str = ""
    search: SearchSpec | None = None
    region_aware: bool = False             # Base-URL/Token-URL variieren je Region (EU/US)
    note: str = ""
    description: str = ""


def _ref(id_: str) -> str:
    return f"env:CNODE_{id_.upper().replace('-', '_')}_TOKEN"


CATALOG: list[ConnectorSpec] = [
    # ------------------------------------------------------------------ CRM / Sales
    ConnectorSpec(
        id="hubspot", name="HubSpot CRM", category="crm",
        api_base="https://api.hubapi.com",
        docs_url="https://developers.hubspot.com/docs/api/overview",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("hubspot"),
                      authorize_url="https://app.hubspot.com/oauth/authorize",
                      token_url="https://api.hubapi.com/oauth/v1/token",
                      scopes=["crm.objects.contacts.read", "crm.objects.companies.read",
                              "crm.objects.deals.read"]),
        capabilities=["input", "output", "oauth"], provenance_label="hubspot",
        search=SearchSpec(method="POST", path="/crm/v3/objects/contacts/search",
                          body_template={"query": "{q}", "limit": 20},
                          result_path="results", map_title="properties.email",
                          map_text="", map_url=""),
        description="Kontakte, Firmen, Deals; Notes/Tasks als Ausgabe (hinter Gate)."),
    ConnectorSpec(
        id="salesforce", name="Salesforce", category="crm",
        api_base="https://login.salesforce.com",  # per-Instance nach OAuth
        docs_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("salesforce"),
                      authorize_url="https://login.salesforce.com/services/oauth2/authorize",
                      token_url="https://login.salesforce.com/services/oauth2/token",
                      scopes=["api", "refresh_token"]),
        capabilities=["input", "output", "oauth"], provenance_label="salesforce",
        search=SearchSpec(method="GET", path="/services/data/v60.0/search",
                          query_param="q", result_path="searchRecords",
                          map_title="Name", map_url=""),
        region_aware=True,
        note="Instance-URL kommt aus der Token-Response; SOQL/SOSL via /services/data.",
        description="Accounts, Contacts, Opportunities per SOQL/SOSL."),
    ConnectorSpec(
        id="pipedrive", name="Pipedrive", category="crm",
        api_base="https://api.pipedrive.com/v1",
        docs_url="https://developers.pipedrive.com/docs/api/v1",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("pipedrive"),
                      query_param="api_token", header=""),
        capabilities=["input", "output", "api_key"], provenance_label="pipedrive",
        search=SearchSpec(method="GET", path="/itemSearch", query_param="term",
                          result_path="data.items", map_title="item.title", map_url=""),
        note="Alternativ OAuth2; hier API-Token als Query-Param.",
        description="Deals, Personen, Organisationen; Notes als Ausgabe (hinter Gate)."),
    ConnectorSpec(
        id="zoho-crm", name="Zoho CRM", category="crm",
        api_base="https://www.zohoapis.eu/crm/v3",
        docs_url="https://www.zoho.com/crm/developer/docs/api/v3/",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("zoho_crm"),
                      authorize_url="https://accounts.zoho.eu/oauth/v2/auth",
                      token_url="https://accounts.zoho.eu/oauth/v2/token",
                      scopes=["ZohoCRM.modules.ALL"], header_prefix="Zoho-oauthtoken "),
        capabilities=["input", "output", "oauth"], provenance_label="zoho-crm",
        region_aware=True,
        note="Region-DC in Base+Accounts-URL (eu/com/in/au); Header 'Zoho-oauthtoken'.",
        description="Leads, Contacts, Deals (Region-aware, EU-DC default)."),

    # -------------------------------------------------------- Productivity / PM / Comms
    ConnectorSpec(
        id="notion", name="Notion", category="productivity",
        api_base="https://api.notion.com/v1",
        docs_url="https://developers.notion.com/reference/intro",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("notion"),
                      extra_headers={"Notion-Version": "2022-06-28"}),
        capabilities=["input", "output", "oauth"], provenance_label="notion",
        search=SearchSpec(method="POST", path="/search",
                          body_template={"query": "{q}", "page_size": 20},
                          result_path="results",
                          map_title="properties.title.title.0.plain_text", map_url="url"),
        description="Seiten & Datenbanken durchsuchen; Seiten anlegen (hinter Gate)."),
    ConnectorSpec(
        id="atlassian-jira", name="Jira (Atlassian)", category="productivity",
        api_base="https://api.atlassian.com",  # Cloud-ID nach OAuth: /ex/jira/{cloudid}
        docs_url="https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("atlassian_jira"),
                      authorize_url="https://auth.atlassian.com/authorize",
                      token_url="https://auth.atlassian.com/oauth/token",
                      scopes=["read:jira-work", "read:jira-user", "offline_access"]),
        capabilities=["input", "output", "oauth"], provenance_label="jira",
        search=SearchSpec(method="GET", path="/ex/jira/{cloudid}/rest/api/3/search",
                          query_param="jql", result_path="issues",
                          map_title="fields.summary", map_url=""),
        note="Alternativ Basic (email+API-Token) gegen https://<site>.atlassian.net.",
        description="Issues per JQL; Kommentare als Ausgabe (hinter Gate)."),
    ConnectorSpec(
        id="asana", name="Asana", category="productivity",
        api_base="https://app.asana.com/api/1.0",
        docs_url="https://developers.asana.com/reference/rest-api-reference",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("asana"),
                      authorize_url="https://app.asana.com/-/oauth_authorize",
                      token_url="https://app.asana.com/-/oauth_token",
                      scopes=["default"]),
        capabilities=["input", "output", "oauth"], provenance_label="asana",
        search=SearchSpec(method="GET", path="/workspaces/{workspace}/tasks/search",
                          query_param="text", result_path="data",
                          map_title="name", map_url="permalink_url"),
        note="Alternativ Personal Access Token (Bearer).",
        description="Aufgaben-Suche je Workspace; Tasks/Comments als Ausgabe (Gate)."),
    ConnectorSpec(
        id="slack", name="Slack", category="comms",
        api_base="https://slack.com/api",
        docs_url="https://api.slack.com/web",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("slack"),
                      authorize_url="https://slack.com/oauth/v2/authorize",
                      token_url="https://slack.com/api/oauth.v2.access",
                      scopes=["search:read", "channels:history", "chat:write"]),
        capabilities=["input", "output", "oauth"], provenance_label="slack",
        search=SearchSpec(method="GET", path="/search.messages", query_param="query",
                          result_path="messages.matches", map_title="text",
                          map_url="permalink", map_text="text"),
        description="Nachrichten-Suche; Posten in Channels als Ausgabe (hinter Gate)."),
    ConnectorSpec(
        id="microsoft-graph", name="Microsoft 365 (Graph)", category="productivity",
        api_base="https://graph.microsoft.com/v1.0",
        docs_url="https://learn.microsoft.com/en-us/graph/api/overview",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("microsoft_graph"),
                      authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                      token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                      scopes=["offline_access", "User.Read", "Files.Read.All",
                              "Mail.Read", "Sites.Read.All", "Chat.Read"]),
        capabilities=["input", "output", "oauth"], provenance_label="ms-graph",
        search=SearchSpec(method="POST", path="/search/query",
                          body_template={"requests": [{"entityTypes": ["driveItem", "message"],
                                                        "query": {"queryString": "{q}"}}]},
                          result_path="value.0.hitsContainers.0.hits",
                          map_title="resource.name", map_url="resource.webUrl"),
        note="Deckt Teams, Outlook, OneDrive, SharePoint über einen Token ab.",
        description="Teams/Outlook/OneDrive/SharePoint per Graph-Search."),
    ConnectorSpec(
        id="google-workspace", name="Google Workspace", category="productivity",
        api_base="https://www.googleapis.com",
        docs_url="https://developers.google.com/workspace",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("google_workspace"),
                      authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                      token_url="https://oauth2.googleapis.com/token",
                      scopes=["https://www.googleapis.com/auth/drive.readonly",
                              "https://www.googleapis.com/auth/gmail.readonly",
                              "https://www.googleapis.com/auth/calendar.events"]),
        capabilities=["input", "output", "oauth"], provenance_label="google",
        note="Gmail/Drive/Calendar laufen bereits über den BFF-OAuth-Pfad.",
        description="Gmail, Drive, Calendar (BFF-OAuth vorhanden)."),
    ConnectorSpec(
        id="zoom", name="Zoom", category="comms",
        api_base="https://api.zoom.us/v2",
        docs_url="https://developers.zoom.us/docs/api/",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("zoom"),
                      authorize_url="https://zoom.us/oauth/authorize",
                      token_url="https://zoom.us/oauth/token",
                      scopes=["meeting:read", "recording:read"]),
        capabilities=["input", "oauth"], provenance_label="zoom",
        search=SearchSpec(method="GET", path="/users/me/meetings", query_param="",
                          result_path="meetings", map_title="topic", map_url="join_url"),
        description="Meetings & Aufzeichnungen (Transkripte als Quelle)."),

    # ---------------------------------------------------------------------- Dev
    ConnectorSpec(
        id="github", name="GitHub", category="dev",
        api_base="https://api.github.com",
        docs_url="https://docs.github.com/en/rest",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("github"),
                      authorize_url="https://github.com/login/oauth/authorize",
                      token_url="https://github.com/login/oauth/access_token",
                      scopes=["repo", "read:org"],
                      extra_headers={"Accept": "application/vnd.github+json"}),
        capabilities=["input", "output", "oauth"], provenance_label="github",
        search=SearchSpec(method="GET", path="/search/issues", query_param="q",
                          result_path="items", map_title="title", map_url="html_url",
                          map_text="body"),
        note="Alternativ Fine-grained PAT (Bearer).",
        description="Issues/PRs/Code durchsuchen; Issues/Comments als Ausgabe (Gate)."),
    ConnectorSpec(
        id="gitlab", name="GitLab", category="dev",
        api_base="https://gitlab.com/api/v4",
        docs_url="https://docs.gitlab.com/ee/api/rest/",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("gitlab"),
                      authorize_url="https://gitlab.com/oauth/authorize",
                      token_url="https://gitlab.com/oauth/token",
                      scopes=["read_api", "read_repository"]),
        capabilities=["input", "output", "oauth"], provenance_label="gitlab",
        search=SearchSpec(method="GET", path="/search", query_param="search",
                          result_path="", map_title="title", map_url="web_url"),
        note="Self-managed: api_base auf eigene Instanz zeigen. Alt: PAT.",
        description="Projekte/Issues/MRs/Code durchsuchen; self-hostbar."),

    # ------------------------------------------------------------------- Storage
    ConnectorSpec(
        id="dropbox", name="Dropbox", category="storage",
        api_base="https://api.dropboxapi.com/2",
        docs_url="https://www.dropbox.com/developers/documentation/http/documentation",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("dropbox"),
                      authorize_url="https://www.dropbox.com/oauth2/authorize",
                      token_url="https://api.dropboxapi.com/oauth2/token",
                      scopes=["files.metadata.read", "files.content.read"]),
        capabilities=["input", "oauth"], provenance_label="dropbox",
        search=SearchSpec(method="POST", path="/files/search_v2",
                          body_template={"query": "{q}"}, result_path="matches",
                          map_title="metadata.metadata.name", map_url=""),
        description="Dateien-Suche & Inhalte als Quelle."),
    ConnectorSpec(
        id="nextcloud", name="Nextcloud", category="storage",
        api_base="https://{host}/remote.php/dav",
        docs_url="https://docs.nextcloud.com/server/latest/developer_manual/client_apis/WebDAV/index.html",
        auth=AuthSpec(kind="basic", secret_ref=_ref("nextcloud")),
        capabilities=["input", "output", "basic"], provenance_label="nextcloud",
        note="Souverän/self-hosted. WebDAV (Dateien) + OCS-API; App-Passwort statt Login.",
        description="Self-hosted EU-Storage: Dateien via WebDAV, Freigaben via OCS."),

    # ------------------------------------------------- Accounting / Finance (DACH)
    ConnectorSpec(
        id="datev", name="DATEV", category="accounting",
        api_base="https://api.datev.de",
        docs_url="https://developer.datev.de/portal/en/documentations",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("datev"),
                      authorize_url="https://login.datev.de/openid/authorize",
                      token_url="https://api.datev.de/token",
                      scopes=["openid", "accounting:documents"]),
        capabilities=["input", "output", "oauth"], provenance_label="datev",
        note="Steuerberater-Standard DE. accounting:documents (Belege), accounting:clients. "
             "Sandbox: login.datev.de/openidsandbox. Zertifikat + Scopes je Anwendung.",
        description="Belege/Buchungen an DATEV Unternehmen online (Steuerberater-Bridge)."),
    ConnectorSpec(
        id="lexware", name="Lexware Office (lexoffice)", category="accounting",
        api_base="https://api.lexware.io",
        docs_url="https://developers.lexware.io/docs/",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("lexware")),
        capabilities=["input", "output", "api_key"], provenance_label="lexware",
        search=SearchSpec(method="GET", path="/v1/contacts", query_param="name",
                          result_path="content", map_title="company.name", map_url=""),
        note="API-Key unter app.lexoffice.de/settings/#/public-api. Rechnungen/Kontakte/Belege.",
        description="Rechnungen, Kontakte, Belege (KMU-Buchhaltung DE)."),
    ConnectorSpec(
        id="sevdesk", name="sevDesk", category="accounting",
        api_base="https://my.sevdesk.de/api/v1",
        docs_url="https://api.sevdesk.de/",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("sevdesk"), header_prefix=""),
        capabilities=["input", "output", "api_key"], provenance_label="sevdesk",
        search=SearchSpec(method="GET", path="/Contact", query_param="name",
                          result_path="objects", map_title="name", map_url=""),
        note="API-Token unter Einstellungen→Benutzer→API (v2 empfohlen). Header ohne 'Bearer'.",
        description="Kontakte, Rechnungen, Belege (KMU-Buchhaltung DE)."),
    ConnectorSpec(
        id="sage", name="Sage Accounting", category="accounting",
        api_base="https://api.accounting.sage.com/v3.1",
        docs_url="https://developer.sage.com/accounting/reference/",
        auth=AuthSpec(kind="oauth2", secret_ref=_ref("sage"),
                      authorize_url="https://www.sageone.com/oauth2/auth/central",
                      token_url="https://oauth.accounting.sage.com/token",
                      scopes=["full_access"]),
        capabilities=["input", "output", "oauth"], provenance_label="sage",
        search=SearchSpec(method="GET", path="/contacts", query_param="search",
                          result_path="$items", map_title="name", map_url=""),
        description="Sage Business Cloud Accounting: Kontakte, Rechnungen, Belege."),

    # -------------------------------------------------------------------- HR
    ConnectorSpec(
        id="personio", name="Personio", category="hr",
        api_base="https://api.personio.de/v2",
        docs_url="https://developer.personio.de/",
        auth=AuthSpec(kind="oauth2_cc", secret_ref=_ref("personio"),
                      token_url="https://api.personio.de/v2/auth/token"),
        capabilities=["input", "oauth"], provenance_label="personio",
        search=SearchSpec(method="GET", path="/persons", query_param="search",
                          result_path="_data", map_title="attributes.name", map_url=""),
        note="Client-Credentials (Client-ID+Secret → Bearer). HR-Standard DACH.",
        description="Mitarbeitende, Abwesenheiten, Attendances (HR-Stammdaten)."),

    # ------------------------------------------------------------------- Cloud (EU)
    ConnectorSpec(
        id="ionos", name="IONOS Cloud", category="cloud",
        api_base="https://api.ionos.com/cloudapi/v6",
        docs_url="https://api.ionos.com/docs/",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("ionos"),
                      header_prefix="Bearer "),
        capabilities=["input", "api_key"], provenance_label="ionos",
        note="EU-Hoster DE. Token-Manager erzeugt Bearer-JWT; alternativ Basic.",
        description="EU-souveräne Cloud-Ressourcen (Server, Storage) als Kontext."),
    ConnectorSpec(
        id="ovhcloud", name="OVHcloud", category="cloud",
        api_base="https://eu.api.ovh.com/1.0",
        docs_url="https://api.ovh.com/",
        auth=AuthSpec(kind="signed", secret_ref=_ref("ovhcloud")),
        capabilities=["input"], provenance_label="ovhcloud", region_aware=True,
        note="EU-Hoster FR. Signatur aus App-Key/App-Secret/Consumer-Key + Zeit + Body "
             "(X-Ovh-Signature). Kein simpler Bearer → eigener Signer nötig.",
        description="EU-Cloud (FR). Signed-API; Ressourcen/Domains als Kontext."),
    ConnectorSpec(
        id="hetzner", name="Hetzner Cloud", category="cloud",
        api_base="https://api.hetzner.cloud/v1",
        docs_url="https://docs.hetzner.cloud/",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("hetzner")),
        capabilities=["input", "api_key"], provenance_label="hetzner",
        search=SearchSpec(method="GET", path="/servers", query_param="name",
                          result_path="servers", map_title="name", map_url=""),
        note="EU-Hoster DE. Projekt-API-Token (Bearer).",
        description="EU-Cloud (DE). Server/Volumes/Netze als Kontext."),
    ConnectorSpec(
        id="telekom-otc", name="Open Telekom Cloud", category="cloud",
        api_base="https://iam.eu-de.otc.t-systems.com/v3",
        docs_url="https://docs.otc.t-systems.com/",
        auth=AuthSpec(kind="signed", secret_ref=_ref("telekom_otc")),
        capabilities=["input"], provenance_label="telekom-otc", region_aware=True,
        note="OpenStack-basiert (Keystone-Token via AK/SK-Signatur oder Username-Auth). "
             "Kein simpler Bearer → OpenStack-Client/Signer nötig.",
        description="Deutsche-Telekom EU-Cloud (OpenStack). Dokumentiert, Signer nötig."),

    # ---------------------------------------------------------- Payments / Banking
    ConnectorSpec(
        id="stripe", name="Stripe", category="payments",
        api_base="https://api.stripe.com/v1",
        docs_url="https://docs.stripe.com/api",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("stripe")),
        capabilities=["input", "output", "api_key"], provenance_label="stripe",
        search=SearchSpec(method="GET", path="/customers/search", query_param="query",
                          result_path="data", map_title="email", map_url=""),
        note="Secret-Key (Bearer). Search-Query-Language für customers/charges/invoices.",
        description="Kunden, Zahlungen, Rechnungen, Subscriptions als Kontext."),
    ConnectorSpec(
        id="mollie", name="Mollie", category="payments",
        api_base="https://api.mollie.com/v2",
        docs_url="https://docs.mollie.com/reference/",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("mollie")),
        capabilities=["input", "api_key"], provenance_label="mollie",
        search=SearchSpec(method="GET", path="/payments", query_param="",
                          result_path="_embedded.payments", map_title="description",
                          map_url=""),
        note="EU-PSP (NL). API-Key (Bearer), test_/live_.",
        description="EU-Payments (NL): Zahlungen, Refunds, Kunden."),
    ConnectorSpec(
        id="klarna", name="Klarna", category="payments",
        api_base="https://api.eu.klarna.com",
        docs_url="https://docs.klarna.com/api/",
        auth=AuthSpec(kind="basic", secret_ref=_ref("klarna")),
        capabilities=["input", "output", "basic"], provenance_label="klarna",
        region_aware=True,
        note="EU-Region-Base (api.eu.klarna.com). HTTP-Basic (username:password aus Merchant-Portal).",
        description="Orders/Payments (EU-Region), Basic-Auth."),
    ConnectorSpec(
        id="qonto", name="Qonto", category="banking",
        api_base="https://thirdparty.qonto.com/v2",
        docs_url="https://api-doc.qonto.com/",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("qonto"), header_prefix=""),
        capabilities=["input", "api_key"], provenance_label="qonto",
        search=SearchSpec(method="GET", path="/transactions", query_param="",
                          result_path="transactions", map_title="label", map_url=""),
        note="EU-Business-Banking (FR). Header 'Authorization: <login>:<secret-key>' "
             "oder OAuth. Transaktionen/Konten.",
        description="EU-Geschäftskonto (FR): Konten, Transaktionen, Belege."),
    ConnectorSpec(
        id="n26", name="N26", category="banking",
        api_base="",
        docs_url="https://n26.com/",
        auth=AuthSpec(kind="api_key", secret_ref=_ref("n26")),
        capabilities=[], provenance_label="n26",
        note="Keine offizielle öffentliche Partner-API. Zugriff nur über PSD2/Open-Banking-"
             "Aggregatoren (z.B. FinAPI, Tink, GoCardless Bank Account Data). Als Platzhalter "
             "dokumentiert — kein Direkt-Connector.",
        description="Kein öffentliches API — PSD2-Aggregator nötig (dokumentiert)."),
]

# ID → Spec (schneller Zugriff für den generischen Connector + BFF)
CATALOG_BY_ID: dict[str, ConnectorSpec] = {c.id: c for c in CATALOG}
