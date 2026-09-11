import { useEffect, useMemo, useRef, useState } from 'react'
import type { GoogleStatus, IngestLevel, Me } from '../types'
import { isSuperAdmin, isAdmin } from '../roles'
import { GATEWAY } from '../config'
import { api } from '../api'
import { useT } from '../i18n'
import { inputConnectors, connDesc, connName, type Connector } from '../connectors'
import ConnectorLogo from './ConnectorLogo'

export type IngestSubmit = {
  mode: 'file' | 'url'
  files?: File[]
  url?: string
  note?: string
  levels: IngestLevel[]
  marketAsProposal: boolean // Admin chose Market → goes through the Promotion flow
}

// Connectoren, die ihre Quelle direkt inline einlesen (live).
const METHOD_UPLOAD = 'upload'
const METHOD_URL = 'url_scrape'
// Google-Eingangs-Connectoren (echter OAuth-Flow).
const GOOGLE_INPUT_IDS = new Set(['google_drive'])

// Ingest-Dialog (connector-first): Eingangs-Connectoren als Karten. Datei-Upload &
// Web/URL öffnen inline ihr Feld; Cloud-Quellen zeigen Verbinden/Setup. Ziel-Ebene
// gilt für die live einlesbaren Methoden (Datei/URL).
export default function IngestDialog({
  open,
  me,
  clientName,
  initialFiles,
  busy,
  onSubmit,
  onClose,
  sandbox = false,
}: {
  open: boolean
  me: Me | null
  clientName?: string
  initialFiles?: File[]
  busy?: boolean
  onSubmit: (s: IngestSubmit) => void
  onClose: () => void
  sandbox?: boolean
}) {
  const t = useT()
  const [selected, setSelected] = useState<string>(METHOD_UPLOAD)
  const [files, setFiles] = useState<File[]>([])
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')
  const [levelClient, setLevelClient] = useState(true)
  const [levelMarket, setLevelMarket] = useState(false)
  const [google, setGoogle] = useState<GoogleStatus | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [moreBelow, setMoreBelow] = useState(false)
  const gridRef = useRef<HTMLDivElement>(null)
  const [gridMore, setGridMore] = useState(false)

  function updateScroll() {
    const el = scrollRef.current
    if (!el) return
    setMoreBelow(el.scrollHeight - el.scrollTop - el.clientHeight > 8)
  }

  function updateGridScroll() {
    const el = gridRef.current
    if (!el) return
    setGridMore(el.scrollHeight - el.scrollTop - el.clientHeight > 8)
  }

  const superAdmin = isSuperAdmin(me)
  const admin = isAdmin(me)
  const connectors = useMemo(() => inputConnectors(), [])

  useEffect(() => {
    if (!open) return
    setFiles(initialFiles ?? [])
    setSelected(initialFiles && initialFiles.length ? METHOD_UPLOAD : METHOD_UPLOAD)
    setUrl('')
    setNote('')
    setLevelClient(true)
    setLevelMarket(false)
    api.googleStatus().then(setGoogle).catch(() => setGoogle(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Scroll-Indikator neu berechnen, wenn sich der Inhalt (Auswahl/Dateien) ändert.
  useEffect(() => {
    updateScroll()
    updateGridScroll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, selected, files.length, google])

  if (!open) return null

  const isLiveMethod = selected === METHOD_UPLOAD || selected === METHOD_URL
  const levels: IngestLevel[] = [
    ...(levelClient ? (['client'] as const) : []),
    ...(levelMarket ? (['market'] as const) : []),
  ]
  const canSubmit =
    isLiveMethod &&
    levels.length > 0 &&
    !busy &&
    (selected === METHOD_UPLOAD ? files.length > 0 : /^https?:\/\/.+/i.test(url.trim()))

  function submit() {
    if (!canSubmit) return
    onSubmit({
      mode: selected === METHOD_UPLOAD ? 'file' : 'url',
      files: selected === METHOD_UPLOAD ? files : undefined,
      url: selected === METHOD_URL ? url.trim() : undefined,
      note: note.trim() || undefined,
      levels,
      marketAsProposal: levelMarket && admin && !superAdmin,
    })
  }

  const googleConnected = !!google?.connected
  const googleConfigured = !!google?.configured

  function pick(c: Connector) {
    setSelected(c.id)
  }

  const selectedConnector = connectors.find((c) => c.id === selected)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/70 backdrop-blur-sm animate-fade-in"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-lg rounded-2xl bg-surface border border-line shadow-2xl shadow-black/60 animate-overlay-in overflow-hidden">
        {/* header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-line">
          <div className="flex items-center gap-2">
            <svg width="18" height="18" viewBox="0 0 18 18" className="text-primary">
              <path
                d="M9 12V3M9 3L5.5 6.5M9 3l3.5 3.5M3 12v2a1 1 0 001 1h10a1 1 0 001-1v-2"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </svg>
            <h2 className="font-display font-bold text-[15px] text-paper">{t('ingest.title')}</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition"
          >
            <svg width="16" height="16" viewBox="0 0 14 14">
              <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="relative">
          <div
            ref={scrollRef}
            onScroll={updateScroll}
            className="p-4 flex flex-col gap-4 max-h-[70vh] overflow-y-auto"
          >
          {/* Connector-Auswahl */}
          <div>
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-faint">
                {t('ingest.pick_source')}
              </span>
              <span className="text-[10px] text-faint">{t('ingest.sources_count', { count: connectors.length })}</span>
            </div>
            <div className="relative">
            <div
              ref={gridRef}
              onScroll={updateGridScroll}
              className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 max-h-[188px] overflow-y-auto pr-0.5"
            >
              {connectors.map((c) => {
                const active = selected === c.id
                // Sandbox: nur credential-lose Quellen (Datei/URL, auth==='none') nutzbar;
                // Konto-Integrationen gesperrt — konsistent mit dem Marktplatz.
                const locked = sandbox && c.auth !== 'none'
                return (
                  <button
                    key={c.id}
                    onClick={locked ? undefined : () => pick(c)}
                    disabled={locked}
                    className={`text-left rounded-xl border p-2.5 flex items-center gap-2 transition ${
                      active
                        ? 'bg-primary/10 border-primary/50'
                        : locked
                          ? 'bg-surface2/50 border-line opacity-60 cursor-not-allowed'
                          : 'bg-surface2 border-line hover:border-line2'
                    }`}
                    title={locked ? t('ingest.sandbox_lock') : connDesc(t, c)}
                  >
                    <span className="shrink-0 w-7 h-7 grid place-items-center rounded-lg bg-surface3 border border-line text-[15px]">
                      <ConnectorLogo id={c.id} fallback={c.icon} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={`block text-[12px] font-medium truncate ${active ? 'text-paper' : 'text-paper/90'}`}>
                        {connName(t, c)}
                      </span>
                      <span className="block text-[9.5px] font-mono uppercase tracking-wide text-faint">
                        {locked ? t('ingest.own_instance') : c.live ? t('ingest.status_live') : t('ingest.status_setup')}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
            {gridMore && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-9 bg-gradient-to-t from-surface via-surface/80 to-transparent flex items-end justify-center pb-0.5">
                <span className="flex items-center gap-1 text-[9.5px] font-mono uppercase tracking-wide text-faint">
                  {t('ingest.more_sources')}
                  <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
                    <path d="M3 4.5L6 8l3-3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
              </div>
            )}
            </div>
          </div>

          {/* Methoden-Panel */}
          {selected === METHOD_UPLOAD && (
            <div>
              <button
                onClick={() => fileRef.current?.click()}
                className="w-full rounded-xl border border-dashed border-line2 hover:border-primary/50 bg-surface2/50 py-6 flex flex-col items-center gap-2 text-muted hover:text-primary transition"
              >
                <svg width="22" height="22" viewBox="0 0 18 18" fill="none">
                  <path d="M9 12V3M9 3L5.5 6.5M9 3l3.5 3.5M3 12v2a1 1 0 001 1h10a1 1 0 001-1v-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="text-[12.5px] font-medium">{t('ingest.choose_files')}</span>
                <span className="text-[10.5px] text-faint">{t('ingest.file_types')}</span>
              </button>
              <input
                ref={fileRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  const fs = Array.from(e.target.files ?? [])
                  if (fs.length) setFiles((prev) => [...prev, ...fs])
                  e.target.value = ''
                }}
              />
              {files.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1">
                  {files.map((f, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between gap-2 text-[12px] px-2.5 py-1.5 rounded-lg bg-surface2 border border-line"
                    >
                      <span className="truncate text-paper/90">{f.name}</span>
                      <button
                        onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                        className="text-faint hover:text-crose shrink-0"
                        title={t('ingest.remove')}
                      >
                        <svg width="13" height="13" viewBox="0 0 14 14">
                          <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                        </svg>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {selected === METHOD_URL && (
            <div>
              <label className="text-[11px] font-mono uppercase tracking-wider text-faint">
                {t('ingest.url_label')}
              </label>
              <input
                type="url"
                value={url}
                autoFocus
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submit()}
                placeholder={t('ingest.url_placeholder')}
                className="mt-1.5 w-full rounded-xl bg-surface2 border border-line px-3.5 py-2.5 text-[13px] text-paper placeholder:text-faint outline-none focus:border-primary/50 transition"
              />
              <p className="text-[10.5px] text-faint mt-1.5">
                {t('ingest.url_hint')}
              </p>
            </div>
          )}

          {/* Cloud-/Setup-Connectoren: Verbinden bzw. Setup-Hinweis */}
          {!isLiveMethod && selectedConnector && (
            <div className="rounded-xl border border-line bg-surface2 p-4 text-center">
              {GOOGLE_INPUT_IDS.has(selected) ? (
                googleConnected ? (
                  <>
                    <p className="text-[12.5px] text-paper font-medium mb-1">{t('ingest.gdrive_connected')}</p>
                    <p className="text-[11.5px] text-muted">
                      {t('ingest.gdrive_import_soon')}
                    </p>
                  </>
                ) : googleConfigured ? (
                  <>
                    <p className="text-[12.5px] text-paper font-medium mb-2">{t('ingest.gdrive_not_connected')}</p>
                    <button
                      onClick={() => (window.location.href = `${GATEWAY}/integrations/google/oauth/install`)}
                      className="text-[12px] font-semibold px-3 py-1.5 rounded-full bg-primary text-ink hover:brightness-105 transition"
                    >
                      {t('ingest.connect_google')}
                    </button>
                  </>
                ) : (
                  <p className="text-[11.5px] text-muted">
                    {t('ingest.google_not_configured')}
                  </p>
                )
              ) : (
                <>
                  <p className="text-[12.5px] text-paper font-medium mb-1">{connName(t, selectedConnector)}</p>
                  <p className="text-[11.5px] text-muted">
                    {t('ingest.connector_setup')}
                  </p>
                </>
              )}
            </div>
          )}

          {/* Ziel-Ebene — nur für live einlesbare Methoden */}
          {isLiveMethod && (
            <div>
              <div className="text-[11px] font-mono uppercase tracking-wider text-faint mb-2">
                {t('ingest.target_level')}
              </div>
              <div className="flex flex-col gap-2">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={levelClient}
                    onChange={(e) => setLevelClient(e.target.checked)}
                    className="mt-0.5 accent-[#FFD21E] w-4 h-4"
                  />
                  <span>
                    <span className="text-[13px] text-paper font-medium">
                      {t('ingest.client_archive')}
                      {clientName ? <span className="text-muted font-normal"> · {clientName}</span> : null}
                    </span>
                    <span className="block text-[11px] text-muted">
                      {t('ingest.client_archive_desc')}
                    </span>
                  </span>
                </label>

                <label
                  className={`flex items-start gap-2.5 ${admin ? 'cursor-pointer' : 'opacity-50 cursor-not-allowed'}`}
                  title={admin ? '' : t('ingest.admin_only_title')}
                >
                  <input
                    type="checkbox"
                    checked={levelMarket}
                    disabled={!admin}
                    onChange={(e) => setLevelMarket(e.target.checked)}
                    className="mt-0.5 accent-[#FFD21E] w-4 h-4"
                  />
                  <span>
                    <span className="text-[13px] text-paper font-medium">{t('ingest.shared_market')}</span>
                    <span className="block text-[11px] text-muted">
                      {superAdmin
                        ? t('ingest.market_superadmin')
                        : admin
                          ? t('ingest.market_admin')
                          : t('ingest.market_admin_only')}
                    </span>
                  </span>
                </label>
              </div>
            </div>
          )}

          {/* optional note */}
          {isLiveMethod && (
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t('ingest.note_placeholder')}
              className="w-full rounded-xl bg-surface2 border border-line px-3.5 py-2 text-[12.5px] text-paper placeholder:text-faint outline-none focus:border-primary/50 transition"
            />
          )}
          </div>

          {/* Scroll-Indikator: „mehr ↓" — verschwindet, sobald unten angekommen */}
          {moreBelow && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-surface via-surface/85 to-transparent flex items-end justify-center pb-2">
              <span className="flex items-center gap-1 text-[10px] font-mono uppercase tracking-wide text-faint animate-pulse">
                {t('ingest.more')}
                <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                  <path d="M3 4.5L6 8l3-3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            </div>
          )}
        </div>

        {/* footer */}
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-line">
          <span className="text-[11px] text-faint">
            {levelMarket && admin && !superAdmin ? t('ingest.market_as_proposal') : ' '}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3 py-2 rounded-xl text-[13px] text-muted hover:text-paper hover:bg-surface2 transition"
            >
              {t('common.cancel')}
            </button>
            <button
              onClick={submit}
              disabled={!canSubmit}
              className="px-4 py-2 rounded-full bg-primary text-ink font-semibold text-[13px] disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-105 transition"
            >
              {busy ? t('ingest.busy') : selected === METHOD_URL ? t('ingest.crawl_ingest') : t('ingest.ingest')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
