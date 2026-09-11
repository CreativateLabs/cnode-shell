import { useEffect, useRef, useState } from 'react'
import type { AgentRun, ChatMessage, Envelope, FormSummary, NBA, Source, TraceStep } from '../types'
import { typeColor } from '../theme'
import Markdown from './Markdown'
import ActionCard from './ActionCard'
import FormRunner from './FormRunner'
import { brand } from '../brand'
import { useT, type TFn } from '../i18n'

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

// Messages that have already played their entrance once (session-scoped, survives
// thread switches / remounts) → reopening an existing chat renders instantly.
const revealed = new Set<string>()
const entered = new Set<string>()

/** Progressive reveal — animates a message ONCE, then shows it instantly on any later mount. */
function useTypewriter(id: string, full: string, enabled: boolean) {
  const already = revealed.has(id)
  const [shown, setShown] = useState(already || !enabled ? full : '')
  useEffect(() => {
    if (!enabled || already || prefersReducedMotion()) {
      setShown(full)
      if (full) revealed.add(id)
      return
    }
    setShown('')
    let i = 0
    const step = Math.max(2, Math.round(full.length / 90)) // ~90 frames total
    const timer = setInterval(() => {
      i = Math.min(full.length, i + step)
      setShown(full.slice(0, i))
      if (i >= full.length) {
        clearInterval(timer)
        revealed.add(id)
      }
    }, 16)
    return () => clearInterval(timer)
  }, [full, enabled, id, already])
  return shown
}

function IntentBadge({ envelope }: { envelope: Envelope }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-2">
      <span className="text-[10px] font-mono uppercase tracking-wide px-2 py-0.5 rounded-md bg-primary/12 text-primary border border-primary/25">
        {envelope.intent} → {envelope.route}
      </span>
      {envelope.provider && (
        <span className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-surface3 text-muted border border-line">
          {envelope.provider}
          {envelope.model ? ` · ${envelope.model}` : ''}
        </span>
      )}
    </div>
  )
}

