import { useEffect, useRef, useState } from 'react'
import type { Client } from '../types'
import { useT } from '../i18n'

export default function ClientSwitcher({
  clients,
  active,
  onChange,
}: {
  clients: Client[]
  active: Client | null
  onChange: (c: Client) => void
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 pl-2.5 pr-2 py-1.5 rounded-lg bg-surface2 border border-line hover:border-line2 transition text-[13px]"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-primary" />
        <span className="font-medium text-paper max-w-[140px] truncate">
          {active?.name ?? t('clientswitcher.select')}
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
        <div className="absolute left-0 mt-1.5 w-60 z-40 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 p-1.5 animate-fade-in">
          <div className="px-2.5 py-1.5 text-[10px] font-mono uppercase tracking-wider text-faint">
            {t('clientswitcher.header')}
          </div>
          {clients.length === 0 && (
            <div className="px-2.5 py-2 text-[12px] text-muted">{t('clientswitcher.empty')}</div>
          )}
          {clients.map((c) => {
            const isActive = c.id === active?.id
            return (
              <button
                key={c.id}
                onClick={() => {
                  onChange(c)
                  setOpen(false)
                }}
                className={`w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg text-left transition ${
                  isActive ? 'bg-surface3' : 'hover:bg-surface2'
                }`}
              >
                <span className="flex flex-col">
                  <span className="text-[13px] text-paper font-medium">{c.name}</span>
                  <span className="text-[10px] font-mono text-faint">{c.id}</span>
                </span>
                {isActive && (
                  <svg width="14" height="14" viewBox="0 0 14 14" className="text-primary shrink-0">
                    <path d="M3 7.5L6 10.5L11 4" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
