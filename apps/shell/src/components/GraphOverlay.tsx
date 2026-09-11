import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import type { GNode, Graph } from '../types'
import { TYPE_COLOR, typeColor } from '../theme'
import { useT } from '../i18n'

// Minimale, dependency-freie Kollisions-Force (d3-force ist unter pnpm nicht direkt
// auflösbar). O(n²) — bei ≤ einigen hundert Knoten vernachlässigbar. Kompatibel zur
// d3-force-Signatur: force(alpha) + force.initialize(nodes).
function collideForce(radius: (n: any) => number, strength = 0.9) {
  let nodes: any[] = []
  const force = () => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]
        let dx = (b.x ?? 0) - (a.x ?? 0)
        let dy = (b.y ?? 0) - (a.y ?? 0)
        if (dx === 0 && dy === 0) { dx = 0.01; dy = 0.01 }
        const dist = Math.hypot(dx, dy)
        const min = radius(a) + radius(b)
        if (dist < min) {
          const push = ((min - dist) / dist) * strength * 0.5
          const ox = dx * push, oy = dy * push
          a.vx -= ox; a.vy -= oy; b.vx += ox; b.vy += oy
        }
      }
    }
  }
  ;(force as any).initialize = (n: any[]) => { nodes = n }
  return force
}

// Ebenen-Labels für die optionale Layer-Legende. `preview` = kuratierte NENA-Vorschau-Scheibe
// (Free-Sandbox-Teaser); die volle Market-/Mesh-Tiefe ist bezahlt.
// Strings kommen zur Laufzeit aus dem Katalog (graph.layer.<id>); unbekannte Ebenen
// fallen auf ihre rohe ID zurück.
const KNOWN_LAYERS = ['client', 'market', 'mesh', 'base', 'preview']

