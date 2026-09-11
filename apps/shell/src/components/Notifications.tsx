import { useEffect, useMemo, useRef, useState } from 'react'
import type { AppNotification, NotificationType } from '../types'
import Avatar from './Avatar'
import { useT, type TFn } from '../i18n'

function relTime(t: TFn, iso?: string): string {
  if (!iso) return ''
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return ''
  const diff = Date.now() - ts
  const m = Math.round(diff / 60000)
  if (m < 1) return t('notifications.just_now')
  if (m < 60) return t('notifications.min_ago', { count: m })
  const h = Math.round(m / 60)
  if (h < 24) return t('notifications.hours_ago', { count: h })
  const d = Math.round(h / 24)
  return t('notifications.days_ago', { count: d })
}

// Metadaten je Typ: Labelschlüssel (Katalog) + Farbe. Der Anzeigetext kommt zur Laufzeit aus t().
const TYPE_META: Record<string, { labelKey: string; color: string }> = {
  data_request: { labelKey: 'notifications.type_data_request', color: 'text-primary' },
  escalation: { labelKey: 'notifications.type_escalation', color: 'text-primary' },
  thread_invite: { labelKey: 'notifications.type_thread_invite', color: 'text-cmint' },
  promotion: { labelKey: 'notifications.type_promotion', color: 'text-cviolet' },
  system: { labelKey: 'notifications.type_system', color: 'text-muted' },
}

function typeMeta(type: NotificationType): { labelKey?: string; color: string } {
  return TYPE_META[type] ?? { color: 'text-muted' }
}

// Anzeige-Label eines Typs: übersetzt, sonst der rohe Typ-String als Fallback.
function typeLabel(t: TFn, type: NotificationType): string {
  const meta = TYPE_META[type]
  return meta ? t(meta.labelKey) : String(type)
}

function NotificationItem({
  n,
  onMarkRead,
  compact,
}: {
  n: AppNotification
  onMarkRead: (id: string) => void
  compact?: boolean
}) {
  const t = useT()
  const meta = typeMeta(n.type)
  return (
    <div
      className={`flex gap-2.5 px-3 py-2.5 transition ${
        n.read ? 'opacity-60' : 'bg-surface2/40'
      } ${compact ? 'hover:bg-surface2' : 'rounded-xl border border-line bg-surface2'}`}
    >
      {n.from ? (
        <Avatar email={n.from} size="sm" />
      ) : (
        <span className="shrink-0 w-6 h-6 rounded-full bg-surface3 border border-line grid place-items-center text-primary">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
            <path d="M8 2a4 4 0 00-4 4v2.5L2.5 11h11L12 8.5V6a4 4 0 00-4-4zM6.5 13a1.5 1.5 0 003 0" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
          </svg>
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`text-[9px] font-mono uppercase tracking-wide ${meta.color}`}>{typeLabel(t, n.type)}</span>
          {!n.read && <span className="w-1.5 h-1.5 rounded-full bg-primary" />}
          <span className="text-[10px] text-faint ml-auto shrink-0">{relTime(t, n.created_at)}</span>
        </div>
        <div className="text-[12.5px] text-paper mt-0.5 leading-snug">{n.title}</div>
        {n.body && <div className="text-[11.5px] text-muted mt-0.5 leading-snug">{n.body}</div>}
        {n.from && <div className="text-[10.5px] text-faint mt-0.5 truncate">{t('notifications.from', { from: n.from })}</div>}
      </div>
      {!n.read && (
        <button
          onClick={() => onMarkRead(n.id)}
          title={t('notifications.mark_read')}
          className="shrink-0 self-start p-1 rounded text-faint hover:text-cmint transition"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </div>
  )
}

// -------- Bell + dropdown inbox (im Header) --------
export function NotificationBell({
  items,
  unread,
  loading,
  onMarkRead,
  onMarkAllRead,
  onOpenPage,
  onRefresh,
}: {
  items: AppNotification[]
  unread: number
  loading?: boolean
  onMarkRead: (id: string) => void
  onMarkAllRead: () => void
  onOpenPage: () => void
  onRefresh: () => void
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    onRefresh()
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onEsc)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const recent = useMemo(() => items.slice(0, 8), [items])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        title={t('notifications.title')}
        aria-haspopup="menu"
        aria-expanded={open}
        className={`relative p-2 rounded-lg transition ${
          open ? 'bg-surface2 text-paper' : 'text-muted hover:text-paper hover:bg-surface2'
        }`}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <path
            d="M9 2.5a4.5 4.5 0 00-4.5 4.5v2.8L3 12.5h12l-1.5-2.7V7A4.5 4.5 0 009 2.5zM7 14.5a2 2 0 004 0"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-primary text-ink text-[10px] font-bold flex items-center justify-center">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 z-50 animate-fade-up overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-line">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-medium text-paper">{t('notifications.title')}</span>
              {unread > 0 && (
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/15 text-primary border border-primary/25">
                  {t('notifications.new_count', { count: unread })}
                </span>
              )}
            </div>
            {unread > 0 && (
              <button onClick={onMarkAllRead} className="text-[11px] text-muted hover:text-cmint transition">
                {t('notifications.mark_all_read')}
              </button>
            )}
          </div>

          <div className="max-h-[50vh] overflow-y-auto divide-y divide-line">
            {loading && recent.length === 0 ? (
              <div className="px-3 py-6 text-center text-[12px] text-muted">{t('notifications.loading')}</div>
            ) : recent.length === 0 ? (
              <div className="px-3 py-8 text-center text-[12px] text-faint">{t('notifications.empty')}</div>
            ) : (
              recent.map((n) => <NotificationItem key={n.id} n={n} onMarkRead={onMarkRead} compact />)
            )}
          </div>

          <button
            onClick={() => {
              setOpen(false)
              onOpenPage()
            }}
            className="w-full px-3 py-2.5 text-[12px] text-center text-primary hover:bg-surface2 border-t border-line transition"
          >
            {t('notifications.view_all')}
          </button>
        </div>
      )}
    </div>
  )
}

