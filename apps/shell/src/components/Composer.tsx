import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { AgentSpec } from '../types'
import { useT } from '../i18n'

// "/"-Command-Palette: Funktionen je Bereich, direkt im Chat triggerbar.
// Strings (label/hint/group/template) sind lokalisiert — hier steht nur die stabile Metadaten;
// die Texte kommen zur Laufzeit aus dem Katalog (composer.cmd.<id>.*).
type Cmd = {
  id: string
  group: string
  icon: string
  label: string
  hint?: string
  mode: 'send' | 'fill' | 'ingest'
  template?: string
}
const COMMAND_META: { id: string; icon: string; mode: 'send' | 'fill' | 'ingest' }[] = [
  { id: 'entscheidung', icon: '⚖️', mode: 'fill' },
  { id: 'erklaeren', icon: '💡', mode: 'fill' },
  { id: 'leads', icon: '🎯', mode: 'fill' },
  { id: 'foerderung', icon: '💶', mode: 'fill' },
  { id: 'einlesen', icon: '📥', mode: 'ingest' },
  { id: 'graph', icon: '◍', mode: 'send' },
  { id: 'memo', icon: '📝', mode: 'send' },
  { id: 'protokoll', icon: '🗒️', mode: 'send' },
  { id: 'proposal', icon: '📄', mode: 'fill' },
  { id: 'onepager', icon: '📑', mode: 'send' },
]

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export default function Composer({
  onSend,
  onFiles,
  onOpenIngest,
  busy,
  disabled,
  onNotice,
  agentCatalog = [],
  domainAgents = [],
  draft = null,
  onDraftConsumed,
  onStop,
  sandbox = false,
}: {
  onSend: (text: string) => void
  onFiles: (files: File[]) => void
  onOpenIngest: () => void
  busy: boolean
  disabled?: boolean
  onStop?: () => void
  sandbox?: boolean
  onNotice?: (msg: string) => void
  agentCatalog?: AgentSpec[]
  domainAgents?: any[]
  draft?: string | null
  onDraftConsumed?: () => void
}) {
  const t = useT()
  const [text, setText] = useState('')
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  // ---- Voice (MediaRecorder → /voice/transcribe → text → /ask) ----
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const recRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      // cleanup on unmount
      if (timerRef.current) clearInterval(timerRef.current)
      streamRef.current?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  // Draft von außen (z.B. Klick auf einen Agenten in der rechten Sidebar) → in den Input.
  useEffect(() => {
    if (draft != null) {
      setInput(draft)
      requestAnimationFrame(() => {
        const el = taRef.current
        if (el) {
          el.focus()
          el.selectionStart = el.selectionEnd = el.value.length
        }
      })
      onDraftConsumed?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft])

  function setInput(v: string) {
    setText(v)
    if (taRef.current) {
      taRef.current.value = v
      autosize(taRef.current)
    }
  }

  function submit(value?: string) {
    const t = (value ?? text).trim()
    // busy blockiert NICHT mehr: läuft schon eine Antwort, reiht send() die Nachricht
    // chronologisch ein (E11.2) statt sie zu verwerfen.
    if (!t || disabled) return
    onSend(t)
    setInput('')
    if (taRef.current) taRef.current.style.height = 'auto'
  }

  function autosize(el: HTMLTextAreaElement) {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 180) + 'px'
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length) onFiles(files)
  }

  async function startRecording() {
    if (disabled || busy || transcribing) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mime =
        typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.('audio/webm')
          ? 'audio/webm'
          : ''
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      chunksRef.current = []
      rec.ondataavailable = (ev) => ev.data.size && chunksRef.current.push(ev.data)
      rec.onstop = onRecStopped
      recRef.current = rec
      rec.start()
      setRecording(true)
      setElapsed(0)
      timerRef.current = window.setInterval(() => setElapsed((s) => s + 1), 1000)
    } catch (e: any) {
      onNotice?.(t('composer.mic_unavailable', { error: e?.message ?? t('composer.access_denied') }))
    }
  }

  function stopRecording() {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setRecording(false)
    recRef.current?.state === 'recording' && recRef.current.stop()
  }

  async function onRecStopped() {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    const blob = new Blob(chunksRef.current, { type: recRef.current?.mimeType || 'audio/webm' })
    chunksRef.current = []
    if (!blob.size) return
    setTranscribing(true)
    try {
      const { text: transcript } = await api.transcribe(blob)
      const tr = (transcript || '').trim()
      if (tr) {
        setInput(tr)
        submit(tr) // route through the normal /ask send path
      } else {
        onNotice?.(t('composer.no_speech'))
      }
    } catch (e: any) {
      onNotice?.(t('composer.transcribe_failed', { error: e.message }))
    } finally {
      setTranscribing(false)
    }
  }

  // Agenten dynamisch aus dem Katalog als "/"-Kommandos (Gruppe „Agenten", ganz oben).
  // Benannte Fach-Agenten (Personas) — „@Name "-Route in den Consult-Endpoint (A2A + Belege).
  const domainCmds: Cmd[] = (domainAgents || []).map((a) => ({
    id: `domain_${a.id}`,
    group: t('composer.group.domain_agents'),
    icon: '◆',
    label: `${a.name} — ${a.role || a.domain || ''}`,
    hint: a.trigger_question,
    mode: 'fill',
    template: `@${a.name} `,
  }))
  const agentCmds: Cmd[] = agentCatalog.map((a) => ({
    id: `agent_${a.id}`,
    group: t('composer.group.agents'),
    icon: '✦',
    label: t('composer.cmd.agent.label', { name: a.name }),
    hint: a.description,
    mode: 'fill',
    template: t('composer.cmd.agent.tpl', { name: a.name }),
  }))
  // Statische Kommandos: Strings zur Laufzeit aus dem Katalog (composer.cmd.<id>.*).
  const staticCmds: Cmd[] = COMMAND_META.map((m) => {
    const hint = t(`composer.cmd.${m.id}.hint`)
    return {
      id: m.id,
      icon: m.icon,
      mode: m.mode,
      group: t(`composer.cmd.${m.id}.group`),
      label: t(`composer.cmd.${m.id}.label`),
      hint: hint && hint !== `composer.cmd.${m.id}.hint` ? hint : undefined,
      template: m.mode === 'ingest' ? undefined : t(`composer.cmd.${m.id}.tpl`),
    }
  })
  const COMMAND_LIST: Cmd[] = [...domainCmds, ...agentCmds, ...staticCmds]

  // "/"-Command-Palette
  const slashActive = !disabled && !recording && !transcribing && text.startsWith('/')
  const q = slashActive ? text.slice(1).trim().toLowerCase() : ''
  const cmdMatches = slashActive
    ? COMMAND_LIST.filter((c) => `${c.label} ${c.id} ${c.group} ${c.hint ?? ''}`.toLowerCase().includes(q))
    : []
  const cmdGroups = Array.from(new Set(cmdMatches.map((c) => c.group)))

  function runCommand(cmd: Cmd) {
    if (cmd.mode === 'ingest') {
      setInput('')
      onOpenIngest()
      return
    }
    if (cmd.mode === 'send' && cmd.template) {
      onSend(cmd.template)
      setInput('')
      return
    }
    if (cmd.mode === 'fill' && cmd.template) {
      setInput(cmd.template)
      requestAnimationFrame(() => taRef.current?.focus())
    }
  }

  return (
    <div className="relative px-4 pb-4 pt-1 shrink-0 bg-ink">
      {/* Fade: chat content scrolls out under the chips/composer */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-12 h-12 bg-gradient-to-t from-ink to-transparent"
      />
      <div className="max-w-3xl mx-auto">
        {/* Input row + drop zone */}
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={`relative rounded-2xl border bg-surface transition ${
            dragging ? 'border-primary bg-primary/5' : recording ? 'border-crose/60' : 'border-line focus-within:border-line2'
          }`}
        >
          {/* "/"-Command-Palette */}
          {slashActive && cmdMatches.length > 0 && (
            <div className="absolute bottom-full left-0 right-0 mb-2 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 py-2 z-30 max-h-[320px] overflow-y-auto animate-fade-up">
              <div className="px-3 pb-1 text-[10px] font-mono uppercase tracking-wider text-faint">
                {t('composer.palette_header')}
              </div>
              {cmdGroups.map((g) => (
                <div key={g}>
                  <div className="px-3 pt-2 pb-0.5 text-[10px] font-mono uppercase tracking-wider text-primary/70">
                    {g}
                  </div>
                  {cmdMatches
                    .filter((c) => c.group === g)
                    .map((c) => {
                      const first = cmdMatches[0]?.id === c.id
                      return (
                        <button
                          key={c.id}
                          onClick={() => runCommand(c)}
                          className={`w-full flex items-center gap-2.5 px-3 py-2 text-left transition hover:bg-surface2 ${
                            first ? 'bg-surface2' : ''
                          }`}
                        >
                          <span className="text-[15px] w-5 text-center shrink-0">{c.icon}</span>
                          <span className="flex-1 min-w-0">
                            <span className="block text-[13px] text-paper truncate">{c.label}</span>
                            {c.hint && <span className="block text-[11px] text-faint truncate">{c.hint}</span>}
                          </span>
                          {first && <span className="text-[10px] font-mono text-faint shrink-0">↵</span>}
                        </button>
                      )
                    })}
                </div>
              ))}
            </div>
          )}

          {dragging && (
            <div className="absolute inset-0 z-10 rounded-2xl bg-ink/80 backdrop-blur-sm flex items-center justify-center pointer-events-none animate-fade-in">
              <span className="text-[13px] font-medium text-primary flex items-center gap-2">
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                  <path d="M9 12V3M9 3L5.5 6.5M9 3l3.5 3.5M3 12v2a1 1 0 001 1h10a1 1 0 001-1v-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {t('composer.drop_hint')}
              </span>
            </div>
          )}

          <div className="flex items-end gap-1.5 px-2.5 py-2">
            {/* Ingest / source */}
            <button
              onClick={onOpenIngest}
              title={t('composer.ingest_title')}
              disabled={disabled}
              className="p-2 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition shrink-0 disabled:opacity-40"
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path d="M8.5 4.5l-4 4a3 3 0 004.24 4.24l5-5a2 2 0 00-2.83-2.83l-5 5a1 1 0 001.42 1.42l4.5-4.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <input
              ref={fileRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? [])
                if (files.length) onFiles(files)
                e.target.value = ''
              }}
            />

            {recording || transcribing ? (
              <div className="flex-1 flex items-center gap-2 py-2 text-[13px]">
                {recording ? (
                  <>
                    <span
                      className={`w-2.5 h-2.5 rounded-full bg-crose ${prefersReducedMotion() ? '' : 'animate-blink'}`}
                    />
                    <span className="text-paper">{t('composer.recording')}</span>
                    <span className="font-mono text-muted">
                      {String(Math.floor(elapsed / 60)).padStart(2, '0')}:
                      {String(elapsed % 60).padStart(2, '0')}
                    </span>
                  </>
                ) : (
                  <>
                    <svg width="15" height="15" viewBox="0 0 16 16" className="animate-spin text-primary">
                      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" fill="none" opacity="0.3" />
                      <path d="M8 2a6 6 0 016 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />
                    </svg>
                    <span className="text-muted">{t('composer.transcribing')}</span>
                  </>
                )}
              </div>
            ) : (
              <textarea
                ref={taRef}
                value={text}
                rows={1}
                disabled={disabled}
                onChange={(e) => {
                  setText(e.target.value)
                  autosize(e.target)
                }}
                onKeyDown={(e) => {
                  if (slashActive && cmdMatches.length) {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      runCommand(cmdMatches[0])
                      return
                    }
                    if (e.key === 'Escape') {
                      e.preventDefault()
                      setInput('')
                      return
                    }
                  }
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
                placeholder={disabled ? t('composer.placeholder_disabled') : t('composer.placeholder')}
                className="flex-1 resize-none bg-transparent outline-none text-[14px] text-paper placeholder:text-faint py-1.5 max-h-[180px] leading-relaxed"
              />
            )}

            {/* Voice */}
            <button
              onClick={recording ? stopRecording : startRecording}
              disabled={disabled || busy || transcribing}
              title={recording ? t('composer.stop_record') : t('composer.voice')}
              className={`p-2 rounded-lg shrink-0 transition disabled:opacity-40 disabled:cursor-not-allowed ${
                recording ? 'bg-crose/20 text-crose' : 'text-muted hover:text-paper hover:bg-surface2'
              }`}
            >
              {recording ? (
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                  <rect x="5" y="5" width="8" height="8" rx="1.5" fill="currentColor" />
                </svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                  <rect x="6.5" y="2" width="5" height="9" rx="2.5" stroke="currentColor" strokeWidth="1.4" />
                  <path d="M4 8a5 5 0 0010 0M9 13v3M6.5 16h5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                </svg>
              )}
            </button>

            {/* Stop (läuft + kein Text) — laufende Antwort zurückrufen (E11.1) */}
            {busy && !text.trim() ? (
              <button
                onClick={() => onStop?.()}
                title={t('composer.recall')}
                className="shrink-0 w-9 h-9 rounded-xl bg-crose/15 border border-crose/50 text-crose flex items-center justify-center hover:bg-crose/25 transition"
              >
                <svg width="14" height="14" viewBox="0 0 14 14">
                  <rect x="3" y="3" width="8" height="8" rx="1.5" fill="currentColor" />
                </svg>
              </button>
            ) : (
              /* Send — während busy reiht ein Klick die Nachricht ein (E11.2) */
              <button
                onClick={() => submit()}
                disabled={disabled || !text.trim() || recording}
                title={busy ? t('composer.enqueue') : t('composer.send')}
                className="shrink-0 w-9 h-9 rounded-full cta-grad flex items-center justify-center font-bold"
              >
                <svg width="17" height="17" viewBox="0 0 18 18" fill="none">
                  <path d="M9 15V4M9 4L4.5 8.5M9 4l4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        </div>
        <p className="text-[10.5px] text-faint text-center mt-2">
          {sandbox ? t('composer.footer_sandbox') : t('composer.footer_local')}
        </p>
      </div>
    </div>
  )
}
