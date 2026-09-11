// Single source of truth for the frozen BFF contracts (SCOPE.md §2).

export type NodeType =
  | 'Company'
  | 'Product'
  | 'Decision'
  | 'Document'
  | 'Person'
  | 'FundingProgram'
  | 'Lead'
  | 'Thought'
  | string

export type GNode = {
  id: string
  label: string
  type: NodeType
  props?: Record<string, any>
}

export type GEdge = {
  source: string
  target: string
  rel: string
  provenance?: string
}

export type Graph = { nodes: GNode[]; edges: GEdge[] }

// --- Epic O — Teams ---
export type TeamRole = 'lead' | 'member'
export type Team = {
  id: string
  name: string
  slug: string
  description?: string
  member_count?: number
  my_role?: TeamRole | null
  created_at?: string
}
export type TeamMember = {
  id: string
  team_id: string
  user_id: string
  email: string
  role: TeamRole
  created_at?: string
}

// --- Tenant Interactive Forms (FraBö) ---
export type FormSummary = {
  id: string
  title: string
  kind: string
  description: string
  triggers: string[]
  subject_prompt?: string
  sections: number
  questions: number
}

export type FormScale = {
  min: number
  max: number
  labels: string[]
  na_value: number
  na_label: string
}

export type FormField = {
  key: string
  label: string
  type: 'number' | 'text' | 'textarea' | 'select'
  unit?: string
  prev?: string
  prev_label?: string
  placeholder?: string
  help?: string
  options?: string[]
}

export type FormSectionSpec = {
  key: string
  title: string
  description?: string
  questions?: string[]
  fields?: FormField[]
}

export type FormSpec = {
  id: string
  title: string
  kind: string
  description: string
  triggers: string[]
  subject_prompt: string
  scale: FormScale
  sections: FormSectionSpec[]
  scoring: { per_section_max: number; normalize: boolean; total_max: number }
  report: { intro: string; llm_narrative: boolean }
}

export type FormSectionScore = {
  key: string
  title: string
  score: number
  max: number
  answered: number
  questions: number
}

export type FormReportField = {
  section: string
  section_title: string
  key: string
  label: string
  unit?: string
  type: string
  prev?: string
  prev_label?: string
  value: any
}

export type FormScoreResult = {
  ok: boolean
  form_id: string
  kind?: string
  score?: {
    form_id: string
    title: string
    sections: FormSectionScore[]
    total: number
    total_max: number
    percent: number
  }
  report?: {
    subject: string
    period: string
    fields: FormReportField[]
  }
  narrative: string
  persisted: boolean
}

export type Source = {
  id: string
  label: string
  type: string
  props?: Record<string, any>
  provenance?: string
}

export type TraceStep = {
  step: string
  method?: string
  result?: string
  service?: string
  [k: string]: any
}

export type ArtifactKind = 'dialog_protocol' | 'memo' | 'proposal' | 'one_pager' | string

export type Artifact = {
  id: string
  kind: ArtifactKind
  title: string
  markdown: string
  client_id?: string
  thread_id?: string
  created_at?: string
  // false / undefined = nur Session (Download/Export); true = in Bibliothek + Graph gespeichert.
  saved?: boolean
}

export type Intent =
  | 'decision'
  | 'knowledge'
  | 'leads'
  | 'foerderung'
  | 'ingest'
  | 'graph'
  | 'smalltalk'
  | string

// The unified Envelope — identical for every route.
export type Envelope = {
  intent: Intent
  route: 'engine' | 'assets' | 'graph' | string
  result_text: string
  sources: Source[]
  artifact: Artifact | null
  graph_delta: Graph
  highlight: string[]
  trace: TraceStep[]
  provider: string
  model: string
  // Ehrlichkeits-Signal: Beleg-Basis der Antwort. 'gedaechtnis' = aus belegten Knoten,
  // 'allgemein' = allgemeine Einschätzung (nicht belegt), 'chat' = Gesprächs-/Schreib-Turn.
  grounding?: 'gedaechtnis' | 'allgemein' | 'chat' | 'web' | string
  grounded?: boolean
  // Dynamische, kontextuelle Folge-Vorschläge (vom LLM je Antwort erzeugt).
  suggestions?: string[]
  // Agentische Aktion mit Außenwirkung → wird erst nach Bestätigung ausgeführt.
  action?: AgentAction
  // Proaktive Inline-CTAs (z.B. „Web-Recherche" / „Quelle bereitstellen" / „Agent starten").
  // type 'agent' trägt eine echte Tool-Bindung: agent (+ optional goal) statt Prompt-Text.
  ctas?: {
    type: 'ingest' | 'connect' | 'research' | 'agent' | 'upgrade' | string
    label: string
    agent?: string
    goal?: string
    note?: string
  }[]
}

