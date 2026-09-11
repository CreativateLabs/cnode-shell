import { useEffect, useRef, useState } from 'react'
import type { Me, Provider } from '../types'
import { useRoleLabel } from '../roles'
import { useT } from '../i18n'
import LanguageSwitcher from './LanguageSwitcher'

type MobileHeaderMenuProps = {
  me: Me | null
  provider: Provider
  model?: string
  claudeReady: boolean
  geminiReady: boolean
  onProviderDefault: (p: Provider) => void
  onSettings: (section?: string) => void
  onLogout: () => void
  sandbox?: boolean
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
      <span className="text-[9px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-surface3 border border-line text-faint">{t('mobileheader.soon')}</span>
    </div>
  )
}

/**
 * Avatar-Button + Profil-Dropdown für die mobile Top-Leiste (< md).
 * Spiegelt die Sandbox-Logik der Sidebar-„AccountMenu": im Public-Demo ist das Modell
 * fest Gemini · Cloud (gesperrt), sonst wählbar über onProviderDefault.
 * Menü ist oben-rechts verankert und schließt bei Klick nach außen / Esc.
 */
export default function MobileHeaderMenu({
  me,
  provider,
  model,
  claudeReady,
  geminiReady,
  onProviderDefault,
  onSettings,
  onLogout,
  sandbox = false,
}: MobileHeaderMenuProps) {
  const t = useT()
  const roleName = useRoleLabel()
  const [open, setOpen] = useState(false)
  const [modelSub, setModelSub] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const initial = (me?.user?.email?.[0] ?? '?').toUpperCase()
  const tenantLabel = me?.tenant?.label ?? me?.tenant?.name ?? me?.tenant?.id ?? ''
  const mdl = model || 'qwen2.5:7b'
  const providerLabel = sandbox
    ? t('mobileheader.gemini_cloud')
    : provider === 'claude' ? 'Claude' : provider === 'gemini' ? 'Gemini' : t('mobileheader.ollama_model', { model: mdl })
  const providerDot = provider === 'claude' ? 'bg-cviolet' : 'bg-cmint'

  const closeAll = () => { setOpen(false); setModelSub(false) }

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) closeAll()
    }
    function onEsc(e: KeyboardEvent) { if (e.key === 'Escape') closeAll() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        onClick={() => setOpen((v) => { if (v) setModelSub(false); return !v })}
        title={me?.user?.email ?? t('mobileheader.account')}
        aria-label={t('mobileheader.menu_aria')}
        aria-expanded={open}
        className="h-11 pl-1 pr-1.5 flex items-center gap-1 rounded-lg hover:bg-surface2 transition"
      >
        <span className="w-8 h-8 rounded-full bg-primary text-ink grid place-items-center font-display font-extrabold text-[13px]">
          {initial}
        </span>
        <svg width="12" height="12" viewBox="0 0 12 12" className={`text-muted shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}>
          <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-64 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 py-1 z-50 animate-fade-down">
          {/* Konto-Kopf */}
          <div className="flex items-center gap-2 px-3 py-2 mb-1 border-b border-line">
            <span className="w-7 h-7 rounded-full bg-primary text-ink grid place-items-center font-display font-extrabold text-[12px] shrink-0">{initial}</span>
            <span className="min-w-0">
              <span className="block text-[12px] text-paper truncate">{me?.user?.email ?? t('mobileheader.account')}</span>
              <span className="block text-[10px] text-faint truncate">{me ? roleName(me.role) : ''}{tenantLabel ? ` · ${tenantLabel}` : ''}</span>
            </span>
          </div>

          {/* Sprache — ganz oben im Dropdown */}
          <div className="flex items-center justify-between gap-2 px-3 py-2">
            <span className="text-[12.5px] text-paper">{t('common.language')}</span>
            <LanguageSwitcher />
          </div>
          <div className="h-px bg-line my-1" />

          {/* Modell — klappt inline aus */}
          <button
            onClick={() => setModelSub((v) => !v)}
            className={`w-full flex items-center gap-2 px-3 py-2.5 text-[12.5px] transition ${
              modelSub ? 'bg-surface2 text-paper' : 'text-paper hover:bg-surface2'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${providerDot}`} />
            <span className="flex-1 text-left truncate"><span className="text-faint">{t('mobileheader.model_label')}</span>{providerLabel}</span>
            <svg width="11" height="11" viewBox="0 0 12 12" className={`text-faint shrink-0 transition-transform ${modelSub ? 'rotate-90' : ''}`}><path d="M4.5 2.5L8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>

          {modelSub && (
            <div className="mx-1 mb-1 rounded-lg bg-surface2 border border-line py-1">
              {sandbox ? (
                <>
                  <div className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-paper">
                    <span className="w-1.5 h-1.5 rounded-full bg-cmint shrink-0" />
                    <span className="flex-1 text-left truncate">{t('mobileheader.gemini_cloud')}</span>
                    <Check />
                  </div>
                  <p className="px-3 pb-1.5 pt-0.5 text-[10.5px] text-faint leading-snug">
                    {t('mobileheader.sandbox_note')}
                  </p>
                </>
              ) : (
                <>
                  <button
                    onClick={() => { onProviderDefault('ollama'); closeAll() }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-paper hover:bg-surface3 transition"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-cmint shrink-0" />
                    <span className="flex-1 text-left truncate">{t('mobileheader.local_ollama', { model: mdl })}</span>
                    {provider === 'ollama' && <Check />}
                  </button>
                  {geminiReady ? (
                    <button
                      onClick={() => { onProviderDefault('gemini'); closeAll() }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-paper hover:bg-surface3 transition"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-cmint shrink-0" />
                      <span className="flex-1 text-left truncate">{t('mobileheader.gemini_paren')}</span>
                      {provider === 'gemini' && <Check />}
                    </button>
                  ) : (
                    <ComingRow label="Gemini" />
                  )}
                  {claudeReady ? (
                    <button
                      onClick={() => { onProviderDefault('claude'); closeAll() }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-paper hover:bg-surface3 transition"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-cviolet shrink-0" />
                      <span className="flex-1 text-left truncate">{t('mobileheader.claude_paren')}</span>
                      {provider === 'claude' && <Check />}
                    </button>
                  ) : (
                    <ComingRow label="Claude" />
                  )}
                </>
              )}
            </div>
          )}

          <div className="h-px bg-line my-1" />
          <button
            onClick={() => { closeAll(); onSettings('profile') }}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[12.5px] text-paper hover:bg-surface2 transition"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" className="text-muted shrink-0">
              <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
              <path d="M19.4 13a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.7 1.7 0 009 19.3a1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1A1.7 1.7 0 004.7 9a1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('common.settings')}
          </button>
          <button
            onClick={() => { closeAll(); onLogout() }}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[12.5px] text-crose hover:bg-crose/10 transition"
          >
            <svg width="15" height="15" viewBox="0 0 18 18" fill="none" className="shrink-0">
              <path d="M7 2.5H4a1.5 1.5 0 00-1.5 1.5v10A1.5 1.5 0 004 15.5h3M11.5 12l3-3-3-3M14 9H6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('common.logout')}
          </button>
        </div>
      )}
    </div>
  )
}
