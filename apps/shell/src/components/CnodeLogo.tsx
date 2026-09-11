import { brand } from '../brand'

const _isCnode = () => (brand().wordmark || '').toLowerCase().replace(/\s/g, '') === 'c:node'

// Echtes c:node-Bracket-Mark (identisch zur Landingpage): violetter Verlauf, weiße Node-Bracket.
export function CnodeMark({ size = 26, className = '' }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden className={className}>
      <defs>
        <linearGradient id="cnodeMark" x1="0" y1="0" x2="512" y2="512" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#7C3AED" />
          <stop offset="1" stopColor="#6366F1" />
        </linearGradient>
      </defs>
      <rect x="0" y="0" width="512" height="512" rx="114" fill="url(#cnodeMark)" />
      <g transform="translate(116 116) scale(0.6452)">
        <path fill="#FFFFFF" d="M433.467 86.4621V166.526C433.467 174.357 427.123 180.706 419.292 180.706H357.331C349.506 180.706 343.157 174.357 343.157 166.526V104.533C343.157 96.7021 336.813 90.353 328.983 90.353H104.473C96.6479 90.353 90.2988 96.7021 90.2988 104.533V329.173C90.2988 337.003 96.6425 343.352 104.473 343.352H328.983C336.808 343.352 343.157 337.003 343.157 329.173V267.179C343.157 259.348 349.501 252.999 357.331 252.999H419.292C427.117 252.999 433.467 259.348 433.467 267.179V277.224C433.467 284.853 430.438 292.169 425.044 297.563L297.449 425.234C292.027 430.661 284.669 433.711 277.001 433.711H86.4187C78.5936 433.711 72.2444 427.362 72.2444 419.531V375.608C72.2444 367.777 65.9007 361.428 58.0701 361.428H14.1743C6.34913 361.428 0 355.079 0 347.249V156.286C0 148.787 2.97921 141.591 8.28101 136.284L136.029 8.46006C141.445 3.04431 148.787 0 156.449 0H347.048C354.873 0 361.222 6.34913 361.222 14.1797V58.1027C361.222 65.9333 367.566 72.2824 375.396 72.2824H419.292C427.117 72.2824 433.467 78.6315 433.467 86.4621Z" />
      </g>
    </svg>
  )
}

// Tenant-Marke: für c:node das echte Bracket-Mark, sonst Initial + Primär-/Sekundärfarbe.
export function CnodeIcon({ size = 26, className = '' }: { size?: number; className?: string }) {
  if (_isCnode()) return <CnodeMark size={size} className={className} />
  const initial = brand().initial
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden className={className}>
      <rect x="1" y="1" width="30" height="30" rx="8" fill="#FFFFFF" stroke="rgb(var(--c-primary))" strokeWidth="1.6" />
      <text x="15" y="22" textAnchor="middle" fontSize="17" fontWeight="800"
        fontFamily='"Bricolage Grotesque", system-ui, sans-serif' fill="rgb(var(--c-primary))">{initial}</text>
      <circle cx="24.5" cy="8.5" r="2.1" fill="rgb(var(--c-secondary))" />
    </svg>
  )
}

export default function CnodeLogo({
  className = '',
  iconOnly = false,
  wordmark,
}: {
  className?: string
  iconOnly?: boolean
  wordmark?: string
}) {
  // Whitelabel: der Schriftzug kommt je Tenant aus tenant.yaml (brand.wordmark).
  // Ohne expliziten Prop (z.B. auf der Login-Seite) fällt er auf den Brand-Store zurück,
  // damit auch die Auth-Seite die richtige Tenant-Marke zeigt.
  const wm = wordmark || brand().wordmark || 'c:node'

  // Echtes Marken-Logo (rohes SVG aus tenant.yaml/brand): rendert Wort-/Bildmarke direkt,
  // ersetzt Initial-Icon + Text-Wortmarke. Fallback bleibt das konfigurierbare Initial-Icon.
  const svg = brand().logoSvg
  if (svg && !iconOnly)
    return (
      <div
        className={`flex items-center select-none ${className}`}
        title={wm}
        aria-label={wm}
      >
        <span
          className="inline-flex items-center [&>svg]:h-6 [&>svg]:w-auto [&>svg]:max-w-[150px]"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    )

  return (
    <div
      className={`flex items-center gap-2 select-none ${className}`}
      title={wm}
      aria-label={wm}
    >
      <CnodeIcon />
      {!iconOnly && (
        <div className="leading-none">
          <span className="font-display font-extrabold tracking-tight text-[16px] text-primary">
            {wm.toLowerCase().replace(/\s/g, '') === 'c:node' ? (
              // Mark = „c", Text daneben = „:node" → liest sich als c:node
              <span className="text-paper">:node</span>
            ) : (
              wm
            )}
          </span>
        </div>
      )}
    </div>
  )
}
