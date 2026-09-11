import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api'
import { brand } from '../brand'
import type { FormSpec, FormScoreResult } from '../types'
import { useT } from '../i18n'

// WICHTIG: Card/Header auf Modulebene — NICHT in FormRunner definieren. Sonst bekämen
// sie bei jedem Render eine neue Komponenten-Identität → React remountet den Teilbaum
// (Fokus-Verlust im Input + Flash durch erneutes animate-fade-in).
function RunnerCard({ children }: { children: ReactNode }) {
  return (
    <div className="pl-11 animate-fade-in">
      <div className="rounded-2xl border border-line bg-surface shadow-lg shadow-black/30 overflow-hidden">
        {children}
      </div>
    </div>
  )
}

function RunnerHeader({ title, sub, onCancel }: { title: string; sub?: string; onCancel: () => void }) {
  const t = useT()
  return (
    <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 min-w-0">
        <span className="w-6 h-6 rounded-md bg-primary/15 border border-primary/40 grid place-items-center text-[11px] font-bold text-primary shrink-0">
          {brand().initial}
        </span>
        <div className="min-w-0">
          <div className="text-[13.5px] font-display font-bold text-paper truncate">{title}</div>
          {sub && <div className="text-[10.5px] font-mono text-faint truncate">{sub}</div>}
        </div>
      </div>
      <button onClick={onCancel} title={t('common.cancel')} className="text-faint hover:text-paper transition shrink-0">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  )
}

