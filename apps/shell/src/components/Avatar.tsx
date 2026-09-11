// Farbiger Kreis-Avatar mit Initiale — deterministische Farbe pro E-Mail.
// Wird im Thread-Header (Owner + Member) und in Notifications genutzt.
import { useT } from '../i18n'

const PALETTE = [
  '#FFD21E', // primary yellow
  '#36C399', // cmint
  '#A78BFA', // cviolet
  '#EC4899', // crose
  '#60A5FA', // blue
  '#F59E0B', // amber
  '#34D399', // emerald
  '#F472B6', // pink
]

function hashString(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

export function avatarColor(seed: string): string {
  return PALETTE[hashString(seed || '?') % PALETTE.length]
}

export function initialOf(email?: string): string {
  const s = (email || '?').trim()
  return (s[0] || '?').toUpperCase()
}

const SIZE_CLS: Record<string, string> = {
  xs: 'w-5 h-5 text-[9px]',
  sm: 'w-6 h-6 text-[11px]',
  md: 'w-8 h-8 text-[13px]',
  lg: 'w-10 h-10 text-[15px]',
}

// Dunkler Text auf hellem Kreis — die Palette ist bewusst hell/gesättigt.
export default function Avatar({
  email,
  size = 'sm',
  ring = false,
  title,
}: {
  email?: string
  size?: 'xs' | 'sm' | 'md' | 'lg'
  ring?: boolean
  title?: string
}) {
  const bg = avatarColor(email || '?')
  return (
    <span
      title={title ?? email}
      className={`inline-flex items-center justify-center rounded-full font-display font-extrabold text-ink shrink-0 select-none ${
        SIZE_CLS[size]
      } ${ring ? 'ring-2 ring-surface' : ''}`}
      style={{ background: bg }}
      aria-label={email}
    >
      {initialOf(email)}
    </span>
  )
}

// Überlappende Avatar-Gruppe (Owner zuerst).
export function AvatarStack({
  emails,
  owner,
  max = 5,
  size = 'sm',
}: {
  emails: string[]
  owner?: string
  max?: number
  size?: 'xs' | 'sm' | 'md' | 'lg'
}) {
  const t = useT()
  const uniq = Array.from(new Set([...(owner ? [owner] : []), ...emails].filter(Boolean)))
  const shown = uniq.slice(0, max)
  const extra = uniq.length - shown.length
  return (
    <div className="flex items-center -space-x-2">
      {shown.map((e) => (
        <Avatar key={e} email={e} size={size} ring title={e === owner ? t('avatar.owner', { email: e }) : e} />
      ))}
      {extra > 0 && (
        <span
          className={`inline-flex items-center justify-center rounded-full bg-surface3 border border-line text-muted font-medium ring-2 ring-surface ${
            SIZE_CLS[size]
          }`}
          title={t('avatar.more', { count: extra })}
        >
          +{extra}
        </span>
      )}
    </div>
  )
}
