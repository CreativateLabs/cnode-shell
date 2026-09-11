import { useEffect, useState } from 'react'
import { api } from '../api'
import { GATEWAY } from '../config'
import ConnectorLogo from './ConnectorLogo'
import type { AgentAction } from '../types'
import { getDoneAction, markActionDone } from '../persist'
import { useT } from '../i18n'

// Bestätigungs-Karte für agentische Aktionen mit Außenwirkung (z.B. Gmail-Entwurf).
// Nichts wird ohne explizite Bestätigung ausgeführt. Vorschau ist editierbar.
export default function ActionCard({ action }: { action: AgentAction }) {
  const t = useT()
  const isCal = action.type === 'gcal_event'
  const [subject, setSubject] = useState(action.params.subject ?? '')
  const [to, setTo] = useState(action.params.to ?? '')
  const [body, setBody] = useState(action.params.body ?? '')
  // Kalender-Felder (nur bei gcal_event)
  const [calSummary, setCalSummary] = useState(action.params.summary ?? '')
  const [calStart, setCalStart] = useState(action.params.start ?? '')
  const [calEnd, setCalEnd] = useState(action.params.end ?? '')
  const [calDesc, setCalDesc] = useState(action.params.description ?? '')
  // Bereits ausgeführte Aktionen bleiben „erledigt" — auch nach Reopen/Reload,
  // damit nicht erneut „Bestätigen & anlegen" angeboten wird (kein Doppel-Versand).
  const persistedDone = getDoneAction(action.id)
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error' | 'cancelled'>(
    persistedDone != null || action.status === 'done' ? 'done' : 'idle',
  )
  const [result, setResult] = useState<string>(
    persistedDone ?? (action.status === 'done' ? action.result ?? t('actioncard.done_default') : ''),
  )
  const [connected, setConnected] = useState<boolean>(action.connected)

  const isGoogle = action.connector === 'gmail' || action.connector === 'gcal'
  const isMs = action.connector === 'outlook' || action.connector === 'msgraph'
  const isOAuth = isGoogle || isMs

  // Live-Status für OAuth-Connectoren nachziehen (Verbindung kann inzwischen bestehen).
  useEffect(() => {
    if (!isOAuth || connected) return
    const p = isMs ? api.microsoftStatus() : api.googleStatus()
    p.then((s) => setConnected(!!s.connected)).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function confirm() {
    setStatus('running')
    setResult('')
    try {
      const params = isCal
        ? { summary: calSummary, start: calStart, end: calEnd, description: calDesc,
            timezone: action.params.timezone }
        : { subject, to, body }
      const r = await api.executeAction(action.type, params)
      if (r.ok) {
        const msg = r.message || t('actioncard.done_default')
        setStatus('done')
        setResult(msg)
        markActionDone(action.id, msg)
      } else {
        setStatus('error')
        setResult(r.detail || r.reason || t('actioncard.failed_default'))
      }
    } catch (e: any) {
      setStatus('error')
      setResult(e?.message || t('actioncard.failed_default'))
    }
  }

  const connectorLabel =
    action.connector === 'gmail' ? 'Gmail'
      : action.connector === 'gcal' ? 'Google Calendar'
      : action.connector === 'outlook' ? 'Outlook'
      : action.connector === 'msgraph' ? 'Microsoft 365'
      : action.connector
  const installPath = isMs ? '/integrations/microsoft/oauth/install' : '/integrations/google/oauth/install'

  return (
    <div className="mt-3 rounded-xl border border-primary/40 bg-primary/[0.06] overflow-hidden">
      {/* Kopf */}
      <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-primary/20">
        <span className="shrink-0 w-7 h-7 grid place-items-center rounded-lg bg-surface3 border border-line">
          <ConnectorLogo id={action.connector} fallback={isCal ? '📅' : '✉️'} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-paper">{action.title}</div>
          {action.summary && <div className="text-[11px] text-muted leading-snug">{action.summary}</div>}
        </div>
        <span className="shrink-0 text-[9.5px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary/15 text-primary border border-primary/25">
          {t('actioncard.confirm_needed')}
        </span>
      </div>

      {/* Body */}
      {status === 'done' ? (
        <div className="px-3.5 py-3 flex items-start gap-2 text-[12.5px] text-cmint">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="mt-0.5 shrink-0">
            <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>{result}</span>
        </div>
      ) : status === 'cancelled' ? (
        <div className="px-3.5 py-3 text-[12.5px] text-muted">{t('actioncard.cancelled')}</div>
      ) : (
        <>
          <div className="px-3.5 py-3 flex flex-col gap-2">
            {isCal ? (
              <>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('actioncard.field_title')}</span>
                  <input
                    value={calSummary}
                    onChange={(e) => setCalSummary(e.target.value)}
                    disabled={status === 'running'}
                    className="rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12.5px] text-paper outline-none focus:border-primary/50 transition disabled:opacity-60"
                  />
                </label>
                <div className="flex gap-2">
                  <label className="flex flex-col gap-1 flex-1">
                    <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('actioncard.field_start')}</span>
                    <input
                      value={calStart}
                      onChange={(e) => setCalStart(e.target.value)}
                      placeholder="2026-09-03T10:00:00"
                      disabled={status === 'running'}
                      className="rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12px] font-mono text-paper placeholder:text-faint outline-none focus:border-primary/50 transition disabled:opacity-60"
                    />
                  </label>
                  <label className="flex flex-col gap-1 flex-1">
                    <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('actioncard.field_end')}</span>
                    <input
                      value={calEnd}
                      onChange={(e) => setCalEnd(e.target.value)}
                      placeholder="2026-09-03T10:30:00"
                      disabled={status === 'running'}
                      className="rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12px] font-mono text-paper placeholder:text-faint outline-none focus:border-primary/50 transition disabled:opacity-60"
                    />
                  </label>
                </div>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('actioncard.field_description')}</span>
                  <textarea
                    value={calDesc}
                    onChange={(e) => setCalDesc(e.target.value)}
                    rows={2}
                    disabled={status === 'running'}
                    className="rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12.5px] text-paper leading-relaxed outline-none focus:border-primary/50 transition resize-y disabled:opacity-60"
                  />
                </label>
              </>
            ) : (
              <>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('actioncard.field_to')}</span>
                  <input
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                    placeholder="name@firma.de"
                    disabled={status === 'running'}
                    className="rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12.5px] text-paper placeholder:text-faint outline-none focus:border-primary/50 transition disabled:opacity-60"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('actioncard.field_subject')}</span>
                  <input
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    disabled={status === 'running'}
                    className="rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12.5px] text-paper outline-none focus:border-primary/50 transition disabled:opacity-60"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{t('actioncard.field_body')}</span>
                  <textarea
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    rows={5}
                    disabled={status === 'running'}
                    className="rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12.5px] text-paper leading-relaxed outline-none focus:border-primary/50 transition resize-y disabled:opacity-60"
                  />
                </label>
              </>
            )}
          </div>

          {status === 'error' && (
            <div className="px-3.5 pb-2 text-[11.5px] text-crose/90">{result}</div>
          )}

          <div className="flex items-center justify-between gap-2 px-3.5 py-2.5 border-t border-primary/20">
            <span className="text-[10.5px] text-faint">
              {isOAuth && !connected
                ? t('actioncard.not_connected', { connector: connectorLabel })
                : t('actioncard.nothing_auto')}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setStatus('cancelled')}
                disabled={status === 'running'}
                className="px-3 py-1.5 rounded-lg text-[12px] text-muted hover:text-paper hover:bg-surface2 transition disabled:opacity-50"
              >
                {t('common.cancel')}
              </button>
              {isOAuth && !connected ? (
                <button
                  onClick={() => (window.location.href = `${GATEWAY}${installPath}`)}
                  className="px-3.5 py-1.5 rounded-full bg-primary text-ink font-semibold text-[12px] hover:brightness-105 transition"
                >
                  {isMs ? t('actioncard.connect_outlook') : t('actioncard.connect_google')}
                </button>
              ) : (
                <button
                  onClick={confirm}
                  disabled={status === 'running'}
                  className="px-3.5 py-1.5 rounded-full bg-primary text-ink font-semibold text-[12px] hover:brightness-105 transition disabled:opacity-60"
                >
                  {status === 'running' ? t('actioncard.creating') : t('actioncard.confirm_create')}
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
