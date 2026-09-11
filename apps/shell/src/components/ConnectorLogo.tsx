// Echte Anbieter-Logos für die Connector-/Marketplace-Karten.
// Markenlogos werden nur zur Wiedererkennung der Integration verwendet.
// Für Connectoren ohne gepflegtes Logo fällt die Komponente auf das Katalog-Emoji zurück.
import type { ReactNode } from 'react'
import { connectorLogo } from '../connectorLogos'

const S = 20 // Render-Größe in px

const gmail = (
  <svg width={S} height={S} viewBox="0 0 52 40" aria-hidden>
    <path fill="#4285f4" d="M3.6 40h8.9V18.2L0 8.9v27.5C0 38.4 1.6 40 3.6 40z" />
    <path fill="#34a853" d="M39.5 40h8.9c2 0 3.6-1.6 3.6-3.6V8.9L39.5 18.2z" />
    <path fill="#fbbc04" d="M39.5 3.6v14.6L52 8.9V5.5c0-3.4-3.9-5.3-6.6-3.3z" />
    <path fill="#ea4335" d="M12.5 18.2V3.6L26 13.7 39.5 3.6v14.6L26 28.3z" />
    <path fill="#c5221f" d="M0 5.5v3.4l12.5 9.3V3.6L6.6 2.2C3.9.2 0 2.1 0 5.5z" />
  </svg>
)

const googleDrive = (
  <svg width={S} height={S} viewBox="0 0 87.3 78" aria-hidden>
    <path fill="#0066da" d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8H0c0 1.55.4 3.1 1.2 4.5z" />
    <path fill="#00ac47" d="M43.65 25 29.9 1.2c-1.35.8-2.5 1.9-3.3 3.3L1.2 48.5c-.8 1.4-1.2 2.95-1.2 4.5h27.5z" />
    <path fill="#ea4335" d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.35c.8-1.4 1.2-2.95 1.2-4.5H59.8l5.85 11.5z" />
    <path fill="#00832d" d="M43.65 25 57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" />
    <path fill="#2684fc" d="M59.8 53H27.5L13.75 76.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" />
    <path fill="#ffba00" d="M73.4 26.5 60.7 4.5c-.8-1.4-1.95-2.5-3.3-3.3L43.65 25 59.8 53h27.45c0-1.55-.4-3.1-1.2-4.5z" />
  </svg>
)

const googleCalendar = (
  <svg width={S} height={S} viewBox="0 0 40 40" aria-hidden>
    <rect x="8" y="8" width="24" height="24" rx="3" fill="#fff" />
    <path d="M8 11a3 3 0 013-3h18a3 3 0 013 3v3H8z" fill="#4285F4" />
    <path d="M8 26h24v3a3 3 0 01-3 3H11a3 3 0 01-3-3z" fill="#188038" opacity=".15" />
    <path d="M8 14h4v12H8z" fill="#1967D2" opacity=".15" />
    <text x="20" y="27" fontSize="12" fontWeight="700" textAnchor="middle" fill="#4285F4" fontFamily="Arial, sans-serif">31</text>
  </svg>
)

const outlook = (
  <svg width={S} height={S} viewBox="0 0 40 40" aria-hidden>
    <rect x="15" y="10" width="21" height="20" rx="2" fill="#fff" stroke="#0F6CBD" strokeWidth="1.4" />
    <path d="M16 12l10 7 10-7" fill="none" stroke="#0F6CBD" strokeWidth="1.6" strokeLinejoin="round" />
    <ellipse cx="12.5" cy="20" rx="9.5" ry="10.5" fill="#0F6CBD" />
    <ellipse cx="12.5" cy="20" rx="4.3" ry="5.4" fill="#fff" />
  </svg>
)

const oneDrive = (
  <svg width={S} height={S} viewBox="0 0 48 30" aria-hidden>
    <path fill="#0364B8" d="M27 12a9 9 0 00-16.5 3.2A7 7 0 0011 29h6l4-9z" />
    <path fill="#0078D4" d="M27 12l-6 8 4 9h15a6.5 6.5 0 001-12.9A8.5 8.5 0 0027 12z" />
    <path fill="#1490DF" d="M11 29h14l-4-9-10 .5z" opacity=".85" />
  </svg>
)

