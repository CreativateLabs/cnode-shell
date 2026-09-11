import { useEffect, useState } from 'react'
import type { Artifact } from '../types'
import { api } from '../api'
import Markdown from './Markdown'
import { loadEnabledIds, outputConnectors, connName, type Connector } from '../connectors'
import { isArtifactSaved, markArtifactSaved } from '../persist'
import { useT } from '../i18n'

// Bekannte Artefakt-Arten → per Katalog-Key auflösbar (`artifact.kind.<art>`).
const KIND_KEYS = new Set(['dialog_protocol', 'memo', 'proposal', 'one_pager'])

export default function ArtifactPanel({
  artifact,
  onClose,
  onShare,
  tenantId,
  onNotice,
}: {
  artifact: Artifact
  onClose: () => void
  onShare: () => void
  tenantId?: string
  onNotice?: (msg: string) => void
}) {
  const t = useT()
  const [saved, setSaved] = useState(!!artifact.saved || isArtifactSaved(artifact.id))
  const [saving, setSaving] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  // Bei Wechsel des Artefakts den Speicher-Zustand zurücksetzen — dabei den
  // dauerhaft persistierten Save-Status berücksichtigen (CTA nicht erneut zeigen).
  useEffect(() => {
    setSaved(!!artifact.saved || isArtifactSaved(artifact.id))
    setSaving(false)
    setDismissed(false)
  }, [artifact.id, artifact.saved])

  async function saveToLibrary() {
    if (saving || saved) return
    setSaving(true)
    try {
      const r = await api.saveArtifact({
        id: artifact.id,
        kind: artifact.kind,
        title: artifact.title,
        markdown: artifact.markdown,
        thread_id: artifact.thread_id,
      })
      setSaved(true)
      markArtifactSaved(artifact.id)
      onNotice?.(
        r.graph_nodes > 0
          ? t('artifact.saved_notice_nodes', { count: r.graph_nodes })
          : t('artifact.saved_notice'),
      )
    } catch {
      onNotice?.(t('artifact.save_failed'))
    } finally {
      setSaving(false)
    }
  }

  function exportMd() {
    const blob = new Blob([artifact.markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${(artifact.title || artifact.kind || 'artifact').replace(/[^\w.-]+/g, '_')}.md`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  // Aktive Output-Connectoren des Mandanten (aus dem Katalog + localStorage).
  const enabled = new Set(loadEnabledIds(tenantId))
  const activeOutputs = outputConnectors().filter((c) => enabled.has(c.id))

  function sendTo(c: Connector) {
    if (c.id === 'pdf_export') {
      exportMd()
      return
    }
    onNotice?.(t('artifact.connector_setup', { name: connName(t, c) }))
  }

  return (
    <aside className="fixed inset-0 z-40 w-full border-l border-line bg-surface flex flex-col animate-panel-in md:static md:inset-auto md:z-auto md:w-[420px] md:max-w-[46vw] md:shrink-0">
      <div className="flex items-start justify-between gap-2 px-4 py-3 border-b border-line shrink-0">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-mono uppercase tracking-wide px-2 py-0.5 rounded-md bg-primary/12 text-primary border border-primary/25">
              {KIND_KEYS.has(artifact.kind) ? t(`artifact.kind.${artifact.kind}`) : artifact.kind}
            </span>
          </div>
          <h2 className="font-display font-bold text-[15px] text-paper leading-tight truncate">
            {artifact.title || t('artifact.title_fallback')}
          </h2>
          {artifact.created_at && (
            <div className="text-[10px] font-mono text-faint mt-0.5">{artifact.created_at}</div>
          )}
        </div>
        <button
          onClick={onClose}
          title={t('common.close')}
          className="p-1.5 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition shrink-0"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        <Markdown className="text-[13px] text-paper/90">{artifact.markdown || t('artifact.no_content')}</Markdown>
      </div>

      {/* Speicher-Entscheidung: Bibliothek (+ Graph) oder nur Session */}
      {saved ? (
        <div className="px-4 py-2.5 border-t border-line shrink-0 flex items-center gap-2 text-[12px] text-cmint">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
            <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('artifact.saved_line')}
        </div>
      ) : !dismissed ? (
        <div className="px-4 py-3 border-t border-line shrink-0 bg-primary/[0.05]">
          <div className="text-[12px] text-paper font-medium mb-0.5">{t('artifact.save_question')}</div>
          <p className="text-[11px] text-muted leading-snug mb-2.5">
            {t('artifact.save_desc_pre')}<b className="text-paper/80">{t('artifact.save_desc_bold')}</b>{t('artifact.save_desc_post')}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={saveToLibrary}
              disabled={saving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/15 border border-primary/45 text-primary text-[12px] font-semibold hover:bg-primary/25 hover:border-primary/70 transition disabled:opacity-60"
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <path d="M3 3.5A1.5 1.5 0 014.5 2h5L13 5.5v7A1.5 1.5 0 0111.5 14h-7A1.5 1.5 0 013 12.5v-9z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
                <path d="M6 2v3h3" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
              </svg>
              {saving ? t('artifact.saving') : t('artifact.save_to_library')}
            </button>
            <button
              onClick={() => setDismissed(true)}
              className="text-[11.5px] text-muted hover:text-paper transition"
            >
              {t('artifact.only_session')}
            </button>
          </div>
        </div>
      ) : (
        <div className="px-4 py-2 border-t border-line shrink-0 flex items-center justify-between gap-2">
          <span className="text-[11px] text-faint">{t('artifact.only_session_download')}</span>
          <button
            onClick={() => setDismissed(false)}
            className="text-[11px] text-primary/90 hover:text-primary transition"
          >
            {t('artifact.save_anyway')}
          </button>
        </div>
      )}

      {activeOutputs.length > 0 && (
        <div className="px-4 pt-3 border-t border-line shrink-0">
          <div className="text-[10px] font-mono uppercase tracking-wider text-faint mb-1.5">
            {t('artifact.send_to')}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {activeOutputs.map((c) => (
              <button
                key={c.id}
                onClick={() => sendTo(c)}
                title={c.live ? connName(t, c) : t('artifact.connector_setup_title', { name: connName(t, c) })}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[12px] transition ${
                  c.live
                    ? 'bg-surface2 border-primary/40 text-paper hover:bg-primary/10'
                    : 'bg-surface2 border-line text-muted hover:text-paper hover:border-line2'
                }`}
              >
                <span aria-hidden>{c.icon}</span>
                <span className="truncate max-w-[9rem]">{connName(t, c)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 px-4 py-3 border-t border-line shrink-0">
        <button
          onClick={exportMd}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-full bg-primary text-ink text-[13px] font-semibold hover:brightness-105 transition"
        >
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
            <path d="M8 2v8M8 10L5 7M8 10l3-3M3 13h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('artifact.export')}
        </button>
        <button
          onClick={onShare}
          className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-surface2 border border-line text-paper text-[13px] font-medium hover:border-line2 transition"
        >
          <svg width="15" height="15" viewBox="0 0 18 18" fill="none">
            <path d="M12 6a2 2 0 100-4 2 2 0 000 4zM6 11a2 2 0 100-4 2 2 0 000 4zM12 16a2 2 0 100-4 2 2 0 000 4z" stroke="currentColor" strokeWidth="1.4" />
            <path d="M7.6 8.1l2.8-1.6M7.6 9.9l2.8 1.6" stroke="currentColor" strokeWidth="1.4" />
          </svg>
          {t('artifact.share')}
        </button>
      </div>
    </aside>
  )
}
