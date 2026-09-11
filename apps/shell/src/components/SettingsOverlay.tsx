import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { Me, Member, Promotion, Provider, Role, Team, TeamMember, TeamRole, Tenant } from '../types'
import { ASSIGNABLE_MEMBER_ROLES, isAdmin, isSuperAdmin, useRoleLabel } from '../roles'
import ConnectorLibrary from './ConnectorLibrary'
import LanguageSwitcher from './LanguageSwitcher'
import { useT } from '../i18n'

type SectionId = 'profile' | 'members' | 'teams' | 'sources' | 'connectors' | 'tenants' | 'promotions' | 'model'

function SectionShell({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="animate-fade-in">
      <h3 className="font-display font-bold text-[17px] text-paper">{title}</h3>
      {desc && <p className="text-[12.5px] text-muted mt-1 mb-4 max-w-xl">{desc}</p>}
      <div className={desc ? '' : 'mt-4'}>{children}</div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11px] font-mono uppercase tracking-wider text-faint">{label}</span>
      <div className="mt-1.5">{children}</div>
    </label>
  )
}

const inputCls =
  'w-full rounded-xl bg-surface2 border border-line px-3.5 py-2.5 text-[13px] text-paper placeholder:text-faint outline-none focus:border-primary/50 transition'
const btnPrimary =
  'px-4 py-2.5 rounded-full bg-primary text-ink font-semibold text-[13px] disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-105 transition'
const btnGhost =
  'px-3 py-2 rounded-xl text-[13px] text-muted hover:text-paper hover:bg-surface2 border border-line transition'

