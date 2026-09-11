// Kuratierte Connector-Library ("App-Library") — statischer Katalog + Enable-State.
// Rein clientseitig: Enable-Zustand pro Mandant in localStorage, kein Backend-Call.

import type { TFn } from './i18n'

export type ConnectorCategory = 'input' | 'output'
export type ConnectorAuth = 'none' | 'oauth' | 'apikey'

export type Connector = {
  id: string
  name: string
  category: ConnectorCategory
  group: string
  icon: string // emoji
  auth: ConnectorAuth
  defaultEnabled: boolean
  live: boolean // heute nutzbar (Fetch/Push funktioniert mit hinterlegtem Credential)
  desc: string
  backed?: boolean // hat ein First-Party-Connector-Plugin im Core (connectors_catalog)
}

// ---- Kuratierter Katalog -------------------------------------------------

export const CONNECTORS: Connector[] = [
  // ================= EINGANG (Ingest) =================
  {
    id: 'upload',
    name: 'Datei-Upload',
    category: 'input',
    group: 'Dateien',
    icon: '📄',
    auth: 'none',
    defaultEnabled: true,
    live: true,
    desc: 'PDF, DOCX, TXT & mehr direkt hochladen.',
  },
  {
    id: 'url_scrape',
    name: 'Web / URL',
    category: 'input',
    group: 'Web',
    icon: '🌐',
    auth: 'none',
    defaultEnabled: true,
    live: true,
    desc: 'Öffentliche Seiten von der Allowlist crawlen.',
  },
  {
    id: 'google_drive',
    name: 'Google Drive',
    category: 'input',
    group: 'Cloud-Speicher',
    icon: '📁',
    auth: 'oauth',
    defaultEnabled: false,
    live: true,
    desc: 'Dokumente & Ordner aus Google Drive einlesen.',
  },
  {
    id: 'sharepoint',
    name: 'SharePoint / OneDrive',
    category: 'input',
    group: 'Cloud-Speicher',
    icon: '🗂️',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    desc: 'Microsoft 365 Dateien & Sites anbinden.',
  },
  {
    id: 'notion',
    name: 'Notion',
    category: 'input',
    group: 'Wissen',
    icon: '📓',
    auth: 'oauth',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'Notion-Seiten & Datenbanken importieren.',
  },
  {
    id: 'confluence',
    name: 'Confluence',
    category: 'input',
    group: 'Wissen',
    icon: '📘',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'Confluence-Spaces & Seiten anbinden.',
  },
  {
    id: 'email_imap',
    name: 'E-Mail (IMAP)',
    category: 'input',
    group: 'Kommunikation',
    icon: '📧',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'Postfächer per IMAP als Quelle einlesen.',
  },
  {
    id: 's3',
    name: 'Objektspeicher (S3)',
    category: 'input',
    group: 'Cloud-Speicher',
    icon: '🪣',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'S3-kompatible Buckets als Quelle nutzen.',
  },
  {
    id: 'slack_import',
    name: 'Slack',
    category: 'input',
    group: 'Kommunikation',
    icon: '💬',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Channels & Threads aus Slack importieren.',
  },
  {
    id: 'gmail_in',
    name: 'Gmail',
    category: 'input',
    group: 'E-Mail',
    icon: '✉️',
    auth: 'oauth',
    defaultEnabled: false,
    live: true,
    desc: 'E-Mails aus Gmail als Quelle lesen. Nutzt deinen Google-Login.',
  },
  {
    id: 'outlook_in',
    name: 'Outlook',
    category: 'input',
    group: 'E-Mail',
    icon: '✉️',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    desc: 'E-Mails aus Outlook / Microsoft 365 lesen.',
  },
  {
    id: 'dropbox',
    name: 'Dropbox',
    category: 'input',
    group: 'Cloud-Speicher',
    icon: '📦',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Dateien & Ordner aus Dropbox einlesen.',
  },
  {
    id: 'box',
    name: 'Box',
    category: 'input',
    group: 'Cloud-Speicher',
    icon: '📦',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    desc: 'Dokumente aus Box anbinden.',
  },
  {
    id: 'gcs',
    name: 'Google Cloud Storage',
    category: 'input',
    group: 'Cloud-Speicher',
    icon: '🪣',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'GCS-Buckets als Quelle nutzen.',
  },
  {
    id: 'azure_blob',
    name: 'Azure Blob Storage',
    category: 'input',
    group: 'Cloud-Speicher',
    icon: '🗄️',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'Azure-Container als Quelle anbinden.',
  },
  {
    id: 'github',
    name: 'GitHub',
    category: 'input',
    group: 'Entwicklung',
    icon: '🐙',
    auth: 'oauth',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'Repos, Issues & Wikis einlesen.',
  },
  {
    id: 'jira',
    name: 'Jira',
    category: 'input',
    group: 'Projekte',
    icon: '📋',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Vorgänge & Projekte aus Jira einlesen.',
  },
  {
    id: 'salesforce',
    name: 'Salesforce',
    category: 'input',
    group: 'CRM',
    icon: '☁️',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Accounts & Opportunities als Quelle.',
  },
  {
    id: 'gsheets',
    name: 'Google Sheets',
    category: 'input',
    group: 'Tabellen',
    icon: '📊',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    desc: 'Tabellen aus Google Sheets einlesen.',
  },
  {
    id: 'teams',
    name: 'Microsoft Teams',
    category: 'input',
    group: 'Kommunikation',
    icon: '💬',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    desc: 'Kanäle & Chats aus Teams importieren.',
  },
  {
    id: 'airtable',
    name: 'Airtable',
    category: 'input',
    group: 'Tabellen',
    icon: '🗂️',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'Bases & Tabellen aus Airtable.',
  },
  {
    id: 'zendesk',
    name: 'Zendesk',
    category: 'input',
    group: 'Support',
    icon: '🎧',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'Tickets & Help-Center-Artikel einlesen.',
  },
  {
    id: 'database',
    name: 'SQL-Datenbank',
    category: 'input',
    group: 'Datenbanken',
    icon: '🗃️',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'Postgres / MySQL als Quelle abfragen.',
  },

  // ===== Business & Buchhaltung (EU/DACH) — First-Party-Connectoren (Core) =====
  {
    id: 'lexware',
    name: 'Lexware Office',
    category: 'input',
    group: 'Buchhaltung',
    icon: '🧾',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'Rechnungen, Kontakte & Belege aus Lexware Office (lexoffice). API-Key.',
  },
  {
    id: 'sevdesk',
    name: 'sevDesk',
    category: 'input',
    group: 'Buchhaltung',
    icon: '🧾',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'Kontakte, Rechnungen & Belege aus sevDesk (KMU-Buchhaltung DE).',
  },
  {
    id: 'datev',
    name: 'DATEV',
    category: 'input',
    group: 'Buchhaltung',
    icon: '📗',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'DATEV Unternehmen online: Belege & Buchungen (Steuerberater-Bridge). OAuth.',
  },
  {
    id: 'sage',
    name: 'Sage Accounting',
    category: 'input',
    group: 'Buchhaltung',
    icon: '🧮',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Sage Business Cloud: Kontakte, Rechnungen & Belege.',
  },
  {
    id: 'personio',
    name: 'Personio',
    category: 'input',
    group: 'HR',
    icon: '👥',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'Mitarbeitende, Abwesenheiten & Stammdaten (HR-Standard DACH). Client-Credentials.',
  },
  {
    id: 'stripe',
    name: 'Stripe',
    category: 'input',
    group: 'Zahlungen',
    icon: '💳',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'Kunden, Zahlungen, Rechnungen & Abos als Kontext.',
  },
  {
    id: 'mollie',
    name: 'Mollie',
    category: 'input',
    group: 'Zahlungen',
    icon: '💳',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'EU-Payments (NL): Zahlungen, Refunds, Kunden.',
  },
  {
    id: 'klarna',
    name: 'Klarna',
    category: 'input',
    group: 'Zahlungen',
    icon: '🩷',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Orders & Payments (EU-Region). HTTP-Basic aus dem Merchant-Portal.',
  },
  {
    id: 'qonto',
    name: 'Qonto',
    category: 'input',
    group: 'Banking',
    icon: '🏦',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'EU-Geschäftskonto (FR): Konten, Transaktionen & Belege.',
  },
  {
    id: 'n26',
    name: 'N26',
    category: 'input',
    group: 'Banking',
    icon: '🏦',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'Kein öffentliches API — Zugriff nur über PSD2-Aggregator (dokumentiert).',
  },
  {
    id: 'ionos',
    name: 'IONOS Cloud',
    category: 'input',
    group: 'Cloud (EU)',
    icon: '☁️',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'EU-souveräne Cloud (DE): Server, Storage & Ressourcen als Kontext.',
  },
  {
    id: 'hetzner',
    name: 'Hetzner Cloud',
    category: 'input',
    group: 'Cloud (EU)',
    icon: '☁️',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'EU-Cloud (DE): Server, Volumes & Netze als Kontext. Projekt-Token.',
  },
  {
    id: 'ovhcloud',
    name: 'OVHcloud',
    category: 'input',
    group: 'Cloud (EU)',
    icon: '☁️',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'EU-Cloud (FR): Ressourcen & Domains. Signierte API (eigener Signer nötig).',
  },
  {
    id: 'telekom-otc',
    name: 'Open Telekom Cloud',
    category: 'input',
    group: 'Cloud (EU)',
    icon: '☁️',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Deutsche-Telekom EU-Cloud (OpenStack). Keystone-Signer nötig.',
  },
  {
    id: 'nextcloud',
    name: 'Nextcloud',
    category: 'input',
    group: 'Cloud-Speicher',
    icon: '🇪🇺',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Self-hosted EU-Storage: Dateien via WebDAV. App-Passwort (Basic).',
  },
  {
    id: 'asana',
    name: 'Asana',
    category: 'input',
    group: 'Projekte',
    icon: '✅',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Aufgaben-Suche je Workspace. OAuth oder Personal Access Token.',
  },
  {
    id: 'zoom',
    name: 'Zoom',
    category: 'input',
    group: 'Kommunikation',
    icon: '🎥',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Meetings, Aufzeichnungen & Transkripte als Quelle.',
  },
  {
    id: 'gitlab',
    name: 'GitLab',
    category: 'input',
    group: 'Entwicklung',
    icon: '🦊',
    auth: 'oauth',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'Projekte, Issues, MRs & Code durchsuchen. Self-hostbar. PAT oder OAuth.',
  },

  // ================= AUSGANG (Output) =================
  {
    id: 'pdf_export',
    name: 'PDF / Markdown-Export',
    category: 'output',
    group: 'Export',
    icon: '📑',
    auth: 'none',
    defaultEnabled: true,
    live: true,
    desc: 'Artefakte als Markdown / PDF herunterladen.',
  },
  {
    id: 'gmail',
    name: 'Gmail',
    category: 'output',
    group: 'E-Mail',
    icon: '✉️',
    auth: 'oauth',
    defaultEnabled: false,
    live: true,
    desc: 'Antworten & Ergebnisse per Gmail versenden. Verbindet sich mit deinem Google-Login.',
  },
  {
    id: 'outlook',
    name: 'Outlook',
    category: 'output',
    group: 'E-Mail',
    icon: '✉️',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    desc: 'Antworten & Ergebnisse per Outlook / Microsoft 365 versenden.',
  },
  {
    id: 'hubspot',
    name: 'HubSpot CRM',
    category: 'output',
    group: 'CRM',
    icon: '🟠',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Kontakte & Notizen nach HubSpot pushen.',
  },
  {
    id: 'pipedrive',
    name: 'Pipedrive',
    category: 'output',
    group: 'CRM',
    icon: '🟢',
    auth: 'apikey',
    defaultEnabled: false,
    live: true,
    backed: true,
    desc: 'Deals & Personen in Pipedrive anlegen.',
  },
  {
    id: 'zoho',
    name: 'Zoho CRM',
    category: 'output',
    group: 'CRM',
    icon: '🔵',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Region-aware Sync nach Zoho CRM.',
  },
  {
    id: 'slack_post',
    name: 'Slack posten',
    category: 'output',
    group: 'Kommunikation',
    icon: '💬',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Ergebnisse in Slack-Channels posten.',
  },
  {
    id: 'webhook',
    name: 'Webhook (HMAC)',
    category: 'output',
    group: 'Automatisierung',
    icon: '🔗',
    auth: 'apikey',
    defaultEnabled: false,
    live: false,
    desc: 'Signierte Events an ein Ziel-Endpoint senden.',
  },
  {
    id: 'gcal',
    name: 'Google Calendar',
    category: 'output',
    group: 'Kalender',
    icon: '📅',
    auth: 'oauth',
    defaultEnabled: false,
    live: true,
    desc: 'Termine & Follow-ups im Kalender anlegen.',
  },
  {
    id: 'notion_export',
    name: 'Notion',
    category: 'output',
    group: 'Wissen',
    icon: '📓',
    auth: 'oauth',
    defaultEnabled: false,
    live: false,
    backed: true,
    desc: 'Artefakte als Notion-Seiten exportieren.',
  },
]

