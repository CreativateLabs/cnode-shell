import { useEffect, useMemo, useRef, useState } from 'react'
import type { Folder } from '../types'
import type { Thread } from './Sidebar'
import { useT } from '../i18n'

// Globale Suche: startet an der Sidebar-Kante und läuft als Overlay in die Header-Nav
// hinein. Autocomplete über alle Threads + Ordnernamen (Titel-basiert).
export default function GlobalSearch({
  threads,
  folders,
  onClose,
  onSelect,
}: {
  threads: Thread[]
  folders: Folder[]
  onClose: () => void
  onSelect: (id: string) => void
}) {
  const t = useT()
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const hits = useMemo(() => {
    const query = q.trim().toLowerCase()
    const sorted = [...threads].sort((a, b) => b.ts - a.ts)
    if (!query) return sorted.slice(0, 8)
    return sorted
      .filter((t) => {
        const folderName = folders.find((f) => f.id === t.folder_id)?.name?.toLowerCase() ?? ''
        return t.title.toLowerCase().includes(query) || folderName.includes(query)
      })
      .slice(0, 10)
  }, [q, threads, folders])

  useEffect(() => {
    setActive(0)
  }, [q])

  function folderName(th: Thread): string {
    return folders.find((f) => f.id === th.folder_id)?.name ?? (th.visibility === 'team' ? t('search.team') : t('search.private'))
  }

  return (
    <div className="fixed inset-0 z-[70]">
      <div className="absolute inset-0 bg-ink/40 backdrop-blur-[1px]" onClick={onClose} />
      <div className="absolute top-2 left-3 w-[min(560px,72vw)] animate-fade-down">
        <div className="rounded-xl bg-surface border border-primary/40 shadow-2xl shadow-black/60 overflow-hidden">
          {/* input */}
          <div className="flex items-center gap-2 px-3 py-2.5 border-b border-line">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-faint shrink-0">
              <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
              <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') onClose()
                else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(i + 1, hits.length - 1)) }
                else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)) }
                else if (e.key === 'Enter' && hits[active]) onSelect(hits[active].id)
              }}
              placeholder={t('search.placeholder')}
              className="flex-1 bg-transparent text-[14px] text-paper placeholder:text-faint outline-none"
            />
            <button onClick={onClose} className="shrink-0 text-faint hover:text-paper transition" title={t('search.close_esc')}>
              <svg width="14" height="14" viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
            </button>
          </div>

          {/* autocomplete */}
          <div className="max-h-[50vh] overflow-y-auto py-1">
            {!q && <div className="px-3 py-1 text-[10px] font-mono uppercase tracking-wider text-faint">{t('search.recent')}</div>}
            {hits.length === 0 ? (
              <div className="px-3 py-4 text-[12.5px] text-faint">{t('search.no_results', { query: q })}</div>
            ) : (
              hits.map((th, i) => (
                <button
                  key={th.id}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => onSelect(th.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 text-left transition ${
                    i === active ? 'bg-surface2' : 'hover:bg-surface2/60'
                  }`}
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-faint shrink-0">
                    <path d="M3 4a1 1 0 011-1h8a1 1 0 011 1v6a1 1 0 01-1 1H6l-3 2.5V4z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
                  </svg>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] text-paper truncate">{th.title || t('search.chat_fallback')}</span>
                    <span className="block text-[10.5px] text-faint truncate">{folderName(th)}</span>
                  </span>
                  {i === active && <span className="text-[10px] font-mono text-faint shrink-0">↵</span>}
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
