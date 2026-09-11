import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { AgentRun, AgentStep, Artifact, LibraryFile } from '../types'
import { useT } from '../i18n'

// Artefakt-Art → Katalog-Schlüssel; der Anzeigetext kommt zur Laufzeit aus t().
const KIND_KEY: Record<string, string> = {
  dialog_protocol: 'rightrail.kind_dialog_protocol',
  memo: 'rightrail.kind_memo',
  proposal: 'rightrail.kind_proposal',
  one_pager: 'rightrail.kind_one_pager',
  briefing: 'rightrail.kind_briefing',
  lead_list: 'rightrail.kind_lead_list',
  funding_list: 'rightrail.kind_funding_list',
  trend_list: 'rightrail.kind_trend_list',
  governance_memo: 'rightrail.kind_governance_memo',
}

// Rechte Chat-Sidebar (E5.1 + E7 + E10): NUR Läufe + Artefakte + Dateien des aktiven
// Chats. Agenten werden über „/" im Composer gestartet — kein Picker mehr hier.
// Läufe sind einzeilig (Loader/Häkchen) und klappen zum Transkript auf.
export default function RightRail({
  threadId,
  clientId,
  refreshKey,
  onOpenArtifact,
  onClose,
  onNotice,
  agentRuns = [],
  liveRun = null,
}: {
  threadId: string | null
  clientId?: string
  refreshKey?: number
  onOpenArtifact: (a: Artifact) => void
  onClose: () => void
  onNotice?: (msg: string) => void
  agentRuns?: AgentRun[]
  liveRun?: AgentRun | null
}) {
  const t = useT()
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [files, setFiles] = useState<LibraryFile[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    if (!threadId) {
      setArtifacts([])
      setFiles([])
      return
    }
    setLoading(true)
    Promise.allSettled([api.artifacts(threadId), api.library(clientId, threadId)])
      .then(([a, f]) => {
        setArtifacts(a.status === 'fulfilled' ? a.value : [])
        setFiles(f.status === 'fulfilled' ? f.value.files : [])
      })
      .finally(() => setLoading(false))
  }, [threadId, clientId])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  // Live-Lauf zuerst, dann persistierte (ohne Dublette des Live-Laufs).
  const runs: AgentRun[] = liveRun
    ? [liveRun, ...agentRuns.filter((r) => r.id !== liveRun.id)]
    : agentRuns

  return (
    <aside className="w-full h-full border-l border-line bg-surface flex flex-col animate-panel-in md:w-[300px] md:max-w-[38vw] md:shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-line shrink-0">
        <h2 className="font-display font-bold text-[14px] text-paper">{t('rightrail.title')}</h2>
        <div className="flex items-center gap-1">
          <button onClick={load} title={t('rightrail.refresh')} className="p-1.5 rounded-lg text-faint hover:text-paper hover:bg-surface2 transition">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M13 8a5 5 0 10-1.5 3.5M13 8V4.5M13 8h-3.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <button onClick={onClose} title={t('common.close')} className="p-1.5 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition">
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-4">
        {/* Läufe — live + persistiert; einzeilig, aufklappbar zum Transkript */}
        <section>
          <SectionTitle count={runs.length}>{t('rightrail.runs')}</SectionTitle>
          {runs.length === 0 ? (
            <Empty>{t('rightrail.no_runs')}</Empty>
          ) : (
            <div className="flex flex-col gap-1">
              {runs.map((r) => (
                <RunRow key={r.id} run={r} defaultOpen={r.status === 'running'} />
              ))}
            </div>
          )}
        </section>

        {!threadId ? (
          <p className="text-[12px] text-faint px-1 py-1">
            {t('rightrail.no_thread')}
          </p>
        ) : (
          <>
            {/* Artefakte */}
            <section>
              <SectionTitle count={artifacts.length}>{t('rightrail.artifacts')}</SectionTitle>
              {artifacts.length === 0 ? (
                <Empty>{loading ? t('rightrail.loading') : t('rightrail.no_artifacts')}</Empty>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {artifacts.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => onOpenArtifact(a)}
                      className="text-left rounded-xl border border-line bg-surface2 hover:border-primary/50 hover:bg-surface2/70 transition px-3 py-2"
                    >
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-[9.5px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary/12 text-primary border border-primary/25">
                          {KIND_KEY[a.kind] ? t(KIND_KEY[a.kind]) : a.kind}
                        </span>
                      </div>
                      <div className="text-[12.5px] text-paper truncate">{a.title || t('rightrail.artifact_fallback')}</div>
                    </button>
                  ))}
                </div>
              )}
            </section>

            {/* Dateien */}
            <section>
              <SectionTitle count={files.length}>{t('rightrail.files')}</SectionTitle>
              {files.length === 0 ? (
                <Empty>{t('rightrail.no_files')}</Empty>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {files.map((f) => (
                    <button
                      key={f.id}
                      onClick={() => onNotice?.(t('rightrail.file_in_library', { name: f.title || f.name }))}
                      className="text-left rounded-xl border border-line bg-surface2 hover:border-line2 transition px-3 py-2 flex items-center gap-2.5"
                    >
                      <span className="shrink-0 w-7 h-7 grid place-items-center rounded-lg bg-surface3 border border-line">
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-muted">
                          <path d="M4 2.5h5l3 3v8a.6.6 0 01-.6.6H4a.6.6 0 01-.6-.6V3.1A.6.6 0 014 2.5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                          <path d="M9 2.5v3h3" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                        </svg>
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[12.5px] text-paper truncate">{f.title || f.name}</span>
                        {(f.chars || f.name) && (
                          <span className="block text-[10.5px] text-faint truncate">
                            {f.name}{f.chars ? t('rightrail.chars_suffix', { chars: f.chars.toLocaleString('de-DE') }) : ''}
                          </span>
                        )}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </aside>
  )
}

// --- Lauf-Zeile: einzeilig (Loader/Häkchen), Klick klappt das Transkript auf ---
function RunStatusIcon({ status }: { status: string }) {
  if (status === 'running') {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" className="shrink-0 text-primary animate-spin">
        <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" opacity="0.25" fill="none" />
        <path d="M8 2a6 6 0 016 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
      </svg>
    )
  }
  if (status === 'done') {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" className="shrink-0 text-cmint">
        <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.2" opacity="0.4" fill="none" />
        <path d="M5 8.2l2.1 2.1L11 6" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (status === 'failed') {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" className="shrink-0 text-crose">
        <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.2" opacity="0.4" fill="none" />
        <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }
  return <span className="shrink-0 w-3 h-3 rounded-full border border-line2" />
}

function RunRow({ run, defaultOpen = false }: { run: AgentRun; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  // Live-Lauf offen halten, solange er läuft (Auto-Expand bei Statuswechsel).
  useEffect(() => {
    if (run.status === 'running') setOpen(true)
  }, [run.status])
  const done = run.steps.filter((s) => s.status === 'done').length
  return (
    <div className="rounded-lg border border-line bg-surface2 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left hover:bg-surface2/70 transition"
        title={run.goal}
      >
        <RunStatusIcon status={run.status} />
        <span className="min-w-0 flex-1">
          <span className="block text-[12px] text-paper truncate">{run.agent_name || run.agent}</span>
          <span className="block text-[10px] text-faint truncate">{run.goal}</span>
        </span>
        {run.steps.length > 0 && (
          <span className="shrink-0 text-[9.5px] font-mono text-faint">{done}/{run.steps.length}</span>
        )}
        <svg
          width="11" height="11" viewBox="0 0 16 16"
          className={`shrink-0 text-faint transition-transform ${open ? 'rotate-90' : ''}`}
        >
          <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && run.steps.length > 0 && (
        <ol className="flex flex-col gap-1 px-3 pb-2.5 pt-1 border-t border-line">
          {run.steps.map((s) => (
            <StepRow key={s.idx} step={s} />
          ))}
        </ol>
      )}
    </div>
  )
}

function StepRow({ step }: { step: AgentStep }) {
  return (
    <li className="flex items-start gap-2 text-[11px]">
      <StepDot status={step.status} />
      <span className="min-w-0 flex-1">
        <span className={`block ${step.status === 'planned' ? 'text-faint' : 'text-paper/90'}`}>
          {step.title}
        </span>
        {step.summary && <span className="block text-[10px] text-faint">{step.summary}</span>}
      </span>
    </li>
  )
}

function StepDot({ status }: { status: string }) {
  if (status === 'running') {
    return <span className="shrink-0 mt-[3px] w-2 h-2 rounded-full bg-primary animate-pulse" />
  }
  if (status === 'done') {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" className="shrink-0 mt-[2px] text-cmint">
        <path d="M2.5 6.2l2.2 2.3L9.5 3.5" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (status === 'failed') {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" className="shrink-0 mt-[2px] text-crose">
        <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }
  if (status === 'skipped') {
    return <span className="shrink-0 mt-[3px] w-2 h-2 rounded-full border border-line2" />
  }
  return <span className="shrink-0 mt-[3px] w-2 h-2 rounded-full border border-line" />
}

function SectionTitle({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <div className="flex items-baseline gap-1.5 mb-1.5 px-1">
      <span className="text-[10px] font-mono uppercase tracking-wider text-faint">{children}</span>
      {count != null && count > 0 && <span className="text-[10px] text-faint">· {count}</span>}
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-[11.5px] text-faint px-1 py-1.5">{children}</p>
}