// ---- Abfrage-Helfer ------------------------------------------------------

export function inputConnectors(): Connector[] {
  return CONNECTORS.filter((c) => c.category === 'input')
}

export function outputConnectors(): Connector[] {
  return CONNECTORS.filter((c) => c.category === 'output')
}

export function defaultEnabledIds(): string[] {
  return CONNECTORS.filter((c) => c.defaultEnabled).map((c) => c.id)
}

export function connectorById(id: string): Connector | undefined {
  return CONNECTORS.find((c) => c.id === id)
}

export const AUTH_LABEL: Record<ConnectorAuth, string> = {
  none: 'kein Login',
  oauth: 'OAuth',
  apikey: 'API-Key',
}

// ---- i18n-Helfer -----------------------------------------------------------
// Muster: Metadaten bleiben im Katalog oben (id/group/auth …), die sichtbaren
// Strings werden zur Render-Zeit über die t()-Funktion aufgelöst. Fällt ein Key
// im Katalog, liefert t(key) den Key zurück → wir fallen auf den Rohwert zurück.

// Nur generische Namen bekommen einen Katalog-Key; echte Markennamen bleiben roh.
const TRANSLATABLE_NAME_IDS = new Set<string>([
  'upload', 'url_scrape', 'email_imap', 's3', 'database', 'pdf_export', 'slack_post',
])

