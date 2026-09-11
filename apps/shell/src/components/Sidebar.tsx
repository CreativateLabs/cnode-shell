import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Client, Folder, Me, Provider } from '../types'
import CnodeLogo, { CnodeIcon } from './CnodeLogo'
import ClientSwitcher from './ClientSwitcher'
import ThreadList, { type Thread } from './ThreadList'
import LanguageSwitcher from './LanguageSwitcher'
import { useRoleLabel } from '../roles'
import { useT } from '../i18n'

// Kanonischer Ort der Thread-Typdefinition ist jetzt ThreadList (eine Quelle der Wahrheit).
// Re-Export für Bestandscode, der `import { Thread } from './Sidebar'` nutzt.
export type { Thread }

type SidebarProps = {
  open: boolean
  threads: Thread[]
  folders: Folder[]
  activeThreadId: string | null
  onSelectThread: (id: string) => void
  onNewThread: () => void
  onToggleSidebar: () => void
  onOpenSearch: () => void
  onCreateFolder: (name: string) => void
  onRenameFolder: (id: string, name: string) => void
  onDeleteFolder: (id: string) => void
  onRenameThread: (id: string, title: string) => void
  onDeleteThread: (id: string) => void
  onMoveThread: (id: string, folderId: string | null) => void
  onArea?: (prompt: string) => void
  // Aus der ehemaligen Top-Nav integriert:
  me: Me | null
  provider: Provider
  model: string
  claudeReady: boolean
  geminiReady: boolean
  onProvider: (p: Provider) => void
  onOpenGraph: () => void
  onOpenLibrary: () => void
  onOpenNotifications: () => void
  onOpenSetup?: () => void
  canSetup?: boolean
  unread: number
  onSettings: (section?: string) => void
  onLogout: () => void
  canSwitchClient: boolean
  clients: Client[]
  activeClient: Client | null
  onClient: (c: Client) => void
  wordmark?: string
  // Öffentliche Sandbox: Modellwahl gesperrt → nur Gemini (Cloud).
  sandbox?: boolean
}

