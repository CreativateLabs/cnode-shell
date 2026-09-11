import { useEffect, useMemo, useRef, useState } from 'react'
import type { ThreadVisibility } from '../types'
import type { Thread } from './Sidebar'
import Avatar, { AvatarStack } from './Avatar'
import { useT } from '../i18n'

// Thread-Header über dem Chat: privat/team-Umschalter + Member-Picker + Avatare.
// Nur Owner/Admin darf umstellen (canManage).
export default function ThreadHeader({
  thread,
  meEmail,
  canManage,
  tenantEmails,
  onSetVisibility,
  onSetMembers,
  onShare,
  railOpen,
  onToggleRail,
}: {
  thread: Thread
  meEmail?: string
  canManage: boolean
  tenantEmails: string[]
  onSetVisibility: (v: ThreadVisibility) => void
  onSetMembers: (emails: string[]) => void
  onShare?: () => void
  railOpen?: boolean
  onToggleRail?: () => void
}) {
  const t = useT()
  const [pickerOpen, setPickerOpen] = useState(false)
  const [query, setQuery] = useState('')
  const pickerRef = useRef<HTMLDivElement>(null)

  const visibility: ThreadVisibility = thread.visibility ?? 'private'
  const owner = thread.owner ?? meEmail
  const members = thread.members ?? []

  useEffect(() => {
    if (!pickerOpen) return
    function onDown(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setPickerOpen(false)
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setPickerOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onEsc)
    }
  }, [pickerOpen])

  const candidates = useMemo(() => {
    const taken = new Set([owner, ...members].filter(Boolean).map((e) => e!.toLowerCase()))
    const q = query.trim().toLowerCase()
    return tenantEmails
      .filter((e) => !taken.has(e.toLowerCase()))
      .filter((e) => !q || e.toLowerCase().includes(q))
      .slice(0, 8)
  }, [tenantEmails, owner, members, query])

  const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(query.trim())

  function addMember(email: string) {
    const e = email.trim()
    if (!e) return
    if (members.some((m) => m.toLowerCase() === e.toLowerCase())) return
    if (owner && e.toLowerCase() === owner.toLowerCase()) return
    onSetMembers([...members, e])
    setQuery('')
  }
  function removeMember(email: string) {
    onSetMembers(members.filter((m) => m !== email))
  }

  return (
    <div className="relative shrink-0 flex items-center justify-between gap-3 px-4 py-2 bg-ink">
      {/* Fade statt harter Border — spiegelt den Fade unten am Composer */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 -bottom-6 h-6 bg-gradient-to-b from-ink to-transparent" />
      {/* left: title */}
      <div className="min-w-0 flex items-center gap-2">
        <span className="text-[13px] font-medium text-paper truncate" title={thread.title}>
          {thread.title || t('threadheader.new_chat_title')}
        </span>
      </div>

      {/* right: visibility toggle + avatars + member picker */}
      <div className="flex items-center gap-2.5 shrink-0">
        {/* avatars */}
        <AvatarStack emails={visibility === 'team' ? members : []} owner={owner} size="sm" />

        {/* visibility toggle */}
        <div
          className="flex items-center rounded-lg bg-surface2 border border-line p-0.5 text-[11.5px]"
          title={canManage ? t('threadheader.toggle_visibility') : t('threadheader.only_owner_admin')}
        >
          <button
            disabled={!canManage}
            onClick={() => canManage && onSetVisibility('private')}
            className={`flex items-center gap-1 px-2 py-1 rounded-md transition ${
              visibility === 'private' ? 'bg-primary/15 text-primary' : 'text-muted'
            } ${!canManage ? 'cursor-not-allowed' : 'hover:text-paper'}`}
          >
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <rect x="2.5" y="5" width="7" height="5" rx="1" stroke="currentColor" strokeWidth="1" />
              <path d="M4 5V3.5a2 2 0 014 0V5" stroke="currentColor" strokeWidth="1" />
            </svg>
            {t('threadheader.private')}
          </button>
          <button
            disabled={!canManage}
            onClick={() => canManage && onSetVisibility('team')}
            className={`flex items-center gap-1 px-2 py-1 rounded-md transition ${
              visibility === 'team' ? 'bg-cmint/15 text-cmint' : 'text-muted'
            } ${!canManage ? 'cursor-not-allowed' : 'hover:text-paper'}`}
          >
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <circle cx="4" cy="4" r="1.6" stroke="currentColor" strokeWidth="1" />
              <circle cx="8.5" cy="4.5" r="1.3" stroke="currentColor" strokeWidth="1" />
              <path d="M1.5 10c0-1.6 1.1-2.5 2.5-2.5S6.5 8.4 6.5 10M7 8c1.2 0 2.5.5 2.5 2" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
            </svg>
            {t('threadheader.team')}
          </button>
          <button
            disabled={!canManage}
            onClick={() => canManage && onSetVisibility('org')}
            title={t('threadheader.org_visible')}
            className={`flex items-center gap-1 px-2 py-1 rounded-md transition ${
              visibility === 'org' ? 'bg-cviolet/15 text-cviolet' : 'text-muted'
            } ${!canManage ? 'cursor-not-allowed' : 'hover:text-paper'}`}
          >
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <rect x="2" y="3" width="5" height="7.5" rx="0.6" stroke="currentColor" strokeWidth="1" />
              <path d="M7 5.5h3v5H7" stroke="currentColor" strokeWidth="1" />
              <path d="M3.5 5h2M3.5 7h2M8.3 7.2h1M2 10.5h8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
            </svg>
            {t('threadheader.org')}
          </button>
        </div>

        {/* member picker (team + manage only) */}
        {visibility === 'team' && canManage && (
          <div className="relative" ref={pickerRef}>
            <button
              onClick={() => setPickerOpen((v) => !v)}
              title={t('threadheader.manage_members')}
              className={`flex items-center gap-1 px-2 py-1.5 rounded-lg border text-[11.5px] transition ${
                pickerOpen ? 'bg-surface2 border-primary/50 text-paper' : 'bg-surface2 border-line text-muted hover:text-paper'
              }`}
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <circle cx="6" cy="5" r="2.2" stroke="currentColor" strokeWidth="1.2" />
                <path d="M2 13c0-2.2 1.8-3.6 4-3.6s4 1.4 4 3.6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                <path d="M12 5.5v4M14 7.5h-4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
              {t('threadheader.members')}
            </button>

            {pickerOpen && (
              <div className="absolute right-0 top-full mt-2 w-72 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 p-3 z-40 animate-fade-up">
                <div className="text-[10px] font-mono uppercase tracking-wider text-faint mb-2">
                  {t('threadheader.members_count', { count: members.length })}
                </div>

                {/* current members */}
                <div className="flex flex-col gap-1 mb-2 max-h-32 overflow-y-auto">
                  {owner && (
                    <div className="flex items-center gap-2 px-1.5 py-1 rounded-lg">
                      <Avatar email={owner} size="xs" />
                      <span className="text-[12px] text-paper/90 truncate flex-1">{owner}</span>
                      <span className="text-[9px] font-mono uppercase text-primary">{t('threadheader.owner')}</span>
                    </div>
                  )}
                  {members.map((m) => (
                    <div key={m} className="flex items-center gap-2 px-1.5 py-1 rounded-lg hover:bg-surface2 group">
                      <Avatar email={m} size="xs" />
                      <span className="text-[12px] text-paper/90 truncate flex-1">{m}</span>
                      <button
                        onClick={() => removeMember(m)}
                        title={t('threadheader.remove')}
                        className="text-faint hover:text-crose opacity-0 group-hover:opacity-100 transition"
                      >
                        <svg width="12" height="12" viewBox="0 0 14 14">
                          <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                        </svg>
                      </button>
                    </div>
                  ))}
                  {members.length === 0 && (
                    <div className="text-[11px] text-faint px-1.5 py-1">{t('threadheader.no_members')}</div>
                  )}
                </div>

                {/* add member */}
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && isValidEmail && addMember(query)}
                  placeholder={t('threadheader.add_email_placeholder')}
                  className="w-full rounded-lg bg-surface2 border border-line px-2.5 py-1.5 text-[12px] text-paper placeholder:text-faint outline-none focus:border-primary/50 transition"
                />
                {(candidates.length > 0 || isValidEmail) && (
                  <div className="mt-1.5 flex flex-col gap-0.5 max-h-32 overflow-y-auto">
                    {candidates.map((e) => (
                      <button
                        key={e}
                        onClick={() => addMember(e)}
                        className="flex items-center gap-2 px-1.5 py-1 rounded-lg text-left hover:bg-surface2 transition"
                      >
                        <Avatar email={e} size="xs" />
                        <span className="text-[12px] text-paper/90 truncate">{e}</span>
                      </button>
                    ))}
                    {isValidEmail && !candidates.some((c) => c.toLowerCase() === query.trim().toLowerCase()) && (
                      <button
                        onClick={() => addMember(query)}
                        className="flex items-center gap-2 px-1.5 py-1 rounded-lg text-left hover:bg-surface2 transition text-primary text-[12px]"
                      >
                        {t('threadheader.invite', { email: query.trim() })}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Thread teilen */}
        {onShare && (
          <button
            onClick={onShare}
            title={t('threadheader.share_chat')}
            className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg border border-line bg-surface2 text-muted hover:text-paper hover:border-line2 transition text-[11.5px]"
          >
            <svg width="13" height="13" viewBox="0 0 18 18" fill="none">
              <path d="M12 6a2 2 0 100-4 2 2 0 000 4zM6 11a2 2 0 100-4 2 2 0 000 4zM12 16a2 2 0 100-4 2 2 0 000 4z" stroke="currentColor" strokeWidth="1.4" />
              <path d="M7.6 8.1l2.8-1.6M7.6 9.9l2.8 1.6" stroke="currentColor" strokeWidth="1.4" />
            </svg>
            {t('threadheader.share')}
          </button>
        )}

        {/* Thread-Kontext-Rail (Agenten · Artefakte · Dateien) — rechts außen, da thread-basiert */}
        {onToggleRail && (
          <>
            <div className="w-px h-5 bg-line mx-0.5" />
            <button
              onClick={onToggleRail}
              title={t('threadheader.context_title')}
              className={`p-1.5 rounded-lg border transition ${
                railOpen
                  ? 'text-primary border-primary/40 bg-primary/10'
                  : 'text-muted border-line hover:text-paper hover:border-line2'
              }`}
            >
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
                <rect x="2.5" y="3" width="13" height="12" rx="2" stroke="currentColor" strokeWidth="1.5" />
                <path d="M11.5 3v12" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </button>
          </>
        )}
      </div>
    </div>
  )
}