// Roher group-Wert → stabiler Slug. WICHTIG: Die Gruppierungs-Logik in den
// Komponenten arbeitet weiter mit dem ROHEN group-Wert — hier wird nur die
// Anzeige lokalisiert.
const GROUP_SLUG: Record<string, string> = {
  'Dateien': 'files',
  'Web': 'web',
  'Cloud-Speicher': 'cloud_storage',
  'Wissen': 'knowledge',
  'Kommunikation': 'communication',
  'E-Mail': 'email',
  'Entwicklung': 'development',
  'Projekte': 'projects',
  'CRM': 'crm',
  'Tabellen': 'spreadsheets',
  'Support': 'support',
  'Datenbanken': 'databases',
  'Buchhaltung': 'accounting',
  'HR': 'hr',
  'Zahlungen': 'payments',
  'Banking': 'banking',
  'Cloud (EU)': 'cloud_eu',
  'Export': 'export',
  'Kalender': 'calendar',
  'Automatisierung': 'automation',
}

/** Lokalisierter Connector-Name (Markennamen bleiben roh). */
export function connName(t: TFn, c: Connector): string {
  if (!TRANSLATABLE_NAME_IDS.has(c.id)) return c.name
  const k = `connectors.item.${c.id}.name`
  const v = t(k)
  return v === k ? c.name : v
}

