// Sticky Bottom-Navigation (< md) — ersetzt auf dem Smartphone die persistente
// Sidebar-Navigation wie in einer nativen App. Auf md+ komplett ausgeblendet.
// Fünf gleichmäßig verteilte Ziele; die zentrale „Neuer Chat"-Aktion ist als
// erhabener Violett-Kreis (.cta-grad) visuell hervorgehoben.
// Reihenfolge: Chats · Gedächtnis · ＋ · Bibliothek · Nachrichten.

import { useT } from '../i18n'

type BottomNavProps = {
  onOpenChats: () => void
  onOpenGraph: () => void
  onNewThread: () => void
  onOpenLibrary: () => void
  onOpenNotifications: () => void
  unread: number
  activeChats?: boolean
  activeGraph?: boolean
  activeLibrary?: boolean
  activeNotifications?: boolean
}

export default function BottomNav({
  onOpenChats,
  onOpenGraph,
  onNewThread,
  onOpenLibrary,
  onOpenNotifications,
  unread,
  activeChats = false,
  activeGraph = false,
  activeLibrary = false,
  activeNotifications = false,
}: BottomNavProps) {
  const t = useT()
  return (
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-30 bg-surface border-t border-line pb-[env(safe-area-inset-bottom)]"
      aria-label={t('bottomnav.main_nav')}
    >
      <div className="h-14 flex items-stretch">
        {/* Chats → Vollbild-Chats-/Ordner-Verwaltung */}
        <NavItem label={t('bottomnav.chats')} onClick={onOpenChats} active={activeChats}>
          <svg width="22" height="22" viewBox="0 0 20 20" fill="none">
            <path d="M3 5.5A1.5 1.5 0 014.5 4h11A1.5 1.5 0 0117 5.5v6A1.5 1.5 0 0115.5 13H8l-3.5 3v-3H4.5A1.5 1.5 0 013 11.5v-6z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
            <path d="M6 7.5h8M6 10h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </NavItem>

        {/* Gedächtnis → Graph-Overlay */}
        <NavItem label={t('bottomnav.memory')} onClick={onOpenGraph} active={activeGraph}>
          <svg width="22" height="22" viewBox="0 0 18 18" fill="none">
            <path d="M9 2l6 3.5v7L9 16l-6-3.5v-7L9 2z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
            <circle cx="9" cy="9" r="1.6" fill="currentColor" />
          </svg>
        </NavItem>

        {/* Neuer Chat — zentrale, erhabene Primäraktion */}
        <div className="flex-1 min-w-0 relative grid place-items-center">
          <button
            onClick={onNewThread}
            aria-label={t('bottomnav.new_chat')}
            title={t('bottomnav.new_chat')}
            className="cta-grad -mt-6 w-14 h-14 rounded-full grid place-items-center shadow-lg shadow-primary/30 active:scale-95 transition"
          >
            <svg width="24" height="24" viewBox="0 0 16 16" fill="none">
              <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Bibliothek → Library-Overlay */}
        <NavItem label={t('bottomnav.library')} onClick={onOpenLibrary} active={activeLibrary}>
          <svg width="22" height="22" viewBox="0 0 18 18" fill="none">
            <path d="M2.5 5A1.5 1.5 0 014 3.5h3l1.4 1.6H14A1.5 1.5 0 0115.5 6.6v6A1.5 1.5 0 0114 14.1H4A1.5 1.5 0 012.5 12.6V5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
          </svg>
        </NavItem>

        {/* Insights → Aktivität/Benachrichtigungen (mit Ungelesen-Badge) */}
        <NavItem label={t('bottomnav.insights')} onClick={onOpenNotifications} active={activeNotifications} badge={unread}>
          <svg width="22" height="22" viewBox="0 0 18 18" fill="none">
            <path d="M3 15V8M7 15V4M11 15v-5M15 15V6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </NavItem>
      </div>
    </nav>
  )
}

function NavItem({
  label,
  onClick,
  active = false,
  badge,
  children,
}: {
  label: string
  onClick: () => void
  active?: boolean
  badge?: number
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`flex-1 min-w-0 min-h-[44px] flex flex-col items-center justify-center gap-0.5 transition ${
        active ? 'text-primary' : 'text-muted hover:text-paper'
      }`}
    >
      <span className="relative">
        {children}
        {badge != null && badge > 0 && (
          <span className="absolute -top-1.5 -right-2 min-w-[15px] h-[15px] px-1 grid place-items-center rounded-full bg-primary text-ink text-[9px] font-bold leading-none">
            {badge > 99 ? '99+' : badge}
          </span>
        )}
      </span>
      <span className="text-[10px] leading-none">{label}</span>
    </button>
  )
}