export default function Sidebar({
  open,
  threads,
  folders,
  activeThreadId,
  onSelectThread,
  onNewThread,
  onToggleSidebar,
  onOpenSearch,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  onRenameThread,
  onDeleteThread,
  onMoveThread,
  me,
  provider,
  model,
  claudeReady,
  geminiReady,
  onProvider,
  onOpenGraph,
  onOpenLibrary,
  onOpenNotifications,
  onOpenSetup,
  canSetup,
  unread,
  onSettings,
  onLogout,
  canSwitchClient,
  clients,
  activeClient,
  onClient,
  wordmark = 'c:node',
  sandbox = false,
}: SidebarProps) {
  const t = useT()
  // „Neuer Ordner": der Button liegt oben in der Sidebar, die Eingabe rendert ThreadList.
  // Ordner-/Thread-Liste + Mehrfachauswahl leben jetzt vollständig in <ThreadList/>.
  const [creatingFolder, setCreatingFolder] = useState(false)
  const initial = (me?.user?.email?.[0] ?? '?').toUpperCase()
  const tenantLabel = me?.tenant?.label ?? me?.tenant?.name ?? me?.tenant?.id ?? ''
  // Klicks auf Rail-Icons dürfen NICHT das Aufklappen (aside onClick) mit auslösen.
  const stop = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation()
    fn()
  }

  // ---- Eingeklappt: schmale Icon-Leiste (Inhalt für das gemeinsame animierte <aside>) ----
  const collapsedRail = (
    <div className="w-14 h-full flex flex-col items-center py-3 gap-2">
        {/* KI-Logo (Icon) — oben */}
        <RailBtn label={t('sidebar.open_sidebar_logo')} onClick={stop(onToggleSidebar)} plain className="mb-1">
          <CnodeIcon size={30} />
        </RailBtn>
        {/* Suche → öffnet Such-Overlay */}
        <RailBtn label={t('common.search')} onClick={stop(onOpenSearch)}>
          <svg width="17" height="17" viewBox="0 0 16 16" fill="none">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
        </RailBtn>
        {/* 1. Graph · 2. Bibliothek · 3. Benachrichtigungen — oben */}
        <RailBtn label={t('sidebar.memory')} onClick={stop(onOpenGraph)}>
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
            <path d="M9 2l6 3.5v7L9 16l-6-3.5v-7L9 2z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
            <circle cx="9" cy="9" r="1.6" fill="currentColor" />
          </svg>
        </RailBtn>
        <RailBtn label={t('sidebar.library')} onClick={stop(onOpenLibrary)}>
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
            <path d="M2.5 5A1.5 1.5 0 014 3.5h3l1.4 1.6H14A1.5 1.5 0 0115.5 6.6v6A1.5 1.5 0 0114 14.1H4A1.5 1.5 0 012.5 12.6V5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
          </svg>
        </RailBtn>
        <RailBtn label={t('sidebar.notifications')} onClick={stop(onOpenNotifications)} badge={unread}>
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
            <path d="M5 8a4 4 0 118 0c0 3 1.2 4 1.2 4H3.8S5 11 5 8z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
            <path d="M7.5 14.5a1.5 1.5 0 003 0" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
        </RailBtn>
        {canSetup && onOpenSetup && (
          <RailBtn label={t('sidebar.setup_org')} onClick={stop(onOpenSetup)}>
            <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
              <path d="M9 2v2M9 14v2M2 9h2M14 9h2M4 4l1.4 1.4M12.6 12.6L14 14M14 4l-1.4 1.4M5.4 12.6L4 14"
                    stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              <circle cx="9" cy="9" r="2.4" stroke="currentColor" strokeWidth="1.3" />
            </svg>
          </RailBtn>
        )}
        <div className="w-6 h-px bg-line my-0.5" />
        {/* Neuer Chat */}
        <RailBtn label={t('sidebar.new_chat')} onClick={stop(onNewThread)} accent>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </RailBtn>
        <div className="w-6 h-px bg-line my-0.5" />
        {/* EINE Chat-Bubble = alle letzten Chats akkumuliert, mit Counter → Klick klappt aus */}
        <RailBtn label={t('sidebar.chats_open', { count: threads.length })} onClick={stop(onToggleSidebar)} badge={threads.length}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M3 4.5A1.5 1.5 0 014.5 3h9A1.5 1.5 0 0115 4.5v6A1.5 1.5 0 0113.5 12H7l-3 2.5V4.5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
          </svg>
        </RailBtn>

        {/* Unten angepinnt: Einstellungen · Account */}
        <div className="mt-auto flex flex-col items-center gap-1.5">
          <RailBtn label={t('common.settings')} onClick={stop(onSettings)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
              <path d="M19.4 13a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.7 1.7 0 009 19.3a1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1A1.7 1.7 0 004.7 9a1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </RailBtn>
          <RailBtn label={me?.user?.email ?? t('sidebar.account')} onClick={stop(onToggleSidebar)} avatar className="mb-0.5">
            {initial}
          </RailBtn>
        </div>
    </div>
  )

  // ---- Ein gemeinsames <aside>: Breite animiert smooth zwischen w-14 (zu) und w-64 (offen) ----
  return (
    <aside
      onClick={!open ? onToggleSidebar : undefined}
      title={!open ? t('sidebar.open_sidebar') : undefined}
      className={`shrink-0 h-full border-r border-line bg-ink overflow-hidden transition-[width] duration-300 ease-out ${
        open ? 'w-64' : 'w-14 cursor-pointer hover:bg-surface2/30'
      }`}
    >
      {open ? (
      <div className="w-64 h-full flex flex-col">
        {/* Kopf: c:node-Logo + Such-Icon + Einklappen (inline) */}
        <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
          <div className="flex items-center gap-1.5">
            <CnodeLogo className="flex-1 min-w-0" wordmark={wordmark} />
            <button
              onClick={onOpenSearch}
              title={t('common.search')}
              className="shrink-0 p-1.5 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition"
            >
              <svg width="17" height="17" viewBox="0 0 16 16" fill="none">
                <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
                <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </button>
            <button
              onClick={onToggleSidebar}
              title={t('sidebar.collapse_sidebar')}
              className="shrink-0 p-1.5 rounded-lg text-muted hover:text-paper hover:bg-surface2 transition"
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <rect x="2" y="3" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.5" />
                <path d="M7 3v12" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </button>
          </div>

          {/* Primäre Nav (aus der ehemaligen Top-Nav) — über „Neuer Thread" */}
          <div className="flex flex-col gap-0.5">
            <NavRow onClick={onOpenGraph} label={t('sidebar.memory')}>
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
                <path d="M9 2l6 3.5v7L9 16l-6-3.5v-7L9 2z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                <circle cx="9" cy="9" r="1.6" fill="currentColor" />
              </svg>
            </NavRow>
            <NavRow onClick={onOpenLibrary} label={t('sidebar.library')}>
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
                <path d="M2.5 5A1.5 1.5 0 014 3.5h3l1.4 1.6H14A1.5 1.5 0 0115.5 6.6v6A1.5 1.5 0 0114 14.1H4A1.5 1.5 0 012.5 12.6V5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
              </svg>
            </NavRow>
            <NavRow onClick={onOpenNotifications} label={t('sidebar.notifications')} badge={unread}>
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
                <path d="M5 8a4 4 0 118 0c0 3 1.2 4 1.2 4H3.8S5 11 5 8z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                <path d="M7.5 14.5a1.5 1.5 0 003 0" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </NavRow>
            {canSwitchClient && (
              <div className="pt-1">
                <ClientSwitcher clients={clients} active={activeClient} onChange={onClient} />
              </div>
            )}
          </div>

          <div className="h-px bg-line my-0.5" />

          <button
            onClick={onNewThread}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] font-medium text-primary hover:bg-primary/10 transition"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            {t('sidebar.new_chat')}
          </button>
          <button
            onClick={() => setCreatingFolder(true)}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] font-medium text-muted hover:text-paper hover:bg-surface2 transition"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M2 4.5a1 1 0 011-1h3l1.2 1.4H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1V4.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
              <path d="M8 7.2v3M6.5 8.7h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            {t('sidebar.new_folder')}
          </button>
        </div>

        {/* Liste: Ordner + Threads (Suche läuft über das Overlay) — geteilt mit dem mobilen Chats-Screen */}
        <ThreadList
          className="px-3 pb-2"
          threads={threads}
          folders={folders}
          activeThreadId={activeThreadId}
          onSelectThread={onSelectThread}
          onCreateFolder={onCreateFolder}
          onRenameFolder={onRenameFolder}
          onDeleteFolder={onDeleteFolder}
          onRenameThread={onRenameThread}
          onDeleteThread={onDeleteThread}
          onMoveThread={onMoveThread}
          creatingFolder={creatingFolder}
          onCreatingFolderChange={setCreatingFolder}
        />

        {/* Footer: kompaktes Account-Drop-up (Modell · Einstellungen · Abmelden) */}
        <div className="mt-auto border-t border-line p-2">
          <AccountMenu
            me={me}
            initial={initial}
            tenantLabel={tenantLabel}
            provider={provider}
            model={model}
            claudeReady={claudeReady}
            geminiReady={geminiReady}
            onProvider={onProvider}
            onSettings={onSettings}
            onLogout={onLogout}
            sandbox={sandbox}
          />
        </div>
      </div>
      ) : (
        collapsedRail
      )}
    </aside>
  )
}