/** Lokalisierte Connector-Beschreibung (Fallback: Rohwert). */
export function connDesc(t: TFn, c: Connector): string {
  const k = `connectors.item.${c.id}.desc`
  const v = t(k)
  return v === k ? c.desc : v
}

/** Lokalisiertes Gruppen-Label für einen ROHEN group-Wert (Fallback: Rohwert). */
export function connGroupLabel(t: TFn, group: string): string {
  const slug = GROUP_SLUG[group]
  if (!slug) return group
  const k = `connectors.group.${slug}`
  const v = t(k)
  return v === k ? group : v
}

/** Lokalisiertes Auth-Label (Fallback: AUTH_LABEL). */
export function connAuthLabel(t: TFn, auth: ConnectorAuth): string {
  const k = `connectors.auth.${auth}`
  const v = t(k)
  return v === k ? AUTH_LABEL[auth] : v
}

// ---- Enable-State pro Mandant (localStorage) -----------------------------

const KEY_PREFIX = 'cnode.connectors.'

export function connectorsStorageKey(tenantId?: string): string {
  return `${KEY_PREFIX}${tenantId || 'default'}`
}

// Nur bekannte IDs zulassen (tolerant gegenüber Katalog-Änderungen).
function sanitize(ids: unknown): string[] {
  if (!Array.isArray(ids)) return defaultEnabledIds()
  const known = new Set(CONNECTORS.map((c) => c.id))
  const out = ids.filter((id): id is string => typeof id === 'string' && known.has(id))
  return out
}

export function loadEnabledIds(tenantId?: string): string[] {
  try {
    const raw = localStorage.getItem(connectorsStorageKey(tenantId))
    if (raw == null) return defaultEnabledIds()
    return sanitize(JSON.parse(raw))
  } catch {
    return defaultEnabledIds()
  }
}

export function saveEnabledIds(tenantId: string | undefined, ids: string[]): void {
  try {
    localStorage.setItem(connectorsStorageKey(tenantId), JSON.stringify(Array.from(new Set(ids))))
  } catch {
    /* ignore — rein clientseitige Convenience */
  }
}
