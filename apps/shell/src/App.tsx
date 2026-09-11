import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { useT } from './i18n'
import { setBrand } from './brand'
import type {
  AgentRun,
  AgentSpec,
  AgentStep,
  AppNotification,
  Artifact,
  ChatMessage,
  Client,
  EntitlementDTO,
  Envelope,
  Folder,
  FormSummary,
  Graph,
  Me,
  Models,
  NBA,
  OnboardingHint,
  Provider,
  ThreadVisibility,
} from './types'
import { isAdmin, isSuperAdmin } from './roles'
import Topbar from './components/Topbar'
import Sidebar, { type Thread } from './components/Sidebar'
import BottomNav from './components/BottomNav'
import ChatsScreen from './components/ChatsScreen'
import MobileHeaderMenu from './components/MobileHeaderMenu'
import CnodeLogo from './components/CnodeLogo'
import ThreadHeader from './components/ThreadHeader'
import ChatView from './components/ChatView'
import Composer from './components/Composer'
import ArtifactPanel from './components/ArtifactPanel'
import RightRail from './components/RightRail'
import GlobalSearch from './components/GlobalSearch'
import GraphOverlay from './components/GraphOverlay'
import LoginScreen from './components/LoginScreen'
import Landing from './components/Landing'
import SettingsOverlay from './components/SettingsOverlay'
import OwnerSetup from './components/OwnerSetup'
import UpgradeBanner from './components/UpgradeBanner'
import IngestDialog, { type IngestSubmit } from './components/IngestDialog'
import { NotificationBell, NotificationsPage } from './components/Notifications'
import LibraryPage from './components/LibraryPage'
import Onboarding from './components/Onboarding'

// Kein hartkodierter Demo-Client mehr — die Client-Liste ist config-driven und wird
// aus dem TenantContext (dediziert) bzw. /clients (shared) befüllt.
const FALLBACK_CLIENTS: Client[] = []

const PROVIDER_KEY = 'cnode.provider.default'