const notion = (
  <svg width={S} height={S} viewBox="0 0 40 40" aria-hidden>
    <rect x="4" y="4" width="32" height="32" rx="5" fill="#fff" stroke="#111" strokeWidth="1.4" />
    <path fill="#111" d="M13.5 13.2l7.6 10.1V15l-2.2-.3v-1.3l5.4.2v1.2l-1.6.3v13.1l-1.4.05-7.9-10.4v9.3l2.3.3v1.2l-5.7-.15v-1.2l1.6-.3V14.9l-1.6-.3v-1.2z" />
  </svg>
)

const confluence = (
  <svg width={S} height={S} viewBox="0 0 40 40" aria-hidden>
    <path fill="#2684FF" d="M6 28.5c7.5-6 19-6.5 27 1.5l-4.3 6.2C22 30.6 14.5 31.2 9 34.8z" />
    <path fill="#0052CC" d="M34 11.5c-7.5 6-19 6.5-27-1.5l4.3-6.2C18 9.4 25.5 8.8 31 5.2z" />
  </svg>
)

const slack = (
  <svg width={S} height={S} viewBox="0 0 122.8 122.8" aria-hidden>
    <path fill="#E01E5A" d="M25.8 77.6a12.9 12.9 0 11-12.9-12.9h12.9zM32.3 77.6a12.9 12.9 0 0125.8 0v32.3a12.9 12.9 0 11-25.8 0z" />
    <path fill="#36C5F0" d="M45.2 25.8a12.9 12.9 0 1112.9-12.9v12.9zM45.2 32.3a12.9 12.9 0 010 25.8H12.9a12.9 12.9 0 110-25.8z" />
    <path fill="#2EB67D" d="M97 45.2a12.9 12.9 0 1112.9 12.9H97zM90.5 45.2a12.9 12.9 0 01-25.8 0V12.9a12.9 12.9 0 1125.8 0z" />
    <path fill="#ECB22E" d="M77.6 97a12.9 12.9 0 11-12.9 12.9V97zM77.6 90.5a12.9 12.9 0 010-25.8h32.3a12.9 12.9 0 110 25.8z" />
  </svg>
)

const hubspot = (
  <svg width={S} height={S} viewBox="0 0 40 40" aria-hidden>
    <circle cx="16.5" cy="25.5" r="8.5" fill="none" stroke="#FF7A59" strokeWidth="3.4" />
    <path d="M16.5 17v-4.2" stroke="#FF7A59" strokeWidth="3" strokeLinecap="round" />
    <circle cx="28.5" cy="11" r="4.6" fill="none" stroke="#FF7A59" strokeWidth="3" />
    <circle cx="28.5" cy="11" r="1.6" fill="#FF7A59" />
  </svg>
)

const pipedrive = (
  <svg width={S} height={S} viewBox="0 0 40 40" aria-hidden>
    <rect width="40" height="40" rx="9" fill="#017737" />
    <path fill="#fff" d="M22.4 11.2c-2.3 0-3.9 1-4.8 2.2l-.2-1.9h-5v25h5.4v-9.1c.9 1 2.4 1.8 4.5 1.8 4.3 0 7.4-3.4 7.4-9 0-5.5-3.1-9-7.3-9zm-1.5 13.4c-2.2 0-3.6-1.8-3.6-4.4 0-2.6 1.4-4.4 3.6-4.4 2.2 0 3.5 1.7 3.5 4.4 0 2.7-1.3 4.4-3.5 4.4z" />
  </svg>
)

const zoho = (
  <svg width={S} height={S} viewBox="0 0 40 40" aria-hidden>
    <rect x="4" y="13" width="7" height="14" rx="1.5" fill="#E42527" />
    <rect x="13" y="13" width="7" height="14" rx="1.5" fill="#F9B21D" />
    <rect x="22" y="13" width="7" height="14" rx="1.5" fill="#089949" />
    <rect x="31" y="13" width="5" height="14" rx="1.5" fill="#226DB4" />
  </svg>
)

