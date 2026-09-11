import { useRef, useState } from 'react'
import { api } from '../api'
import { useT } from '../i18n'

// Owner Launch Wizard — Pflicht-Setup: der Owner MUSS es ausfüllen (Default-Intel in den
// Graphen), bevor die App nutzbar wird. Fullscreen, minimal, keine Struktur-Linien.
// Quellen: URL · Text · Datei (PDF/CSV/… ) · Connector (Google Workspace, M365, …).
// Beim Aufbau wächst das Gedächtnis LIVE + interaktiv (draggable, hover, klick).
// "pre-training" = Graph aus Quellen (geerdet, Provenienz) — KEIN LLM-Weight-Training.

type SrcKind = 'url' | 'text' | 'file' | 'connector'
type Source = { kind: SrcKind; value: string; status?: 'idle' | 'run' | 'done' | 'err'; file?: File }
type GNode = { id: string; label: string; type: string; x: number; y: number; fresh?: boolean }

// Schritt-IDs; Titel + Tag werden zur Laufzeit per t() aufgelöst (ownersetup.step.<id>.*).
const STEP_KEYS = ['orgprofil', 'quellen', 'gedaechtnis', 'lernt'] as const

// Connectoren, die man im Setup vormerken kann (Verbindung via Bibliothek/OAuth).
const CONNECTORS = [
  { id: 'google-workspace', label: 'Google Workspace' },
  { id: 'microsoft-graph', label: 'Microsoft 365' },
  { id: 'dropbox', label: 'Dropbox' },
  { id: 'notion', label: 'Notion' },
  { id: 'hubspot', label: 'HubSpot' },
  { id: 'slack', label: 'Slack' },
]

const FILE_ACCEPT = '.pdf,.csv,.tsv,.txt,.md,.docx,.pptx,.xlsx,.json'
const TYPE_COLOR: Record<string, string> = {
  Company: '#7B95FF', Person: '#36C399', Product: '#9A8CEC', Organization: '#7B95FF',
  Document: '#8B92A8', FundingProgram: '#9A8CEC', Thought: '#C6CCDE', Konzept: '#C6CCDE',
}
const colorFor = (t: string) => TYPE_COLOR[t] || '#7B95FF'

// Phyllotaxis-Layout (organisch, überlappungsarm) in einem 600×380-Feld um die Mitte.
const HUB = { x: 300, y: 190 }
function place(i: number): { x: number; y: number } {
  const a = i * 2.399963 // goldener Winkel
  const r = 46 + 15 * Math.sqrt(i)
  return { x: HUB.x + r * Math.cos(a), y: HUB.y + r * Math.sin(a) }
}