// Inline-Chat-Runner für interaktive Tenant-Formulare (FraBö). Führt Sektion für
// Sektion durch, sammelt 0–max-Antworten (+ n/a), scored serverseitig und rendert
// den Report. Rein config-getrieben aus der FormSpec — kein formularspezifischer Code.
export default function FormRunner({
  formId,
  onComplete,
  onCancel,
}: {
  formId: string
  onComplete: (summaryMarkdown: string) => void
  onCancel: () => void
}) {
  const t = useT()
  const [spec, setSpec] = useState<FormSpec | null>(null)
  const [err, setErr] = useState('')
  const [step, setStep] = useState<'intro' | number | 'result'>('intro')
  const [subject, setSubject] = useState('')
  const [period, setPeriod] = useState('')
  const [answers, setAnswers] = useState<Record<string, (number | null)[]>>({})
  const [values, setValues] = useState<Record<string, string>>({}) // Erfassungs-Modus (fields)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<FormScoreResult | null>(null)

  useEffect(() => {
    let alive = true
    api
      .form(formId)
      .then((s) => {
        if (!alive) return
        setSpec(s)
        const init: Record<string, (number | null)[]> = {}
        s.sections.forEach((sec) => (init[sec.key] = (sec.questions ?? []).map(() => null)))
        setAnswers(init)
      })
      .catch(() => alive && setErr(t('form.load_error')))
    return () => {
      alive = false
    }
  }, [formId])

  const scored = useMemo(
    () => (spec ? !spec.sections.some((s) => (s.fields?.length ?? 0) > 0) : true),
    [spec],
  )
  const totalQ = useMemo(
    () => (spec ? spec.sections.reduce((n, s) => n + (s.fields?.length ?? s.questions?.length ?? 0), 0) : 0),
    [spec],
  )
  const answeredQ = useMemo(
    () =>
      scored
        ? Object.values(answers).flat().filter((v) => v !== null).length
        : Object.keys(values).filter((k) => String(values[k] ?? '').trim() !== '').length,
    [answers, values, scored],
  )

  if (err)
    return (
      <div className="pl-11 text-[13px] text-red-400">
        {err}{' '}
        <button className="underline text-muted" onClick={onCancel}>
          {t('form.close_link')}
        </button>
      </div>
    )
  if (!spec) return <div className="pl-11 text-[13px] text-muted animate-fade-in">{t('form.loading')}</div>

  const scale = spec.scale
  const steps = [0, spec.scale.max] // for typing only
  void steps

  const setAnswer = (key: string, qi: number, val: number) =>
    setAnswers((prev) => {
      const next = { ...prev, [key]: [...(prev[key] || [])] }
      next[key][qi] = next[key][qi] === val ? null : val
      return next
    })
  const setField = (key: string, val: string) => setValues((p) => ({ ...p, [key]: val }))

  async function evaluate() {
    if (!spec) return
    setSubmitting(true)
    try {
      let res
      if (scored) {
        const payload: Record<string, number[]> = {}
        spec.sections.forEach((sec) => {
          payload[sec.key] = (answers[sec.key] || []).map((v) => (v === null ? scale.na_value : v))
        })
        res = await api.submitForm(spec.id, {
          answers: payload, subject: subject.trim(), period: period.trim(), narrative: true,
        })
      } else {
        res = await api.submitForm(spec.id, {
          values, subject: subject.trim(), period: period.trim(), narrative: true,
        })
      }
      setResult(res)
      setStep('result')
    } catch {
      setErr(t('form.eval_error'))
    } finally {
      setSubmitting(false)
    }
  }

  function finish() {
    if (!result) return onComplete('')
    let md = ''
    if (result.score) {
      const s = result.score
      const rows = s.sections
        .map((x) => `- **${x.key} · ${x.title}**: ${x.score} / ${x.max}`)
        .join('\n')
      md =
        `**${s.title}** — ${subject || t('form.default_subject')}${period ? ` · ${period}` : ''}\n\n` +
        `**${t('form.total')}: ${s.total} / ${s.total_max}** (${s.percent} %)\n\n${rows}`
    } else if (result.report) {
      const kv = result.report.fields
        .filter((f) => String(f.value ?? '').trim() !== '')
        .map((f) =>
          f.type === 'textarea'
            ? `- **${f.label}**: ${f.value}`
            : `- **${f.label}**: ${f.value}${f.unit ? ` ${f.unit}` : ''}${f.prev ? ` _(${t('form.prev_short')} ${f.prev})_` : ''}`,
        )
        .join('\n')
      md = `**${spec!.title}** — ${subject || t('form.default_subject')}${period ? ` · ${period}` : ''}\n\n${kv}`
    }
    md +=
      (result.narrative ? `\n\n${result.narrative}` : '') +
      (result.persisted ? `\n\n_${t('form.saved_memory')}_` : '')
    onComplete(md)
  }

  async function exportPdf() {
    if (!result || !spec) return
    try {
      const blob = await api.formPdf(spec.id, {
        subject,
        period,
        answers: scored ? answers : undefined,
        values: scored ? undefined : values,
        narrative: result.narrative,
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download =
        `${spec.id}-${(subject || 'export').toLowerCase().replace(/\s+/g, '-')}` +
        `${period ? '-' + period : ''}.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 4000)
    } catch {
      setErr(t('form.pdf_error'))
    }
  }

  // ---- Intro ----
  if (step === 'intro')
    return (
      <RunnerCard>
        <RunnerHeader title={spec.title} onCancel={onCancel} sub={t('form.intro_sub', { cats: spec.sections.length, questions: totalQ })} />
        <div className="p-4">
          <p className="text-[12.5px] text-muted leading-relaxed mb-3">{spec.description}</p>
          {spec.subject_prompt && (
            <p className="text-[12.5px] text-paper/90 mb-2">{spec.subject_prompt}</p>
          )}
          <div className="flex flex-col sm:flex-row gap-2 mb-4">
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder={t('form.subject_placeholder')}
              className="flex-1 rounded-lg bg-surface2 border border-line px-3 py-2 text-[13px] text-paper placeholder:text-faint outline-none focus:border-primary/50"
            />
            <input
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder={t('form.period_placeholder')}
              className="sm:w-48 rounded-lg bg-surface2 border border-line px-3 py-2 text-[13px] text-paper placeholder:text-faint outline-none focus:border-primary/50"
            />
          </div>
          <div className="flex justify-end">
            <button
              onClick={() => setStep(0)}
              className="px-4 py-2 rounded-full bg-primary text-ink text-[13px] font-bold hover:opacity-90 transition"
            >
              {t('form.start')} →
            </button>
          </div>
        </div>
      </RunnerCard>
    )

  // ---- Result ----
  if (step === 'result' && result) {
    const s = result.score
    const rep = result.report
    return (
      <RunnerCard>
        <RunnerHeader title={spec.title} onCancel={onCancel} sub={`${subject || t('form.default_subject')}${period ? ` · ${period}` : ''}`} />
        <div className="p-4">
          {s && (
            <>
              <div className="flex items-end gap-3 mb-4">
                <div className="text-[34px] leading-none font-display font-extrabold text-primary">
                  {s.total}
                </div>
                <div className="text-[12px] text-muted mb-1">
                  / {s.total_max} <span className="text-faint">({s.percent} %)</span>
                </div>
              </div>
              <div className="flex flex-col gap-2 mb-4">
                {s.sections.map((x) => (
                  <div key={x.key} className="flex items-center gap-2">
                    <span className="w-5 text-[11px] font-mono font-bold text-primary text-center shrink-0">
                      {x.key}
                    </span>
                    <span className="w-40 text-[11.5px] text-muted truncate shrink-0">{x.title}</span>
                    <div className="flex-1 h-2.5 rounded-full bg-surface2 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${Math.max(2, (x.score / x.max) * 100)}%` }}
                      />
                    </div>
                    <span className="w-14 text-[11px] font-mono text-paper/80 text-right shrink-0">
                      {x.score}/{x.max}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
          {rep && (
            <div className="flex flex-col gap-1.5 mb-4">
              {rep.fields
                .filter((f) => String(f.value ?? '').trim() !== '')
                .map((f) => (
                  <div key={f.key} className="flex items-baseline gap-2 text-[12.5px]">
                    <span className="w-48 text-muted shrink-0 truncate">{f.label}</span>
                    <span className="text-paper font-medium">
                      {String(f.value)}
                      {f.unit ? <span className="text-faint"> {f.unit}</span> : null}
                    </span>
                    {f.prev ? (
                      <span className="text-[10.5px] font-mono text-faint ml-auto shrink-0">
                        {f.prev_label || t('form.prev_short')}: {f.prev}
                      </span>
                    ) : null}
                  </div>
                ))}
            </div>
          )}
          {result.narrative && (
            <div className="rounded-lg bg-surface2 border border-line p-3 text-[12.5px] text-paper/90 leading-relaxed whitespace-pre-wrap mb-3">
              {result.narrative}
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-faint">
              {result.persisted ? `✓ ${t('form.saved_memory_inline')}` : ''}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  setResult(null)
                  setStep('intro')
                }}
                className="px-3 py-1.5 rounded-lg border border-line text-muted text-[12.5px] hover:text-paper transition"
              >
                {t('common.new')}
              </button>
              <button
                onClick={exportPdf}
                className="px-3 py-1.5 rounded-lg border border-line text-muted text-[12.5px] hover:text-paper hover:border-primary/40 transition inline-flex items-center gap-1.5"
                title={t('form.export_pdf_title')}
              >
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                  <path d="M8 2v8m0 0L5 7m3 3l3-3M3 13h10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                PDF
              </button>
              <button
                onClick={finish}
                className="px-4 py-1.5 rounded-full bg-primary text-ink text-[12.5px] font-bold hover:opacity-90 transition"
              >
                {t('form.to_chat')}
              </button>
            </div>
          </div>
        </div>
      </RunnerCard>
    )
  }

  // ---- Section step ----
  const idx = step as number
  const sec = spec.sections[idx]
  const isLast = idx === spec.sections.length - 1
  const secFields = sec.fields ?? []
  const secQuestions = sec.questions ?? []
  const fieldMode = secFields.length > 0
  const secTotal = fieldMode ? secFields.length : secQuestions.length
  const secAnswered = fieldMode
    ? secFields.filter((f) => String(values[f.key] ?? '').trim() !== '').length
    : (answers[sec.key] || []).filter((v) => v !== null).length
  const scaleVals = Array.from({ length: scale.max - scale.min + 1 }, (_, i) => scale.min + i)
  const inputCls =
    'rounded-lg bg-surface2 border border-line px-3 py-1.5 text-[13px] text-paper placeholder:text-faint outline-none focus:border-primary/50'

  return (
    <RunnerCard>
      <RunnerHeader title={spec.title} onCancel={onCancel} sub={t('form.section_sub', { current: idx + 1, total: spec.sections.length, answered: answeredQ, questions: totalQ })} />
      {/* progress */}
      <div className="h-1 bg-surface2">
        <div className="h-full bg-primary transition-all" style={{ width: `${(answeredQ / totalQ) * 100}%` }} />
      </div>
      <div className="px-4 py-3 border-b border-line flex items-center gap-2">
        <span className="w-6 h-6 rounded-md bg-primary text-ink grid place-items-center text-[12px] font-extrabold shrink-0">
          {sec.key.slice(0, 1).toUpperCase()}
        </span>
        <span className="text-[13.5px] font-display font-bold text-paper">{sec.title}</span>
        <span className="ml-auto text-[10.5px] font-mono text-faint">
          {secAnswered}/{secTotal}
        </span>
      </div>
      {sec.description && (
        <div className="px-4 py-2 border-b border-line bg-surface2/40 text-[11.5px] text-muted leading-relaxed">
          {sec.description}
        </div>
      )}
      <div className="max-h-[46vh] overflow-y-auto divide-y divide-line/60">
        {/* --- Erfassungs-Modus: getypte Felder --- */}
        {fieldMode &&
          secFields.map((f) => (
            <div key={f.key} className="px-4 py-2.5">
              <div className="flex items-baseline gap-2 mb-1">
                <span className="text-[12.5px] text-paper/90">{f.label}</span>
                {f.unit && <span className="text-[10.5px] font-mono text-faint">({f.unit})</span>}
                {f.prev && (
                  <span className="ml-auto text-[10.5px] font-mono text-faint">
                    {f.prev_label || t('form.prev_quarter')}: <b className="text-muted">{f.prev}</b>
                  </span>
                )}
              </div>
              {f.help && <div className="text-[10.5px] text-faint mb-1">{f.help}</div>}
              {f.type === 'textarea' ? (
                <textarea
                  rows={2}
                  value={values[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  className={`${inputCls} w-full resize-y`}
                />
              ) : f.type === 'select' ? (
                <select
                  value={values[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                  className={`${inputCls} w-full`}
                >
                  <option value="">{t('form.select_placeholder')}</option>
                  {(f.options ?? []).map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  inputMode={f.type === 'number' ? 'decimal' : 'text'}
                  value={values[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  className={`${inputCls} w-full text-end font-medium`}
                />
              )}
            </div>
          ))}
        {/* --- Score-Modus: Aussagen mit 0..max-Skala --- */}
        {!fieldMode &&
          secQuestions.map((q, qi) => {
            const cur = answers[sec.key]?.[qi] ?? null
            return (
              <div key={qi} className="px-4 py-2.5">
                <div className="text-[12.5px] text-paper/90 mb-1.5 leading-snug">
                  <span className="text-faint font-mono mr-1">{qi + 1}.</span>
                  {q}
                </div>
                <div className="flex flex-wrap gap-1">
                  {scaleVals.map((v) => (
                    <button
                      key={v}
                      title={scale.labels[v - scale.min] || String(v)}
                      onClick={() => setAnswer(sec.key, qi, v)}
                      className={`w-8 h-7 rounded-md text-[12px] font-mono border transition ${
                        cur === v
                          ? 'bg-primary text-ink border-primary font-bold'
                          : 'bg-surface2 border-line text-muted hover:text-paper hover:border-primary/40'
                      }`}
                    >
                      {v}
                    </button>
                  ))}
                  <button
                    title={scale.na_label}
                    onClick={() => setAnswer(sec.key, qi, scale.na_value)}
                    className={`px-2 h-7 rounded-md text-[11px] font-mono border transition ${
                      cur === scale.na_value
                        ? 'bg-muted/30 text-paper border-muted'
                        : 'bg-surface2 border-line text-faint hover:text-muted'
                    }`}
                  >
                    n/a
                  </button>
                </div>
              </div>
            )
          })}
      </div>
      {/* scale legend (nur Score-Modus) */}
      {!fieldMode && (
        <div className="px-4 py-2 border-t border-line flex flex-wrap gap-x-3 gap-y-0.5">
          {scale.labels.map((l, i) => (
            <span key={i} className="text-[10px] text-faint">
              <b className="text-muted font-mono">{scale.min + i}</b> {l}
            </span>
          ))}
        </div>
      )}
      {/* nav */}
      <div className="px-4 py-3 border-t border-line flex items-center justify-between">
        <button
          onClick={() => setStep(idx === 0 ? 'intro' : idx - 1)}
          className="px-3 py-1.5 rounded-lg border border-line text-muted text-[12.5px] hover:text-paper transition"
        >
          ← {t('common.back')}
        </button>
        {isLast ? (
          <button
            onClick={evaluate}
            disabled={submitting}
            className="px-4 py-1.5 rounded-full bg-primary text-ink text-[12.5px] font-bold hover:opacity-90 transition disabled:opacity-60"
          >
            {submitting ? t('form.sending') : scored ? t('form.evaluate') : t('form.create_report')}
          </button>
        ) : (
          <button
            onClick={() => setStep(idx + 1)}
            className="px-4 py-1.5 rounded-full bg-primary text-ink text-[12.5px] font-bold hover:opacity-90 transition"
          >
            {t('common.next')} →
          </button>
        )}
      </div>
    </RunnerCard>
  )
}