// Kompaktes Account-Drop-up (öffnet nach oben): Konto-Kopf · Modellauswahl ·
// „Modelle & API konfigurieren" (Settings-Tab) · Einstellungen · Abmelden.
function AccountMenu({
  me,
  initial,
  tenantLabel,
  provider,
  model,
  claudeReady,
  geminiReady,
  onProvider,
  onSettings,
  onLogout,
  sandbox = false,
}: {
  me: Me | null
  initial: string
  tenantLabel: string
  provider: Provider
  model: string
  claudeReady: boolean
  geminiReady: boolean
  onProvider: (p: Provider) => void
  onSettings: (section?: string) => void
  onLogout: () => void
  sandbox?: boolean
}) {
  const t = useT()
  const roleName = useRoleLabel()
  const [open, setOpen] = useState(false)
  const [modelSub, setModelSub] = useState(false)
  const [subPos, setSubPos] = useState<{ left: number; bottom: number } | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const subRef = useRef<HTMLDivElement>(null)
  const modelBtnRef = useRef<HTMLButtonElement>(null)
  const closeAll = () => { setOpen(false); setModelSub(false) }
  const openModelSub = () => {
    const r = modelBtnRef.current?.getBoundingClientRect()
    if (r) setSubPos({ left: r.right + 8, bottom: window.innerHeight - r.bottom })
    setModelSub(true)
  }
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      const t = e.target as Node
      if (ref.current && !ref.current.contains(t) && !subRef.current?.contains(t)) closeAll()
    }
    function onEsc(e: KeyboardEvent) { if (e.key === 'Escape') closeAll() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  const mdl = model || 'qwen2.5:7b'
  const providerLabel = sandbox
    ? t('sidebar.provider_gemini_cloud')
    : provider === 'claude' ? 'Claude' : provider === 'gemini' ? 'Gemini' : t('sidebar.provider_ollama', { model: mdl })
  // Grüner Punkt = live/verbunden (lokal Ollama ODER Cloud Gemini). Beide sind aktiv.
  const providerDot = provider === 'claude' ? 'bg-cviolet' : 'bg-cmint'

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => { if (v) setModelSub(false); return !v })}
        title={t('sidebar.account_menu_title')}
        className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg transition ${
          open ? 'bg-surface2' : 'hover:bg-surface2'
        }`}
      >
        <span className="w-8 h-8 rounded-full bg-primary text-ink grid place-items-center font-display font-extrabold text-[13px] shrink-0">
          {initial}
        </span>
        <span className="min-w-0 flex-1 text-left">
          <span className="block text-[12.5px] text-paper truncate" title={me?.user?.email}>{me?.user?.email ?? t('sidebar.account')}</span>
          <span className="block text-[10px] text-faint truncate">{sandbox ? providerLabel : t('sidebar.local_prefix', { label: providerLabel })}</span>
        </span>
        <svg width="13" height="13" viewBox="0 0 12 12" className={`text-muted shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}>
          <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        </svg>
      </button>

      {open && (
        <div className="absolute bottom-full left-0 right-0 mb-1.5 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 py-1 z-40 animate-fade-up">
          {/* Konto-Kopf */}
          <div className="flex items-center gap-2 px-3 py-2 mb-1 border-b border-line">
            <span className="w-7 h-7 rounded-full bg-primary text-ink grid place-items-center font-display font-extrabold text-[12px] shrink-0">{initial}</span>
            <span className="min-w-0">
              <span className="block text-[12px] text-paper truncate">{me?.user?.email ?? t('sidebar.account')}</span>
              <span className="block text-[10px] text-faint truncate">{me ? roleName(me.role) : ''}{tenantLabel ? ` · ${tenantLabel}` : ''}</span>
            </span>
          </div>

          {/* Modell — ein Menüpunkt, klappt nach rechts aus (Portal, damit nicht geclippt) */}
          <button
            ref={modelBtnRef}
            onClick={() => (modelSub ? setModelSub(false) : openModelSub())}
            className={`w-full flex items-center gap-2 px-3 py-1.5 text-[12.5px] transition ${
              modelSub ? 'bg-surface2 text-paper' : 'text-paper hover:bg-surface2'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${providerDot}`} />
            <span className="flex-1 text-left truncate"><span className="text-faint">{t('sidebar.model_prefix')}</span>{providerLabel}</span>
            <svg width="11" height="11" viewBox="0 0 12 12" className="text-faint shrink-0"><path d="M4.5 2.5L8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>

          {modelSub && subPos && createPortal(
            <div
              ref={subRef}
              style={{ position: 'fixed', left: subPos.left, bottom: subPos.bottom }}
              className="w-60 rounded-xl bg-surface border border-line shadow-2xl shadow-black/60 py-1 z-[60] animate-fade-up"
            >
              <div className="px-3 pt-1 pb-1 text-[10px] font-mono uppercase tracking-wider text-faint">{t('sidebar.choose_model')}</div>
              {sandbox ? (
                <>
                  <div className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] text-paper">
                    <span className="w-1.5 h-1.5 rounded-full bg-cmint shrink-0" />
                    <span className="flex-1 text-left truncate">{t('sidebar.provider_gemini_cloud')}</span>
                    <Check />
                  </div>
                  <p className="px-3 pb-1.5 pt-0.5 text-[10.5px] text-faint leading-snug">
                    {t('sidebar.sandbox_note')}
                  </p>
                </>
              ) : (<>
              <button
                onClick={() => { onProvider('ollama'); closeAll() }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] text-paper hover:bg-surface2 transition"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-cmint shrink-0" />
                <span className="flex-1 text-left truncate">{t('sidebar.model_local_ollama', { model: mdl })}</span>
                {provider === 'ollama' && <Check />}
              </button>
              {geminiReady ? (
                <button
                  onClick={() => { onProvider('gemini'); closeAll() }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] text-paper hover:bg-surface2 transition"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-cmint shrink-0" />
                  <span className="flex-1 text-left truncate">{t('sidebar.model_gemini_cloud')}</span>
                  {provider === 'gemini' && <Check />}
                </button>
              ) : (
                <ComingRow label="Gemini" />
              )}
              {claudeReady ? (
                <button
                  onClick={() => { onProvider('claude'); closeAll() }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] text-paper hover:bg-surface2 transition"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-cviolet shrink-0" />
                  <span className="flex-1 text-left truncate">{t('sidebar.model_claude_cloud')}</span>
                  {provider === 'claude' && <Check />}
                </button>
              ) : (
                <ComingRow label="Claude" />
              )}
              <div className="h-px bg-line my-1" />
              <button
                onClick={() => { closeAll(); onSettings('model') }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[11.5px] text-muted hover:text-paper hover:bg-surface2 transition"
              >
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="shrink-0 text-faint"><circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.3"/><path d="M8 3.2v1.4M8 11.4v1.4M3.2 8h1.4M11.4 8h1.4M4.6 4.6l1 1M9.4 9.4l1 1M11.4 4.6l-1 1M5.6 9.4l-1 1" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round"/></svg>
                <span className="flex-1 text-left truncate">{t('sidebar.configure_models')}</span>
              </button>
              </>)}
            </div>,
            document.body,
          )}

          <div className="h-px bg-line my-1" />
          <button
            onClick={() => { setOpen(false); onSettings() }}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[12.5px] text-paper hover:bg-surface2 transition"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" className="text-muted shrink-0">
              <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
              <path d="M19.4 13a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.7 1.7 0 009 19.3a1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1A1.7 1.7 0 004.7 9a1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('common.settings')}
          </button>
          <button
            onClick={onLogout}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[12.5px] text-crose hover:bg-crose/10 transition"
          >
            <svg width="15" height="15" viewBox="0 0 18 18" fill="none" className="shrink-0">
              <path d="M7 2.5H4a1.5 1.5 0 00-1.5 1.5v10A1.5 1.5 0 004 15.5h3M11.5 12l3-3-3-3M14 9H6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('common.logout')}
          </button>

          {/* Sprache — ganz unten im Profil-Dropdown (Desktop) */}
          <div className="h-px bg-line my-1" />
          <div className="flex items-center justify-between gap-2 px-3 py-1.5">
            <span className="text-[12.5px] text-paper">{t('common.language')}</span>
            <LanguageSwitcher />
          </div>
        </div>
      )}
    </div>
  )
}

