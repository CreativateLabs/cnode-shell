import { useEffect, useRef, useState } from 'react'
import type { Client, Me, Provider } from '../types'
import ClientSwitcher from './ClientSwitcher'
import { useRoleLabel } from '../roles'
import { useT } from '../i18n'

export default function Topbar({
  clients,
  activeClient,
  onClient,
  canSwitchClient,
  me,
  provider,
  model,
  claudeReady,
  geminiReady,
  onProvider,
  onShare,
  onToggleGraph,
  onToggleSidebar,
  onSettings,
  onLogout,
  onOpenLibrary,
  notificationSlot,
  sandbox = false,
}: {
  clients: Client[]
  activeClient: Client | null
  onClient: (c: Client) => void
  canSwitchClient: boolean
  me: Me | null
  provider: Provider
  model: string
  claudeReady: boolean
  geminiReady: boolean
  onProvider: (p: Provider) => void
  sandbox?: boolean
  onShare: () => void
  onToggleGraph: () => void
  onToggleSidebar: () => void
  onSettings: () => void
  onLogout: () => void
  onOpenLibrary: () => void
  notificationSlot?: React.ReactNode
}) {
  const t = useT()
  const roleName = useRoleLabel()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    function onDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onEsc)
    }
  }, [menuOpen])

  const tenantLabel =
    me?.tenant?.label ?? me?.tenant?.name ?? me?.tenant?.id ?? activeClient?.name ?? '—'
  const initial = (me?.user?.email?.[0] ?? '?').toUpperCase()
  const accountName = me?.user?.email ?? t('topbar.account_fallback')

  function run(fn: () => void) {
    setMenuOpen(false)
    fn()
  }

  return (
    <header className="flex items-center justify-between gap-3 px-4 h-14 bg-ink border-b border-line shrink-0">
      {/* left: (super-admin) client switcher — Brand lebt jetzt im Sidebar-Kopf */}
      <div className="flex items-center gap-3 min-w-0">
        {canSwitchClient && (
          <ClientSwitcher clients={clients} active={activeClient} onChange={onClient} />
        )}
      </div>

      {/* right: Notifications + account-name dropdown */}
      <div className="flex items-center gap-1.5">
        {/* Notifications bell (links neben dem Account-Dropdown) */}
        {notificationSlot}

        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            title={t('topbar.account_menu')}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className={`flex items-center gap-2 pl-1.5 pr-2 py-1 rounded-lg border text-[13px] text-paper transition ${
              menuOpen ? 'bg-surface2 border-primary/50' : 'bg-surface2 border-line hover:border-primary/50'
            }`}
          >
            <span className="w-6 h-6 rounded-full bg-primary text-ink flex items-center justify-center font-display font-extrabold text-[12px] shrink-0">
              {initial}
            </span>
            <span className="max-w-[170px] truncate hidden sm:inline">{accountName}</span>
            <svg width="12" height="12" viewBox="0 0 12 12" className={`text-muted transition-transform shrink-0 ${menuOpen ? 'rotate-180' : ''}`}>
              <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
            </svg>
          </button>

          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full mt-2 w-64 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 py-1.5 z-50 animate-fade-up"
            >
              {/* Identität */}
              <div className="px-3 py-2">
                <div className="text-[13px] font-medium text-paper truncate" title={me?.user?.email}>
                  {me?.user?.email ?? t('topbar.signed_in')}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
                  <span className="text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary/15 text-primary border border-primary/25">
                    {me ? roleName(me.role) : '—'}
                  </span>
                  <span className="text-[11px] text-muted truncate max-w-[150px]">{tenantLabel}</span>
                </div>
              </div>

              <div className="h-px bg-line my-1" />

              {/* Modell-Toggle — in der Sandbox nur ein statischer Gemini-Chip. */}
              <div className="px-3 py-1.5">
                <div className="text-[10px] font-mono uppercase tracking-wider text-faint mb-1.5">{t('topbar.model')}</div>
                {sandbox ? (
                  <div className="flex items-center gap-1.5 rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12px] text-paper">
                    <span className="w-1.5 h-1.5 rounded-full bg-cmint shrink-0" />
                    {t('topbar.gemini_cloud')}
                  </div>
                ) : (
                <div className="flex items-center rounded-lg bg-surface2 border border-line p-0.5 text-[12px]">
                  <button
                    onClick={() => onProvider('ollama')}
                    className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1 rounded-md transition ${
                      provider === 'ollama' ? 'bg-primary text-ink font-semibold' : 'text-muted hover:text-paper'
                    }`}
                    title={model ? t('topbar.model_tooltip', { model }) : t('topbar.local_oss_model')}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${provider === 'ollama' ? 'bg-ink' : 'bg-cmint'}`} />
                    {t('topbar.local_oss')}
                  </button>
                  <button
                    onClick={() => geminiReady && onProvider('gemini')}
                    disabled={!geminiReady}
                    title={geminiReady ? t('topbar.gemini_cloud_paren') : t('topbar.google_key_missing')}
                    className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1 rounded-md transition ${
                      provider === 'gemini'
                        ? 'bg-primary text-ink font-semibold'
                        : geminiReady
                          ? 'text-muted hover:text-paper'
                          : 'text-faint cursor-not-allowed'
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${provider === 'gemini' ? 'bg-ink' : 'bg-cmint'}`} />
                    Gemini
                  </button>
                  <button
                    onClick={() => claudeReady && onProvider('claude')}
                    disabled={!claudeReady}
                    title={claudeReady ? t('topbar.claude_cloud_paren') : t('topbar.anthropic_key_missing')}
                    className={`flex-1 px-2 py-1 rounded-md transition ${
                      provider === 'claude'
                        ? 'bg-cviolet text-ink font-semibold'
                        : claudeReady
                          ? 'text-muted hover:text-paper'
                          : 'text-faint cursor-not-allowed'
                    }`}
                  >
                    Claude
                  </button>
                </div>
                )}
              </div>

              <div className="h-px bg-line my-1" />

              {/* Nav-Items */}
              <button role="menuitem" onClick={() => run(onToggleGraph)} className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-paper hover:bg-surface2 transition">
                <svg width="16" height="16" viewBox="0 0 18 18" fill="none" className="text-muted">
                  <path d="M9 2l6 3.5v7L9 16l-6-3.5v-7L9 2z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                  <circle cx="9" cy="9" r="1.6" fill="currentColor" />
                </svg>
                {t('topbar.memory')}
              </button>
              <button role="menuitem" onClick={() => run(onOpenLibrary)} className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-paper hover:bg-surface2 transition">
                <svg width="16" height="16" viewBox="0 0 18 18" fill="none" className="text-muted">
                  <path d="M2.5 5A1.5 1.5 0 014 3.5h3l1.4 1.6H14A1.5 1.5 0 0115.5 6.6v6A1.5 1.5 0 0114 14.1H4A1.5 1.5 0 012.5 12.6V5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                </svg>
                {t('topbar.library')}
              </button>
              <button role="menuitem" onClick={() => run(onShare)} className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-paper hover:bg-surface2 transition">
                <svg width="16" height="16" viewBox="0 0 18 18" fill="none" className="text-muted">
                  <path d="M12 6a2 2 0 100-4 2 2 0 000 4zM6 11a2 2 0 100-4 2 2 0 000 4zM12 16a2 2 0 100-4 2 2 0 000 4z" stroke="currentColor" strokeWidth="1.4" />
                  <path d="M7.6 8.1l2.8-1.6M7.6 9.9l2.8 1.6" stroke="currentColor" strokeWidth="1.4" />
                </svg>
                {t('topbar.share_thread')}
              </button>
              <button role="menuitem" onClick={() => run(onSettings)} className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-paper hover:bg-surface2 transition">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-muted">
                  <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
                  <path d="M19.4 13a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.7 1.7 0 009 19.3a1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1A1.7 1.7 0 004.7 9a1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {t('common.settings')}
              </button>

              <div className="h-px bg-line my-1" />

              <button role="menuitem" onClick={() => run(onLogout)} className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-crose hover:bg-crose/10 transition">
                <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
                  <path d="M7 2.5H4a1.5 1.5 0 00-1.5 1.5v10A1.5 1.5 0 004 15.5h3M11.5 12l3-3-3-3M14 9H6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {t('common.logout')}
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