export default function OwnerSetup({
  clientId, tenantName, initialName, initialProfile, initialSources, onClose, onGraphRefresh, mandatory = false,
}: {
  clientId: string
  tenantName: string
  initialName: string
  initialProfile: string
  initialSources: Source[]
  onClose: () => void
  onGraphRefresh: () => void
  mandatory?: boolean
}) {
  const t = useT()
  const [step, setStep] = useState(0)
  const [orgName, setOrgName] = useState(initialName || '')
  const [profile, setProfile] = useState(initialProfile || '')
  const [sources, setSources] = useState<Source[]>(initialSources?.length ? initialSources : [])
  const [addKind, setAddKind] = useState<SrcKind>('url')
  const [draft, setDraft] = useState('')
  const [running, setRunning] = useState(false)
  const [added, setAdded] = useState(0)
  const [gnodes, setGnodes] = useState<GNode[]>([])
  const [sel, setSel] = useState<GNode | null>(null)
  const dragRef = useRef<{ id: string } | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)

  // nur serialisierbare Quellen persistieren (Dateien sind transient).
  const persist = (completed: boolean, srcs = sources) =>
    api.saveTenantSetup({
      org_name: orgName,
      org_profile: profile,
      sources: srcs.filter((s) => s.kind !== 'file').map(({ kind, value }) => ({ kind, value })),
      completed,
    }).catch(() => {})

  const addTyped = () => {
    const v = draft.trim()
    if (!v) return
    setSources((s) => [...s, { kind: addKind, value: v, status: 'idle' }])
    setDraft('')
  }
  const addFiles = (fl: FileList | null) => {
    const arr = Array.from(fl ?? [])
    if (!arr.length) return
    setSources((s) => [...s, ...arr.map((f) => ({ kind: 'file' as const, value: f.name, status: 'idle' as const, file: f }))])
  }
  const toggleConnector = (id: string) =>
    setSources((s) => {
      const has = s.some((x) => x.kind === 'connector' && x.value === id)
      return has ? s.filter((x) => !(x.kind === 'connector' && x.value === id))
                 : [...s, { kind: 'connector', value: id, status: 'idle' }]
    })
  const removeSource = (i: number) => setSources((s) => s.filter((_, k) => k !== i))

  // Knoten live in den Graphen einstreuen (Phyllotaxis um den Hub) + Pop-in.
  const pushNodes = (items: { label: string; type?: string }[]) => {
    if (!items?.length) return
    setGnodes((cur) => {
      const seen = new Set(cur.map((n) => n.label.toLowerCase()))
      const out = [...cur]
      for (const it of items) {
        const lbl = String(it.label || '').trim()
        if (!lbl || seen.has(lbl.toLowerCase())) continue
        seen.add(lbl.toLowerCase())
        const p = place(out.length)
        out.push({ id: `${lbl}-${out.length}`, label: lbl.slice(0, 40), type: it.type || 'Thought', x: p.x, y: p.y, fresh: true })
      }
      return out
    })
  }

  const initialize = async () => {
    setRunning(true)
    // Hub-Knoten (die Org) zuerst.
    setGnodes([{ id: '__hub', label: (orgName.trim() || tenantName), type: 'Organization', x: HUB.x, y: HUB.y }])
    let nodes = 0
    const bump = (n: number) => { nodes += n; setAdded((a) => a + n) }

    if (orgName.trim() || profile.trim()) {
      try {
        const seed = `${orgName.trim() ? orgName.trim() + '. ' : ''}${profile.trim()}`
        const r = await api.capture(seed); pushNodes(r?.added ?? []); bump(r?.added?.length ?? 0)
      } catch { /* skip */ }
    }
    const next = [...sources]
    for (let i = 0; i < next.length; i++) {
      const s = next[i]
      next[i] = { ...s, status: 'run' }; setSources([...next])
      try {
        if (s.kind === 'connector') {
          next[i] = { ...s, status: 'idle' } // in der Bibliothek zu verbinden (kein Inline-Fetch)
        } else if (s.kind === 'url') {
          const r = await api.ingest({ client_id: clientId, levels: ['client'], url: s.value })
          const nn = (r as any)?.graph_delta?.nodes ?? []
          pushNodes(nn.map((n: any) => ({ label: n.label, type: n.type }))); bump(nn.length); next[i] = { ...s, status: 'done' }
        } else if (s.kind === 'file' && s.file) {
          const r = await api.ingest({ client_id: clientId, levels: ['client'], files: [s.file] })
          const nn = (r as any)?.graph_delta?.nodes ?? []
          pushNodes(nn.map((n: any) => ({ label: n.label, type: n.type }))); bump(nn.length); next[i] = { ...s, status: 'done' }
        } else if (s.kind === 'text') {
          const r = await api.capture(s.value); pushNodes(r?.added ?? []); bump(r?.added?.length ?? 0); next[i] = { ...s, status: 'done' }
        }
      } catch { next[i] = { ...s, status: 'err' } }
      setSources([...next])
    }
    await persist(true, next)
    onGraphRefresh()
    setRunning(false)
    setStep(3)
  }

  const canForward = step === 0 ? orgName.trim().length > 0 : true
  const forward = () => { if (step < 2 && canForward) { persist(false); setStep(step + 1) } }
  const goTo = (i: number) => { if (i <= step) setStep(i) }

  // ---- Drag der Live-Graph-Knoten (Client→viewBox 600×380) ----
  const toView = (e: React.PointerEvent) => {
    const r = svgRef.current?.getBoundingClientRect()
    if (!r) return null
    return { x: ((e.clientX - r.left) / r.width) * 600, y: ((e.clientY - r.top) / r.height) * 380 }
  }
  const onNodeDown = (e: React.PointerEvent, id: string) => {
    if (id === '__hub') return
    e.preventDefault(); dragRef.current = { id }
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }
  const onMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return
    const p = toView(e); if (!p) return
    const id = dragRef.current.id
    setGnodes((cur) => cur.map((n) => (n.id === id ? { ...n, x: p.x, y: p.y, fresh: false } : n)))
  }
  const onUp = () => { dragRef.current = null }

  const hub = gnodes.find((n) => n.id === '__hub')
  const petals = gnodes.filter((n) => n.id !== '__hub')

  const LiveGraph = (
    <div className="rounded-xl bg-surface2/60 p-2">
      <svg
        ref={svgRef}
        viewBox="0 0 600 380"
        className="w-full h-[340px] touch-none select-none"
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
      >
        {hub && petals.map((n) => (
          <line key={`e-${n.id}`} x1={hub.x} y1={hub.y} x2={n.x} y2={n.y}
                stroke="#3a4157" strokeWidth={1} opacity={0.6} />
        ))}
        {gnodes.map((n) => {
          const isHub = n.id === '__hub'
          const active = sel?.id === n.id
          const r = isHub ? 9 : active ? 8 : 6
          return (
            <g key={n.id} transform={`translate(${n.x},${n.y})`}
               style={{ cursor: isHub ? 'default' : 'grab' }}
               onPointerDown={(e) => onNodeDown(e, n.id)}
               onClick={() => !isHub && setSel(n)}>
              <circle r={r} fill={isHub ? '#FAFAF6' : colorFor(n.type)}
                      stroke={active ? '#fff' : 'transparent'} strokeWidth={active ? 2 : 0}
                      style={{ transition: 'r .15s', transformOrigin: 'center' }}
                      className={n.fresh ? 'wz-pop' : undefined} />
              <text x={r + 5} y={4} fontSize={isHub ? 13 : 11}
                    fill={isHub ? '#FAFAF6' : '#C6CCDE'} fontWeight={isHub ? 600 : 400}
                    style={{ pointerEvents: 'none' }}>{n.label}</text>
            </g>
          )
        })}
      </svg>
      <div className="flex items-center justify-between px-2 pt-1 text-[12px]">
        <span className="text-faint">{t('ownersetup.graph_hint', { n: petals.length })}</span>
        {sel && <span className="text-paper">{sel.label} <span className="text-faint">· {sel.type}</span></span>}
      </div>
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex bg-ink text-paper">
      <style>{`
        @keyframes wzSlide { from { opacity:0; transform:translateY(12px) } to { opacity:1; transform:none } }
        .wz-slide { animation: wzSlide .38s cubic-bezier(.22,1,.36,1) both }
        @keyframes wzSpin { to { transform: rotate(360deg) } }
        .wz-spin { display:inline-block; width:14px; height:14px; margin-right:9px; vertical-align:-2px;
          border:2px solid rgba(255,255,255,.35); border-top-color:#fff; border-radius:999px; animation: wzSpin .7s linear infinite }
        @keyframes wzPop { 0% { transform:scale(0); opacity:0 } 60% { transform:scale(1.35) } 100% { transform:scale(1); opacity:1 } }
        .wz-pop { animation: wzPop .5s cubic-bezier(.34,1.56,.64,1) both }
        @media (prefers-reduced-motion: reduce) { .wz-slide,.wz-spin,.wz-pop { animation: none } }
      `}</style>

      {/* ── Left: Steps ── */}
      <aside className="hidden sm:flex w-[268px] shrink-0 flex-col px-9 pt-10 pb-9">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-faint">c:node</div>
        <div className="mt-1 text-[13px] text-muted">{t('ownersetup.setup_label', { name: orgName.trim() || tenantName })}</div>
        <nav className="mt-14 flex flex-col gap-8">
          {STEP_KEYS.map((k, i) => {
            const done = i < step, active = i === step, reachable = i <= step
            return (
              <button key={k} onClick={() => goTo(i)} disabled={!reachable}
                className={`flex items-baseline gap-4 text-left transition-opacity ${reachable ? '' : 'opacity-30 cursor-default'}`}>
                <span className={`w-4 shrink-0 text-right font-mono text-[13px] tabular-nums ${active ? 'text-primary' : done ? 'text-primary/60' : 'text-faint'}`}>{done ? '✓' : i + 1}</span>
                <span className="leading-snug">
                  <span className={`block text-[15px] tracking-[-0.01em] ${active ? 'text-paper font-semibold' : done ? 'text-muted' : 'text-faint'}`}>{t(`ownersetup.step.${k}.title`)}</span>
                  <span className="mt-0.5 block font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint/60">{t(`ownersetup.step.${k}.tag`)}</span>
                </span>
              </button>
            )
          })}
        </nav>
      </aside>

      {/* ── Right ── */}
      <div className="relative flex flex-1 flex-col min-w-0">
        {!mandatory && (
          <button onClick={onClose} className="absolute right-8 top-7 z-10 text-[17px] leading-none text-faint hover:text-paper" aria-label={t('common.close')}>✕</button>
        )}

        <div className="flex flex-1 flex-col justify-center overflow-y-auto">
          <div key={step} className="wz-slide w-full px-10 sm:px-20 py-12">
            <div className="max-w-[46rem]">
              <div className="mb-1 font-mono text-[11px] uppercase tracking-[0.16em] text-faint">{t('ownersetup.step_counter', { n: step + 1 })}</div>
              <h2 className="mb-6 text-[26px] font-semibold tracking-[-0.025em]">{t(`ownersetup.step.${STEP_KEYS[step]}.title`)}</h2>

              {step === 0 && (
                <div className="space-y-5">
                  <p className="text-[15px] leading-relaxed text-muted">
                    {t('ownersetup.step0.p_a')}<span className="text-paper/80">{t('ownersetup.step0.p_name')}</span>{t('ownersetup.step0.p_b')}<span className="text-paper/80">{t('ownersetup.step0.p_c')}</span>
                  </p>
                  <div className="space-y-2">
                    <label className="block font-mono text-[10.5px] uppercase tracking-[0.14em] text-faint">{t('ownersetup.name_label')}</label>
                    <input
                      autoFocus
                      value={orgName}
                      onChange={(e) => setOrgName(e.target.value)}
                      placeholder={t('ownersetup.name_ph')}
                      className="w-full rounded-xl bg-surface2 px-4 py-3 text-[16px] font-medium text-paper placeholder:text-faint/50 outline-none ring-1 ring-transparent transition focus:ring-primary/50"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="block font-mono text-[10.5px] uppercase tracking-[0.14em] text-faint">{t('ownersetup.desc_label')}</label>
                    <textarea value={profile} onChange={(e) => setProfile(e.target.value)} rows={6}
                      placeholder={t('ownersetup.desc_ph')}
                      className="w-full resize-y rounded-xl bg-surface2 p-4 text-[15px] leading-relaxed text-paper placeholder:text-faint/50 outline-none ring-1 ring-transparent transition focus:ring-primary/50" />
                  </div>
                </div>
              )}

              {step === 1 && (
                <div className="space-y-5">
                  <p className="text-[15px] leading-relaxed text-muted">
                    {t('ownersetup.step1.p_a')}<span className="text-paper/80">{t('ownersetup.step1.p_lib')}</span>{t('ownersetup.step1.p_b')}
                  </p>

                  {/* Typ-Umschalter */}
                  <div className="flex gap-1 rounded-lg bg-surface2 p-1 text-[13px] w-max">
                    {(['url', 'text', 'file', 'connector'] as SrcKind[]).map((k) => (
                      <button key={k} onClick={() => setAddKind(k)}
                        className={`rounded-md px-3 py-1.5 capitalize transition ${addKind === k ? 'bg-primary text-white' : 'text-muted hover:text-paper'}`}>
                        {t(`ownersetup.kind.${k}`)}
                      </button>
                    ))}
                  </div>

                  {(addKind === 'url' || addKind === 'text') && (
                    <div className="flex gap-2">
                      <input value={draft} onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && addTyped()}
                        placeholder={addKind === 'url' ? 'https://…' : t('ownersetup.text_ph')}
                        className="flex-1 rounded-lg bg-surface2 px-3.5 py-2.5 text-[14px] text-paper placeholder:text-faint/50 outline-none ring-1 ring-transparent focus:ring-primary/50" />
                      <button onClick={addTyped} className="rounded-full bg-primary px-4 py-2.5 text-[14px] font-medium text-white transition hover:opacity-90">{t('ownersetup.add')}</button>
                    </div>
                  )}

                  {addKind === 'file' && (
                    <div>
                      <input ref={fileRef} type="file" multiple accept={FILE_ACCEPT} className="hidden"
                        onChange={(e) => { addFiles(e.target.files); if (fileRef.current) fileRef.current.value = '' }} />
                      <button onClick={() => fileRef.current?.click()}
                        className="rounded-lg border border-dashed border-line px-4 py-3 text-[14px] text-muted transition hover:border-primary/60 hover:text-paper">
                        {t('ownersetup.choose_files')} <span className="text-faint">{t('ownersetup.file_formats')}</span>
                      </button>
                    </div>
                  )}

                  {addKind === 'connector' && (
                    <div className="flex flex-wrap gap-2">
                      {CONNECTORS.map((c) => {
                        const on = sources.some((s) => s.kind === 'connector' && s.value === c.id)
                        return (
                          <button key={c.id} onClick={() => toggleConnector(c.id)}
                            className={`rounded-full px-3.5 py-1.5 text-[13px] transition ${on ? 'bg-primary text-white' : 'bg-surface2 text-muted hover:text-paper'}`}>
                            {on ? '✓ ' : '+ '}{c.label}
                          </button>
                        )
                      })}
                    </div>
                  )}

                  {/* gesammelte Quellen */}
                  <ul className="space-y-2">
                    {sources.length === 0 && <li className="py-1 text-[13.5px] text-faint">{t('ownersetup.sources_empty')}</li>}
                    {sources.map((s, i) => (
                      <li key={i} className="flex items-center justify-between gap-3 rounded-lg bg-surface2 px-4 py-3">
                        <span className="flex min-w-0 items-center gap-3">
                          <span className="w-16 shrink-0 font-mono text-[10px] uppercase text-faint">{s.kind}</span>
                          <span className="truncate text-[14px] text-paper">
                            {s.kind === 'connector' ? (CONNECTORS.find((c) => c.id === s.value)?.label || s.value) : s.value}
                            {s.kind === 'connector' && <span className="ml-2 text-[11px] text-faint">{t('ownersetup.connector_note')}</span>}
                          </span>
                        </span>
                        <button onClick={() => removeSource(i)} className="shrink-0 text-faint hover:text-paper" aria-label={t('ownersetup.remove')}>✕</button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {step === 2 && (
                <div className="space-y-5">
                  {!running && gnodes.length === 0 ? (
                    <>
                      <p className="text-[15px] leading-relaxed text-muted">
                        {t('ownersetup.step2.p_a')}
                        <span className="text-paper/80"> {t('ownersetup.step2.p_b')}</span>
                      </p>
                      <div className="font-mono text-[12.5px] text-faint">
                        {profile.trim() ? t('ownersetup.stat_profile_yes') : t('ownersetup.stat_profile_no')} · {t('ownersetup.stat_sources', { n: sources.filter((s) => s.kind !== 'connector').length })}
                        {sources.some((s) => s.kind === 'connector') && ` · ${t('ownersetup.stat_connectors', { n: sources.filter((s) => s.kind === 'connector').length })}`}
                      </div>
                      <button onClick={initialize} className="rounded-full bg-primary px-6 py-3 text-[15px] font-medium text-white transition hover:opacity-90">{t('ownersetup.build')}</button>
                    </>
                  ) : (
                    <>
                      <p className="text-[14px] text-muted">
                        {running ? <><span className="wz-spin" />{t('ownersetup.building')}</> : t('ownersetup.build_done')}
                      </p>
                      {LiveGraph}
                    </>
                  )}
                </div>
              )}

              {step === 3 && (
                <div className="space-y-5">
                  <p className="text-[19px] font-semibold tracking-[-0.01em]">{t('ownersetup.done_title')}</p>
                  <p className="text-[15px] text-muted">{t('ownersetup.done_count', { n: added })}</p>
                  {gnodes.length > 1 && LiveGraph}
                  <p className="text-[15px] leading-relaxed text-muted">
                    {t('ownersetup.step3.p_a')}<span className="text-paper/80">{t('ownersetup.step3.p_learn')}</span>{t('ownersetup.step3.p_b')}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* footer */}
        <div className="flex h-[84px] items-center justify-between px-10 sm:px-20">
          <div>
            {step > 0 && step < 3 && !running && (
              <button onClick={() => setStep(step - 1)} className="text-[14px] text-faint transition hover:text-paper">← {t('common.back')}</button>
            )}
            {step === 0 && !mandatory && (
              <button onClick={onClose} className="text-[14px] text-faint transition hover:text-paper">{t('common.close')}</button>
            )}
          </div>
          <div>
            {step < 2 && (
              <button onClick={forward} disabled={!canForward}
                className="rounded-full bg-primary px-7 py-2.5 text-[14px] font-medium text-white transition hover:opacity-90 disabled:opacity-40">{t('common.next')} →</button>
            )}
            {step === 3 && (
              <button onClick={onClose} className="rounded-full bg-primary px-7 py-2.5 text-[14px] font-medium text-white transition hover:opacity-90">{t('ownersetup.finish')}</button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