export default function GraphOverlay({
  graph,
  highlight,
  clientName,
  onClose,
  focusId,
}: {
  graph: Graph
  highlight: string[]
  clientName?: string
  onClose: () => void
  focusId?: string | null
}) {
  const t = useT()
  const wrap = useRef<HTMLDivElement>(null)
  const fg = useRef<any>(null)
  const [size, setSize] = useState({ w: 800, h: 600 })
  const [selected, setSelected] = useState<GNode | null>(null)
  const [query, setQuery] = useState('')
  const [showOrphans, setShowOrphans] = useState(true)
  const [layersOff, setLayersOff] = useState<Set<string>>(new Set())
  const [showEdgeLabels, setShowEdgeLabels] = useState(true)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    if (!wrap.current) return
    const ro = new ResizeObserver((e) => {
      const r = e[0].contentRect
      setSize({ w: r.width, h: r.height })
    })
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  const layerOf = (n: GNode): string => ((n.props as any)?.layer as string) || 'client'

  // Grad je Knoten (für Orphan-Erkennung) + vorhandene Ebenen.
  const { deg, layersPresent } = useMemo(() => {
    const d = new Map<string, number>()
    for (const e of graph.edges) {
      d.set(e.source, (d.get(e.source) ?? 0) + 1)
      d.set(e.target, (d.get(e.target) ?? 0) + 1)
    }
    const ls = new Set<string>()
    graph.nodes.forEach((n) => ls.add(layerOf(n)))
    return { deg: d, layersPresent: Array.from(ls) }
  }, [graph])

  const orphanCount = useMemo(
    () => graph.nodes.filter((n) => (deg.get(n.id) ?? 0) === 0).length,
    [graph, deg],
  )

  // Gefilterte Sicht: Ebenen-Toggle + Orphan-Toggle. Kanten nur zwischen sichtbaren Knoten.
  const data = useMemo(() => {
    const visible = graph.nodes.filter(
      (n) => !layersOff.has(layerOf(n)) && (showOrphans || (deg.get(n.id) ?? 0) > 0),
    )
    const ids = new Set(visible.map((n) => n.id))
    return {
      nodes: visible.map((n) => ({ ...n })),
      links: graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ ...e })),
    }
  }, [graph, layersOff, showOrphans, deg])
  // Semantische Node-Suche: über Label + Typ + Prop-Werte, alle Tokens müssen matchen.
  const q = query.trim().toLowerCase()
  const matchIds = useMemo(() => {
    const ids = new Set<string>()
    if (!q) return ids
    const toks = q.split(/\s+/).filter(Boolean)
    for (const n of graph.nodes) {
      const propStr = n.props
        ? Object.entries(n.props).map(([k, v]) => `${k} ${v}`).join(' ')
        : ''
      const hay = `${n.label ?? ''} ${n.type ?? ''} ${propStr}`.toLowerCase()
      if (toks.every((tok) => hay.includes(tok))) ids.add(n.id)
    }
    return ids
  }, [q, graph])

  // Aktives Highlight: Suchtreffer haben Vorrang, sonst die vom Chat gelieferten Highlights.
  const hi = useMemo(
    () => (q ? matchIds : new Set(highlight)),
    [q, matchIds, highlight],
  )

  // Kräfte tunen: stärkere Abstoßung + echte Kollisions-Force → weniger Overlap.
  useEffect(() => {
    const t = setTimeout(() => {
      const g = fg.current
      if (!g?.d3Force) return
      g.d3Force('charge')?.strength(-150).distanceMax(360)
      g.d3Force('link')?.distance(42)
      g.d3Force('collide', collideForce((n: any) => (n.id === selected?.id ? 12 : 9)))
      g.d3ReheatSimulation?.()
    }, 120)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.nodes.length])

  useEffect(() => {
    const t = setTimeout(() => fg.current?.zoomToFit?.(500, 60), 350)
    return () => clearTimeout(t)
  }, [data.nodes.length])

  // Bei Suche auf die Treffer zoomen.
  useEffect(() => {
    if (q && matchIds.size > 0) {
      const t = setTimeout(
        () => fg.current?.zoomToFit?.(600, 80, (n: any) => matchIds.has(n.id)),
        120,
      )
      return () => clearTimeout(t)
    }
  }, [q, matchIds])

  // Angeklickte Quelle: existiert der Knoten im Graph, wird er selektiert und
  // angezoomt (direkt gehighlightet einsehbar). Sonst bleibt es beim Fit-all.
  useEffect(() => {
    if (!focusId) return
    const node = graph.nodes.find((n) => n.id === focusId)
    if (!node) return
    setSelected(node)
    const t = setTimeout(
      () => fg.current?.zoomToFit?.(650, 140, (n: any) => n.id === focusId),
      520,
    )
    return () => clearTimeout(t)
  }, [focusId, graph.nodes])

  const neighbors = useMemo(() => {
    if (!selected) return []
    return graph.edges
      .filter((e) => e.source === selected.id || e.target === selected.id)
      .map((e) => {
        const outgoing = e.source === selected.id
        const otherId = outgoing ? e.target : e.source
        return { rel: e.rel, provenance: e.provenance, outgoing, other: graph.nodes.find((n) => n.id === otherId) }
      })
  }, [selected, graph])

  const usedTypes = useMemo(() => {
    const s = new Set<string>()
    graph.nodes.forEach((n) => s.add(n.type))
    return Array.from(s)
  }, [graph])

  const layerLabel = (l: string) => (KNOWN_LAYERS.includes(l) ? t(`graph.layer.${l}`) : l)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-0 md:p-8 animate-fade-in">
      <div className="absolute inset-0 bg-ink/80 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full h-full max-w-6xl rounded-none md:rounded-2xl border border-line bg-surface overflow-hidden flex flex-col animate-overlay-in shadow-2xl shadow-black/60">
        {/* header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-line shrink-0">
          <div className="flex items-center gap-2.5">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" className="text-primary">
              <path d="M9 2l6 3.5v7L9 16l-6-3.5v-7L9 2z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
              <circle cx="9" cy="9" r="1.6" fill="currentColor" />
            </svg>
            <h2 className="font-display font-bold text-[15px] text-paper">{t('graph.title')}</h2>
            <span className="hidden sm:inline text-[11px] font-mono text-muted">
              {clientName ? `${clientName} · ` : ''}
              {t('graph.stats', { nodes: graph.nodes.length, edges: graph.edges.length })}
            </span>
          </div>

          {/* Node-Suche: findet & highlightet passende Knoten */}
          <div className="flex items-center gap-2 flex-1 justify-end">
            <div className="relative w-full max-w-[320px]">
              <svg
                width="14" height="14" viewBox="0 0 16 16" fill="none"
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint pointer-events-none"
              >
                <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
                <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Escape' && (query ? (e.stopPropagation(), setQuery('')) : onClose())}
                placeholder={t('graph.search_placeholder')}
                className="w-full rounded-lg bg-surface2 border border-line pl-8 pr-16 py-1.5 text-[12.5px] text-paper placeholder:text-faint outline-none focus:border-primary/50 transition"
              />
              {q && (
                <span className="absolute right-7 top-1/2 -translate-y-1/2 text-[10.5px] font-mono text-faint">
                  {t('graph.hits', { count: matchIds.size })}
                </span>
              )}
              {query && (
                <button
                  onClick={() => setQuery('')}
                  title={t('graph.clear_search')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-paper transition"
                >
                  <svg width="12" height="12" viewBox="0 0 14 14">
                    <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                  </svg>
                </button>
              )}
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition shrink-0"
            title={t('graph.close_esc')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex-1 flex min-h-0 relative">
          {/* graph canvas */}
          <div ref={wrap} className="flex-1 relative min-w-0 bg-ink">
            {graph.nodes.length === 0 ? (
              <div className="absolute inset-0 flex items-center justify-center px-8 text-center text-[13px] text-muted">
                <div className="max-w-sm">
                  <div className="font-display font-semibold text-paper text-[15px] mb-1.5">
                    {t('graph.empty_title')}
                  </div>
                  {t('graph.empty_body')}
                </div>
              </div>
            ) : (
              <ForceGraph2D
                ref={fg}
                width={size.w}
                height={size.h}
                graphData={data}
                backgroundColor="#F7F8FC"
                cooldownTicks={120}
                linkColor={() => 'rgba(140,140,148,0.35)'}
                linkDirectionalArrowLength={3}
                linkDirectionalArrowRelPos={1}
                linkWidth={(l: any) =>
                  hi.has(l.source.id ?? l.source) && hi.has(l.target.id ?? l.target) ? 2.4 : 0.7
                }
                linkCanvasObjectMode={() => (showEdgeLabels ? 'after' : undefined)}
                linkCanvasObject={(link: any, ctx, scale) => {
                  if (!showEdgeLabels) return
                  const sId = link.source.id ?? link.source
                  const tId = link.target.id ?? link.target
                  const linkHi = hi.has(sId) && hi.has(tId)
                  // Nur ab Zoomstufe (oder wenn beide Endpunkte gehighlightet) → kein Text-Matsch.
                  if (scale < 2.2 && !linkHi) return
                  const label = link.rel
                  if (!label || typeof link.source !== 'object' || typeof link.target !== 'object') return
                  const mx = (link.source.x + link.target.x) / 2
                  const my = (link.source.y + link.target.y) / 2
                  ctx.save()
                  ctx.font = `${9 / scale + 1.5}px ui-monospace, monospace`
                  ctx.textAlign = 'center'
                  ctx.textBaseline = 'middle'
                  const tw = ctx.measureText(label).width
                  const pad = 2 / scale
                  ctx.fillStyle = 'rgba(255,255,255,0.85)'
                  ctx.fillRect(mx - tw / 2 - pad, my - (5 / scale + 1), tw + pad * 2, 10 / scale + 2)
                  ctx.fillStyle = linkHi ? '#181B26' : 'rgba(92,98,115,0.9)'
                  ctx.fillText(label, mx, my)
                  ctx.restore()
                }}
                onNodeClick={(n: any) => setSelected(n)}
                onBackgroundClick={() => setSelected(null)}
                nodeRelSize={6}
                nodePointerAreaPaint={(node: any, paintColor, ctx) => {
                  ctx.fillStyle = paintColor
                  ctx.beginPath()
                  ctx.arc(node.x, node.y, 10, 0, 2 * Math.PI)
                  ctx.fill()
                }}
                nodeCanvasObject={(node: any, ctx, scale) => {
                  const isHi = hi.has(node.id)
                  const isSel = node.id === selected?.id
                  const r = isSel ? 7.5 : isHi ? 6.5 : 5
                  ctx.globalAlpha = isHi || isSel || hi.size === 0 ? 1 : 0.3
                  ctx.beginPath()
                  ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
                  ctx.fillStyle = typeColor(node.type)
                  ctx.fill()
                  if (isSel) {
                    ctx.lineWidth = 2.5
                    ctx.strokeStyle = '#181B26'
                    ctx.stroke()
                  }
                  ctx.globalAlpha = 1
                  if (scale > 1.2 || isSel || isHi) {
                    const label = node.label?.length > 26 ? node.label.slice(0, 24) + '…' : node.label
                    ctx.font = `${isSel ? 600 : 400} ${10 / scale + 3.5}px Inter, sans-serif`
                    ctx.fillStyle = '#181B26'
                    ctx.textAlign = 'center'
                    ctx.fillText(label ?? '', node.x, node.y + r + 9)
                  }
                }}
              />
            )}

            {/* controls: Ebenen-Filter · Orphan-Toggle · Kanten-Labels */}
            {graph.nodes.length > 0 && (
              <div className="absolute top-3 left-3 flex flex-wrap items-center gap-1.5 bg-surface/80 backdrop-blur border border-line rounded-lg px-2 py-1.5">
                {layersPresent.length > 1 &&
                  layersPresent.map((l) => {
                    const on = !layersOff.has(l)
                    return (
                      <button
                        key={l}
                        onClick={() =>
                          setLayersOff((prev) => {
                            const next = new Set(prev)
                            next.has(l) ? next.delete(l) : next.add(l)
                            return next
                          })
                        }
                        className={`px-2 py-0.5 rounded-md text-[10.5px] font-mono border transition ${
                          on
                            ? 'bg-primary/15 border-primary/40 text-paper'
                            : 'bg-transparent border-line text-faint hover:text-muted'
                        }`}
                        title={t('graph.layer_toggle', { layer: l })}
                      >
                        {layerLabel(l)}
                      </button>
                    )
                  })}
                {layersPresent.length > 1 && orphanCount > 0 && <span className="w-px h-4 bg-line" />}
                {orphanCount > 0 && (
                  <button
                    onClick={() => setShowOrphans((v) => !v)}
                    className={`px-2 py-0.5 rounded-md text-[10.5px] font-mono border transition ${
                      showOrphans
                        ? 'bg-transparent border-line text-muted hover:text-paper'
                        : 'bg-primary/15 border-primary/40 text-paper'
                    }`}
                    title={t('graph.orphan_toggle_title')}
                  >
                    {showOrphans
                      ? t('graph.orphan_hide', { count: orphanCount })
                      : t('graph.orphan_show', { count: orphanCount })}
                  </button>
                )}
                <span className="w-px h-4 bg-line" />
                <button
                  onClick={() => setShowEdgeLabels((v) => !v)}
                  className={`px-2 py-0.5 rounded-md text-[10.5px] font-mono border transition ${
                    showEdgeLabels
                      ? 'bg-primary/15 border-primary/40 text-paper'
                      : 'bg-transparent border-line text-faint hover:text-muted'
                  }`}
                  title={t('graph.edge_labels_title')}
                >
                  {t('graph.edge_labels')}
                </button>
              </div>
            )}

            {/* legend */}
            {usedTypes.length > 0 && (
              <div className="absolute bottom-3 left-3 flex flex-wrap gap-x-3 gap-y-1 max-w-[70%] bg-surface/80 backdrop-blur border border-line rounded-lg px-3 py-2">
                {usedTypes.map((ty) => (
                  <span key={ty} className="flex items-center gap-1.5 text-[10.5px] text-muted">
                    <span className="w-2 h-2 rounded-full" style={{ background: TYPE_COLOR[ty] || '#8C8C94' }} />
                    {ty}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* node inspector — Desktop: feste rechte Spalte. Mobil (< md): Bottom-Sheet,
              erscheint nur bei ausgewähltem Knoten (überlagert den unteren Canvas-Rand). */}
          <div
            className={`bg-surface overflow-y-auto border-line
              absolute inset-x-0 bottom-0 z-20 max-h-[48%] border-t rounded-t-2xl shadow-2xl shadow-black/40
              md:static md:inset-auto md:z-auto md:max-h-none md:w-[300px] md:shrink-0 md:border-l md:border-t-0 md:rounded-none md:shadow-none md:block
              ${selected ? 'block' : 'hidden md:block'}`}
          >
            {!selected ? (
              <div className="p-4 text-[12.5px] text-muted">
                {t('graph.inspector_hint')}
              </div>
            ) : (
              <div className="p-4 animate-fade-in">
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-3 h-3 rounded-full" style={{ background: typeColor(selected.type) }} />
                  <span className="text-[10px] font-mono uppercase tracking-wide text-faint">{selected.type}</span>
                </div>
                <div className="font-display font-bold text-[15px] text-paper leading-tight mb-2">
                  {selected.label}
                </div>
                {Number((selected.props as any)?.merged_count) > 1 && (
                  <div className="mb-2 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-cmint/15 border border-cmint/40 text-cmint text-[10.5px] font-mono">
                    ⌾ {t('graph.merged', { count: (selected.props as any).merged_count })}
                  </div>
                )}
                {selected.props && Object.keys(selected.props).length > 0 && (
                  <div className="mb-3 flex flex-col gap-1">
                    {Object.entries(selected.props).map(([k, v]) => (
                      <div key={k} className="text-[11.5px]">
                        <span className="font-mono text-faint">{k}: </span>
                        <span className="text-paper/85">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="text-[10px] font-mono uppercase tracking-wider text-faint mb-1.5">
                  {t('graph.connections', { count: neighbors.length })}
                </div>
                <div className="flex flex-col gap-1.5">
                  {neighbors.map((nb, i) => (
                    <div key={i} className="text-[11.5px] rounded-lg bg-surface2 border border-line px-2.5 py-1.5">
                      <div>
                        <span className="text-primary font-mono">{nb.outgoing ? '→' : '←'} {nb.rel}</span>{' '}
                        <b className="text-paper">{nb.other?.label ?? '?'}</b>
                      </div>
                      {nb.provenance && (
                        <div className="text-faint mt-0.5">{t('graph.source', { source: nb.provenance })}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
