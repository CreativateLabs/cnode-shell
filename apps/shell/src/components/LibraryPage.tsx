import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useT } from '../i18n'
import type { LibraryFile } from '../types'
import ConnectorLibrary from './ConnectorLibrary'

function fmtBytes(n?: number): string {
  if (!n && n !== 0) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtDate(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function fileTypeLabel(f: LibraryFile, fallback: string): string {
  if (f.type) return f.type
  const m = f.mime || ''
  if (m.includes('pdf')) return 'PDF'
  if (m.includes('word') || m.includes('docx')) return 'DOCX'
  if (m.includes('sheet') || m.includes('xlsx') || m.includes('excel')) return 'XLSX'
  if (m.includes('csv')) return 'CSV'
  if (m.startsWith('text/')) return 'TXT'
  const ext = f.name.split('.').pop()
  return (ext || fallback).toUpperCase()
}

// Library-Seite: Tenant-Dateien (Liste + Upload + Löschen) + Marketplace-Apps.
export default function LibraryPage({
  clientId,
  admin = false,
  onNotice,
  onClose,
  sandbox = false,
}: {
  clientId?: string
  admin?: boolean
  onOpenConnectors?: () => void
  onNotice: (msg: string) => void
  onClose: () => void
  sandbox?: boolean
}) {
  const t = useT()
  const [files, setFiles] = useState<LibraryFile[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [tab, setTab] = useState<'files' | 'marketplace'>('files')
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    setLoading(true)
    setErr(null)
    api
      .library(clientId)
      .then((r) => {
        setFiles(r.files)
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [clientId])

  useEffect(() => {
    load()
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load])

  async function upload(picked: File[]) {
    if (!picked.length) return
    setUploading(true)
    try {
      await api.libraryUpload(picked, clientId)
      onNotice(t('library.uploaded', { count: picked.length }))
      load()
    } catch {
      onNotice(t('library.upload_unavailable'))
    } finally {
      setUploading(false)
    }
  }

  async function del(f: LibraryFile) {
    if (!confirm(t('library.delete_confirm', { name: f.name }))) return
    try {
      await api.deleteLibraryFile(f.id)
      setFiles((xs) => xs.filter((x) => x.id !== f.id))
    } catch {
      onNotice(t('library.delete_unavailable'))
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-ink/80 backdrop-blur-sm p-0 md:p-8 flex items-center justify-center animate-fade-in">
      <div className="w-full h-full rounded-none md:max-w-4xl md:h-[82vh] md:rounded-2xl bg-surface border border-line shadow-2xl shadow-black/60 flex flex-col overflow-hidden animate-overlay-in">
        {/* header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-line shrink-0">
          <div className="flex items-center gap-2">
            <svg width="17" height="17" viewBox="0 0 18 18" fill="none" className="text-primary">
              <path d="M2.5 5A1.5 1.5 0 014 3.5h3l1.4 1.6H14A1.5 1.5 0 0115.5 6.6v6A1.5 1.5 0 0114 14.1H4A1.5 1.5 0 012.5 12.6V5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
            </svg>
            <h2 className="font-display font-bold text-[15px] text-paper">{t('library.title')}</h2>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition">
            <svg width="16" height="16" viewBox="0 0 14 14">
              <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* tabs */}
        <div className="flex items-center justify-between gap-2 px-4 pt-3 shrink-0">
          <div className="flex gap-1">
            {(['files', 'marketplace'] as const).map((tb) => (
              <button
                key={tb}
                onClick={() => setTab(tb)}
                className={`px-3 py-1.5 rounded-lg text-[12.5px] font-medium transition ${
                  tab === tb ? 'bg-surface3 text-paper' : 'text-muted hover:text-paper hover:bg-surface2'
                }`}
              >
                {tb === 'files'
                  ? `${t('library.tab_files')}${files.length ? ` (${files.length})` : ''}`
                  : t('library.tab_marketplace')}
              </button>
            ))}
          </div>
          {tab === 'files' && (
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary text-ink font-semibold text-[12.5px] disabled:opacity-50 hover:brightness-105 transition"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M8 11V3M8 3L5 6M8 3l3 3M3 11v2a1 1 0 001 1h8a1 1 0 001-1v-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {uploading ? t('library.uploading') : t('library.upload')}
            </button>
          )}
          <input
            ref={fileRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              const fs = Array.from(e.target.files ?? [])
              e.target.value = ''
              upload(fs)
            }}
          />
        </div>

        {/* body */}
        <div className="flex-1 overflow-y-auto p-4">
          {tab === 'files' ? (
            <>
              {err && <p className="text-[12px] text-crose/90 mb-3">{err}</p>}
              {loading ? (
                <p className="text-[12.5px] text-muted">{t('library.loading_files')}</p>
              ) : files.length === 0 ? (
                <div className="text-center py-14">
                  <p className="text-[13px] text-muted mb-1">{t('library.empty_title')}</p>
                  <p className="text-[12px] text-faint">
                    {t('library.empty_hint')}
                  </p>
                </div>
              ) : (
                <div className="rounded-xl border border-line overflow-hidden">
                  <div className="grid grid-cols-[1fr_auto_auto_auto] gap-3 px-3.5 py-2 bg-surface2 text-[10px] font-mono uppercase tracking-wider text-faint">
                    <span>{t('library.col_name')}</span>
                    <span className="text-right">{t('library.col_type')}</span>
                    <span className="text-right hidden sm:block">{t('library.col_date')}</span>
                    <span className="text-right w-6" />
                  </div>
                  <div className="divide-y divide-line">
                    {files.map((f) => (
                      <div
                        key={f.id}
                        className="grid grid-cols-[1fr_auto_auto_auto] gap-3 px-3.5 py-2.5 items-center hover:bg-surface2/50 transition"
                      >
                        <div className="min-w-0">
                          <div className="text-[13px] text-paper truncate" title={f.name}>
                            {f.name}
                          </div>
                          {(f.size || f.chars) && (
                            <div className="text-[10.5px] text-faint">
                              {[fmtBytes(f.size), f.chars ? t('library.chars', { count: f.chars.toLocaleString('de-DE') }) : '']
                                .filter(Boolean)
                                .join(' · ')}
                            </div>
                          )}
                        </div>
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface3 text-muted border border-line justify-self-end">
                          {fileTypeLabel(f, t('library.filetype_fallback'))}
                        </span>
                        <span className="text-[11.5px] text-muted text-right hidden sm:block justify-self-end">
                          {fmtDate(f.created_at)}
                        </span>
                        <button
                          onClick={() => del(f)}
                          title={t('common.delete')}
                          className="text-faint hover:text-crose transition justify-self-end"
                        >
                          <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                            <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 8.5a1 1 0 001 1h4a1 1 0 001-1l.5-8.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <p className="text-[12px] text-muted mb-4 max-w-2xl">
                {t('library.marketplace_intro')}
              </p>
              <ConnectorLibrary
                tenantId={clientId}
                filter="all"
                readOnly={!admin}
                sandbox={sandbox}
                onNotice={onNotice}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
