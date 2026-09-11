// Role helpers — tolerant to backend naming variants (super_admin / superadmin / super-admin …).
import type { Me, Role } from './types'
import { useT } from './i18n'

function norm(role?: Role): string {
  return String(role ?? '').toLowerCase().replace(/[\s-]+/g, '_')
}

export function isSuperAdmin(me: Me | null): boolean {
  if (!me) return false
  const r = norm(me.role)
  return r === 'super_admin' || r === 'superadmin' || r === 'root' || r === 'owner'
}

export function isAdmin(me: Me | null): boolean {
  // Admin-or-above (Super-Admin can do everything an Admin can).
  if (!me) return false
  const r = norm(me.role)
  return isSuperAdmin(me) || r === 'admin' || r === 'tenant_admin'
}

export function isMember(me: Me | null): boolean {
  if (!me) return false
  const r = norm(me.role)
  return isAdmin(me) || r === 'member' || r === 'user'
}

export function isViewer(me: Me | null): boolean {
  return norm(me?.role) === 'viewer'
}

export const ROLE_LABEL: Record<string, string> = {
  super_admin: 'Super-Admin',
  admin: 'Admin',
  member: 'Member',
  viewer: 'Viewer',
}

export function roleLabel(role?: Role): string {
  return ROLE_LABEL[norm(role)] ?? String(role ?? '—')
}

/**
 * i18n-Hook für Rollen-Labels: `const roleName = useRoleLabel()` → `roleName(me.role)`.
 * Liefert das lokalisierte Label; fällt bei fehlendem Katalog-Key auf ROLE_LABEL/Rohwert
 * zurück (identisch zu roleLabel()). Werte/Identifier der Rolle bleiben unverändert.
 */
export function useRoleLabel(): (role?: Role) => string {
  const t = useT()
  return (role?: Role) => {
    const key = `roles.${norm(role)}`
    const v = t(key)
    if (v !== key) return v
    return roleLabel(role)
  }
}

// Assignable roles when inviting a member (Admin cannot mint Super-Admins).
export const ASSIGNABLE_MEMBER_ROLES: { value: Role; label: string }[] = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'viewer', label: 'Viewer' },
]