// -------- Full inbox page (Overlay) --------
type Filter = 'all' | 'unread' | NotificationType

export function NotificationsPage({
  items,
  loading,
  onMarkRead,
  onMarkAllRead,
  onRefresh,
  onClose,
}: {
  items: AppNotification[]
  loading?: boolean
  onMarkRead: (id: string) => void
  onMarkAllRead: () => void
  onRefresh: () => void
  onClose: () => void
}) {
  const t = useT()
  const [filter, setFilter] = useState<Filter>('all')

  useEffect(() => {
    onRefresh()
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const types = useMemo(() => Array.from(new Set(items.map((n) => n.type))), [items])
  const unread = items.filter((n) => !n.read).length
  const filtered = items.filter((n) =>
    filter === 'all' ? true : filter === 'unread' ? !n.read : n.type === filter,
  )

  const chips: { id: Filter; label: string }[] = [
    { id: 'all', label: t('notifications.filter_all') },
    { id: 'unread', label: unread ? t('notifications.filter_unread_count', { count: unread }) : t('notifications.filter_unread') },
    ...types.map((ty) => ({ id: ty as Filter, label: typeLabel(t, ty) })),
  ]

  return (
    <div className="fixed inset-0 z-50 bg-ink/80 backdrop-blur-sm p-0 md:p-8 flex items-center justify-center animate-fade-in">
      <div className="w-full h-full rounded-none md:max-w-2xl md:h-[80vh] md:rounded-2xl bg-surface border border-line shadow-2xl shadow-black/60 flex flex-col overflow-hidden animate-overlay-in">
        <div className="flex items-center justify-between px-4 py-3 border-b border-line shrink-0">
          <div className="flex items-center gap-2">
            <svg width="17" height="17" viewBox="0 0 18 18" fill="none" className="text-primary">
              <path d="M9 2.5a4.5 4.5 0 00-4.5 4.5v2.8L3 12.5h12l-1.5-2.7V7A4.5 4.5 0 009 2.5zM7 14.5a2 2 0 004 0" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
            </svg>
            <h2 className="font-display font-bold text-[15px] text-paper">{t('notifications.title')}</h2>
            {unread > 0 && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/15 text-primary border border-primary/25">
                {t('notifications.new_count', { count: unread })}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {unread > 0 && (
              <button onClick={onMarkAllRead} className="text-[12px] text-muted hover:text-cmint transition">
                {t('notifications.mark_all_read')}
              </button>
            )}
            <button onClick={onClose} className="p-1.5 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition">
              <svg width="16" height="16" viewBox="0 0 14 14">
                <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5 px-4 py-2.5 border-b border-line shrink-0">
          {chips.map((c) => (
            <button
              key={String(c.id)}
              onClick={() => setFilter(c.id)}
              className={`text-[11.5px] px-2.5 py-1 rounded-full border transition ${
                filter === c.id
                  ? 'bg-primary/15 border-primary/40 text-primary'
                  : 'bg-surface2 border-line text-muted hover:text-paper'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
          {loading && items.length === 0 ? (
            <p className="text-[12.5px] text-muted">{t('notifications.loading')}</p>
          ) : filtered.length === 0 ? (
            <p className="text-[12.5px] text-faint">{t('notifications.no_entries')}</p>
          ) : (
            filtered.map((n) => <NotificationItem key={n.id} n={n} onMarkRead={onMarkRead} />)
          )}
        </div>
      </div>
    </div>
  )
}