const uid = (p: string) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`

function mergeGraph(base: Graph, delta?: Graph): Graph {
  if (!delta) return base
  const ids = new Set(base.nodes.map((n) => n.id))
  const nodes = [...base.nodes]
  for (const n of delta.nodes || []) if (!ids.has(n.id)) { nodes.push(n); ids.add(n.id) }
  const key = (e: any) => `${e.source}-${e.rel}-${e.target}`
  const eset = new Set(base.edges.map(key))
  const edges = [...base.edges]
  for (const e of delta.edges || []) if (!eset.has(key(e))) { edges.push(e); eset.add(key(e)) }
  return { nodes, edges }
}

// Client-seitiger NBA-Fallback, falls die BFF keinen /nba-Endpunkt liefert.
// TODO(WS-MW/WS-INT): durch echte GET /nba-Antwort ersetzen, sobald verfügbar.
function buildFallbackNba(graph: Graph, clientName?: string): NBA[] {
  const has = (t: string) => graph.nodes.some((n) => n.type === t)
  const out: NBA[] = []
  if (has('Decision')) {
    out.push({
      id: 'nba_memo',
      title: 'Memo aus letzter Entscheidung',
      reason: 'im Gedächtnis liegt eine Entscheidung ohne Protokoll-Artefakt.',
      prompt: 'Erstelle ein Memo zur letzten Entscheidung im Gedächtnis.',
      cta: 'Memo erstellen',
      intent: 'decision',
    })
  }
  out.push({
    id: 'nba_leads',
    title: `Leads für ${clientName || 'diesen Mandanten'} finden`,
    reason: 'in diesem Thread wurde noch keine Lead-Recherche gestartet.',
    prompt: 'Finde passende Leads für den kommunalen Sektor',
    cta: 'LeadScout starten',
    intent: 'leads',
  })
  out.push({
    id: 'nba_foerderung',
    title: 'Passende Förderung prüfen',
    reason: 'FuE-Vorhaben lassen sich häufig fördern — Förder gleicht ~14k Programme ab.',
    prompt: 'Welche Förderung passt zu unserem FuE-Vorhaben?',
    cta: 'Förder-Match',
    intent: 'foerderung',
  })
  return out.slice(0, 4)
}

function Toast({ text, onClose }: { text: string; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4200)
    return () => clearTimeout(t)
  }, [onClose])
  return (
    <div className="fixed top-6 inset-x-0 z-[60] flex justify-center px-4 animate-fade-down pointer-events-none">
      <div className="pointer-events-auto flex items-center gap-3 px-4 py-2.5 rounded-xl bg-surface2 border border-line shadow-2xl shadow-black/50 text-[13px] text-paper text-center max-w-[min(90vw,640px)]">
        <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
        <span className="flex-1">{text}</span>
        <button onClick={onClose} className="text-muted hover:text-paper shrink-0">
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
        </button>
      </div>
    </div>
  )
}

export default function App() {
  const t = useT()
  // ---- auth / session ----
  const [me, setMe] = useState<Me | null>(null)
  const [authState, setAuthState] = useState<'checking' | 'out' | 'in'>('checking')

  const [clients, setClients] = useState<Client[]>(FALLBACK_CLIENTS)
  const [activeClient, setActiveClient] = useState<Client | null>(null)
  // null = noch keine explizite Nutzerwahl → dann folgt der Provider dem Server-Default
  // (LLM_PROVIDER, z.B. gemini als Sandbox-LLM). Sobald umgeschaltet, wird die Wahl persistiert.
  const [provider, setProvider] = useState<Provider>(
    () => (localStorage.getItem(PROVIDER_KEY) as Provider) || 'ollama',
  )
  const [models, setModels] = useState<Models>({})

  const [threads, setThreads] = useState<Thread[]>([])
  const [folders, setFolders] = useState<Folder[]>([])
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  // Rechte Thread-Sidebar: default ZU — öffnet sich nur auf Thread-Ebene (Datei-Upload
  // oder Agenten-Start). Manuell per Toggle in der Thread-Nav umschaltbar.
  const [railOpen, setRailOpen] = useState(false)
  const [railRefresh, setRailRefresh] = useState(0)
  // E7 Agenten: Katalog, persistierte Läufe, aktuell streamender Lauf.
  const [agentCatalog, setAgentCatalog] = useState<AgentSpec[]>([])
  const [domainAgents, setDomainAgents] = useState<any[]>([])  // benannte Fach-Agenten (Personas)
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([])
  const [liveRun, setLiveRun] = useState<AgentRun | null>(null)
  // Composer-Draft von außen (Klick auf Agent in der rechten Sidebar → Slash-artige Vorbefüllung).
  const [composerDraft, setComposerDraft] = useState<string | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [msgByThread, setMsgByThread] = useState<Record<string, ChatMessage[]>>({})

  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] })
  const [highlight, setHighlight] = useState<string[]>([])
  const [nba, setNba] = useState<NBA[]>([])

  const [busy, setBusy] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  // Mobile (< md): Chats/Ordner leben in einem Vollbild-Screen (Bottom-Nav „Chats"),
  // nicht mehr in einem Sidebar-Drawer. Die Desktop-Sidebar bleibt unverändert.
  const [chatsOpen, setChatsOpen] = useState(false)
  const [showGraph, setShowGraph] = useState(false)
  const [graphFocus, setGraphFocus] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [settingsSection, setSettingsSection] = useState<
    'profile' | 'members' | 'sources' | 'connectors' | 'tenants' | 'promotions' | 'model'
  >('profile')
  const [artifact, setArtifact] = useState<Artifact | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [currentModel, setCurrentModel] = useState('')
  const [tenantWordmark, setTenantWordmark] = useState('c:node')
  const [tenantScope, setTenantScope] = useState<{ id: string; name: string; mode: string } | null>(null)
  const [forms, setForms] = useState<FormSummary[]>([])
  const [activeFormId, setActiveFormId] = useState<string | null>(null)
  const [captureMode, setCaptureMode] = useState(false) // Orchestrator-Route graph_ingest: Knoten-Aufnahme aktiv
  // Owner Launch Wizard (Org einrichten): Setup-State + Overlay-Sichtbarkeit.
  const [ownerSetup, setOwnerSetup] = useState<
    { can_edit: boolean; completed: boolean; org_name: string; org_profile: string; sources: { kind: string; value: string; status?: string }[] } | null
  >(null)
  const [showOwnerSetup, setShowOwnerSetup] = useState(false)
  // Sandbox: Login ist die Default-Seite — keine öffentliche Landing davor.
  const [showLanding, setShowLanding] = useState(false)
  // Monetarisierung: Entitlement (Tier/NENA) + Cap-Hit (429) → Upsell-Surface.
  const [entitlement, setEntitlement] = useState<EntitlementDTO | null>(null)
  const [capHit, setCapHit] = useState(false)
  // Zähler, dessen Erhöhung den Upgrade-Modal öffnet (Chat-CTA „Volle NENA-Tiefe freischalten").
  const [upgradeSignal, setUpgradeSignal] = useState(0)

  // v3: notifications, library, tenant member emails, onboarding
  const [notifs, setNotifs] = useState<AppNotification[]>([])
  const [unread, setUnread] = useState(0)
  const [notifsLoading, setNotifsLoading] = useState(false)
  const [showNotifications, setShowNotifications] = useState(false)
  const [showLibrary, setShowLibrary] = useState(false)
  const [tenantEmails, setTenantEmails] = useState<string[]>([])
  const [onboardingHint, setOnboardingHint] = useState<OnboardingHint | null>(null)

  // ingest dialog
  const [ingestOpen, setIngestOpen] = useState(false)
  const [ingestFiles, setIngestFiles] = useState<File[]>([])
  const [ingestBusy, setIngestBusy] = useState(false)

  const superAdmin = isSuperAdmin(me)
  const admin = isAdmin(me)
  const meEmail = me?.user?.email
  const escalationTarget = superAdmin ? t('app.escalation_team') : admin ? t('app.escalation_superadmin') : t('app.escalation_admin')

  // ---- session check on mount ----
  const loadMe = useCallback(async () => {
    try {
      const m = await api.me()
      setMe(m)
      setAuthState('in')
    } catch {
      setMe(null)
      setAuthState('out')
    }
  }, [])
  useEffect(() => {
    loadMe()
  }, [loadMe])

  // Rückkehr vom Google-OAuth-Consent (?google=connected|error) → Toast + URL bereinigen.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search)
    const g = p.get('google')
    if (!g) return
    setToast(g === 'connected' ? t('app.google_connected') : t('app.google_connect_failed'))
    p.delete('google')
    const q = p.toString()
    window.history.replaceState({}, '', window.location.pathname + (q ? `?${q}` : ''))
  }, [])

  // Rückkehr vom Google-SSO-Login (?login=ok|error|noaccess) → Toast + URL bereinigen.
  // Bei ok setzt der Callback bereits das Session-Cookie; loadMe() greift beim Mount.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search)
    const l = p.get('login')
    if (!l) return
    if (l === 'error') setToast(t('app.google_login_failed'))
    else if (l === 'noaccess') setToast(t('app.google_no_access'))
    p.delete('login')
    const q = p.toString()
    window.history.replaceState({}, '', window.location.pathname + (q ? `?${q}` : ''))
  }, [])

  // ---- bootstrap once authenticated ----
  useEffect(() => {
    if (authState !== 'in') return
    api.models().then((m) => {
      setModels(m)
      // Kein gespeicherter Nutzer-Wunsch? → Server-Default übernehmen (z.B. gemini-Sandbox).
      if (!localStorage.getItem(PROVIDER_KEY) && m.default_provider) {
        setProvider(m.default_provider)
      }
    }).catch(() => {})
    api.forms().then(setForms).catch(() => setForms([]))
    // Dediziertes Tenant-Deployment: Client-Liste ist auf DIESEN Tenant gescoped —
    // auch ein Super-Admin sieht hier nicht die globale Workspace-Liste (z.B. „Beispiel"),
    // sondern nur den Tenant (z.B. „Beispiel-Mandant"). client_id = tenant.id → Tenant-Graph.
    if (tenantScope?.mode === 'dedicated') {
      const c = { id: tenantScope.id, name: tenantScope.name }
      setClients([c])
      setActiveClient((prev) => (prev?.id === c.id ? prev : c))
      return
    }
    if (superAdmin) {
      api
        .clients()
        .then((cs) => {
          if (cs.length) {
            setClients(cs)
            setActiveClient((prev) => cs.find((c) => c.id === prev?.id) ?? cs[0])
          } else if (me?.tenant) {
            setActiveClient({ id: me.tenant.id, name: me.tenant.label ?? me.tenant.name ?? me.tenant.id })
          }
        })
        .catch(() => {
          if (me?.tenant) setActiveClient({ id: me.tenant.id, name: me.tenant.label ?? me.tenant.name ?? me.tenant.id })
        })
    } else if (me?.tenant) {
      // non-super-admins are locked to their own tenant (from JWT)
      const t = { id: me.tenant.id, name: me.tenant.label ?? me.tenant.name ?? me.tenant.id }
      setClients([t])
      setActiveClient(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authState, superAdmin, me, tenantScope])

  // ---- (re)load graph + NBA on client change ----
  useEffect(() => {
    if (!activeClient || authState !== 'in') return
    api.graph(activeClient.id).then(setGraph).catch(() => setGraph({ nodes: [], edges: [] }))
  }, [activeClient, authState])

  // ---- Owner-Org-Setup laden. Pflicht-Setup (can_edit && !completed) blockiert die App,
  //      bis die Gedächtnis initialisiert ist — die Render-Bedingung zeigt es dann. ----
  useEffect(() => {
    if (authState !== 'in') return
    api.tenantSetup().then(setOwnerSetup).catch(() => setOwnerSetup(null))
    api.entitlement().then(setEntitlement).catch(() => setEntitlement(null))
  }, [authState, activeClient])

  // Öffentliche Sandbox (public_demo): Provider ist fest Gemini — Nutzerwahl/Server-Default
  // werden überstimmt (Backend clampt ohnehin, das hält die UI konsistent).
  useEffect(() => {
    if (entitlement?.public_demo) setProvider('gemini')
  }, [entitlement])

  useEffect(() => {
    if (!activeClient || authState !== 'in') return
    api
      .nba(activeClient.id)
      .then((items) => setNba(items.length ? items : buildFallbackNba(graph, activeClient.name)))
      .catch(() => setNba(buildFallbackNba(graph, activeClient.name)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeClient, authState, graph.nodes.length])

  // ---- v3: notifications (poll lightly) ----
  const loadNotifs = useCallback(() => {
    setNotifsLoading(true)
    api
      .notifications()
      .then((r) => {
        setNotifs(r.items)
        setUnread(r.unread)
      })
      .catch(() => {
        /* tolerate absent endpoint */
      })
      .finally(() => setNotifsLoading(false))
  }, [])

  useEffect(() => {
    if (authState !== 'in') return
    loadNotifs()
    const t = setInterval(loadNotifs, 45000)
    return () => clearInterval(t)
  }, [authState, loadNotifs])

  // ---- v3: folders + tenant member emails ----
  useEffect(() => {
    if (authState !== 'in') return
    api.folders().then(setFolders).catch(() => setFolders([]))
    api
      .members()
      .then((ms) => setTenantEmails(ms.map((m) => m.email).filter(Boolean)))
      .catch(() => setTenantEmails([]))
  }, [authState])

  // ---- v3: best-effort load of persisted threads for the active client ----
  useEffect(() => {
    if (!activeClient || authState !== 'in') return
    api
      .threads(activeClient.id)
      .then((server) => {
        if (!server.length) return
        setThreads((local) => {
          const have = new Set(local.map((t) => t.id))
          const add: Thread[] = server
            .filter((s) => !have.has(s.id))
            .map((s, i) => ({
              id: s.id,
              title: s.title || t('app.thread_fallback'),
              ts: s.updated_at ? new Date(s.updated_at).getTime() : Date.now() - i,
              folder_id: s.folder_id ?? null,
              visibility: s.visibility ?? 'private',
              members: s.members ?? [],
              owner: s.owner ?? meEmail,
            }))
          return add.length ? [...add, ...local] : local
        })
      })
      .catch(() => {
        /* keep local threads */
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeClient, authState])

  const claudeReady = !!models.claude?.configured
  const geminiReady = !!models.gemini?.configured
  const messages = activeThreadId ? msgByThread[activeThreadId] ?? [] : []

  // Persistierte Thread-Historie laden, wenn ein Thread geöffnet wird, dessen
  // Nachrichten diese Session noch nicht im Speicher hat (undefined = nie geladen;
  // [] = bereits geladen/neu). So sieht man beim Wechsel den bisherigen Verlauf.
  const loadingThreadRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    const id = activeThreadId
    if (!id || msgByThread[id] !== undefined || loadingThreadRef.current.has(id)) return
    loadingThreadRef.current.add(id)
    api
      .threadMessages(id)
      .then((msgs) => {
        const restored: ChatMessage[] = msgs.map((m, i) => ({
          id: `hist-${id}-${i}`,
          role: m.role,
          text: m.text,
          author: m.author,
        }))
        setMsgByThread((prev) => (prev[id] !== undefined ? prev : { ...prev, [id]: restored }))
      })
      .catch(() =>
        setMsgByThread((prev) => (prev[id] !== undefined ? prev : { ...prev, [id]: [] })),
      )
      .finally(() => loadingThreadRef.current.delete(id))
  }, [activeThreadId, msgByThread])

  // Ref gegen Stale-Closure: mehrere Aufrufe im selben Handler (Upload → send) sollen
  // NICHT zwei Threads erzeugen.
  const activeThreadIdRef = useRef<string | null>(null)
  useEffect(() => {
    activeThreadIdRef.current = activeThreadId
  }, [activeThreadId])

  const ensureThread = useCallback((): string => {
    const cur = activeThreadIdRef.current
    if (cur) return cur
    const id = uid('t')
    activeThreadIdRef.current = id
    // Neue Chats sind standardmäßig privat; Sichtbarkeit wird je Chat oben im Header gesetzt.
    setThreads((ts) => [
      { id, title: t('app.new_chat'), ts: Date.now(), folder_id: null,
        visibility: 'private', members: [], owner: meEmail },
      ...ts,
    ])
    setMsgByThread((m) => ({ ...m, [id]: [] }))
    setActiveThreadId(id)
    return id
  }, [meEmail])

  const patchMessages = useCallback((threadId: string, fn: (arr: ChatMessage[]) => ChatMessage[]) => {
    setMsgByThread((m) => ({ ...m, [threadId]: fn(m[threadId] ?? []) }))
  }, [])

  // E11: Cancel/Recall + chronologische Sende-Warteschlange.
  const abortRef = useRef<AbortController | null>(null)
  const queueRef = useRef<{ id: string; text: string }[]>([])
  const busyRef = useRef(false)
  const runSendRef = useRef<(t: string) => Promise<void>>()
  const startAgentRef = useRef<(agentId: string, goal: string) => void>()
  const [queued, setQueued] = useState<{ id: string; text: string }[]>([])
  const syncQueued = () => setQueued([...queueRef.current])

  const runSend = useCallback(
    async (text: string) => {
      if (!text.trim() || !activeClient) return
      busyRef.current = true
      setBusy(true)
      const ctrl = new AbortController()
      abortRef.current = ctrl
      const threadId = ensureThread()
      const userMsg: ChatMessage = { id: uid('u'), role: 'user', text, author: meEmail }
      const pendingMsg: ChatMessage = { id: uid('a'), role: 'assistant', text: '', pending: true }
      patchMessages(threadId, (arr) => [...arr, userMsg, pendingMsg])

      const newChatTitle = t('app.new_chat')
      setThreads((ts) =>
        ts.map((th) =>
          th.id === threadId && (th.title === newChatTitle || !th.title)
            ? { ...th, title: text.length > 42 ? text.slice(0, 40) + '…' : text }
            : th,
        ),
      )

      let acc = ''
      const finalize = (env: Envelope & { thread_id?: string }) => {
        patchMessages(threadId, (arr) =>
          arr.map((m) =>
            m.id === pendingMsg.id
              ? { ...m, pending: false, text: env.result_text || acc || t('app.empty_answer'), envelope: env }
              : m,
          ),
        )
        if (env.graph_delta) setGraph((g) => mergeGraph(g, env.graph_delta))
        if (env.highlight?.length) setHighlight(env.highlight)
        if (env.model) setCurrentModel(env.model)
        if (env.artifact) setArtifact(env.artifact)
        // Chat speist das Gedächtnis (fire-and-forget) → Graph kurz danach neu laden,
        // damit die neu gelernten Knoten im Wissensgraph sichtbar werden.
        if (activeClient) setTimeout(() => {
          api.graph(activeClient.id).then(setGraph).catch(() => {})
        }, 1800)
      }
      try {
        await api.askStream(
          { text, client_id: activeClient.id, thread_id: threadId, provider },
          {
            onToken: (t) => {
              acc += t
              // Token-für-Token anzeigen (kein Envelope → kein Typewriter, sofort sichtbar).
              patchMessages(threadId, (arr) =>
                arr.map((m) => (m.id === pendingMsg.id ? { ...m, pending: false, text: acc } : m)),
              )
            },
            onDone: (env) => finalize(env),
          },
          ctrl.signal,
        )
      } catch (e: any) {
        const aborted = e?.name === 'AbortError' || ctrl.signal.aborted
        const rateLimited = e?.status === 429
        if (rateLimited) {
          setCapHit(true) // Upsell-Surface öffnen (Sandbox-Limit erreicht)
          api.entitlement().then(setEntitlement).catch(() => {})
        }
        patchMessages(threadId, (arr) =>
          arr.map((m) =>
            m.id === pendingMsg.id
              ? aborted
                ? {
                    ...m,
                    pending: false,
                    error: false,
                    text: acc ? acc + '\n\n' + t('app.recalled_suffix') : t('app.recalled_msg'),
                  }
                : rateLimited
                ? {
                    ...m,
                    pending: false,
                    error: false,
                    text: t('app.rate_limited'),
                  }
                : {
                    ...m,
                    pending: false,
                    error: true,
                    text: t('app.gateway_failed', { error: e.message }),
                  }
              : m,
          ),
        )
      } finally {
        abortRef.current = null
        busyRef.current = false
        setBusy(false)
        // Nächste eingereihte Nachricht chronologisch abarbeiten (E11.2).
        const next = queueRef.current.shift()
        syncQueued()
        if (next) void runSendRef.current?.(next.text)
      }
    },
    [activeClient, provider, ensureThread, patchMessages, meEmail],
  )
  useEffect(() => {
    runSendRef.current = runSend
  }, [runSend])

  // Öffentliches send: läuft sofort — oder reiht chronologisch ein, wenn schon eine
  // Antwort streamt (E11.2). Mehrere schnell abgeschickte Prompts gehen nicht verloren.
  // NL-Trigger für interaktive Formulare (FraBö): matcht Trigger-Phrasen / /id / Titel.
  // Normalisieren: Diakritika + Sonderzeichen raus → „Quartals-Report" == „quartalsreport".
  const normKey = (s: string): string =>
    s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '')

  // Agent-Start-Absicht hat Vorrang vor Formular-Matching: „starte den Startup-Scout" darf
  // NICHT im Start-up-Impact-Score-Formular landen. Starkes Signal = Start-Verb + scout/agent
  // bzw. ein Agenten-Name. /ask erkennt dann den konkreten Agenten und schlägt ihn vor.
  const isAgentStart = (text: string): boolean => {
    const t = text.toLowerCase()
    const launch = /\b(starte|start|los|aktivier\w*|f[üue]+hre?|leg\s+los)\b/.test(t)
    const agentSig =
      /scout|agent/.test(t) ||
      /\b(recherche|memo|governance|compliance|outreach)\b/.test(t)
    return launch && agentSig
  }

  // Agent + Ziel direkt aus der Nachricht ableiten (spiegelt die Engine-Erkennung), damit der
  // Chat den Agenten SOFORT startet — statt Button → Panel → Ziel erneut tippen. Das Ziel + der
  // Thread-Kontext (Verlauf/Gedächtnis) reichen dem Agenten, um sich auf das Vorherige zu beziehen.
  const parseAgent = (text: string): { agentId: string; goal: string } | null => {
    const t = text.toLowerCase()
    let agentId: string | null = null
    if (/governance|compliance|dsgvo|gdpr|ai act|ai-act|ki-verordnung|audit/.test(t)) agentId = 'governance'
    else if (/förder|foerder|funding|foerder/.test(t)) agentId = 'funding'
    else if (/trend/.test(t)) agentId = 'trend'
    else if (/outreach|anschreiben|mail-agent|e-mail-agent/.test(t)) agentId = 'outreach'
    else if (/startup|start-up|ausgründ|ausgruend/.test(t)) agentId = 'startup'
    else if (/scout|lead/.test(t)) agentId = 'leadscout'
    else if (/memo|entscheid/.test(t)) agentId = 'memo'
    else if (/recherche|briefing/.test(t)) agentId = 'recherche'
    if (!agentId) return null
    // Ziel = Text nach zu/an/über/für/: — sonst leer (dann fragt /ask per CTA nach).
    const m =
      text.match(/\b(?:zu|an|über|ueber|zum|zur|für|fuer|about|on)\b[:\s]+(.+)$/i) ||
      text.match(/:\s*(.+)$/)
    const goal = (m ? m[1] : '').trim()
    return { agentId, goal }
  }

  const matchForm = useCallback(
    (text: string): string | null => {
      const raw = text.trim().toLowerCase()
      if (!raw) return null
      const nt = normKey(text)
      let best: string | null = null
      let bestLen = 0 // längster Treffer gewinnt (disambiguiert mehrere Formulare)
      for (const f of forms) {
        if (raw === `/${f.id}` || raw === f.id.toLowerCase()) return f.id
        for (const k of [f.id, f.id.replace(/-/g, ' '), f.title, ...f.triggers]) {
          const nk = normKey(k)
          if (nk.length >= 4 && nt.includes(nk) && nk.length > bestLen) {
            best = f.id
            bestLen = nk.length
          }
        }
      }
      return best
    },
    [forms],
  )

  const startForm = useCallback(
    (formId: string, triggerText: string) => {
      const threadId = ensureThread()
      const f = forms.find((x) => x.id === formId)
      const title = f?.title || t('app.form_title_fallback')
      const scored = (f?.kind ?? 'assessment') === 'assessment'
      const framing = scored
        ? t('app.form_framing_scored', { title })
        : t('app.form_framing_report', { title })
      patchMessages(threadId, (arr) => [
        ...arr,
        { id: uid('u'), role: 'user', text: triggerText, author: meEmail },
        { id: uid('a'), role: 'assistant', text: framing, author: 'assistant' },
      ])
      // Trigger in die DB-History (damit die Konversation um das Artefakt kohärent bleibt).
      api.appendMessage(threadId, { role: 'user', text: triggerText, author: meEmail }).catch(() => {})
      setActiveFormId(formId)
    },
    [forms, ensureThread, patchMessages, meEmail],
  )

  const onFormComplete = useCallback(
    (md: string) => {
      const threadId = activeThreadIdRef.current
      if (threadId && md) {
        patchMessages(threadId, (arr) => [
          ...arr,
          { id: uid('a'), role: 'assistant', text: md, author: 'assistant' },
        ])
        // Artefakt in die DB-History → Chat kann sich in Folgefragen darauf beziehen.
        api.appendMessage(threadId, { role: 'assistant', text: md, author: 'assistant' }).catch(() => {})
      }
      setActiveFormId(null)
      // persistierter Assessment-Knoten → Graph neu laden
      if (activeClient) api.graph(activeClient.id).then(setGraph).catch(() => {})
    },
    [patchMessages, activeClient],
  )

  const dispatchChat = useCallback(
    (text: string) => {
      if (busyRef.current) {
        queueRef.current.push({ id: uid('q'), text })
        syncQueued()
      } else {
        void runSend(text)
      }
    },
    [runSend, syncQueued],
  )

  // Orchestrator-Route graph_ingest: Freitext → geerdete Extraktion → in den Tenant-Graph.
  const startCapture = useCallback(
    async (text: string) => {
      const threadId = ensureThread()
      patchMessages(threadId, (arr) => [...arr, { id: uid('u'), role: 'user', text, author: meEmail }])
      api.appendMessage(threadId, { role: 'user', text, author: meEmail }).catch(() => {})
      try {
        const res = await api.capture(text)
        const added = res?.added ?? []
        if (res?.ok && added.length > 0) {
          const lines = added.map((a) => `• **${a.label}** _(${a.type})_`).join('\n')
          const head =
            t('app.capture_recorded', { count: added.length }) +
            (res.edges ? t('app.capture_edges_suffix', { count: res.edges }) : '')
          const msg =
            `${head}:\n\n${lines}\n\n` +
            (res.provenance ? t('app.capture_provenance', { provenance: res.provenance }) + '\n\n' : '') +
            t('app.capture_more')
          patchMessages(threadId, (arr) => [...arr, { id: uid('a'), role: 'assistant', text: msg, author: 'assistant' }])
          api.appendMessage(threadId, { role: 'assistant', text: msg, author: 'assistant' }).catch(() => {})
          setCaptureMode(true)
          if (activeClient) api.graph(activeClient.id).then(setGraph).catch(() => {})
        } else {
          const ask = t('app.capture_prompt')
          patchMessages(threadId, (arr) => [...arr, { id: uid('a'), role: 'assistant', text: ask, author: 'assistant' }])
          api.appendMessage(threadId, { role: 'assistant', text: ask, author: 'assistant' }).catch(() => {})
          setCaptureMode(true)
        }
      } catch {
        setCaptureMode(false)
        dispatchChat(text)
      }
    },
    [ensureThread, patchMessages, meEmail, activeClient, dispatchChat],
  )

  // Benannten Fach-Agenten (Persona) direkt im Chat konsultieren (A2A + Belege + Freigabe-Gate).
  const startDomainAgent = useCallback(
    async (agentId: string, agentName: string, question: string) => {
      if (!activeClient || !question.trim()) return
      const tid = ensureThread()
      const shown = `@${agentName} ${question}`
      const pendingId = uid('a')
      patchMessages(tid, (arr) => [
        ...arr,
        { id: uid('u'), role: 'user', text: shown, author: meEmail },
        { id: pendingId, role: 'assistant', text: '', pending: true, author: agentName },
      ])
      api.appendMessage(tid, { role: 'user', text: shown, author: meEmail }).catch(() => {})
      try {
        const d = await api.agentConsult(agentId, question)
        const others = (d.contributions || []).slice(1).map((c: any) => c.name).filter(Boolean)
        const header = others.length
          ? `**${d.agent?.name || agentName}** · ${t('app.consulted', { names: others.join(', ') })}\n\n`
          : `**${d.agent?.name || agentName}**\n\n`
        const text = header + (d.answer || t('app.empty_answer'))
        const sources = (d.provenance || []).map((p: any) => ({
          id: p.source_id || uid('s'), label: p.claim || '', type: p.source_type || 'Fact',
          props: { snippet: p.snippet }, provenance: p.by_agent || p.provenance || '',
        }))
        const env: any = {
          intent: 'agent', route: 'engine', result_text: text, sources, artifact: null,
          graph_delta: { nodes: [], edges: [] }, highlight: [], trace: [], provider: 'gemini',
          model: '', grounding: 'gedaechtnis', action: d.pending_action || undefined, suggestions: [],
        }
        patchMessages(tid, (arr) =>
          arr.map((m) => (m.id === pendingId ? { ...m, pending: false, text, envelope: env } : m)))
        api.appendMessage(tid, { role: 'assistant', text, author: d.agent?.name || agentName }).catch(() => {})
      } catch (e: any) {
        patchMessages(tid, (arr) =>
          arr.map((m) => (m.id === pendingId
            ? { ...m, pending: false, text: t('app.domain_agent_unreachable', { error: e?.message || t('app.error_generic') }) }
            : m)))
      }
    },
    [activeClient, ensureThread, patchMessages, meEmail],
  )

  // Erkennt „@Name <Frage>" → passenden Fach-Agenten (per Name ODER Slug), sonst null.
  const matchDomainAgent = useCallback(
    (text: string): { agentId: string; name: string; question: string } | null => {
      const m = text.match(/^@([A-Za-zÄÖÜäöü:.\-]+)\s+([\s\S]+)$/)
      if (!m) return null
      const key = m[1].toLowerCase()
      const a = domainAgents.find(
        (x) => (x.name || '').toLowerCase() === key ||
               (x.id || '').toLowerCase() === key ||
               (x.id || '').toLowerCase() === `agent-${key}`)
      return a ? { agentId: a.id, name: a.name, question: m[2].trim() } : null
    },
    [domainAgents],
  )

  const send = useCallback(
    (text: string) => {
      if (!text.trim() || !activeClient) return
      // Fach-Agent per „@Name <Frage>" (aus der „/"-Palette oder direkt getippt) hat Vorrang.
      const da = matchDomainAgent(text)
      if (da) {
        if (captureMode) setCaptureMode(false)
        void startDomainAgent(da.agentId, da.name, da.question)
        return
      }
      // Agent-Start hat Vorrang vor Formularen. Ist das Ziel erkennbar, läuft der Agent SOFORT
      // (kein Button/Panel, kein erneutes Tippen) — im aktuellen Thread, also mit Kontext/Verlauf.
      // Fehlt das Ziel, geht es an /ask (das per CTA nachfragt).
      if (isAgentStart(text)) {
        if (captureMode) setCaptureMode(false)
        const parsed = parseAgent(text)
        if (parsed && parsed.goal) {
          const tid = ensureThread()
          patchMessages(tid, (arr) => [...arr, { id: uid('u'), role: 'user', text, author: meEmail }])
          api.appendMessage(tid, { role: 'user', text, author: meEmail }).catch(() => {})
          startAgentRef.current?.(parsed.agentId, parsed.goal)
        } else {
          dispatchChat(text)
        }
        return
      }
      // Knoten-Aufnahme aktiv (graph_ingest): jede Nachricht ist Erfassungs-Input.
      if (captureMode) {
        const low = text.trim().toLowerCase().replace(/[.!]+$/, '')
        if (['fertig', 'stopp', 'stop', 'ende', 'abbrechen', 'nein danke', 'passt', 'das wars', "das war's"].includes(low)) {
          setCaptureMode(false)
          const tid = ensureThread()
          const done = t('app.capture_done')
          patchMessages(tid, (arr) => [...arr, { id: uid('a'), role: 'assistant', text: done, author: 'assistant' }])
          api.appendMessage(tid, { role: 'assistant', text: done, author: 'assistant' }).catch(() => {})
          return
        }
        const fmid = matchForm(text) // erlaubt Ausbruch in ein Formular
        if (fmid) {
          setCaptureMode(false)
          startForm(fmid, text)
          return
        }
        void startCapture(text)
        return
      }
      // Tier 1 — sofortiger, deterministischer Form-Match (Bindestrich/Akzente egal).
      const fid = matchForm(text)
      if (fid) {
        startForm(fid, text)
        return
      }
      // Tier 2 — Tenant-Orchestrator (Engine). Fängt Paraphrasen („hilf mir den Report auszufüllen").
      // Fällt bei Nicht-Erreichbarkeit/keinem Form-Intent auf den normalen Chat-/Wissenspfad zurück.
      void (async () => {
        try {
          const dec = await api.route(text)
          if (dec?.route === 'form' && dec.form_id && forms.some((f) => f.id === dec.form_id)) {
            startForm(dec.form_id, text)
            return
          }
          if (dec?.route === 'graph_ingest') {
            void startCapture(text)
            return
          }
        } catch {
          /* Orchestrator nicht erreichbar → normaler Chat-Pfad */
        }
        dispatchChat(text)
      })()
    },
    [activeClient, captureMode, matchForm, startForm, startCapture, forms,
     dispatchChat, ensureThread, patchMessages, meEmail, matchDomainAgent, startDomainAgent],
  )

  // E11.1: laufende Antwort zurückrufen (Stream abbrechen).
  const cancelInFlight = useCallback(() => {
    abortRef.current?.abort()
  }, [])
  // E11.1: eine eingereihte (noch nicht gestartete) Nachricht wieder entfernen.
  const recallQueued = useCallback((id: string) => {
    queueRef.current = queueRef.current.filter((q) => q.id !== id)
    syncQueued()
  }, [])

  // ---- Tenant-Branding (config-driven Whitelabel) ----
  // Titel + Marken-Farben + Favicon aus /tenant/context. Läuft schon vor dem Login,
  // damit c:node vs. Beispiel vom ersten Frame an unterschiedlich wirken.
  useEffect(() => {
    api
      .tenantContext()
      .then((t) => {
        if (t?.name) document.title = t.name
        const b: any = t?.brand ?? {}
        const wm = b.wordmark || t?.name || 'c:node'
        setTenantWordmark(wm)
        if (t?.id) setTenantScope({ id: t.id, name: t.name || wm, mode: (t as any).mode || 'dedicated' })
        setBrand({ wordmark: wm, assistantName: b.assistant_name || t?.name || wm,
                   assistantRole: b.assistant_role || '', logoSvg: b.logo_svg || '' })
        const root = document.documentElement
        // Primär-/Sekundärfarbe → Theme-Tokens (RGB-Triplet); färbt die GANZE UI + das Logo.
        const trip = (hex?: string): string | null => {
          const m = /^#?([0-9a-f]{6})$/i.exec((hex || '').trim())
          if (!m) return null
          const n = parseInt(m[1], 16)
          return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`
        }
        const prim = trip(b.primary)
        const sec = trip(b.secondary || b.accent)
        if (prim) root.style.setProperty('--c-primary', prim)
        if (sec) root.style.setProperty('--c-secondary', sec)
        if (b.favicon) {
          const link =
            (document.querySelector("link[rel='icon']") as HTMLLinkElement) ||
            document.createElement('link')
          link.rel = 'icon'
          link.href =
            'data:image/svg+xml,' +
            encodeURIComponent(
              `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">${b.favicon}</text></svg>`,
            )
          document.head.appendChild(link)
        }
      })
      .catch(() => {})
  }, [])

  // ---- E7 Agenten: Katalog laden (einmal) + Läufe je Thread ----
  useEffect(() => {
    if (authState !== 'in') return
    api.agents().then(setAgentCatalog).catch(() => setAgentCatalog([]))
    // Benannte Fach-Agenten (Personas) für „/"-Palette + @Name-Routing.
    api.agentCards()
      .then((d) => setDomainAgents((d.agents || []).filter((a: any) => a.status === 'live')))
      .catch(() => setDomainAgents([]))
  }, [authState])

  useEffect(() => {
    if (authState !== 'in' || !activeThreadId) {
      setAgentRuns([])
      return
    }
    api.agentRuns(activeThreadId).then(setAgentRuns).catch(() => setAgentRuns([]))
  }, [authState, activeThreadId, railRefresh])

  const startAgent = useCallback(
    async (agentId: string, goal: string) => {
      if (!goal.trim() || !activeClient) return
      const threadId = ensureThread()
      const spec = agentCatalog.find((a) => a.id === agentId)
      setRailOpen(true) // rechte Sidebar auf Thread-Ebene aufklappen (Agent startet)
      // optimistischer Live-Lauf, bis das plan-Event kommt
      setLiveRun({
        id: 'pending', agent: agentId, agent_name: spec?.name || agentId, goal,
        status: 'running', thread_id: threadId, steps: [],
      })
      const patchStep = (idx: number, patch: Partial<AgentStep>) =>
        setLiveRun((r) =>
          r ? { ...r, steps: r.steps.map((s) => (s.idx === idx ? { ...s, ...patch } : s)) } : r,
        )
      try {
        await api.runAgent(
          agentId,
          { goal, thread_id: threadId, provider },
          {
            onPlan: (p) =>
              setLiveRun({
                id: p.run_id, agent: p.agent, agent_name: p.agent_name, goal: p.goal,
                status: 'running', thread_id: threadId, steps: p.steps,
              }),
            onStep: (s) =>
              patchStep(s.idx, { status: s.status, summary: s.summary, provenance: s.provenance }),
            onDone: (d) => {
              setLiveRun((r) => (r ? { ...r, status: 'done', result: d.result_text } : r))
              if (d.result_text) {
                // Action-Agenten (Outreach) liefern ActionCards → Envelope mit action,
                // damit ChatView die Bestätigungs-Karte rendert (Draft→Freigabe).
                const mkEnv = (action: any, text = ''): Envelope =>
                  ({
                    intent: 'action', route: 'agent', result_text: text,
                    sources: [], artifact: null, graph_delta: { nodes: [], edges: [] },
                    highlight: [], trace: [], provider: d.provider || 'ollama', model: '',
                    action,
                  } as Envelope)
                patchMessages(threadId, (arr) => [
                  ...arr,
                  {
                    id: uid('a'), role: 'assistant', text: d.result_text, author: 'c:node',
                    envelope: d.action ? mkEnv(d.action, d.result_text) : undefined,
                  },
                ])
                // Zweite Karte (z.B. Kalender-Slot) als eigene Nachricht.
                if (d.calendar_action) {
                  patchMessages(threadId, (arr) => [
                    ...arr,
                    { id: uid('a'), role: 'assistant', text: '', author: 'c:node', envelope: mkEnv(d.calendar_action) },
                  ])
                }
              }
              // Scout → Outreach-Handoff: Folge-Aktionen als klickbare Vorschläge zeigen.
              if (Array.isArray(d.suggestions) && d.suggestions.length && !d.action) {
                patchMessages(threadId, (arr) =>
                  arr.map((m, i) =>
                    i === arr.length - 1 && m.role === 'assistant'
                      ? { ...m, envelope: { ...(m.envelope || {} as any), suggestions: d.suggestions } }
                      : m,
                  ),
                )
              }
              if (d.artifact) setArtifact(d.artifact)
              // Scout schreibt Knoten → Graph live mitwachsen lassen + highlighten.
              if (d.graph_delta) setGraph((g) => mergeGraph(g, d.graph_delta))
              if (Array.isArray(d.sources) && d.sources.length) {
                setHighlight(d.sources.map((s: any) => s.id).filter(Boolean))
              }
              // persistierte Läufe + Rail (Artefakte/Dateien) auffrischen
              setRailRefresh((k) => k + 1)
              setTimeout(() => setLiveRun(null), 1200)
            },
            onError: (e) => setToast(t('app.agent_error', { error: e.error || t('app.unknown') })),
          },
        )
      } catch (e: any) {
        if (e?.status === 402) {
          // Bezahltes Feature (z.B. Outreach) in der Free-Sandbox → Upsell statt Fehler.
          setCapHit(true)
          api.entitlement().then(setEntitlement).catch(() => {})
          setLiveRun(null)
          return
        }
        setToast(t('app.agent_start_failed', { error: e?.message || t('app.gateway_fallback') }))
        setLiveRun(null)
      }
    },
    [activeClient, agentCatalog, provider, ensureThread, patchMessages],
  )
  useEffect(() => {
    startAgentRef.current = startAgent
  }, [startAgent])

  // Agent aus der rechten Sidebar wählen → Composer mit „starte den <Agent> zu " vorbefüllen
  // (Start läuft über die saubere Inline-Intent-Route beim Senden — kein statisches Input-Feld).
  const pickAgent = useCallback(
    (agentId: string) => {
      const spec = agentCatalog.find((a) => a.id === agentId)
      setComposerDraft(t('app.agent_draft', { name: spec?.name || agentId }))
    },
    [agentCatalog],
  )

  // ---- ingest (files or URL, with target levels) ----
  const openIngest = useCallback((files?: File[]) => {
    setIngestFiles(files ?? [])
    setIngestOpen(true)
  }, [])

  const onIngest = useCallback(
    async (s: IngestSubmit) => {
      if (!activeClient) return
      setIngestBusy(true)
      // Admin proposing Market: ingest to client only, then submit a Promotion for each source.
      const directLevels = (s.marketAsProposal ? s.levels.filter((l) => l !== 'market') : s.levels)
      const levels = directLevels.length ? directLevels : (['client'] as const)
      try {
        if (s.mode === 'file' && s.files?.length) {
          // Datei-Upload → Bibliothek (assets): dort abgelegt, extrahiert UND in den
          // Graphen eingelesen. Mit thread_id getaggt → erscheint in der rechten Thread-Sidebar.
          const tid = ensureThread()
          const r = await api.libraryUpload(s.files, activeClient.id, tid)
          const n = r?.ingested ?? s.files.length
          // Graph frisch nachladen (Library-Upload liefert kein graph_delta zurück).
          api.graph(activeClient.id).then(setGraph).catch(() => {})
          setRailRefresh((k) => k + 1) // rechte Thread-Sidebar (Dateien) aktualisieren
          setRailOpen(true) // auf Thread-Ebene aufklappen, damit die neue Datei sichtbar ist
          setToast(t('app.library_stored', { count: n }))
          setIngestOpen(false)
          // Thread-Turn: Inhalt referenzieren und in den bisherigen Kontext einordnen.
          const uploaded: any[] = Array.isArray(r?.files) ? r.files : []
          const names = uploaded.map((f) => f.title || f.name).filter(Boolean)
          const blocks = uploaded.slice(0, 3).map((f) => {
            const title = f.title || f.name || t('app.file_fallback')
            const ex = String(f.excerpt || '').trim()
            return ex
              ? t('app.ingest_block_excerpt', { title, excerpt: ex.slice(0, 700) })
              : t('app.ingest_block_no_text', { title })
          })
          const header =
            names.length > 1
              ? t('app.ingest_header_multi', { count: names.length })
              : t('app.ingest_header_single', { name: names[0] ?? t('app.upload_fallback') })
          send(
            `${header}\n\n${blocks.join('\n\n')}\n\n${t('app.ingest_instruction')}`,
          )
          return
        }
        // URL-Mode → Scrape (holt Seite, extrahiert, ingestet).
        const env: Envelope = await api.scrape(s.url as string, activeClient.id, levels as any)
        if (env?.graph_delta) setGraph((g) => mergeGraph(g, env.graph_delta))
        if (env?.highlight?.length) setHighlight(env.highlight)
        if (s.marketAsProposal) {
          const ids = (env?.sources || []).map((x) => x.id).filter(Boolean)
          await Promise.allSettled(ids.map((id) => api.proposePromotion(id)))
          setToast(
            ids.length
              ? t('app.market_proposal_ok')
              : t('app.market_proposal_no_id'),
          )
        } else {
          setToast(t('app.ingested', { levels: levels.join('+'), source: s.url || t('app.source_fallback') }))
        }
        setIngestOpen(false)
      } catch {
        // Fallback: route through /ask so the demo stays stable if /ingest|/scrape is absent.
        setIngestOpen(false)
        const label = s.url || s.files?.map((f) => f.name).join(', ') || t('app.source_fallback')
        setToast(t('app.ingest_unavailable'))
        send(
          t('app.ingest_via_chat', { levels: s.levels.join('+'), label }),
        )
      } finally {
        setIngestBusy(false)
      }
    },
    [activeClient, send],
  )

  const onNewThread = useCallback(() => {
    setActiveThreadId(null)
    setArtifact(null)
    setHighlight([])
    setOnboardingHint(null)
  }, [])

  // ---- v3: onboarding hint for an empty thread ----
  useEffect(() => {
    if (authState !== 'in') return
    if (!activeThreadId || messages.length > 0) {
      setOnboardingHint(null)
      return
    }
    api.onboarding(activeThreadId).then(setOnboardingHint).catch(() => setOnboardingHint(null))
  }, [authState, activeThreadId, messages.length])

  // ---- v3: folder CRUD (optimistic + tolerant) ----
  const onCreateFolder = useCallback((name: string) => {
    const tmp: Folder = { id: uid('f'), name }
    setFolders((fs) => [...fs, tmp])
    api
      .createFolder(name)
      .then((real) => {
        if (real?.id) setFolders((fs) => fs.map((f) => (f.id === tmp.id ? { ...tmp, ...real } : f)))
      })
      .catch(() => {
        /* keep local folder for the demo */
      })
  }, [])

  const onRenameFolder = useCallback((id: string, name: string) => {
    setFolders((fs) => fs.map((f) => (f.id === id ? { ...f, name } : f)))
    api.renameFolder(id, name).catch(() => {})
  }, [])

  const onDeleteFolder = useCallback((id: string) => {
    setFolders((fs) => fs.filter((f) => f.id !== id))
    // threads in that folder become unfiled
    setThreads((ts) => ts.map((t) => (t.folder_id === id ? { ...t, folder_id: null } : t)))
    api.deleteFolder(id).catch(() => {})
  }, [])

  // ---- v3: thread rename / delete / move ----
  const onRenameThread = useCallback((id: string, title: string) => {
    setThreads((ts) => ts.map((t) => (t.id === id ? { ...t, title } : t)))
    api.updateThread(id, { title }).catch(() => {})
  }, [])

  const onDeleteThread = useCallback(
    (id: string) => {
      setThreads((ts) => ts.filter((t) => t.id !== id))
      setMsgByThread((m) => {
        const next = { ...m }
        delete next[id]
        return next
      })
      if (activeThreadId === id) setActiveThreadId(null)
      api.deleteThread(id).catch(() => {})
    },
    [activeThreadId],
  )

  const onMoveThread = useCallback((id: string, folderId: string | null) => {
    setThreads((ts) => ts.map((t) => (t.id === id ? { ...t, folder_id: folderId } : t)))
    api.updateThread(id, { folder_id: folderId }).catch(() => {})
  }, [])

  // ---- v3: thread visibility + members ----
  const onSetVisibility = useCallback((id: string, visibility: ThreadVisibility) => {
    setThreads((ts) => ts.map((t) => (t.id === id ? { ...t, visibility } : t)))
    api.updateThread(id, { visibility }).catch(() => {})
    setToast(visibility === 'team' ? t('app.visibility_team') : t('app.visibility_private'))
  }, [])

  const onSetMembers = useCallback((id: string, members: string[]) => {
    setThreads((ts) => ts.map((t) => (t.id === id ? { ...t, members } : t)))
    api.updateThread(id, { members }).catch(() => {})
  }, [])

  // ---- v3: notifications actions ----
  const onMarkNotifRead = useCallback((id: string) => {
    setNotifs((ns) => ns.map((n) => (n.id === id ? { ...n, read: true } : n)))
    setUnread((u) => Math.max(0, u - 1))
    api.markNotificationRead(id).catch(() => {})
  }, [])

  const onMarkAllNotifsRead = useCallback(() => {
    setNotifs((ns) => ns.map((n) => ({ ...n, read: true })))
    setUnread(0)
    api.markAllNotificationsRead().catch(() => {})
  }, [])

  // ---- v3: data-request / connector-suggestion escalation ----
  const requestData = useCallback(
    async (scope: 'scoped' | 'connector', connector?: string): Promise<boolean> => {
      try {
        await api.createDataRequest({
          scope,
          connector,
          thread_id: activeThreadId ?? undefined,
          note:
            scope === 'connector'
              ? t('app.data_request_connector_note', { client: activeClient?.name ?? t('app.client_fallback') })
              : t('app.data_request_scoped_note', { client: activeClient?.name ?? t('app.client_fallback') }),
        })
        setToast(
          scope === 'connector'
            ? t('app.escalation_connector_sent', { target: escalationTarget })
            : t('app.escalation_data_sent', { target: escalationTarget }),
        )
        loadNotifs()
        return true
      } catch {
        setToast(t('app.escalation_unavailable'))
        return false
      }
    },
    [activeThreadId, activeClient, escalationTarget, loadNotifs],
  )

  const openLibrary = useCallback(() => setShowLibrary(true), [])
  const openConnectorsSettings = useCallback(() => {
    setShowLibrary(false)
    setSettingsSection('connectors')
    setShowSettings(true)
  }, [])

  const onShare = useCallback(async () => {
    if (!activeThreadId) {
      setToast(t('app.no_active_thread_share'))
      return
    }
    try {
      const { url, role } = await api.share(activeThreadId)
      try {
        await navigator.clipboard.writeText(url)
        setToast(t('app.share_link_copied', { role, url }))
      } catch {
        setToast(t('app.share_link', { role, url }))
      }
    } catch {
      setToast(t('app.share_unavailable'))
    }
  }, [activeThreadId])

  const onProviderDefault = useCallback((p: Provider) => {
    setProvider(p)
    try {
      localStorage.setItem(PROVIDER_KEY, p)
    } catch {
      /* ignore */
    }
  }, [])

  const onLogout = useCallback(async () => {
    await api.logout()
    setMe(null)
    setAuthState('out')
    // reset session-scoped UI
    setThreads([])
    setActiveThreadId(null)
    setMsgByThread({})
    setGraph({ nodes: [], edges: [] })
    setArtifact(null)
    setShowSettings(false)
    setShowGraph(false)
  }, [])

  const runNba = useCallback((n: NBA) => send(n.prompt || n.title), [send])

  const clientName = useMemo(() => activeClient?.name, [activeClient])
  const activeThread = useMemo(
    () => threads.find((t) => t.id === activeThreadId) ?? null,
    [threads, activeThreadId],
  )
  const canManageThread =
    !!activeThread && (admin || !activeThread.owner || activeThread.owner === meEmail)
  const lowData = onboardingHint?.low_data ?? graph.nodes.length < 5
  const lastResetRef = useRef<string | null>(null)
  useEffect(() => {
    if (activeThreadId && lastResetRef.current !== activeThreadId) {
      lastResetRef.current = activeThreadId
      setArtifact(null)
    }
  }, [activeThreadId])

  // ---- auth gates ----
  if (authState === 'checking') {
    return (
      <div className="h-full flex items-center justify-center bg-ink text-muted">
        <svg width="22" height="22" viewBox="0 0 16 16" className="animate-spin text-primary">
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" fill="none" opacity="0.3" />
          <path d="M8 2a6 6 0 016 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />
        </svg>
      </div>
    )
  }
  if (authState === 'out')
    return showLanding
      ? <Landing onStart={() => setShowLanding(false)} />
      : <LoginScreen onAuthed={loadMe} />

  return (
    <div className="h-full flex bg-ink text-paper">
      {/*
        Sidebar nur auf Desktop (≥ md): `hidden` blendet sie auf dem Smartphone komplett aus,
        `md:contents` lässt sie ab md exakt wie zuvor als persistente Spalte fließen
        (Desktop pixel-identisch — kein Wrapper-Box im Flow). Auf mobil ersetzt die
        Bottom-Nav + der Chats-Screen + das Header-Avatar-Menü ihre Funktionen.
      */}
      <div className="hidden md:contents">
      <Sidebar
        open={sidebarOpen}
        threads={threads}
        folders={folders}
        activeThreadId={activeThreadId}
        onSelectThread={(id) => setActiveThreadId(id)}
        onNewThread={onNewThread}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
        onOpenSearch={() => setSearchOpen(true)}
        onCreateFolder={onCreateFolder}
        onRenameFolder={onRenameFolder}
        onDeleteFolder={onDeleteFolder}
        onRenameThread={onRenameThread}
        onDeleteThread={onDeleteThread}
        onMoveThread={onMoveThread}
        onArea={(p) => send(p)}
        me={me}
        provider={provider}
        model={currentModel || models.ollama?.models?.[0] || ''}
        claudeReady={claudeReady}
        geminiReady={geminiReady}
        onProvider={onProviderDefault}
        onOpenGraph={() => {
          setShowGraph((v) => !v)
          if (activeClient) api.graph(activeClient.id).then(setGraph).catch(() => {})
        }}
        onOpenLibrary={openLibrary}
        onOpenNotifications={() => setShowNotifications(true)}
        onOpenSetup={() => setShowOwnerSetup(true)}
        canSetup={!!ownerSetup?.can_edit}
        unread={unread}
        onSettings={(section) => {
          setSettingsSection((section as typeof settingsSection) || 'profile')
          setShowSettings(true)
        }}
        onLogout={onLogout}
        canSwitchClient={superAdmin && tenantScope?.mode !== 'dedicated' && clients.length > 1}
        clients={clients}
        activeClient={activeClient}
        onClient={setActiveClient}
        wordmark={tenantWordmark}
        sandbox={!!entitlement?.public_demo}
      />
      </div>

      {/*
        Vertikale Spalte neben der Sidebar: Upsell-Strip oben, Chat-Zeile darunter.
        Mobil: unten Platz freihalten für die fixierte BottomNav (h-14 + Safe-Area).
      */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0 pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0">
      {/* Schlanke Mobile-Topbar (< md): Marke + Suche + Avatar-Menü (Logo/Suche/Konto liegen sonst in der Sidebar). */}
      <div className="md:hidden flex items-center gap-1 px-3 h-12 shrink-0 border-b border-line bg-surface">
        <CnodeLogo className="min-w-0" wordmark={tenantWordmark} />
        <button
          onClick={() => setSearchOpen(true)}
          title={t('common.search')}
          aria-label={t('common.search')}
          className="ml-auto shrink-0 w-11 h-11 grid place-items-center rounded-lg text-muted hover:text-paper hover:bg-surface2 transition"
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
        </button>
        <MobileHeaderMenu
          me={me}
          provider={provider}
          model={currentModel || models.ollama?.models?.[0] || ''}
          claudeReady={claudeReady}
          geminiReady={geminiReady}
          onProviderDefault={onProviderDefault}
          onSettings={(section) => {
            setSettingsSection((section as typeof settingsSection) || 'profile')
            setShowSettings(true)
          }}
          onLogout={onLogout}
          sandbox={!!entitlement?.public_demo}
        />
      </div>
      <UpgradeBanner
        entitlement={entitlement}
        capHit={capHit}
        onDismissCap={() => setCapHit(false)}
        openSignal={upgradeSignal}
      />

      <div className="flex-1 flex min-h-0">
        <main className="flex-1 flex min-w-0">
          <div className="flex-1 flex flex-col min-w-0">
            {activeThread && (
              <ThreadHeader
                thread={activeThread}
                meEmail={meEmail}
                canManage={canManageThread}
                tenantEmails={tenantEmails}
                onSetVisibility={(v) => onSetVisibility(activeThread.id, v)}
                onSetMembers={(m) => onSetMembers(activeThread.id, m)}
                onShare={onShare}
                railOpen={railOpen}
                onToggleRail={() => setRailOpen((v) => !v)}
              />
            )}
            <div className="flex-1 min-h-0">
              <ChatView
                messages={messages}
                onPrompt={send}
                nba={nba}
                onRunNba={runNba}
                runs={
                  // Inline im Chat NUR der aktuell laufende Lauf (an der jetzigen Stelle).
                  // Fertige Läufe stehen bereits als Abschluss-Nachricht chronologisch im
                  // Verlauf — kein auflaufender Stapel fertiger Agenten am Chat-Ende.
                  liveRun && liveRun.status === 'running' ? [liveRun] : []
                }
                onOpenRuns={() => setRailOpen(true)}
                queued={queued}
                onRecallQueued={recallQueued}
                onOpenSource={(s) => {
                  // Quelle im Gedächtnis direkt gehighlightet + angezoomt anzeigen.
                  setHighlight([s.id])
                  setGraphFocus(s.id)
                  setShowGraph(true)
                }}
                onCta={(cta) => {
                  if (cta.type === 'upgrade') return setUpgradeSignal((n) => n + 1)
                  if (cta.type === 'connect') return openConnectorsSettings()
                  if (cta.type === 'agent' && cta.agent) {
                    // Echte Tool-Bindung (F4): goal vorhanden → Agent sofort starten;
                    // sonst Composer mit „starte den <Agent> zu " vorbefüllen (Inline-Route).
                    if (cta.goal && cta.goal.trim()) return startAgent(cta.agent, cta.goal.trim())
                    return pickAgent(cta.agent)
                  }
                  if (cta.type === 'research') {
                    const lastUser = [...messages].reverse().find((m) => m.role === 'user')?.text || ''
                    return send(
                      `Recherchiere dazu im Web mit wissenschaftlichen/offiziellen Quellen: ${lastUser}`,
                    )
                  }
                  return openIngest()
                }}
                activeFormId={activeFormId}
                forms={forms}
                onStartForm={(id) => startForm(id, forms.find((f) => f.id === id)?.title || id)}
                onFormComplete={onFormComplete}
                onFormCancel={() => setActiveFormId(null)}
                onboarding={
                  <Onboarding
                    hint={onboardingHint}
                    lowData={lowData}
                    escalationTarget={escalationTarget}
                    onGeneral={() => {}}
                    onScoped={() => {}}
                    onRequestData={() => requestData('scoped')}
                    onSuggestConnector={() => requestData('connector', 'suggested')}
                  />
                }
              />
            </div>
            <Composer
              onSend={send}
              onFiles={(files) => openIngest(files)}
              onOpenIngest={() => openIngest()}
              onNotice={(msg) => setToast(msg)}
              busy={busy}
              disabled={!activeClient}
              onStop={cancelInFlight}
              agentCatalog={agentCatalog}
              domainAgents={domainAgents}
              draft={composerDraft}
              onDraftConsumed={() => setComposerDraft(null)}
              sandbox={!!entitlement?.public_demo}
            />
          </div>

          {artifact ? (
            <ArtifactPanel
              artifact={artifact}
              onClose={() => setArtifact(null)}
              onShare={onShare}
              tenantId={me?.tenant?.id}
              onNotice={setToast}
            />
          ) : (
            // Breiten-Wrapper: Desktop = smoothes Ein-/Ausklappen der rechten Thread-Sidebar.
            // Mobil (< md): Vollbild-Overlay (fixed inset-0) statt vw-Bruchteil-Spalte.
            <div
              className={`md:h-full md:overflow-hidden md:shrink-0 md:transition-[width] md:duration-300 md:ease-out ${
                railOpen
                  ? 'fixed inset-0 z-40 md:static md:z-auto md:w-[300px] md:max-w-[38vw]'
                  : 'hidden md:block md:w-0'
              }`}
            >
              <RightRail
                threadId={activeThreadId}
                clientId={activeClient?.id}
                refreshKey={railRefresh}
                onOpenArtifact={(a) => setArtifact(a)}
                onClose={() => setRailOpen(false)}
                onNotice={setToast}
                agentRuns={agentRuns}
                liveRun={liveRun}
              />
            </div>
          )}
        </main>
      </div>
      </div>

      {/* Sticky Bottom-Nav (< md): ersetzt die Sidebar-Navigation wie in einer nativen App. */}
      <BottomNav
        onOpenChats={() => setChatsOpen(true)}
        onOpenGraph={() => {
          setShowGraph((v) => !v)
          if (activeClient) api.graph(activeClient.id).then(setGraph).catch(() => {})
        }}
        onNewThread={onNewThread}
        onOpenLibrary={openLibrary}
        onOpenNotifications={() => setShowNotifications(true)}
        unread={unread}
        activeChats={chatsOpen}
        activeGraph={showGraph}
        activeLibrary={showLibrary}
        activeNotifications={showNotifications}
      />

      {/* Mobile-Vollbild: Chats/Ordner-Verwaltung (< md), ersetzt den früheren Sidebar-Drawer. */}
      {chatsOpen && (
        <ChatsScreen
          threads={threads}
          folders={folders}
          activeThreadId={activeThreadId}
          onSelectThread={(id) => { setActiveThreadId(id); setChatsOpen(false) }}
          onNewThread={() => { onNewThread(); setChatsOpen(false) }}
          onCreateFolder={onCreateFolder}
          onRenameFolder={onRenameFolder}
          onDeleteFolder={onDeleteFolder}
          onRenameThread={onRenameThread}
          onDeleteThread={onDeleteThread}
          onMoveThread={onMoveThread}
          onClose={() => setChatsOpen(false)}
        />
      )}

      {searchOpen && (
        <GlobalSearch
          threads={threads}
          folders={folders}
          onClose={() => setSearchOpen(false)}
          onSelect={(id) => {
            setActiveThreadId(id)
            setSearchOpen(false)
          }}
        />
      )}

      {showGraph && (
        <GraphOverlay
          graph={graph}
          highlight={highlight}
          clientName={clientName}
          focusId={graphFocus}
          onClose={() => {
            setShowGraph(false)
            setGraphFocus(null)
          }}
        />
      )}

      {showSettings && me && (
        <SettingsOverlay
          me={me}
          provider={provider}
          model={currentModel}
          claudeReady={claudeReady}
          geminiReady={geminiReady}
          onProviderDefault={onProviderDefault}
          initialSection={settingsSection}
          onClose={() => setShowSettings(false)}
          sandbox={!!entitlement?.public_demo}
        />
      )}

      {showLibrary && (
        <LibraryPage
          clientId={activeClient?.id}
          admin={admin}
          onOpenConnectors={openConnectorsSettings}
          onNotice={setToast}
          onClose={() => setShowLibrary(false)}
          sandbox={!!entitlement?.public_demo}
        />
      )}

      {activeClient && ownerSetup?.can_edit && (!ownerSetup.completed || showOwnerSetup) && (
        <OwnerSetup
          clientId={activeClient.id}
          tenantName={tenantScope?.name || activeClient.name}
          initialName={ownerSetup.org_name}
          initialProfile={ownerSetup.org_profile}
          initialSources={(ownerSetup.sources as { kind: 'url' | 'text'; value: string }[]) || []}
          mandatory={!ownerSetup.completed}
          onGraphRefresh={() => api.graph(activeClient.id).then(setGraph).catch(() => {})}
          onClose={() => {
            setShowOwnerSetup(false)
            api.tenantSetup().then(setOwnerSetup).catch(() => {})
          }}
        />
      )}

      {showNotifications && (
        <NotificationsPage
          items={notifs}
          loading={notifsLoading}
          onMarkRead={onMarkNotifRead}
          onMarkAllRead={onMarkAllNotifsRead}
          onRefresh={loadNotifs}
          onClose={() => setShowNotifications(false)}
        />
      )}

      <IngestDialog
        open={ingestOpen}
        me={me}
        clientName={clientName}
        initialFiles={ingestFiles}
        busy={ingestBusy}
        onSubmit={onIngest}
        onClose={() => setIngestOpen(false)}
        sandbox={!!entitlement?.public_demo}
      />

      {toast && <Toast text={toast} onClose={() => setToast(null)} />}
    </div>
  )
}