function SourceChips({ sources, onOpen }: { sources: Source[]; onOpen?: (s: Source) => void }) {
  const t = useT()
  if (!sources?.length) return null
  return (
    <div className="mt-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-faint mb-1.5">
        {t('chatview.sources_header')} {onOpen && <span className="normal-case tracking-normal">{t('chatview.sources_click_hint')}</span>}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((s, i) => (
          <button
            key={s.id || i}
            onClick={() => onOpen?.(s)}
            disabled={!onOpen}
            title={
              onOpen
                ? t('chatview.source_open_title', { meta: [s.type, s.provenance].filter(Boolean).join(' · ') })
                : [s.type, s.provenance].filter(Boolean).join(' · ')
            }
            className="group inline-flex items-center gap-1.5 pl-2 pr-2.5 py-1 rounded-full bg-surface2 border border-line enabled:hover:border-primary/50 enabled:hover:bg-primary/5 transition text-[11.5px] max-w-full text-left disabled:cursor-default"
          >
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: typeColor(s.type) }} />
            <span className="truncate text-paper/90">{s.label}</span>
            {s.type && <span className="text-faint text-[10px] shrink-0">{s.type}</span>}
            {onOpen && (
              <svg width="11" height="11" viewBox="0 0 16 16" className="shrink-0 text-faint opacity-0 group-hover:opacity-100 transition">
                <path d="M6 3h7v7M13 3L6.5 9.5M11 10.5V13H3V5h2.5" stroke="currentColor" strokeWidth="1.3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

function TraceView({ trace }: { trace: TraceStep[] }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  if (!trace?.length) return null
  return (
    <div className="mt-3 rounded-lg border border-line bg-surface2/60 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-surface2 transition"
      >
        <span className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-wider text-muted">
          <svg width="13" height="13" viewBox="0 0 14 14" className="text-primary">
            <path d="M2 3h10M2 7h10M2 11h6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          {t('chatview.trace_toggle', { count: trace.length })}
        </span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          className={`text-muted transition-transform ${open ? 'rotate-180' : ''}`}
        >
          <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <ol className="px-3 pb-3 pt-1 flex flex-col gap-1.5 animate-fade-in">
          {trace.map((t, i) => (
            <li key={i} className="flex gap-2 text-[11.5px] leading-snug">
              <span className="font-mono text-primary shrink-0">{String(i + 1).padStart(2, '0')}</span>
              <span className="text-muted">
                <b className="text-paper font-medium">{t.step}</b>
                {t.method ? ` · ${t.method}` : ''}
                {t.service ? <span className="text-cmint"> · {t.service}</span> : ''}
                {t.result ? <span className="text-muted"> → {t.result}</span> : ''}
                {t.hits !== undefined ? ` (${t.hits})` : ''}
                {t.error ? <span className="text-crose"> · ⚠ {t.error}</span> : ''}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-muted animate-blink"
          style={{ animationDelay: `${i * 0.18}s` }}
        />
      ))}
    </div>
  )
}

// Ehrlichkeits-Signal: macht sichtbar, ob die Antwort belegt ist oder eine allgemeine
// Einschätzung — Parität zur belegten Scout-/Consult-Ausgabe (keine unsichtbare Halluzination).
function GroundingBadge({ envelope }: { envelope: Envelope }) {
  const t = useT()
  const g = envelope.grounding
  const hasSrc = (envelope.sources?.length ?? 0) > 0
  if (g === 'gedaechtnis' || (envelope.grounded && hasSrc)) {
    return (
      <div className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-emerald-400/90">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400/90" />
        {t('chatview.grounding_memory')}
      </div>
    )
  }
  if (g === 'web') {
    return (
      <div className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-sky-400/90">
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400/90" />
        {t('chatview.grounding_web')}
      </div>
    )
  }
  if (g === 'allgemein') {
    return (
      <div className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-amber-400/80">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400/80" />
        {t('chatview.grounding_general')}
      </div>
    )
  }
  return null // chat/smalltalk/generation → kein Badge
}

function AssistantBody({ msg, onOpenSource }: { msg: ChatMessage; onOpenSource?: (s: Source) => void }) {
  const t = useT()
  const text = useTypewriter(msg.id, cleanSuggestionMarker(msg.text), !!msg.envelope && !msg.error)
  if (msg.pending) return <TypingDots />
  return (
    <>
      {msg.envelope && !msg.error && (msg.envelope.sources?.length ?? 0) > 0 && (
        <IntentBadge envelope={msg.envelope} />
      )}
      {msg.error ? (
        <div className="text-[13px] text-crose/90 leading-relaxed">{msg.text}</div>
      ) : (
        <Markdown className="text-[13.5px] text-paper/90">{text}</Markdown>
      )}
      {msg.envelope?.action && <ActionCard action={msg.envelope.action} />}
      {msg.envelope && !msg.error && !msg.pending && <GroundingBadge envelope={msg.envelope} />}
      {msg.envelope && (
        <>
          <SourceChips sources={msg.envelope.sources} onOpen={onOpenSource} />
          <TraceView trace={msg.envelope.trace} />
          {msg.envelope.artifact && (
            <div className="mt-3 inline-flex items-center gap-2 text-[11.5px] font-mono text-primary">
              <svg width="13" height="13" viewBox="0 0 14 14">
                <path d="M3 1.5h5l3 3v8H3v-11z" stroke="currentColor" strokeWidth="1.2" fill="none" />
              </svg>
              {t('chatview.artifact_created')}
            </div>
          )}
        </>
      )}
    </>
  )
}

function UserAvatar({ author }: { author?: string }) {
  const t = useT()
  const email = (author || t('chatview.you')).trim()
  const initial = (email[0] || '?').toUpperCase()
  // Identisch zum Account-Avatar oben im Dropdown: bg-primary + dunkle Initiale.
  return (
    <div
      title={email}
      className="shrink-0 w-8 h-8 rounded-full bg-primary text-ink flex items-center justify-center font-display font-extrabold text-[13px] mt-0.5"
    >
      {initial}
    </div>
  )
}

// Defensiv: eine am Ende geleakte „VORSCHLÄGE: …"-Marke aus dem Anzeigetext entfernen —
// greift auch bei alten, vor dem Server-Fix gespeicherten Nachrichten.
function cleanSuggestionMarker(text: string): string {
  if (!text) return text
  const matches = [...text.matchAll(/(?:[*_>#\s-]*)vorschl(?:ä|ae|a)ge\s*:?/gi)]
  const m = matches[matches.length - 1]
  if (!m || m.index === undefined || m.index < text.length - 240) return text
  const clean = text.slice(0, m.index).replace(/[\s\-*_>#·|]+$/, '').trim()
  return clean || text
}

function Bubble({ msg, onOpenSource }: { msg: ChatMessage; onOpenSource?: (s: Source) => void }) {
  const isUser = msg.role === 'user'
  const isNew = !entered.has(msg.id)
  useEffect(() => {
    entered.add(msg.id)
  }, [msg.id])
  return (
    <div className={`flex gap-3 ${isNew ? 'animate-fade-up' : ''} ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="shrink-0 w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-ink font-display font-extrabold text-[13px] mt-0.5">
          {brand().initial}
        </div>
      )}
      <div
        className={
          isUser
            ? 'max-w-[78%] rounded-2xl rounded-tr-md bg-surface3 border border-line px-4 py-2.5 text-[13.5px] text-paper leading-relaxed whitespace-pre-wrap'
            : 'max-w-[82%] rounded-2xl rounded-tl-md bg-surface border border-line px-4 py-3'
        }
      >
        {isUser ? msg.text : <AssistantBody msg={msg} onOpenSource={onOpenSource} />}
      </div>
      {isUser && <UserAvatar author={msg.author} />}
    </div>
  )
}

type StartItem = { icon: React.ReactNode; label: string; reason?: string; run: () => void }

function EmptyState({
  onPrompt,
  nba,
  onRunNba,
  forms = [],
  onStartForm,
}: {
  onPrompt: (p: string) => void
  nba: NBA[]
  onRunNba: (n: NBA) => void
  onboarding?: React.ReactNode
  forms?: FormSummary[]
  onStartForm?: (id: string) => void
}) {
  const t = useT()
  const _b = brand()
  const intro = _b.assistantRole
    ? t('chatview.intro_role', { role: _b.assistantRole })
    : t('chatview.intro_name', { name: _b.assistantName })
  const typed = useTypewriter('__cnode_intro__', intro, true)
  const done = typed.length >= intro.length

  const chatIcon = (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
      <path d="M3 4a1 1 0 011-1h8a1 1 0 011 1v6a1 1 0 01-1 1H6l-3 2.5V4z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  )
  const caseIcon = (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
      <path d="M2.5 5.5h11M2.5 5.5l1-2h9l1 2M2.5 5.5V12a1 1 0 001 1h9a1 1 0 001-1V5.5" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  )
  const sparkIcon = (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
      <path d="M8 2l1.4 3.6L13 7l-3.6 1.4L8 12l-1.4-3.6L3 7l3.6-1.4L8 2z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  )
  const targetIcon = (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  )
  const memoIcon = (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
      <path d="M4 2.5h6l2.5 2.5v8a.8.8 0 01-.8.8H4a.8.8 0 01-.8-.8V3.3A.8.8 0 014 2.5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M5.5 7.5h5M5.5 10h3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )

  // Alles zu EINER proaktiven Liste: zwei Start-Modi + dynamische Next-Best-Actions + Fähigkeiten.
  const modeItems: StartItem[] = [
    {
      icon: chatIcon,
      label: t('chatview.mode_general_label'),
      reason: t('chatview.mode_general_reason'),
      run: () => onPrompt(t('chatview.mode_general_prompt')),
    },
    {
      icon: caseIcon,
      label: t('chatview.mode_case_label'),
      reason: t('chatview.mode_case_reason'),
      run: () => onPrompt(t('chatview.mode_case_prompt')),
    },
  ]
  const nbaItems: StartItem[] = nba.slice(0, 3).map((n) => ({
    icon: sparkIcon,
    label: n.title,
    reason: n.reason,
    run: () => onRunNba(n),
  }))
  const capItems: StartItem[] = [
    {
      icon: targetIcon,
      label: t('chatview.cap_abilities_label'),
      run: () => onPrompt(t('chatview.cap_abilities_prompt')),
    },
    {
      icon: memoIcon,
      label: t('chatview.cap_memo_label'),
      run: () => onPrompt(t('chatview.cap_memo_prompt')),
    },
  ]
  // Tenant-Formulare (FraBö) als proaktive Startpunkte — direkt im Chat startbar.
  const formItems: StartItem[] = onStartForm
    ? forms.map((f) => ({
        icon: memoIcon,
        label: f.title,
        reason: f.description ? f.description.slice(0, 120) : t('chatview.form_meta', { sections: f.sections, questions: f.questions }),
        run: () => onStartForm(f.id),
      }))
    : []
  const items = [...modeItems, ...formItems, ...nbaItems, ...capItems]

  return (
    <div className="h-full overflow-y-auto">
      <div className="min-h-full flex flex-col items-center justify-center px-6 py-10">
        <div className="w-full max-w-xl animate-fade-in">
          {/* c:node meldet sich proaktiv */}
          <div className="flex items-start gap-3 mb-5">
            <span className="shrink-0 w-9 h-9 rounded-xl bg-primary flex items-center justify-center text-ink font-display font-extrabold text-lg">
              {brand().initial}
            </span>
            <div className="pt-0.5 min-w-0">
              <div className="text-[11px] font-mono uppercase tracking-wide text-faint mb-1">{brand().assistantName}</div>
              <p className="text-[14px] text-paper leading-relaxed">
                {typed}
                {!done && <span className="inline-block w-[2px] h-4 -mb-0.5 ml-0.5 bg-primary/80 animate-pulse align-middle" />}
              </p>
            </div>
          </div>

          {/* EINE getippte Vorschlagsliste */}
          {done && (
            <div className="flex flex-col gap-1.5">
              {items.map((it, i) => (
                <button
                  key={it.label + i}
                  onClick={it.run}
                  style={{ animationDelay: `${i * 70}ms`, animationFillMode: 'backwards' }}
                  className="group/item text-left flex items-start gap-3 px-3.5 py-3 rounded-xl bg-surface border border-line hover:border-primary/50 hover:bg-surface2 transition animate-fade-up"
                >
                  <span className="shrink-0 mt-0.5 w-7 h-7 grid place-items-center rounded-lg bg-surface3 border border-line text-primary group-hover/item:border-primary/40 transition">
                    {it.icon}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13.5px] text-paper font-medium leading-snug">{it.label}</span>
                    {it.reason && (
                      <span className="block text-[11.5px] text-muted leading-snug mt-0.5">{it.reason}</span>
                    )}
                  </span>
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 16 16"
                    fill="none"
                    className="shrink-0 mt-1 text-faint group-hover/item:text-primary group-hover/item:translate-x-0.5 transition"
                  >
                    <path d="M5 3l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              ))}
            </div>
          )}

          {done && (
            <p className="text-[11px] text-faint mt-5">
              {t('chatview.empty_hint_pre')}{' '}
              <span className="font-mono text-muted bg-surface2 border border-line rounded px-1">/</span>{' '}
              {t('chatview.empty_hint_post')}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// Kontextuelle Follow-up-Vorschläge — dynamisch aus dem letzten Reply (Intent + Top-Quelle).
function contextualFollowUps(t: TFn, msg?: ChatMessage): { label: string; prompt: string }[] {
  const env = msg?.envelope
  if (!env) return []
  const fu = (k: string) => ({ label: t(`chatview.follow.${k}.label`), prompt: t(`chatview.follow.${k}.prompt`) })
  const byIntent: Record<string, { label: string; prompt: string }[]> = {
    foerderung: [fu('foerderung.memo'), fu('foerderung.best'), fu('foerderung.deadlines')],
    leads: [fu('leads.outreach'), fu('leads.narrow'), fu('leads.graph')],
    decision: [fu('decision.memo'), fu('decision.counter'), fu('decision.evidence')],
    knowledge: [fu('knowledge.details'), fu('knowledge.onepager'), fu('knowledge.sources')],
    graph: [fu('graph.nodes'), fu('graph.gaps')],
    ingest: [fu('ingest.linked'), fu('ingest.summary')],
  }
  const base = byIntent[env.intent] ?? [fu('base.decisions'), fu('base.funding'), fu('base.leads')]
  const out = [...base]
  const top = env.sources?.[0]?.label
  if (top) {
    const short = top.length > 40 ? top.slice(0, 38) + '…' : top
    out.push({ label: t('chatview.follow.deepen.label', { short }), prompt: t('chatview.follow.deepen.prompt', { top }) })
  }
  return out.slice(0, 4)
}

// Wartende Nachricht in der Sende-Queue: als gedimmte User-Bubble mit „Wartet"-Badge
// und Abbrechen-Knopf — chronologisch im Verlauf, noch nicht gesendet.
function QueuedBubble({ text, onRecall }: { text: string; onRecall: () => void }) {
  const t = useT()
  return (
    <div className="flex gap-3 justify-end animate-fade-up">
      <div className="max-w-[78%] rounded-2xl rounded-tr-md bg-surface3/50 border border-dashed border-line2 px-4 py-2.5">
        <div className="flex items-center gap-1.5 mb-1">
          <svg width="11" height="11" viewBox="0 0 16 16" className="text-faint">
            <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.3" fill="none" />
            <path d="M8 4.5V8l2.2 1.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
          <span className="text-[9.5px] font-mono uppercase tracking-wide text-faint">{t('chatview.queued')}</span>
          <button
            onClick={onRecall}
            title={t('chatview.queued_cancel')}
            className="ml-1 w-4 h-4 grid place-items-center rounded-full text-faint hover:text-crose hover:bg-crose/10 transition"
          >
            <svg width="9" height="9" viewBox="0 0 12 12">
              <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="text-[13.5px] text-paper/70 leading-relaxed whitespace-pre-wrap">{text}</div>
      </div>
    </div>
  )
}

// Kompakte Inline-Lauf-Zeile im Chat: Status-Icon + Agent + Fortschritt; Klick öffnet die rechte Leiste.
const INLINE_RUN_STATUSES = new Set(['planned', 'running', 'done', 'failed'])
function InlineRun({ run, onOpen }: { run: AgentRun; onOpen?: () => void }) {
  const t = useT()
  const done = run.steps.filter((s) => s.status === 'done').length
  const running = run.status === 'running'
  return (
    <button
      onClick={onOpen}
      title={run.goal}
      className="group text-left inline-flex items-center gap-2 self-start max-w-full px-2.5 py-1.5 rounded-lg bg-surface2 border border-line hover:border-primary/40 transition"
    >
      {running ? (
        <svg width="13" height="13" viewBox="0 0 16 16" className="shrink-0 text-primary animate-spin">
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" opacity="0.25" fill="none" />
          <path d="M8 2a6 6 0 016 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
        </svg>
      ) : run.status === 'failed' ? (
        <svg width="13" height="13" viewBox="0 0 16 16" className="shrink-0 text-crose">
          <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 16 16" className="shrink-0 text-cmint">
          <path d="M4 8.2l2.2 2.3L12 5" stroke="currentColor" strokeWidth="1.7" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      <span className="text-[12px] text-paper truncate">{run.agent_name || run.agent}</span>
      <span className="text-[10.5px] font-mono text-faint shrink-0">
        {INLINE_RUN_STATUSES.has(run.status) ? t(`chatview.run.${run.status}`) : run.status}
        {run.steps.length > 0 ? ` · ${done}/${run.steps.length}` : ''}
      </span>
      <span className="shrink-0 text-faint text-[11px] opacity-0 group-hover:opacity-100 transition">↗</span>
    </button>
  )
}

export default function ChatView({
  messages,
  onPrompt,
  nba = [],
  onRunNba,
  onboarding,
  onCta,
  runs = [],
  onOpenRuns,
  queued = [],
  onRecallQueued,
  onOpenSource,
  activeFormId = null,
  forms = [],
  onStartForm,
  onFormComplete,
  onFormCancel,
}: {
  messages: ChatMessage[]
  onPrompt: (p: string) => void
  nba?: NBA[]
  onRunNba?: (n: NBA) => void
  onboarding?: React.ReactNode
  onCta?: (cta: { type: string; label: string; agent?: string; goal?: string }) => void
  runs?: AgentRun[]
  onOpenRuns?: () => void
  queued?: { id: string; text: string }[]
  onRecallQueued?: (id: string) => void
  onOpenSource?: (s: Source) => void
  activeFormId?: string | null
  forms?: FormSummary[]
  onStartForm?: (id: string) => void
  onFormComplete?: (md: string) => void
  onFormCancel?: () => void
}) {
  const t = useT()
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'end',
    })
  }, [messages, queued.length])

  const runNba = onRunNba ?? ((n: NBA) => onPrompt(n.prompt || n.title))

  if (messages.length === 0 && !activeFormId)
    return (
      <EmptyState
        onPrompt={onPrompt}
        nba={nba}
        onRunNba={runNba}
        onboarding={onboarding}
        forms={forms}
        onStartForm={onStartForm}
      />
    )

  const last = messages[messages.length - 1]
  const showFollow =
    last && last.role === 'assistant' && !last.pending && !last.error && last.envelope
  // LLM-erzeugte, kontextuelle Vorschläge bevorzugen; sonst intent-basierter Fallback.
  const llmSugs = last?.envelope?.suggestions?.filter((s) => s && s.trim()) ?? []
  const followUps = !showFollow
    ? []
    : llmSugs.length > 0
      ? llmSugs.map((s) => ({ label: s, prompt: s }))
      : contextualFollowUps(t, last)

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-6 flex flex-col gap-5">
        {messages.map((m) => (
          <Bubble key={m.id} msg={m} onOpenSource={onOpenSource} />
        ))}
        {/* Interaktives Tenant-Formular (FraBö) inline im Chatflow */}
        {activeFormId && (
          <FormRunner
            key={activeFormId}
            formId={activeFormId}
            onComplete={(md) => onFormComplete?.(md)}
            onCancel={() => onFormCancel?.()}
          />
        )}
        {/* E10.3: laufende/erledigte Agenten-Läufe inline im Chat sichtbar */}
        {runs.length > 0 && (
          <div className="pl-11 flex flex-col gap-1 animate-fade-in">
            {runs.slice(0, 4).map((r) => (
              <InlineRun key={r.id} run={r} onOpen={onOpenRuns} />
            ))}
          </div>
        )}
        {/* E11.2: wartende Prompts chronologisch im Verlauf — je einzeln abbrechbar */}
        {queued.map((q) => (
          <QueuedBubble key={q.id} text={q.text} onRecall={() => onRecallQueued?.(q.id)} />
        ))}
        {/* Proaktive Inline-CTAs (Web-Recherche / Quelle bereitstellen) */}
        {showFollow && (last?.envelope?.ctas?.length ?? 0) > 0 && (
          <div className="pl-11 -mt-1 flex flex-wrap gap-2 animate-fade-in">
            {last!.envelope!.ctas!.map((c, i) => (
              <button
                key={i}
                onClick={() => onCta?.(c)}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-primary/15 border border-primary/45 text-primary text-[12.5px] font-semibold hover:bg-primary/25 hover:border-primary/70 transition"
              >
                {c.label}
              </button>
            ))}
          </div>
        )}
        {/* Dynamische, kontextuelle Vorschläge — abhängig vom letzten Prompt + Reply */}
        {followUps.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pl-11 animate-fade-in">
            <span className="w-full text-[10px] font-mono uppercase tracking-wider text-faint mb-0.5">
              {t('chatview.suggestions')}
            </span>
            {followUps.map((s, i) => (
              <button
                key={i}
                onClick={() => onPrompt(s.prompt)}
                className="text-[11.5px] px-2.5 py-1 rounded-full bg-surface2 border border-line text-muted hover:text-primary hover:border-primary/40 transition"
              >
                {s.label}
              </button>
            ))}
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