const awsS3 = (
  <svg width={S} height={S} viewBox="0 0 40 40" aria-hidden>
    <path fill="#E25444" d="M8 11l12-4 12 4-2 18-10 4-10-4z" />
    <path fill="#7B1D13" d="M20 7v30l10-4 2-18z" opacity=".55" />
    <path fill="#fff" d="M20 15c-4 0-7 .9-7 2.1v5.8c0 1.2 3 2.1 7 2.1s7-.9 7-2.1v-5.8c0-1.2-3-2.1-7-2.1zm0 1.3c3.3 0 5.4.7 5.4.8s-2.1.8-5.4.8-5.4-.7-5.4-.8 2.1-.8 5.4-.8z" opacity=".95" />
  </svg>
)

const webhook = (
  <svg width={S} height={S} viewBox="0 0 24 24" aria-hidden className="text-primary">
    <path d="M8.5 9.5a4 4 0 116 3.4l2 3.6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    <path d="M15 16h-6a3.5 3.5 0 11.9-6.9" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    <circle cx="12" cy="9.5" r="1.8" fill="currentColor" />
    <circle cx="7.5" cy="16" r="1.8" fill="currentColor" />
    <circle cx="16.5" cy="16" r="1.8" fill="currentColor" />
  </svg>
)

const globe = (
  <svg width={S} height={S} viewBox="0 0 24 24" aria-hidden className="text-cmint">
    <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
    <path d="M3.5 12h17M12 3.5c2.4 2.3 3.6 5.3 3.6 8.5S14.4 18.2 12 20.5c-2.4-2.3-3.6-5.3-3.6-8.5S9.6 5.8 12 3.5z" fill="none" stroke="currentColor" strokeWidth="1.5" />
  </svg>
)

const mail = (
  <svg width={S} height={S} viewBox="0 0 24 24" aria-hidden className="text-muted">
    <rect x="3" y="5.5" width="18" height="13" rx="2.2" fill="none" stroke="currentColor" strokeWidth="1.5" />
    <path d="M4 7l8 6 8-6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
)

// id → Marken-/Themen-Logo
const LOGOS: Record<string, ReactNode> = {
  gmail,
  gmail_in: gmail,
  gmail_send: gmail,
  google_drive: googleDrive,
  gcal: googleCalendar,
  outlook: outlook,
  outlook_send: outlook,
  sharepoint: oneDrive,
  notion,
  notion_export: notion,
  confluence,
  slack_import: slack,
  slack_post: slack,
  hubspot,
  pipedrive,
  zoho,
  s3: awsS3,
  webhook,
  url_scrape: globe,
  email_imap: mail,
}

export default function ConnectorLogo({
  id,
  fallback,
  className = '',
}: {
  id: string
  fallback?: string
  className?: string
}) {
  const logo = LOGOS[id]
  if (logo) return <span className={`inline-flex ${className}`}>{logo}</span>

  // Echte Marken-Logos (simple-icons) bzw. Marken-Monogramm-Fallback
  const brand = connectorLogo(id)
  if (brand?.path) {
    return (
      <span className={`inline-flex ${className}`}>
        <svg width={S} height={S} viewBox="0 0 24 24" role="img" aria-label={brand.title}>
          <path d={brand.path} fill={brand.hex} />
        </svg>
      </span>
    )
  }
  if (brand) {
    return (
      <span className={`inline-flex ${className}`} aria-label={brand.title}>
        <svg width={S} height={S} viewBox="0 0 24 24" role="img" aria-label={brand.title}>
          <rect width="24" height="24" rx="5" fill={brand.hex} />
          <text
            x="12"
            y="12"
            dominantBaseline="central"
            textAnchor="middle"
            fontFamily="Inter, Arial, sans-serif"
            fontWeight="700"
            fontSize={brand.mono && brand.mono.length > 1 ? 8.5 : 12}
            fill="#ffffff"
          >
            {brand.mono ?? brand.title.slice(0, 1).toUpperCase()}
          </text>
        </svg>
      </span>
    )
  }

  return <span className={className}>{fallback ?? '🔌'}</span>
}
