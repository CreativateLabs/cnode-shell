import { GATEWAY } from './config'
import type {
  AgentRun,
  AgentSpec,
  AppNotification,
  Artifact,
  Client,
  DataRequest,
  DataRequestScope,
  DemoAccount,
  Envelope,
  Folder,
  FormSummary,
  FormSpec,
  FormScoreResult,
  Graph,
  GoogleStatus,
  IngestLevel,
  LibraryFile,
  LibraryResponse,
  Me,
  Member,
  Models,
  NBA,
  NotificationsResponse,
  OnboardingHint,
  PluginDTO,
  Promotion,
  Provider,
  Role,
  Team,
  TeamMember,
  TeamRole,
  Tenant,
  TenantContextDTO,
  EntitlementDTO,
  ThreadMeta,
  ThreadVisibility,
} from './types'

// Every call is cookie-authenticated (HttpOnly session JWT set by /auth/verify).
class HttpError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'HttpError'
  }
}
export { HttpError }

async function jfetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${GATEWAY}${path}`, { credentials: 'include', ...init })
  if (!r.ok) throw new HttpError(r.status, `${path} → ${r.status} ${r.statusText}`)
  // Some endpoints (logout, approve …) may return empty bodies.
  const txt = await r.text()
  return (txt ? JSON.parse(txt) : ({} as any)) as T
}

function jsend<T>(method: string, path: string, body?: unknown): Promise<T> {
  return jfetch<T>(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
}

const jpost = <T,>(path: string, body?: unknown) => jsend<T>('POST', path, body)
const jput = <T,>(path: string, body?: unknown) => jsend<T>('PUT', path, body)
const jdel = <T,>(path: string, body?: unknown) => jsend<T>('DELETE', path, body)

// Tolerate a few plausible response shapes for /clients so the UI never crashes.
function normalizeClients(raw: any): Client[] {
  const arr: any[] = Array.isArray(raw) ? raw : raw?.clients ?? raw?.tenants ?? []
  return arr
    .map((c) =>
      typeof c === 'string'
        ? { id: c, name: c }
        : { id: String(c.id ?? c.client_id ?? c.name), name: String(c.name ?? c.label ?? c.id) },
    )
    .filter((c) => c.id)
}

function asArray<T>(raw: any, ...keys: string[]): T[] {
  if (Array.isArray(raw)) return raw
  for (const k of keys) if (Array.isArray(raw?.[k])) return raw[k]
  return []
}

export type AskArgs = {
  text: string
  client_id: string
  thread_id: string
  provider: Provider
}

export type IngestArgs = {
  client_id: string
  levels: IngestLevel[]
  files?: File[]
  url?: string
  note?: string
}

export const api = {
  // ---- core (v1, now auth-gated + tenant-scoped from JWT) ----
  health: () => jfetch<any>('/health'),
  // Tenant-Identität + Branding + aktive Module (config-driven, für Whitelabel).
  tenantContext: () => jfetch<TenantContextDTO>('/tenant/context'),
  // Plugin-Katalog dieses Tenants (Connectoren/Formate/Agenten/Systeme) für die Bibliothek.
  plugins: () => jfetch<{ plugins: PluginDTO[] }>('/plugins').then((r) => r.plugins ?? []),
  // Tenant-scoped interaktive Formulare (FraBö)
  forms: () => jfetch<{ forms: FormSummary[] }>('/forms').then((r) => r.forms ?? []),
  form: (id: string) => jfetch<FormSpec>(`/forms/${encodeURIComponent(id)}`),
  // Tenant-Orchestrator: entscheidet den Pfad einer Nachricht (form|graph_ingest|knowledge|chat).
  route: (text: string, history?: unknown[]) =>
    jpost<{ route: string; form_id?: string; method?: string; confidence?: number }>(
      '/route', { text, history: history ?? [] },
    ),
  // Owner-Org-Setup (Launch-Wizard): Org-Profil + vordefinierte Quellen + Fortschritt.
  tenantSetup: () =>
    jfetch<{
      tenant_id: string; can_edit: boolean; completed: boolean
      org_name: string; org_profile: string
      sources: { kind: string; value: string; status?: string }[]
      updated_at: string | null
    }>('/tenant/setup'),
  saveTenantSetup: (body: {
    org_name: string
    org_profile: string
    sources: { kind: string; value: string; status?: string }[]
    completed: boolean
  }) => jput<{ ok: boolean; completed: boolean }>('/tenant/setup', body),
  // Entitlement (Monetarisierung): Tier + NENA-Flag + Upsell-Ziele — steuert Upgrade-Banner.
  entitlement: () =>
    jfetch<EntitlementDTO>('/tenant/entitlement').catch(
      () => ({ tenant_id: '', tier: 'free', intel: false, public_demo: false,
               caps: {}, upgrade: {} } as EntitlementDTO)),
  // Chat-basierte Knoten-Aufnahme in den Tenant-Graph (Orchestrator-Route graph_ingest).
  capture: (text: string) =>
    jpost<{ ok: boolean; added?: { label: string; type: string }[]; edges?: number; provenance?: string }>(
      '/graph/capture', { text },
    ),
  submitForm: (id: string, body: {
    answers?: Record<string, number[]>
    values?: Record<string, any>
    subject?: string
    period?: string
    narrative?: boolean
  }) => jpost<FormScoreResult>(`/forms/${encodeURIComponent(id)}/submit`, body),
  formPdf: async (id: string, body: Record<string, any>): Promise<Blob> => {
    const r = await fetch(`${GATEWAY}/forms/${encodeURIComponent(id)}/pdf`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new HttpError(r.status, `pdf → ${r.status}`)
    return r.blob()
  },
  // Nachricht (z.B. integriertes Formular-Artefakt) in die Thread-History persistieren,
  // damit der Chat sich in Folgefragen darauf beziehen kann.
  appendMessage: (threadId: string, body: { role: 'user' | 'assistant'; text: string; author?: string }) =>
    jpost<{ ok: boolean }>(`/threads/${encodeURIComponent(threadId)}/messages`, body),
  models: () => jfetch<Models>('/models'),
  clients: () => jfetch<any>('/clients').then(normalizeClients),
  graph: (client_id?: string) =>
    jfetch<Graph>(`/graph${client_id ? `?client_id=${encodeURIComponent(client_id)}` : ''}`),
  ask: (args: AskArgs) => jpost<Envelope>('/ask', args),
  // SSE-Stream: Token-für-Token + finales Envelope. Fällt der Stream aus, wirft er → Caller kann auf ask() zurückfallen.
  askStream: async (
    args: AskArgs,
    handlers: {
      onToken?: (t: string) => void
      onDone?: (env: Envelope & { thread_id?: string }) => void
      onMeta?: (m: any) => void
    },
    signal?: AbortSignal,
  ): Promise<void> => {
    const res = await fetch(`${GATEWAY}/ask/stream`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(args),
      signal,
    })
    if (!res.ok || !res.body) throw new HttpError(res.status, `/ask/stream → ${res.status}`)
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let idx: number
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const line = chunk.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        let evt: any
        try {
          evt = JSON.parse(line.slice(5).trim())
        } catch {
          continue
        }
        if (evt.type === 'token') handlers.onToken?.(evt.text || '')
        else if (evt.type === 'done') handlers.onDone?.(evt.envelope)
        else if (evt.type === 'meta') handlers.onMeta?.(evt)
      }
    }
  },
  share: (thread_id: string) =>
    jpost<{ url: string; role: string }>(`/threads/${encodeURIComponent(thread_id)}/share`, {}),

  // ---- auth & session (v2) ----
  // Passwort-Signup: legt User (+ optional neuen Mandanten via company) an und loggt direkt ein.
  signup: (body: { email: string; password: string; name?: string; company?: string; altcha?: string }) =>
    jpost<Partial<Me>>('/auth/signup', body),
  // Altcha PoW-Challenge holen (server-signiert). Widget/Solver löst sie clientseitig.
  altchaChallenge: () =>
    jfetch<{ algorithm: string; challenge: string; maxnumber: number; salt: string; signature: string }>(
      '/auth/altcha/challenge'),
  // Passwort-Login: setzt das Session-Cookie. 401 = falsch, 400 = nur-Magic-Link-User.
  login: (email: string, password: string) =>
    jpost<Partial<Me>>('/auth/login', { email, password }),
  requestLink: (email: string) =>
    jpost<{
      token?: string
      link?: string
      dev_token?: string
      dev_link?: string
      dev?: boolean
      message?: string
      [k: string]: any
    }>('/auth/request-link', { email }),
  verify: (token: string) => jpost<Partial<Me>>('/auth/verify', { token }),
  // OTP-Code-Login (primär): Code anfordern → verifizieren. dev_code/dev_link nur ohne Mailversand.
  requestCode: (email: string) =>
    jpost<{ sent: boolean; email: string; dev_code?: string; dev_link?: string }>(
      '/auth/request-code', { email }),
  verifyCode: (email: string, code: string) =>
    jpost<Partial<Me>>('/auth/verify-code', { email, code }),
  // Passwortloser Signup (Sandbox): erfasst Profil + schickt OTP; Login danach via verifyCode.
  signupDemo: (body: { email: string; name?: string; company?: string }) =>
    jpost<{ sent: boolean; email: string; signup?: boolean; dev_code?: string; dev_link?: string }>(
      '/auth/signup-demo', body),
  // Google SSO: Browser dorthin navigieren (Redirect → Google → Callback setzt Cookie).
  ssoGoogleLoginUrl: () => `${GATEWAY}/auth/sso/google/login`,
  // Benannte Fach-Agenten (Personas) — Registry-Cards + A2A-Konsultation.
  // Prüft, ob zu einer E-Mail bereits ein Konto existiert (Login/Signup-Hinweise).
  authExists: (email: string) =>
    jfetch<{ exists: boolean; has_password: boolean }>(`/auth/exists?email=${encodeURIComponent(email)}`),
  agentCards: () => jfetch<{ agents: any[] }>('/agents/cards'),
  agentConsult: (agentId: string, text: string) =>
    jpost<any>(`/agents/domain/${agentId}/consult`, { text }),
  me: () => jfetch<Me>('/me'),
  logout: () => jpost<void>('/auth/logout').catch(() => {}), // tolerate absence
  // Demo-Schnellzugänge pro Rolle (Dev/Demo). Tolerant ggü. mehreren Wrapper-Shapes.
  demoAccounts: () =>
    jfetch<any>('/auth/demo-accounts')
      .then((r) => asArray<DemoAccount>(r, 'accounts', 'demo_accounts', 'demoAccounts', 'items'))
      .catch(() => [] as DemoAccount[]),

  // ---- Super-Admin: tenants + promotions ----
  tenants: () => jfetch<any>('/admin/tenants').then((r) => asArray<Tenant>(r, 'tenants', 'items')),
  createTenant: (name: string) => jpost<Tenant>('/admin/tenants', { name }),
  deleteTenant: (id: string) => jdel<void>(`/admin/tenants/${encodeURIComponent(id)}`),
  assignAdmin: (tenantId: string, email: string) =>
    jpost<any>(`/admin/tenants/${encodeURIComponent(tenantId)}/admins`, { email }),
  promotions: () =>
    jfetch<any>('/admin/promotions').then((r) => asArray<Promotion>(r, 'promotions', 'items')),
  approvePromotion: (id: string) => jpost<any>(`/admin/promotions/${encodeURIComponent(id)}/approve`),
  rejectPromotion: (id: string) => jpost<any>(`/admin/promotions/${encodeURIComponent(id)}/reject`),
  proposePromotion: (source_id: string) => jpost<Promotion>('/promotions', { source_id }),

  // ---- Admin: members + tenant settings ----
  members: () => jfetch<any>('/tenant/members').then((r) => asArray<Member>(r, 'members', 'items')),
  inviteMember: (email: string, role: Role) => jpost<Member>('/tenant/members', { email, role }),
  removeMember: (id: string) => jdel<void>(`/tenant/members/${encodeURIComponent(id)}`),
  updateTenantSettings: (settings: Record<string, any>) => jput<any>('/tenant/settings', settings),
  // ---- Epic O: Teams ----
  teams: () => jfetch<{ teams: Team[] }>('/tenant/teams').then((r) => r.teams ?? []),
  myTeams: () => jfetch<{ teams: Team[] }>('/tenant/my-teams').then((r) => r.teams ?? []),
  createTeam: (name: string, description = '') =>
    jpost<{ ok: boolean; team: Team }>('/tenant/teams', { name, description }),
  deleteTeam: (id: string) => jdel<void>(`/tenant/teams/${encodeURIComponent(id)}`),
  teamMembers: (id: string) =>
    jfetch<{ members: TeamMember[] }>(`/tenant/teams/${encodeURIComponent(id)}/members`).then((r) => r.members ?? []),
  addTeamMember: (id: string, email: string, role: TeamRole = 'member') =>
    jpost<any>(`/tenant/teams/${encodeURIComponent(id)}/members`, { email, role }),
  setTeamRole: (id: string, userId: string, role: TeamRole) =>
    jput<any>(`/tenant/teams/${encodeURIComponent(id)}/members/${encodeURIComponent(userId)}`, { role }),
  removeTeamMember: (id: string, userId: string) =>
    jdel<void>(`/tenant/teams/${encodeURIComponent(id)}/members/${encodeURIComponent(userId)}`),
  createInvite: (body: { email: string; org_role?: string; team_id?: string; team_role?: TeamRole }) =>
    jpost<{ ok: boolean; sent: boolean; dev_link: string | null; invite_id: string }>('/tenant/invites', body),

  // ---- Scraping allowlist (Admin) ----
  getAllowlist: () =>
    jfetch<any>('/scrape/allowlist').then((r) => asArray<string>(r, 'allowlist', 'domains', 'items')),
  setAllowlist: (allowlist: string[]) => jput<any>('/scrape/allowlist', { allowlist }),

  // ---- Ingest with target levels (client / market) ----
  ingest: (args: IngestArgs) => {
    if (args.files && args.files.length) {
      const fd = new FormData()
      fd.append('client_id', args.client_id)
      for (const lvl of args.levels) fd.append('levels', lvl)
      if (args.note) fd.append('note', args.note)
      for (const f of args.files) fd.append('files', f, f.name)
      return jfetch<Envelope>('/ingest', { method: 'POST', body: fd })
    }
    return jpost<Envelope>('/ingest', {
      client_id: args.client_id,
      levels: args.levels,
      url: args.url,
      note: args.note,
    })
  },

  // ---- Web scraping (URL → extract → ingest) ----
  scrape: (url: string, client_id: string, levels: IngestLevel[]) =>
    jpost<Envelope>('/scrape', { url, client_id, levels }),

  // ---- Voice: audio → local faster-whisper transcript ----
  transcribe: (audio: Blob, filename = 'voice.webm') => {
    const fd = new FormData()
    fd.append('file', audio, filename)
    fd.append('audio', audio, filename) // tolerate either field name
    return jfetch<{ text: string; language?: string; duration?: number }>('/voice/transcribe', {
      method: 'POST',
      body: fd,
    })
  },

  // ---- Next Best Actions (optional BFF endpoint) ----
  nba: (client_id?: string) =>
    jfetch<any>(`/nba${client_id ? `?client_id=${encodeURIComponent(client_id)}` : ''}`).then((r) =>
      asArray<NBA>(r, 'nba', 'actions', 'items'),
    ),

  // ====================================================================
  // SCOPE v3 — Folders, Threads, Notifications, Data-Requests, Library,
  //            Google, Onboarding
  // ====================================================================

  // ---- Threads (list persisted threads for a client/tenant) ----
  threads: (client_id: string) =>
    jfetch<any>(`/clients/${encodeURIComponent(client_id)}/threads`).then((r) =>
      asArray<ThreadMeta>(r, 'threads', 'items'),
    ),
  updateThread: (
    id: string,
    patch: {
      title?: string
      folder_id?: string | null
      visibility?: ThreadVisibility
      members?: string[]
      team_id?: string | null
      set_team?: boolean
    },
  ) => jput<ThreadMeta>(`/threads/${encodeURIComponent(id)}`, patch),
  deleteThread: (id: string) => jdel<void>(`/threads/${encodeURIComponent(id)}`),
  threadMessages: (id: string) =>
    jfetch<{ messages: { role: 'user' | 'assistant'; text: string; author?: string }[] }>(
      `/threads/${encodeURIComponent(id)}/messages`,
    ).then((r) => r.messages ?? []),

  // ---- Folders ----
  folders: () => jfetch<any>('/folders').then((r) => asArray<Folder>(r, 'folders', 'items')),
  createFolder: (name: string) => jpost<Folder>('/folders', { name }),
  renameFolder: (id: string, name: string) => jput<Folder>(`/folders/${encodeURIComponent(id)}`, { name }),
  deleteFolder: (id: string) => jdel<void>(`/folders/${encodeURIComponent(id)}`),

  // ---- Notifications ----
  notifications: () =>
    jfetch<any>('/notifications').then(
      (r): NotificationsResponse => ({
        items: asArray<AppNotification>(r, 'items', 'notifications'),
        unread:
          typeof r?.unread === 'number'
            ? r.unread
            : asArray<AppNotification>(r, 'items', 'notifications').filter((n) => !n.read).length,
      }),
    ),
  markNotificationRead: (id: string) => jpost<void>(`/notifications/${encodeURIComponent(id)}/read`),
  markAllNotificationsRead: () => jpost<void>('/notifications/read-all'),

  // ---- Data-Requests / Eskalation ----
  dataRequests: () =>
    jfetch<any>('/data-requests').then((r) => asArray<DataRequest>(r, 'data_requests', 'items', 'requests')),
  createDataRequest: (body: { scope: DataRequestScope; note?: string; connector?: string; thread_id?: string }) =>
    jpost<DataRequest>('/data-requests', body),
  approveDataRequest: (id: string) => jpost<any>(`/data-requests/${encodeURIComponent(id)}/approve`),
  rejectDataRequest: (id: string) => jpost<any>(`/data-requests/${encodeURIComponent(id)}/reject`),

  // ---- Library (Tenant-Dateien + aktive Connectoren); thread_id → nur Dateien des Threads ----
  library: (client_id?: string, thread_id?: string) => {
    const qs = new URLSearchParams()
    if (client_id) qs.set('client_id', client_id)
    if (thread_id) qs.set('thread_id', thread_id)
    const q = qs.toString()
    return jfetch<any>(`/library${q ? `?${q}` : ''}`).then(
      (r): LibraryResponse => ({
        files: asArray<LibraryFile>(r, 'files', 'items'),
        connectors: Array.isArray(r?.connectors) ? r.connectors : undefined,
      }),
    )
  },
  libraryUpload: (files: File[], client_id?: string, thread_id?: string) => {
    const fd = new FormData()
    if (client_id) fd.append('client_id', client_id)
    if (thread_id) fd.append('thread_id', thread_id)
    for (const f of files) fd.append('files', f, f.name)
    return jfetch<any>('/library/upload', { method: 'POST', body: fd })
  },
  deleteLibraryFile: (id: string) => jdel<void>(`/library/files/${encodeURIComponent(id)}`),
  // Artefakte eines Threads (für die rechte Thread-Sidebar).
  artifacts: (thread_id?: string) =>
    jfetch<any>(`/artifacts${thread_id ? `?thread_id=${encodeURIComponent(thread_id)}` : ''}`).then(
      (r): Artifact[] => asArray<Artifact>(r, 'artifacts', 'items'),
    ),

  // ---- Google integration status (stub-tolerant) ----
  googleStatus: () =>
    jfetch<GoogleStatus>('/integrations/google/status').catch(
      () => ({ ok: false, connected: false, reason: 'not_configured' } as GoogleStatus),
    ),
  googleDisconnect: () =>
    jpost<{ ok: boolean; connected: boolean }>('/integrations/google/disconnect'),
  // Connector-Auto-Ingest (E2.1): Gmail/Drive → Gedächtnis (mit Provenienz).
  googleSync: (body?: { max_gmail?: number; max_drive?: number }) =>
    jpost<{ ok: boolean; reason?: string; detail?: string; gmail?: number; drive?: number; nodes?: number; graph_delta?: Graph }>(
      '/integrations/google/sync',
      body ?? {},
    ),

  // Microsoft / Outlook (Graph) — Status + Disconnect (Connect via /oauth/install-Redirect).
  microsoftStatus: () =>
    jfetch<GoogleStatus>('/integrations/microsoft/status').catch(
      () => ({ ok: false, connected: false, reason: 'not_configured' } as GoogleStatus),
    ),
  microsoftDisconnect: () =>
    jpost<{ ok: boolean; connected: boolean }>('/integrations/microsoft/disconnect'),

  // NEN-Verarbeitungs-Queue-Snapshot (C: Sichtbarkeit der Ingest-Latenz).
  queue: () =>
    jfetch<{ nen: { pending: number; processed: number; failed: number; processing?: string | null; ts?: string | null } | null }>(
      '/queue',
    ).catch(() => ({ nen: null })),

  // ---- Artefakt dauerhaft in Bibliothek + Graph speichern ----
  saveArtifact: (art: { id?: string; kind?: string; title?: string; markdown?: string; thread_id?: string }) =>
    jpost<{ ok: boolean; artifact: any; graph_nodes: number }>('/artifacts/save', art),

  // ---- Agentische Aktion ausführen (nach Bestätigung) ----
  executeAction: (type: string, params: Record<string, any>) =>
    jpost<{ ok: boolean; message?: string; detail?: string; reason?: string; id?: string }>(
      '/action/execute',
      { type, params },
    ),

  // ---- Onboarding-Hint for a (new) thread ----
  onboarding: (thread_id: string) =>
    jfetch<OnboardingHint>(`/threads/${encodeURIComponent(thread_id)}/onboarding`),

  // ---- E7 Agenten (Katalog · Läufe · Ausführung mit Live-Fortschritt) ----
  agents: () => jfetch<any>('/agents').then((r) => asArray<AgentSpec>(r, 'agents', 'items')),
  agentRuns: (thread_id?: string) =>
    jfetch<any>(`/agents/runs${thread_id ? `?thread_id=${encodeURIComponent(thread_id)}` : ''}`).then(
      (r) => asArray<AgentRun>(r, 'runs', 'items'),
    ),
  // Startet einen Agenten-Lauf als SSE-Stream: plan → step* → done.
  runAgent: async (
    agentId: string,
    body: { goal: string; thread_id?: string | null; provider?: Provider },
    handlers: {
      onMeta?: (m: any) => void
      onPlan?: (p: any) => void
      onStep?: (s: any) => void
      onDone?: (d: any) => void
      onError?: (e: any) => void
    },
  ): Promise<void> => {
    const res = await fetch(`${GATEWAY}/agents/${encodeURIComponent(agentId)}/run/stream`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    })
    if (!res.ok || !res.body) throw new HttpError(res.status, `/agents/${agentId}/run/stream → ${res.status}`)
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let idx: number
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const line = chunk.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        let evt: any
        try {
          evt = JSON.parse(line.slice(5).trim())
        } catch {
          continue
        }
        if (evt.type === 'meta') handlers.onMeta?.(evt)
        else if (evt.type === 'plan') handlers.onPlan?.(evt)
        else if (evt.type === 'step') handlers.onStep?.(evt)
        else if (evt.type === 'done') handlers.onDone?.(evt)
        else if (evt.type === 'error') handlers.onError?.(evt)
      }
    }
  },
}
