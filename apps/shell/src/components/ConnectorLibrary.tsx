import { useCallback, useEffect, useMemo, useState } from 'react'
import { GATEWAY } from '../config'
import { api } from '../api'
import { useT } from '../i18n'
import ConnectorLogo from './ConnectorLogo'
import type { GoogleStatus, PluginDTO } from '../types'
import {
  CONNECTORS,
  connAuthLabel,
  connDesc,
  connName,
  loadEnabledIds,
  saveEnabledIds,
  type Connector,
} from '../connectors'

type Filter = 'input' | 'output' | 'all'

// Diese Connectoren nutzen den echten Google-OAuth-Flow (gmail.readonly + drive).
const GOOGLE_OAUTH_IDS = new Set(['google_drive', 'gmail', 'gcal'])

// Live-Zustand einer Google-Karte: aus dem Backend-Status abgeleitet.
type GoogleState = 'connected' | 'connect' | 'setup'

// Kuratierte Connector-Bibliothek: Karten-Grid, gruppiert in Eingang / Ausgang.
// Google-Karten spiegeln den ECHTEN Verbindungsstatus (Backend), alle anderen den
// Enable-Zustand pro Mandant in localStorage.
export default function ConnectorLibrary({
  tenantId,
  filter = 'all',
  compact = false,
  readOnly = false,
  sandbox = false,
  onNotice,
}: {
  tenantId?: string
  filter?: Filter
  compact?: boolean
  readOnly?: boolean
  // Öffentliche Sandbox: nur Datei-/URL-Connectoren (auth==='none') sind nutzbar,
  // alle Konto-Integrationen (oauth/apikey) sind gesperrt.
  sandbox?: boolean
  onNotice?: (msg: string) => void
}) {
  const t = useT()
  const [enabled, setEnabled] = useState<Set<string>>(() => new Set(loadEnabledIds(tenantId)))
  const [note, setNote] = useState<string | null>(null)
  const [google, setGoogle] = useState<GoogleStatus | null>(null)
  const [busyGoogle, setBusyGoogle] = useState(false)
  const [microsoft, setMicrosoft] = useState<GoogleStatus | null>(null)
  const [busyMs, setBusyMs] = useState(false)
  // Plattform-Plugins des Tenants (Connectoren/Formate/Agenten/Systeme) aus der Registry.
  const [plugins, setPlugins] = useState<PluginDTO[]>([])
  useEffect(() => {
    api.plugins().then(setPlugins).catch(() => setPlugins([]))
  }, [])

  const notify = useCallback(
    (msg: string) => {
      if (onNotice) onNotice(msg)
      else {
        setNote(msg)
        window.setTimeout(() => setNote((n) => (n === msg ? null : n)), 3200)
      }
    },
    [onNotice],
  )

  // Echten Google-Status laden (verbunden? konfiguriert? welche Mail?).
  const refreshGoogle = useCallback(() => {
    api
      .googleStatus()
      .then(setGoogle)
      .catch(() => setGoogle({ ok: false, connected: false, configured: false } as GoogleStatus))
  }, [])

  useEffect(() => {
    refreshGoogle()
  }, [refreshGoogle])

  // Ableiten, in welchem Zustand die Google-Karten stehen.
  // 'setup' NUR wenn der Status geladen ist UND configured===false — sonst (auch beim
  // initialen Laden, wenn google===null) neutral 'connect', damit nichts „Setup nötig" aufblitzt.
  const googleState: GoogleState = google?.connected
    ? 'connected'
    : google && google.configured === false
    ? 'setup'
    : 'connect'
  const googleEmail = google?.email || undefined

  const connectGoogle = useCallback(() => {
    if (readOnly || sandbox) return
    if (googleState === 'setup') {
      notify(t('connectors.google_not_configured'))
      return
    }
    notify(t('connectors.redirect_google'))
    window.location.href = `${GATEWAY}/integrations/google/oauth/install`
  }, [readOnly, sandbox, googleState, notify, t])

  const disconnectGoogle = useCallback(() => {
    if (readOnly || busyGoogle) return
    setBusyGoogle(true)
    api
      .googleDisconnect()
      .then(() => {
        notify(t('connectors.google_disconnected'))
        refreshGoogle()
      })
      .catch(() => notify(t('connectors.disconnect_failed')))
      .finally(() => setBusyGoogle(false))
  }, [readOnly, busyGoogle, notify, refreshGoogle, t])

  // Microsoft / Outlook — parallel zu Google.
  const refreshMs = useCallback(() => {
    api.microsoftStatus().then(setMicrosoft)
      .catch(() => setMicrosoft({ ok: false, connected: false, configured: false } as GoogleStatus))
  }, [])
  useEffect(() => { refreshMs() }, [refreshMs])
  const msState: GoogleState = microsoft?.connected
    ? 'connected'
    : microsoft && microsoft.configured === false
    ? 'setup'
    : 'connect'
  const connectMs = useCallback(() => {
    if (readOnly || sandbox) return
    if (msState === 'setup') {
      notify(t('connectors.ms_not_configured'))
      return
    }
    notify(t('connectors.redirect_ms'))
    window.location.href = `${GATEWAY}/integrations/microsoft/oauth/install`
  }, [readOnly, sandbox, msState, notify, t])
  const disconnectMs = useCallback(() => {
    if (readOnly || busyMs) return
    setBusyMs(true)
    api.microsoftDisconnect().then(() => { notify(t('connectors.outlook_disconnected')); refreshMs() })
      .catch(() => notify(t('connectors.disconnect_failed'))).finally(() => setBusyMs(false))
  }, [readOnly, busyMs, notify, refreshMs, t])

  const toggle = useCallback(
    (c: Connector) => {
      if (readOnly) return
      // Sandbox: nur Datei-/URL-Connectoren (auth==='none') sind nutzbar — der Rest ist gesperrt.
      if (sandbox && c.auth !== 'none') return
      // Google: echter OAuth-Flow bzw. Trennen.
      if (GOOGLE_OAUTH_IDS.has(c.id)) {
        if (googleState === 'connected') disconnectGoogle()
        else connectGoogle()
        return
      }
      setEnabled((prev) => {
        const next = new Set(prev)
        const wasOn = next.has(c.id)
        if (wasOn) next.delete(c.id)
        else next.add(c.id)
        saveEnabledIds(tenantId, Array.from(next))
        if (!wasOn && !c.live) notify(t('connectors.setup_pending', { name: connName(t, c) }))
        return next
      })
    },
    [readOnly, sandbox, tenantId, notify, googleState, connectGoogle, disconnectGoogle, t],
  )

  const inputs = useMemo(() => CONNECTORS.filter((c) => c.category === 'input'), [])
  const outputs = useMemo(() => CONNECTORS.filter((c) => c.category === 'output'), [])

  // Ist eine Karte aktiv? Google → echter Status; sonst → localStorage.
  const isActive = useCallback(
    (c: Connector) => (GOOGLE_OAUTH_IDS.has(c.id) ? googleState === 'connected' : enabled.has(c.id)),
    [enabled, googleState],
  )
  const googleStateOf = useCallback(
    (c: Connector): GoogleState | undefined => (GOOGLE_OAUTH_IDS.has(c.id) ? googleState : undefined),
    [googleState],
  )

  const hasGoogle = useMemo(
    () => CONNECTORS.some((c) => GOOGLE_OAUTH_IDS.has(c.id)),
    [],
  )

  return (
    <div className="flex flex-col gap-5">
      {sandbox && (
        <div className="rounded-xl border border-primary/25 bg-primary/[0.06] px-3.5 py-2.5">
          <div className="text-[12.5px] font-semibold text-paper">{t('connectors.marketplace')}</div>
          <p className="text-[11.5px] text-muted leading-snug mt-0.5">
            {t('connectors.sandbox_note')}
          </p>
        </div>
      )}
      {hasGoogle && (
        <GoogleBanner
          state={googleState}
          email={googleEmail}
          busy={busyGoogle}
          readOnly={readOnly || sandbox}
          sandbox={sandbox}
          onConnect={connectGoogle}
          onDisconnect={disconnectGoogle}
        />
      )}
      <MicrosoftBanner
        state={msState}
        email={microsoft?.email || undefined}
        busy={busyMs}
        readOnly={readOnly || sandbox}
        sandbox={sandbox}
        onConnect={connectMs}
        onDisconnect={disconnectMs}
      />
      {(filter === 'all' || filter === 'input') && (
        <Group
          label={t('connectors.group_input')}
          hint={t('connectors.group_input_hint')}
          items={inputs}
          isActive={isActive}
          googleStateOf={googleStateOf}
          googleEmail={googleEmail}
          busyGoogle={busyGoogle}
          compact={compact}
          readOnly={readOnly}
          sandbox={sandbox}
          onToggle={toggle}
        />
      )}
      {(filter === 'all' || filter === 'output') && (
        <Group
          label={t('connectors.group_output')}
          hint={t('connectors.group_output_hint')}
          items={outputs}
          isActive={isActive}
          googleStateOf={googleStateOf}
          googleEmail={googleEmail}
          busyGoogle={busyGoogle}
          compact={compact}
          readOnly={readOnly}
          sandbox={sandbox}
          onToggle={toggle}
        />
      )}
      {plugins.length > 0 && (filter === 'all') && (
        <div className="flex flex-col gap-2">
          <div>
            <div className="text-[13px] font-semibold text-paper">{t('connectors.plugins_title')}</div>
            <div className="text-[11.5px] text-muted">
              {t('connectors.plugins_desc')}
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {plugins.map((p) => (
              <div
                key={p.id}
                title={p.description || p.name}
                className="rounded-lg border border-line bg-surface2 px-2.5 py-2"
              >
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary/12 text-primary border border-primary/25">
                    {p.kind}
                  </span>
                  <span className="text-[12px] text-paper truncate">{p.name}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {!onNotice && note && <p className="text-[12px] text-primary/90 animate-fade-in">{note}</p>}
    </div>
  )
}

// Kompaktes Status-Band für Google — sichtbar in Settings UND Bibliothek (identisch).
function GoogleBanner({
  state,
  email,
  busy,
  readOnly,
  sandbox,
  onConnect,
  onDisconnect,
}: {
  state: GoogleState
  email?: string
  busy: boolean
  readOnly: boolean
  sandbox?: boolean
  onConnect: () => void
  onDisconnect: () => void
}) {
  const t = useT()
  const connected = state === 'connected'
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [autoSync, setAutoSync] = useState(() => {
    try { return localStorage.getItem('cnode.google.autosync') === '1' } catch { return false }
  })
  useEffect(() => {
    if (!connected) { setScopes([]); return }
    api.googleStatus().then((s) => setScopes(s.scopes || [])).catch(() => {})
  }, [connected])
  // Auto-Poll (C): während App offen + aktiviert, alle 30 min synchronisieren (client-seitig,
  // privacy-schonend — kein Server-Cron, kein Zugriff ohne offene Session).
  useEffect(() => {
    if (!connected || !autoSync) return
    const id = window.setInterval(() => { void doSync() }, 30 * 60 * 1000)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, autoSync])
  function toggleAuto() {
    setAutoSync((v) => {
      const nv = !v
      try { localStorage.setItem('cnode.google.autosync', nv ? '1' : '0') } catch { /* ignore */ }
      return nv
    })
  }
  const hasScope = (frag: string) => scopes.some((s) => s.includes(frag))
  const grants = [
    { label: 'Gmail', ok: hasScope('gmail') },
    { label: 'Drive', ok: hasScope('drive') },
    { label: t('connectors.grant_calendar'), ok: hasScope('calendar') },
  ]
  const calMissing = connected && scopes.length > 0 && !hasScope('calendar')
  async function doSync() {
    setSyncing(true)
    setSyncMsg('')
    try {
      const r = await api.googleSync()
      if (r.ok) {
        let msg = t('connectors.sync_result', { nodes: r.nodes ?? 0, gmail: r.gmail ?? 0, drive: r.drive ?? 0 })
        const q = await api.queue().catch(() => ({ nen: null }))
        if (q.nen && q.nen.pending > 0) msg += t('connectors.sync_nen', { pending: q.nen.pending })
        setSyncMsg(msg)
      } else {
        setSyncMsg(
          r.reason === 'not_connected'
            ? t('connectors.not_connected_short')
            : t('connectors.sync_failed', { reason: r.reason ?? t('connectors.error_generic') }),
        )
      }
    } catch {
      setSyncMsg(t('connectors.sync_unreachable'))
    } finally {
      setSyncing(false)
    }
  }
  return (
    <div
      title={sandbox ? t('connectors.sandbox_lock') : undefined}
      className={`rounded-xl border px-3.5 py-2.5 flex items-center gap-3 flex-wrap ${
        connected ? 'border-emerald-500/40 bg-emerald-500/[0.07]' : 'border-line bg-surface2'
      }`}
    >
      <span
        className={`shrink-0 w-8 h-8 grid place-items-center rounded-lg border text-[15px] ${
          connected ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-line bg-surface3'
        }`}
        aria-hidden
      >
        {/* Google „G" */}
        <svg width="16" height="16" viewBox="0 0 18 18">
          <path fill="#4285F4" d="M17.6 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 01-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
          <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.94v2.33A9 9 0 009 18z" />
          <path fill="#FBBC05" d="M3.97 10.72A5.41 5.41 0 013.68 9c0-.6.1-1.18.29-1.72V4.95H.94A9 9 0 000 9c0 1.45.35 2.82.94 4.05l3.03-2.33z" />
          <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.47.89 11.43 0 9 0A9 9 0 00.94 4.95l3.03 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
        </svg>
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-semibold text-paper">Google Workspace</span>
          {connected ? (
            <span className="text-[10px] font-mono uppercase tracking-wide text-emerald-400">● {t('connectors.connected')}</span>
          ) : state === 'connect' ? (
            <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('connectors.not_connected')}</span>
          ) : (
            <span className="text-[10px] font-mono uppercase tracking-wide text-amber-400">{t('connectors.setup_needed')}</span>
          )}
        </div>
        <p className="text-[11px] text-muted leading-snug mt-0.5 truncate">
          {connected
            ? `${email || t('connectors.connected_fallback')}`
            : state === 'connect'
            ? t('connectors.google_scope_hint')
            : t('connectors.google_oauth_missing')}
        </p>
        {connected && scopes.length > 0 && (
          <div className="flex items-center gap-1.5 mt-1">
            {grants.map((g) => (
              <span
                key={g.label}
                className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded border ${
                  g.ok
                    ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
                    : 'text-faint border-line bg-surface3'
                }`}
              >
                {g.ok ? '✓' : '○'} {g.label}
              </span>
            ))}
          </div>
        )}
      </div>
      {!readOnly && connected && (
        <>
          <button
            onClick={toggleAuto}
            title={t('connectors.auto_sync_title')}
            className={`shrink-0 text-[11.5px] font-medium px-2.5 py-1.5 rounded-lg border transition ${
              autoSync
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
                : 'border-line text-muted hover:text-paper hover:border-line2'
            }`}
          >
            {autoSync ? t('connectors.auto_on') : t('connectors.auto')}
          </button>
          <button
            onClick={doSync}
            disabled={syncing}
            title={t('connectors.sync_title')}
            className="shrink-0 text-[12px] font-semibold px-3 py-1.5 rounded-lg border border-primary/45 bg-primary/15 text-primary hover:bg-primary/25 transition disabled:opacity-50"
          >
            {syncing ? t('connectors.syncing') : t('connectors.to_graph')}
          </button>
        </>
      )}
      {!readOnly && state !== 'setup' && (
        <button
          onClick={connected ? onDisconnect : onConnect}
          disabled={busy}
          className={`shrink-0 text-[12px] font-semibold px-3 py-1.5 rounded-lg border transition disabled:opacity-50 ${
            connected
              ? 'text-muted border-line hover:text-paper hover:border-line2'
              : 'bg-primary text-ink border-primary hover:brightness-105'
          }`}
        >
          {busy ? '…' : connected ? t('connectors.disconnect') : t('connectors.connect_google')}
        </button>
      )}
      {calMissing && !readOnly && (
        <p className="w-full text-[11.5px] basis-full mt-0.5 text-amber-400/90">
          {t('connectors.cal_scope_prefix')}{' '}
          <button onClick={onConnect} className="underline underline-offset-2 hover:text-amber-300">
            {t('connectors.reconnect_google')}
          </button>{' '}
          {t('connectors.cal_scope_suffix')}
        </p>
      )}
      {syncMsg && (
        <p className="w-full text-[11.5px] text-muted mt-0.5 basis-full">{syncMsg}</p>
      )}
    </div>
  )
}

// Kompaktes Status-Band für Microsoft/Outlook (Graph) — mirror zu GoogleBanner.
function MicrosoftBanner({
  state,
  email,
  busy,
  readOnly,
  sandbox,
  onConnect,
  onDisconnect,
}: {
  state: GoogleState
  email?: string
  busy: boolean
  readOnly: boolean
  sandbox?: boolean
  onConnect: () => void
  onDisconnect: () => void
}) {
  const t = useT()
  const connected = state === 'connected'
  return (
    <div
      title={sandbox ? t('connectors.sandbox_lock') : undefined}
      className={`rounded-xl border px-3.5 py-2.5 flex items-center gap-3 ${
        connected ? 'border-sky-500/40 bg-sky-500/[0.07]' : 'border-line bg-surface2'
      }`}
    >
      <span
        className={`shrink-0 w-8 h-8 grid place-items-center rounded-lg border ${
          connected ? 'border-sky-500/40 bg-sky-500/10' : 'border-line bg-surface3'
        }`}
        aria-hidden
      >
        <svg width="16" height="16" viewBox="0 0 18 18">
          <rect x="1" y="1" width="7.6" height="7.6" fill="#F35325" />
          <rect x="9.4" y="1" width="7.6" height="7.6" fill="#81BC06" />
          <rect x="1" y="9.4" width="7.6" height="7.6" fill="#05A6F0" />
          <rect x="9.4" y="9.4" width="7.6" height="7.6" fill="#FFBA08" />
        </svg>
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-semibold text-paper">Microsoft 365 / Outlook</span>
          {connected ? (
            <span className="text-[10px] font-mono uppercase tracking-wide text-sky-400">● {t('connectors.connected')}</span>
          ) : state === 'connect' ? (
            <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('connectors.not_connected')}</span>
          ) : (
            <span className="text-[10px] font-mono uppercase tracking-wide text-amber-400">{t('connectors.setup_needed')}</span>
          )}
        </div>
        <p className="text-[11px] text-muted leading-snug mt-0.5 truncate">
          {connected
            ? `${email || t('connectors.connected_fallback')}`
            : state === 'connect'
            ? t('connectors.ms_scope_hint')
            : t('connectors.ms_azure_missing')}
        </p>
      </div>
      {!readOnly && state !== 'setup' && (
        <button
          onClick={connected ? onDisconnect : onConnect}
          disabled={busy}
          className={`shrink-0 text-[12px] font-semibold px-3 py-1.5 rounded-lg border transition disabled:opacity-50 ${
            connected
              ? 'text-muted border-line hover:text-paper hover:border-line2'
              : 'bg-primary text-ink border-primary hover:brightness-105'
          }`}
        >
          {busy ? '…' : connected ? t('connectors.disconnect') : t('connectors.connect_outlook')}
        </button>
      )}
    </div>
  )
}


function Group({
  label,
  hint,
  items,
  isActive,
  googleStateOf,
  googleEmail,
  busyGoogle,
  compact,
  readOnly,
  sandbox,
  onToggle,
}: {
  label: string
  hint: string
  items: Connector[]
  isActive: (c: Connector) => boolean
  googleStateOf: (c: Connector) => GoogleState | undefined
  googleEmail?: string
  busyGoogle: boolean
  compact: boolean
  readOnly: boolean
  sandbox: boolean
  onToggle: (c: Connector) => void
}) {
  if (items.length === 0) return null
  return (
    <section>
      <div className="flex items-baseline gap-2 mb-2.5">
        <h4 className="font-display font-bold text-[13px] text-paper">{label}</h4>
        {!compact && <span className="text-[11px] text-faint">{hint}</span>}
      </div>
      <div
        className={`grid gap-2 ${
          compact ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'
        }`}
      >
        {items.map((c) => (
          <ConnectorCard
            key={c.id}
            connector={c}
            active={isActive(c)}
            googleState={googleStateOf(c)}
            googleEmail={googleEmail}
            busy={busyGoogle}
            compact={compact}
            readOnly={readOnly}
            locked={sandbox && c.auth !== 'none'}
            onToggle={onToggle}
          />
        ))}
      </div>
    </section>
  )
}

function ConnectorCard({
  connector: c,
  active,
  googleState,
  googleEmail,
  busy,
  compact,
  readOnly,
  locked = false,
  onToggle,
}: {
  connector: Connector
  active: boolean
  googleState?: GoogleState
  googleEmail?: string
  busy: boolean
  compact: boolean
  readOnly: boolean
  // Sandbox: Konto-Integration gesperrt (nur in eigener Instanz freischaltbar).
  locked?: boolean
  onToggle: (c: Connector) => void
}) {
  const t = useT()
  // Button-Label: Google-Karten spiegeln echten Status; sonst lokaler Enable-Zustand.
  const label = googleState
    ? googleState === 'connected'
      ? t('connectors.connected')
      : googleState === 'connect'
      ? t('connectors.connect')
      : t('connectors.setup_needed')
    : active
    ? t('connectors.active')
    : c.live
    ? t('connectors.activate')
    : t('connectors.connect')

  const on = active && !locked // aktiv/verbunden → gelber Rahmen (in Sandbox nie für gesperrte)
  const sub = googleState === 'connected' && googleEmail ? googleEmail : connDesc(t, c)

  return (
    <div
      title={locked ? t('connectors.sandbox_lock') : undefined}
      className={`rounded-xl border p-3 flex flex-col gap-2 transition ${
        locked
          ? 'bg-surface2/50 border-line opacity-80'
          : on ? 'bg-surface2 border-primary/40' : 'bg-surface2 border-line hover:border-line2'
      }`}
    >
      <div className="flex items-start gap-2.5">
        <span
          className="shrink-0 w-8 h-8 grid place-items-center rounded-lg bg-surface3 border border-line text-[16px]"
          aria-hidden
        >
          <ConnectorLogo id={c.id} fallback={c.icon} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[13px] font-medium text-paper truncate">{connName(t, c)}</span>
            {locked && <span className="text-[12px] shrink-0" aria-hidden>🔒</span>}
            {on && <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />}
          </div>
          {!compact && (
            <p className="text-[11px] text-muted leading-snug mt-0.5 truncate">
              {locked ? t('connectors.locked_sub') : sub}
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 mt-auto">
        <span className="text-[10px] font-mono uppercase tracking-wide text-faint">
          {connAuthLabel(t, c.auth)}
        </span>
        {locked ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded-lg border border-line text-faint">
            {t('connectors.locked_badge')}
          </span>
        ) : readOnly ? (
          <span
            className={`text-[11px] font-medium px-2.5 py-1 rounded-lg border ${
              on ? 'text-primary border-primary/40 bg-primary/10' : 'text-faint border-line'
            }`}
          >
            {on ? (googleState === 'connected' ? t('connectors.connected') : t('connectors.active')) : t('connectors.inactive')}
          </span>
        ) : (
          <button
            onClick={() => onToggle(c)}
            disabled={busy && !!googleState}
            className={`text-[11px] font-medium px-2.5 py-1 rounded-lg border transition disabled:opacity-50 ${
              on
                ? 'text-primary border-primary/40 bg-primary/10 hover:bg-primary/20'
                : 'text-muted border-line hover:text-paper hover:border-line2'
            }`}
            title={
              googleState === 'connected'
                ? t('connectors.disconnect')
                : googleState
                ? t('connectors.title_connect_google')
                : active
                ? t('connectors.deactivate')
                : c.live
                ? t('connectors.activate')
                : t('connectors.connect_setup')
            }
          >
            {label}
          </button>
        )}
      </div>
    </div>
  )
}