// ---------------- Profile (all roles) ----------------
function ProfileSection({
  me,
  provider,
  claudeReady,
  geminiReady,
  onProviderDefault,
}: {
  me: Me
  provider: Provider
  claudeReady: boolean
  geminiReady: boolean
  onProviderDefault: (p: Provider) => void
}) {
  const t = useT()
  const roleName = useRoleLabel()
  return (
    <SectionShell title={t('settings.profile.title')} desc={t('settings.profile.desc')}>
      <div className="flex flex-col gap-4 max-w-md">
        <Field label={t('common.language')}>
          <LanguageSwitcher variant="segmented" />
        </Field>
        <Field label={t('settings.profile.email')}>
          <div className={`${inputCls} opacity-70`}>{me.user.email}</div>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('settings.profile.role')}>
            <div className={`${inputCls} opacity-70`}>{roleName(me.role)}</div>
          </Field>
          <Field label={t('settings.profile.tenant')}>
            <div className={`${inputCls} opacity-70`}>{me.tenant?.name ?? '—'}</div>
          </Field>
        </div>
        <Field label={t('settings.profile.default_model')}>
          <div className="flex items-center rounded-xl bg-surface2 border border-line p-1 text-[12.5px] w-fit">
            <button
              onClick={() => onProviderDefault('ollama')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition ${
                provider === 'ollama' ? 'bg-primary text-ink font-semibold' : 'text-muted hover:text-paper'
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${provider === 'ollama' ? 'bg-ink' : 'bg-cmint'}`} />
              {t('settings.profile.local_oss')}
            </button>
            <button
              onClick={() => geminiReady && onProviderDefault('gemini')}
              disabled={!geminiReady}
              title={geminiReady ? t('settings.provider.gemini_title') : t('settings.provider.gemini_missing')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition ${
                provider === 'gemini'
                  ? 'bg-primary text-ink font-semibold'
                  : geminiReady
                    ? 'text-muted hover:text-paper'
                    : 'text-faint cursor-not-allowed'
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${provider === 'gemini' ? 'bg-ink' : 'bg-cmint'}`} />
              {t('settings.profile.gemini_cloud')}
            </button>
            <button
              onClick={() => claudeReady && onProviderDefault('claude')}
              disabled={!claudeReady}
              title={claudeReady ? t('settings.provider.claude_title') : t('settings.provider.claude_missing')}
              className={`px-3 py-1.5 rounded-lg transition ${
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
        </Field>
      </div>
    </SectionShell>
  )
}

// ---------------- Teams (Admin/Owner + Team-Lead) ----------------
function TeamDetail({ team, admin, onChanged }: { team: Team; admin: boolean; onChanged: () => void }) {
  const t = useT()
  const [members, setMembers] = useState<TeamMember[]>([])
  const [loading, setLoading] = useState(true)
  const [email, setEmail] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [invite, setInvite] = useState<string | null>(null)
  const canManage = admin || team.my_role === 'lead'

  const load = useCallback(() => {
    setLoading(true)
    api.teamMembers(team.id).then(setMembers).catch((e) => setErr(e.message)).finally(() => setLoading(false))
  }, [team.id])
  useEffect(load, [load])

  async function add() {
    if (!email.trim()) return
    try { await api.addTeamMember(team.id, email.trim()); setEmail(''); load(); onChanged() }
    catch (e: any) { setErr(e.message) }
  }
  async function inviteLink() {
    if (!email.trim()) return
    setErr(null); setInvite(null)
    try {
      const r = await api.createInvite({ email: email.trim(), team_id: team.id, team_role: 'member' })
      setEmail('')
      if (r.sent) setInvite(t('settings.team.invite_sent'))
      else if (r.dev_link) {
        try { await navigator.clipboard.writeText(r.dev_link) } catch { /* ignore */ }
        setInvite(t('settings.team.magic_copied', { link: r.dev_link }))
      }
    } catch (e: any) { setErr(e.message) }
  }
  async function toggleRole(m: TeamMember) {
    const next: TeamRole = m.role === 'lead' ? 'member' : 'lead'
    try { await api.setTeamRole(team.id, m.user_id, next); load() } catch (e: any) { setErr(e.message) }
  }
  async function remove(m: TeamMember) {
    try { await api.removeTeamMember(team.id, m.user_id); load(); onChanged() } catch (e: any) { setErr(e.message) }
  }

  return (
    <div className="mt-2 pl-3 border-l-2 border-line flex flex-col gap-2">
      {canManage && (
        <div className="flex items-end gap-2">
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
            placeholder={t('settings.team.member_ph')} className={`${inputCls} flex-1`}
          />
          <button onClick={add} disabled={!email.trim()} className={btnPrimary}>{t('settings.team.add_member')}</button>
          <button onClick={inviteLink} disabled={!email.trim()} className={btnGhost}>{t('settings.team.invite_link')}</button>
        </div>
      )}
      {invite && <p className="text-[11.5px] text-cmint/90 break-all">{invite}</p>}
      {err && <p className="text-[12px] text-crose/90">{err}</p>}
      {loading ? (
        <p className="text-[12px] text-muted">{t('settings.team.loading')}</p>
      ) : members.length === 0 ? (
        <p className="text-[12px] text-faint">{t('settings.team.empty')}</p>
      ) : (
        members.map((m) => (
          <div key={m.id} className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-surface2 border border-line">
            <span className="text-[12.5px] text-paper truncate">{m.email}</span>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => canManage && toggleRole(m)} disabled={!canManage}
                title={canManage ? t('settings.team.toggle_role') : ''}
                className={`text-[10.5px] font-mono px-2 py-0.5 rounded-md border ${
                  m.role === 'lead' ? 'bg-primary/15 border-primary/40 text-primary' : 'bg-surface3 border-line text-muted'
                } ${canManage ? 'hover:brightness-110' : 'cursor-default'}`}
              >
                {m.role === 'lead' ? t('settings.role.lead_badge') : t('settings.role.member')}
              </button>
              {canManage && (
                <button onClick={() => remove(m)} title={t('settings.team.remove')} className="text-faint hover:text-crose transition">
                  <svg width="14" height="14" viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
                </button>
              )}
            </div>
          </div>
        ))
      )}
    </div>
  )
}

function TeamsSection({ admin }: { admin: boolean }) {
  const t = useT()
  const [teams, setTeams] = useState<Team[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.teams().then(setTeams).catch((e) => setErr(e.message)).finally(() => setLoading(false))
  }, [])
  useEffect(load, [load])

  async function create() {
    if (!name.trim() || busy) return
    setBusy(true); setErr(null)
    try { await api.createTeam(name.trim()); setName(''); load() }
    catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  async function del(team: Team) {
    if (!confirm(t('settings.teams.delete_confirm', { name: team.name }))) return
    try { await api.deleteTeam(team.id); load() } catch (e: any) { setErr(e.message) }
  }

  return (
    <SectionShell title={t('settings.teams.title')} desc={t('settings.teams.desc')}>
      {admin && (
        <div className="flex items-end gap-2 mb-4 max-w-2xl">
          <div className="flex-1">
            <Field label={t('settings.teams.new_label')}>
              <input value={name} onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && create()}
                placeholder={t('settings.teams.new_ph')} className={inputCls} />
            </Field>
          </div>
          <button onClick={create} disabled={busy || !name.trim()} className={btnPrimary}>{t('settings.teams.create')}</button>
        </div>
      )}
      {err && <p className="text-[12px] text-crose/90 mb-2">{err}</p>}
      {loading ? (
        <p className="text-[12.5px] text-muted">{t('settings.teams.loading')}</p>
      ) : teams.length === 0 ? (
        <p className="text-[12.5px] text-faint">{t('settings.teams.empty')}</p>
      ) : (
        <div className="flex flex-col gap-2 max-w-2xl">
          {teams.map((team) => (
            <div key={team.id} className="rounded-xl bg-surface2 border border-line p-3">
              <div className="flex items-center justify-between gap-3">
                <button onClick={() => setOpen(open === team.id ? null : team.id)} className="flex items-center gap-2 min-w-0 text-left">
                  <svg width="12" height="12" viewBox="0 0 12 12" className={`text-faint transition-transform ${open === team.id ? 'rotate-90' : ''}`}>
                    <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span className="text-[13.5px] font-semibold text-paper truncate">{team.name}</span>
                  <span className="text-[11px] font-mono text-faint">{t('settings.teams.member_count', { count: team.member_count ?? 0 })}{team.my_role ? ` · ${t('settings.teams.you_role', { role: team.my_role === 'lead' ? t('settings.role.lead') : t('settings.role.member') })}` : ''}</span>
                </button>
                {admin && (
                  <button onClick={() => del(team)} title={t('settings.teams.delete_title')} className="text-faint hover:text-crose transition shrink-0">
                    <svg width="15" height="15" viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
                  </button>
                )}
              </div>
              {open === team.id && <TeamDetail team={team} admin={admin} onChanged={load} />}
            </div>
          ))}
        </div>
      )}
    </SectionShell>
  )
}

// ---------------- Members (Admin) ----------------
function MembersSection() {
  const t = useT()
  const roleName = useRoleLabel()
  const [members, setMembers] = useState<Member[]>([])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('member')
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api
      .members()
      .then(setMembers)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(load, [load])

  async function invite() {
    if (!email.trim() || busy) return
    setBusy(true)
    setErr(null)
    try {
      await api.inviteMember(email.trim(), role)
      setEmail('')
      load()
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }
  async function remove(id: string) {
    try {
      await api.removeMember(id)
      setMembers((m) => m.filter((x) => x.id !== id))
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <SectionShell title={t('settings.members.title')} desc={t('settings.members.desc')}>
      <div className="flex flex-wrap items-end gap-2 mb-4 max-w-2xl">
        <div className="flex-1 min-w-[200px]">
          <Field label={t('settings.members.invite_label')}>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && invite()}
              placeholder={t('settings.members.invite_ph')}
              className={inputCls}
            />
          </Field>
        </div>
        <select value={role} onChange={(e) => setRole(e.target.value)} className={`${inputCls} w-auto`}>
          {ASSIGNABLE_MEMBER_ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {roleName(r.value)}
            </option>
          ))}
        </select>
        <button onClick={invite} disabled={busy || !email.trim()} className={btnPrimary}>
          {t('settings.members.invite')}
        </button>
      </div>

      {err && <p className="text-[12px] text-crose/90 mb-2">{err}</p>}
      {loading ? (
        <p className="text-[12.5px] text-muted">{t('settings.members.loading')}</p>
      ) : members.length === 0 ? (
        <p className="text-[12.5px] text-faint">{t('settings.members.empty')}</p>
      ) : (
        <div className="flex flex-col gap-1.5 max-w-2xl">
          {members.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-xl bg-surface2 border border-line"
            >
              <div className="min-w-0">
                <div className="text-[13px] text-paper truncate">{m.name || m.email}</div>
                {m.name && <div className="text-[11px] text-faint truncate">{m.email}</div>}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-surface3 text-muted border border-line">
                  {roleName(m.role)}
                </span>
                <button
                  onClick={() => remove(m.id)}
                  title={t('settings.members.remove')}
                  className="text-faint hover:text-crose transition"
                >
                  <svg width="15" height="15" viewBox="0 0 14 14">
                    <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionShell>
  )
}

// ---------------- Ingest sources + scraping allowlist (Admin) ----------------
function SourcesSection() {
  const t = useT()
  const [allowlist, setAllowlist] = useState<string[]>([])
  const [domain, setDomain] = useState('')
  const [loading, setLoading] = useState(true)
  const [dirty, setDirty] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api
      .getAllowlist()
      .then(setAllowlist)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  function add() {
    const d = domain.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '')
    if (!d || allowlist.includes(d)) return
    setAllowlist((a) => [...a, d])
    setDomain('')
    setDirty(true)
    setSaved(false)
  }
  function del(d: string) {
    setAllowlist((a) => a.filter((x) => x !== d))
    setDirty(true)
    setSaved(false)
  }
  async function save() {
    setErr(null)
    try {
      await api.setAllowlist(allowlist)
      setDirty(false)
      setSaved(true)
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <SectionShell
      title={t('settings.sources.title')}
      desc={t('settings.sources.desc')}
    >
      <div className="flex items-end gap-2 mb-4 max-w-xl">
        <div className="flex-1">
          <Field label={t('settings.sources.domain_label')}>
            <input
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && add()}
              placeholder={t('settings.sources.domain_ph')}
              className={inputCls}
            />
          </Field>
        </div>
        <button onClick={add} disabled={!domain.trim()} className={btnPrimary}>
          {t('settings.sources.add')}
        </button>
      </div>

      {err && <p className="text-[12px] text-crose/90 mb-2">{err}</p>}
      {loading ? (
        <p className="text-[12.5px] text-muted">{t('settings.sources.loading')}</p>
      ) : allowlist.length === 0 ? (
        <p className="text-[12.5px] text-faint mb-4">{t('settings.sources.empty')}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5 mb-4 max-w-xl">
          {allowlist.map((d) => (
            <span
              key={d}
              className="inline-flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-full bg-surface2 border border-line text-[12px] text-paper/90"
            >
              {d}
              <button onClick={() => del(d)} className="text-faint hover:text-crose">
                <svg width="12" height="12" viewBox="0 0 14 14">
                  <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={!dirty} className={btnPrimary}>
          {t('settings.sources.save')}
        </button>
        {saved && <span className="text-[12px] text-cmint">{t('settings.sources.saved')}</span>}
      </div>
    </SectionShell>
  )
}

// ---------------- Tenants (Super-Admin) ----------------
function TenantsSection() {
  const t = useT()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [adminEmail, setAdminEmail] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api
      .tenants()
      .then(setTenants)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(load, [load])

  async function create() {
    if (!name.trim() || busy) return
    setBusy(true)
    setErr(null)
    try {
      await api.createTenant(name.trim())
      setName('')
      load()
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }
  async function del(id: string) {
    if (!confirm(t('settings.tenants.delete_confirm'))) return
    try {
      await api.deleteTenant(id)
      setTenants((ts) => ts.filter((x) => x.id !== id))
    } catch (e: any) {
      setErr(e.message)
    }
  }
  async function assign(id: string) {
    const email = (adminEmail[id] || '').trim()
    if (!email) return
    setNote(null)
    try {
      await api.assignAdmin(id, email)
      setAdminEmail((m) => ({ ...m, [id]: '' }))
      setNote(t('settings.tenants.assigned', { email }))
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <SectionShell title={t('settings.tenants.title')} desc={t('settings.tenants.desc')}>
      <div className="flex items-end gap-2 mb-4 max-w-xl">
        <div className="flex-1">
          <Field label={t('settings.tenants.new_label')}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && create()}
              placeholder={t('settings.tenants.new_ph')}
              className={inputCls}
            />
          </Field>
        </div>
        <button onClick={create} disabled={busy || !name.trim()} className={btnPrimary}>
          {t('settings.tenants.create')}
        </button>
      </div>

      {err && <p className="text-[12px] text-crose/90 mb-2">{err}</p>}
      {note && <p className="text-[12px] text-cmint mb-2">{note}</p>}
      {loading ? (
        <p className="text-[12.5px] text-muted">{t('settings.tenants.loading')}</p>
      ) : tenants.length === 0 ? (
        <p className="text-[12.5px] text-faint">{t('settings.tenants.empty')}</p>
      ) : (
        <div className="flex flex-col gap-2 max-w-2xl">
          {tenants.map((tenant) => (
            <div key={tenant.id} className="rounded-xl bg-surface2 border border-line p-3.5">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[13.5px] text-paper font-medium truncate">{tenant.name}</div>
                  <div className="text-[10.5px] font-mono text-faint truncate">{tenant.id}</div>
                </div>
                <button
                  onClick={() => del(tenant.id)}
                  title={t('settings.tenants.delete_title')}
                  className="text-faint hover:text-crose transition shrink-0"
                >
                  <svg width="15" height="15" viewBox="0 0 14 14">
                    <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
              <div className="flex items-end gap-2 mt-3">
                <input
                  value={adminEmail[tenant.id] || ''}
                  onChange={(e) => setAdminEmail((m) => ({ ...m, [tenant.id]: e.target.value }))}
                  onKeyDown={(e) => e.key === 'Enter' && assign(tenant.id)}
                  placeholder={t('settings.tenants.admin_ph')}
                  className={`${inputCls} py-2`}
                />
                <button onClick={() => assign(tenant.id)} className={btnGhost}>
                  {t('settings.tenants.assign_admin')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionShell>
  )
}

// ---------------- Promotions (Super-Admin) ----------------
function PromotionsSection() {
  const t = useT()
  const [items, setItems] = useState<Promotion[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api
      .promotions()
      .then(setItems)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(load, [load])

  async function act(id: string, approve: boolean) {
    try {
      await (approve ? api.approvePromotion(id) : api.rejectPromotion(id))
      setItems((xs) => xs.filter((x) => x.id !== id))
    } catch (e: any) {
      setErr(e.message)
    }
  }

  const open = items.filter((p) => (p.status ?? 'open') === 'open')

  return (
    <SectionShell
      title={t('settings.promotions.title')}
      desc={t('settings.promotions.desc')}
    >
      {err && <p className="text-[12px] text-crose/90 mb-2">{err}</p>}
      {loading ? (
        <p className="text-[12.5px] text-muted">{t('settings.promotions.loading')}</p>
      ) : open.length === 0 ? (
        <p className="text-[12.5px] text-faint">{t('settings.promotions.empty')}</p>
      ) : (
        <div className="flex flex-col gap-2 max-w-2xl">
          {open.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between gap-3 px-3.5 py-3 rounded-xl bg-surface2 border border-line"
            >
              <div className="min-w-0">
                <div className="text-[13px] text-paper truncate">{p.label || p.source_id}</div>
                <div className="text-[11px] text-faint truncate">
                  {[p.tenant || p.tenant_id, p.reason].filter(Boolean).join(' · ') || p.source_id}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => act(p.id, true)}
                  className="px-3 py-1.5 rounded-lg bg-cmint/15 border border-cmint/40 text-cmint text-[12px] font-medium hover:bg-cmint/25 transition"
                >
                  {t('settings.promotions.approve')}
                </button>
                <button
                  onClick={() => act(p.id, false)}
                  className="px-3 py-1.5 rounded-lg border border-line text-muted text-[12px] hover:text-crose hover:border-crose/40 transition"
                >
                  {t('settings.promotions.reject')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionShell>
  )
}

// ---------------- Modell & API ----------------
function ModelSection({
  provider,
  model,
  claudeReady,
  onProviderDefault,
  sandbox = false,
}: {
  provider: Provider
  model?: string
  claudeReady: boolean
  onProviderDefault: (p: Provider) => void
  sandbox?: boolean
}) {
  const t = useT()
  const mdl = model || 'qwen2.5:7b'

  function ProviderCard({
    id, dot, name, sub, active, selectable, badge,
  }: {
    id: Provider; dot: string; name: string; sub: string
    active: boolean; selectable: boolean; badge?: string
  }) {
    return (
      <button
        disabled={!selectable}
        onClick={() => selectable && onProviderDefault(id)}
        className={`w-full flex items-center gap-3 px-3.5 py-3 rounded-xl border text-left transition ${
          active
            ? 'border-primary/50 bg-primary/[0.06]'
            : selectable
              ? 'border-line bg-surface2 hover:border-line2'
              : 'border-line bg-surface2/40 opacity-70 cursor-not-allowed'
        }`}
      >
        <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${dot}`} />
        <span className="min-w-0 flex-1">
          <span className="block text-[13.5px] text-paper">{name}</span>
          <span className="block text-[11.5px] text-faint">{sub}</span>
        </span>
        {badge && (
          <span className="shrink-0 text-[9.5px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-surface3 border border-line text-faint">{badge}</span>
        )}
        {active && (
          <span className="shrink-0 text-[10px] font-mono uppercase tracking-wide px-2 py-0.5 rounded-full bg-primary/15 border border-primary/40 text-primary">{t('settings.model.badge_default')}</span>
        )}
      </button>
    )
  }

  return (
    <SectionShell
      title={t('settings.model.title')}
      desc={sandbox ? t('settings.model.desc_sandbox') : t('settings.model.desc')}
    >
      <div className="flex flex-col gap-2 max-w-xl">
        {!sandbox && (
          <ProviderCard
            id="ollama"
            dot="bg-cmint"
            name={t('settings.model.ollama_name', { model: mdl })}
            sub={t('settings.model.ollama_sub')}
            active={provider === 'ollama'}
            selectable
          />
        )}
        {!sandbox && (
          <ProviderCard
            id="claude"
            dot="bg-cviolet"
            name="Claude (Anthropic)"
            sub={claudeReady ? t('settings.model.claude_sub_ready') : t('settings.model.claude_sub_missing')}
            active={provider === 'claude'}
            selectable={claudeReady}
            badge={claudeReady ? undefined : t('settings.model.badge_soon')}
          />
        )}
        <ProviderCard
          id={'gemini' as Provider}
          dot={sandbox ? 'bg-cmint' : 'bg-line2'}
          name="Gemini (Google)"
          sub={sandbox ? t('settings.model.gemini_sub_sandbox') : t('settings.model.gemini_sub')}
          active={sandbox}
          selectable={false}
          badge={sandbox ? undefined : t('settings.model.badge_soon')}
        />
      </div>

      <div className="mt-6 max-w-xl">
        <div className="text-[10px] font-mono uppercase tracking-wider text-faint mb-2">{t('settings.model.api_config')}</div>
        <div className="rounded-xl border border-line bg-surface2/50 p-4 flex flex-col gap-3">
          {[
            { k: t('settings.model.anthropic_key'), ph: 'sk-ant-…' },
            { k: t('settings.model.gemini_key'), ph: 'AIza…' },
          ].map((f) => (
            <label key={f.k} className="flex flex-col gap-1">
              <span className="text-[11.5px] text-muted">{f.k}</span>
              <input
                disabled
                placeholder={f.ph}
                className="rounded-lg bg-surface2 border border-line px-3 py-2 text-[12.5px] text-paper placeholder:text-faint outline-none opacity-60 cursor-not-allowed font-mono"
              />
            </label>
          ))}
          <p className="text-[11.5px] text-faint leading-snug">
            {t('settings.model.note_before')}<b className="text-muted">{t('settings.model.note_bold')}</b>{t('settings.model.note_after')}
          </p>
        </div>
      </div>
    </SectionShell>
  )
}