export type AgentAction = {
  id: string
  type: string // z.B. 'gmail_draft'
  connector: string // 'gmail' | 'gcal' | …
  connected: boolean
  title: string
  summary?: string
  params: { subject?: string; body?: string; to?: string; [k: string]: any }
  status?: 'pending' | 'running' | 'done' | 'error'
  result?: string // Ergebnis-/Fehlermeldung nach Ausführung
}

export type Client = { id: string; name: string }

export type Provider = 'ollama' | 'gemini' | 'claude'

// Spiegelt die Engine-/models-Antwort. On-Prem (Ollama) ist immer da; Gemini/Claude nur mit Key.
export type ProviderInfo = {
  reachable?: boolean
  configured?: boolean
  models?: string[]
  model?: string | null
}
export type Models = {
  default?: string
  default_provider?: Provider
  ollama?: ProviderInfo
  gemini?: ProviderInfo
  claude?: ProviderInfo
  providers?: string[]
}

// ---- Local UI state (not part of the contract) ----
export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  pending?: boolean
  error?: boolean
  envelope?: Envelope
  author?: string // Sender-Email (User) bzw. "c:node" — für Avatare / Team-Chat
}

// ======================================================================
// SCOPE v2 — Auth / Tenancy / Governance / Voice contracts (§ v2)
// ======================================================================

// Rollen: Super-Admin / Admin / Member / Viewer (siehe Governance-Konzept).
export type Role = 'super_admin' | 'admin' | 'member' | 'viewer' | string

export type User = {
  id?: string
  user_id?: string
  email: string
  name?: string
  role?: Role
}

export type Tenant = { id: string; name?: string; label?: string; settings?: Record<string, unknown>; created_at?: string }

// GET /tenant/entitlement → Monetarisierung: Tier + NENA-Flag + Upsell-Ziele.
export type EntitlementTier = 'free' | 'pro' | 'team' | 'enterprise' | string
export type EntitlementDTO = {
  tenant_id: string
  tier: EntitlementTier
  intel: boolean               // NENA (market/mesh) freigeschaltet?
  public_demo: boolean         // läuft diese Instanz als öffentliche Sandbox?
  caps: { per_min?: number; per_day?: number; tokens_per_day?: number }
  upgrade: { pro?: string; team?: string; enterprise?: string; whitelabel?: string }
}

// GET /me → { user, tenant, role, permissions }
export type Me = {
  user: User
  tenant: Tenant | null
  role: Role
  permissions?: string[]
}

// Mitglied eines Mandanten (Admin-Verwaltung)
export type Member = {
  id: string
  email: string
  role: Role
  name?: string
  created_at?: string
}

// Market-Promotion (Admin schlägt vor → Super-Admin gibt frei)
export type Promotion = {
  id: string
  source_id: string
  label?: string
  tenant_id?: string
  tenant?: string
  reason?: string
  status?: 'open' | 'approved' | 'rejected' | string
  created_at?: string
  [k: string]: any
}

// Ingest-Ebene: Mandanten-Archiv (client) / c:node Gesamt (market) / Data-Mesh (mesh)
export type IngestLevel = 'client' | 'market' | 'mesh'

// Demo-Zugang (Schnellanmeldung pro Rolle) — GET /auth/demo-accounts
export type DemoAccount = {
  email: string
  password: string
  role: Role
  tenant?: string
  label?: string
}

// Next-Best-Action Vorschlag (proaktive Karte)
export type NBA = {
  id: string
  title: string
  reason: string // "weil …"-Begründung
  prompt?: string // was an /ask gesendet wird
  cta?: string // Button-Label
  intent?: Intent
  [k: string]: any
}

// ======================================================================
// SCOPE v3 — Folders, Threads/Collab, Notifications, Data-Requests,
//            Library, Google, Onboarding (§ v3)
// ======================================================================

// Sichtbarkeit eines Threads: privat (nur Owner) / team (Owner + Member)
export type ThreadVisibility = 'private' | 'team' | 'org'