function Check() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="text-primary shrink-0">
      <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function ComingRow({ label }: { label: string }) {
  const t = useT()
  return (
    <div className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-faint cursor-not-allowed">
      <span className="w-1.5 h-1.5 rounded-full bg-line shrink-0" />
      <span className="flex-1 text-left truncate">{label}</span>
      <span className="text-[9px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-surface3 border border-line text-faint">{t('sidebar.coming_soon')}</span>
    </div>
  )
}

// Kleiner Hover-Tooltip (erscheint rechts neben dem Icon) für die eingeklappte Leiste.
function Tip({ children }: { children: React.ReactNode }) {
  return (
    <span className="pointer-events-none absolute left-full ml-2 top-1/2 -translate-y-1/2 whitespace-nowrap rounded-md bg-surface3 border border-line px-2 py-1 text-[11px] text-paper opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-[60] shadow-lg shadow-black/40">
      {children}
    </span>
  )
}

// Icon-Button der eingeklappten Leiste: Tooltip bei Hover + optionaler Badge/Akzent.
function RailBtn({
  label,
  onClick,
  badge,
  accent,
  plain,
  avatar,
  className = '',
  children,
}: {
  label: string
  onClick: (e: React.MouseEvent) => void
  badge?: number
  accent?: boolean
  plain?: boolean
  avatar?: boolean
  className?: string
  children: React.ReactNode
}) {
  const base = plain
    ? 'grid place-items-center'
    : avatar
      ? 'w-8 h-8 rounded-full bg-primary text-ink grid place-items-center font-display font-extrabold text-[12px]'
      : accent
        ? 'w-9 h-9 grid place-items-center rounded-lg bg-primary/15 border border-primary/45 text-primary hover:bg-primary/25'
        : 'w-9 h-9 grid place-items-center rounded-lg text-muted hover:text-paper hover:bg-surface2'
  return (
    <button onClick={onClick} className={`group relative transition ${base} ${className}`}>
      {children}
      {badge != null && badge > 0 && !avatar && (
        <span className="absolute -top-1 -right-1 min-w-[16px] h-[16px] px-1 grid place-items-center rounded-full bg-primary text-ink text-[9.5px] font-bold leading-none">
          {badge > 99 ? '99+' : badge}
        </span>
      )}
      <Tip>{label}</Tip>
    </button>
  )
}

function NavRow({
  onClick,
  label,
  badge,
  children,
}: {
  onClick: () => void
  label: string
  badge?: number
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] text-muted hover:text-paper hover:bg-surface2 transition"
    >
      <span className="shrink-0">{children}</span>
      <span className="flex-1 text-left truncate">{label}</span>
      {badge != null && badge > 0 && (
        <span className="shrink-0 min-w-[18px] h-[18px] px-1 grid place-items-center rounded-full bg-primary text-ink text-[10px] font-bold leading-none">
          {badge > 99 ? '99+' : badge}
        </span>
      )}
    </button>
  )
}