// ---------------- Overlay shell ----------------
export default function SettingsOverlay({
  me,
  provider,
  model,
  claudeReady,
  geminiReady = false,
  onProviderDefault,
  onClose,
  initialSection = 'profile',
  sandbox = false,
}: {
  me: Me
  provider: Provider
  model?: string
  claudeReady: boolean
  geminiReady?: boolean
  onProviderDefault: (p: Provider) => void
  onClose: () => void
  initialSection?: SectionId
  sandbox?: boolean
}) {
  const t = useT()
  const roleName = useRoleLabel()
  const admin = isAdmin(me)
  const superAdmin = isSuperAdmin(me)

  const nav: { id: SectionId; label: string; show: boolean }[] = [
    { id: 'profile', label: t('settings.nav.profile'), show: true },
    { id: 'model', label: t('settings.nav.model'), show: true },
    { id: 'members', label: t('settings.nav.members'), show: admin },
    { id: 'teams', label: t('settings.nav.teams'), show: true },
    { id: 'connectors', label: t('settings.nav.connectors'), show: true },
    { id: 'tenants', label: t('settings.nav.tenants'), show: superAdmin },
    { id: 'promotions', label: t('settings.nav.promotions'), show: superAdmin },
  ]
  const visible = nav.filter((n) => n.show)
  const [section, setSection] = useState<SectionId>(initialSection)
  useEffect(() => { setSection(initialSection) }, [initialSection])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 bg-ink/80 backdrop-blur-sm p-0 md:p-8 flex items-center justify-center animate-fade-in">
      <div className="w-full max-w-none md:max-w-4xl h-full md:h-[80vh] rounded-none md:rounded-2xl bg-surface border border-line shadow-2xl shadow-black/60 flex flex-col overflow-hidden animate-overlay-in">
        <div className="flex items-center justify-between px-4 py-3 border-b border-line shrink-0">
          <div className="flex items-center gap-2">
            <svg width="17" height="17" viewBox="0 0 18 18" className="text-primary">
              <path
                d="M9 6.5A2.5 2.5 0 109 11.5 2.5 2.5 0 009 6.5z"
                stroke="currentColor"
                strokeWidth="1.3"
                fill="none"
              />
              <path
                d="M9 1.5l1 2 2.2-.6.6 2.2 2 .9-1 2 1 2-2 .9-.6 2.2-2.2-.6-1 2-1-2-2.2.6-.6-2.2-2-.9 1-2-1-2 2-.9.6-2.2 2.2.6 1-2z"
                stroke="currentColor"
                strokeWidth="1"
                fill="none"
                opacity="0.4"
              />
            </svg>
            <h2 className="font-display font-bold text-[15px] text-paper">{t('common.settings')}</h2>
            <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-surface3 text-muted border border-line ml-1">
              {roleName(me.role)}
            </span>
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

        {/* Mobile (< md): horizontal scrollbare Tab-Leiste oben, Inhalt darunter.
            Desktop (md+): unveränderte vertikale Seiten-Navigation links. */}
        <div className="flex-1 flex flex-col md:flex-row min-h-0">
          <nav className="flex md:flex-col md:w-48 shrink-0 border-b md:border-b-0 md:border-r border-line p-2 gap-0.5 overflow-x-auto md:overflow-y-auto">
            {visible.map((n) => (
              <button
                key={n.id}
                onClick={() => setSection(n.id)}
                className={`shrink-0 whitespace-nowrap text-left px-3 py-2 rounded-lg text-[13px] transition ${
                  section === n.id ? 'bg-surface3 text-paper' : 'text-muted hover:bg-surface2 hover:text-paper'
                }`}
              >
                {n.label}
              </button>
            ))}
          </nav>

          <div className="flex-1 overflow-y-auto p-5">
            {section === 'profile' && (
              <ProfileSection
                me={me}
                provider={provider}
                claudeReady={claudeReady}
                geminiReady={geminiReady}
                onProviderDefault={onProviderDefault}
              />
            )}
            {section === 'model' && (
              <ModelSection
                provider={provider}
                model={model}
                claudeReady={claudeReady}
                onProviderDefault={onProviderDefault}
                sandbox={sandbox}
              />
            )}
            {section === 'members' && admin && <MembersSection />}
            {section === 'teams' && <TeamsSection admin={admin} />}
            {section === 'connectors' && (
              <SectionShell
                title={t('settings.connectors.title')}
                desc={admin ? t('settings.connectors.desc_admin') : t('settings.connectors.desc')}
              >
                <ConnectorLibrary tenantId={me.tenant?.id} filter="all" readOnly={!admin} sandbox={sandbox} />
              </SectionShell>
            )}
            {section === 'tenants' && superAdmin && <TenantsSection />}
            {section === 'promotions' && superAdmin && <PromotionsSection />}
          </div>
        </div>
      </div>
    </div>
  )
}