// Ordner in der Sidebar (BFF: GET/POST /folders, PUT/DELETE /folders/{id})
export type Folder = {
  id: string
  name: string
  created_at?: string
  [k: string]: any
}

// Thread wie ihn die BFF liefert/persistiert.
// (Die Sidebar-UI erweitert dies um lokale Felder — siehe components/Sidebar.tsx)
export type ThreadMeta = {
  id: string
  title: string
  folder_id?: string | null
  visibility?: ThreadVisibility
  members?: string[] // E-Mails (nur bei visibility === 'team')
  owner?: string // Owner-E-Mail
  created_at?: string
  updated_at?: string
  [k: string]: any
}

// Notification (BFF: GET /notifications, POST /notifications/{id}/read, /read-all)
export type NotificationType =
  | 'data_request'
  | 'thread_invite'
  | 'promotion'
  | 'escalation'
  | 'system'
  | string

export type AppNotification = {
  id: string
  type: NotificationType
  title: string
  body?: string
  from?: string
  created_at?: string
  read?: boolean
  [k: string]: any
}

export type NotificationsResponse = {
  items: AppNotification[]
  unread: number
}

// Data-Request / Eskalation (BFF: POST /data-requests, GET /data-requests,
// POST /data-requests/{id}/{approve|reject})
export type DataRequestScope = 'general' | 'scoped' | 'connector' | string

export type DataRequest = {
  id: string
  scope: DataRequestScope
  note?: string
  connector?: string
  status?: 'open' | 'approved' | 'rejected' | string
  from?: string
  to_role?: Role
  thread_id?: string
  client_id?: string
  created_at?: string
  [k: string]: any
}

// Library-Datei (Assets/BFF: GET /library → files[])
export type LibraryFile = {
  id: string
  name: string
  mime?: string
  type?: string
  size?: number
  chars?: number
  client_id?: string
  created_at?: string
  [k: string]: any
}

// GET /library → Tenant-Dateien + aktive Connectoren
export type LibraryResponse = {
  files: LibraryFile[]
  connectors?: string[] // IDs aktiver Connectoren (aus tenant settings)
  [k: string]: any
}

// GET /integrations/google/status
export type GoogleStatus = {
  ok: boolean
  connected?: boolean
  reason?: string
  email?: string
  scopes?: string[]
  [k: string]: any
}

// ---- E7 Agenten ----------------------------------------------------------
export type AgentFamily = 'advisor' | 'scout' | 'governance' | 'action' | string

// GET /agents → Katalog verfügbarer Agenten (Config über geteilter Engine)
export type AgentSpec = {
  id: string
  name: string
  family: AgentFamily
  description: string
  tier: string
}

export type AgentStepStatus = 'planned' | 'running' | 'done' | 'failed' | 'skipped'

export type AgentStep = {
  id?: string
  idx: number
  title: string
  tool?: string | null
  status: AgentStepStatus
  summary?: string | null
  provenance?: any[]
}

export type AgentRunStatus = 'planned' | 'running' | 'done' | 'failed'

// GET /agents/runs → persistierter Lauf (Source of Truth in Postgres)
export type AgentRun = {
  id: string
  agent: string
  agent_name?: string
  goal: string
  status: AgentRunStatus
  provider?: string
  thread_id?: string | null
  artifact_id?: string | null
  result?: string | null
  created_at?: string
  steps: AgentStep[]
}

// GET /threads/{id}/onboarding → Vorschlag general vs scoped + Data-Gaps
export type OnboardingHint = {
  mode?: 'general' | 'scoped' | string
  suggestion?: string
  data_gaps?: string[]
  gaps?: string[]
  low_data?: boolean
  node_count?: number
  [k: string]: any
}

// --- Tenant + Plugins (config-driven Whitelabel) ---------------------------
export type TenantContextDTO = {
  id: string
  name: string
  mode?: string
  locale?: string
  brand?: { wordmark?: string; logo?: string; primary?: string; accent?: string; favicon?: string }
  modules?: { scouts?: string[]; agents?: string[]; ontology_studio?: boolean; verifiable_reasoning?: boolean }
}

export type PluginDTO = {
  id: string
  kind: 'connector' | 'format' | 'agent' | 'system' | string
  name: string
  version?: string
  description?: string
  capabilities?: string[]
}
