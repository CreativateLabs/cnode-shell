import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { EntitlementDTO } from '../types'
import { useT, type TFn } from '../i18n'

/**
 * Upsell-Surface der Sandbox (Monetarisierung).
 *
 * Zwei Modi:
 *  - `strip`  : schlanke Dauer-Leiste, wenn Free-Tier in der Public-Sandbox läuft
 *               (lädt zum Upgrade auf NENA-Intel / eigene Instanz / White-Label ein).
 *  - `modal`  : erscheint, wenn ein Cap gerissen wurde (HTTP 429) — mit denselben CTAs.
 *
 * Ziele kommen aus dem Entitlement (`upgrade.*`, Env-konfiguriert). Fehlt ein Stripe/IAP-Link,
 * fällt der Button auf den Sales-/Kontakt-Link (enterprise/whitelabel) bzw. mailto zurück.
 */

// 150000 → "150k", 1500000 → "1.5M" — kompakt für die schmale Sandbox-Leiste.
function compactNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}k`
  return String(n)
}

type Offer = {
  key: 'pro' | 'team' | 'whitelabel'
  title: string
  tagline: string
  bullets: string[]
  cta: string
}

// Composer-Muster: stabile Metadaten (key + Anzahl Bullets) auf Modulebene; die sichtbaren
// Strings (title/tagline/bullets/cta) kommen zur Laufzeit aus dem Katalog (upgrade.offer.<key>.*).
const OFFER_META: { key: Offer['key']; bullets: number }[] = [
  { key: 'pro', bullets: 3 },
  { key: 'team', bullets: 3 },
  { key: 'whitelabel', bullets: 3 },
]

// In der Sandbox gibt es KEINEN Self-Checkout — jeder Upgrade-Pfad führt zum Vertrieb.
// Ist ein Sales-/Meeting-Link konfiguriert (upgrade.enterprise/whitelabel), wird der genutzt;
// sonst eine vorbereitete Mail mit Tarif- + Workspace-Kontext (lokalisiert via t()).
function salesHref(o: Offer, ent: EntitlementDTO | null, t: TFn, tenantId?: string): string {
  const up = ent?.upgrade || {}
  const raw = up.enterprise || up.whitelabel
  if (raw && /^https?:\/\//.test(raw)) return raw
  const subject = t('upgrade.mail_subject', { title: o.title })
  const workspace = tenantId ? t('upgrade.mail_workspace', { tenant: tenantId }) : ''
  const body = t('upgrade.mail_body', { title: o.title, workspace })
  return `mailto:sales@c-node.ai?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}

export function UpgradeBanner({
  entitlement,
  capHit,
  onDismissCap,
  openSignal,
}: {
  entitlement: EntitlementDTO | null
  capHit: boolean
  onDismissCap: () => void
  // Von außen den Upgrade-Modal öffnen (z.B. Chat-CTA „Volle NENA-Tiefe freischalten"):
  // jede Erhöhung dieses Zählers triggert das Öffnen.
  openSignal?: number
}) {
  const t = useT()
  const offers: Offer[] = OFFER_META.map((m) => ({
    key: m.key,
    title: t(`upgrade.offer.${m.key}.title`),
    tagline: t(`upgrade.offer.${m.key}.tagline`),
    bullets: Array.from({ length: m.bullets }, (_, i) => t(`upgrade.offer.${m.key}.b${i}`)),
    cta: t(`upgrade.offer.${m.key}.cta`),
  }))
  const [openModal, setOpenModal] = useState(false)
  useEffect(() => {
    if (openSignal && openSignal > 0) setOpenModal(true)
  }, [openSignal])
  const ent = entitlement
  const isFreeSandbox = !!ent && ent.public_demo && ent.tier === 'free'
  const tenantId = ent?.tenant_id

  // Sandbox-Phase transparent machen: Modell + geltende Caps direkt in der Leiste zeigen.
  const caps = ent?.caps || {}
  const stripParts: string[] = [t('upgrade.strip.free_sandbox'), 'Gemini']
  if (caps.per_min != null) stripParts.push(`${caps.per_min}/min`)
  if (caps.per_day != null) stripParts.push(t('upgrade.strip.per_day', { n: caps.per_day }))
  if (caps.tokens_per_day != null) stripParts.push(t('upgrade.strip.tokens_per_day', { n: compactNum(caps.tokens_per_day) }))
  stripParts.push(t('upgrade.strip.own_layer_only'))
  const stripText = stripParts.join(' · ')

  // Nur rollen (Marquee), wenn der Text NICHT auf eine Zeile passt (z.B. mobil/schmal).
  // Auf Desktop mit genug Platz → statische Single-Line, keine Animation.
  const trackRef = useRef<HTMLDivElement>(null)
  const segRef = useRef<HTMLSpanElement>(null)
  const [rolling, setRolling] = useState(true)
  useLayoutEffect(() => {
    const measure = () => {
      const track = trackRef.current, seg = segRef.current
      if (track && seg) setRolling(seg.scrollWidth > track.clientWidth + 4)
    }
    measure()
    const track = trackRef.current
    if (!track) return
    const ro = new ResizeObserver(measure)
    ro.observe(track)
    return () => ro.disconnect()
  }, [stripText])

  // In dedizierten (bezahlten) Deployments: keinerlei Upsell.
  if (!ent || (!isFreeSandbox && !capHit)) return null

  return (
    <>
      {isFreeSandbox && (
        <div style={s.strip}>
          <span style={s.stripDot} />
          <div className="cnode-marquee-track" ref={trackRef}>
            <div className={`cnode-marquee${rolling ? '' : ' is-static'}`}>
              <span ref={segRef} style={rolling ? s.stripSeg : undefined}>{stripText}</span>
              {rolling && (
                <span style={s.stripSeg} className="cnode-marquee-dup" aria-hidden>
                  {stripText}
                </span>
              )}
            </div>
          </div>
          <button style={s.stripBtn} onClick={() => setOpenModal(true)}>
            {t('upgrade.strip.cta')}
          </button>
        </div>
      )}

      {(openModal || capHit) && (
        <div
          className="fixed inset-0 z-[1000] bg-ink/70 backdrop-blur-sm flex items-stretch md:items-center justify-center p-0 md:p-6 animate-fade-in"
          onClick={() => { setOpenModal(false); onDismissCap() }}
        >
          <div
            className="w-full h-full md:w-[min(920px,96vw)] md:h-auto md:max-h-[90vh] bg-surface md:border md:border-line md:rounded-2xl shadow-2xl shadow-black/40 flex flex-col overflow-hidden animate-overlay-in"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 px-4 md:px-6 py-4 border-b border-line shrink-0">
              <div>
                <h2 className="font-display font-bold text-[17px] text-paper">
                  {capHit ? t('upgrade.modal.title_cap') : t('upgrade.modal.title_default')}
                </h2>
                <p className="text-[12.5px] text-muted mt-1 max-w-[560px]">
                  {capHit ? t('upgrade.modal.body_cap') : t('upgrade.modal.body_default')}
                </p>
              </div>
              <button
                onClick={() => { setOpenModal(false); onDismissCap() }}
                aria-label={t('common.close')}
                className="shrink-0 w-9 h-9 grid place-items-center rounded-lg text-muted hover:text-paper hover:bg-surface2 transition"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 md:p-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {offers.map((o) => (
                  <div key={o.key} className="flex flex-col gap-2 rounded-2xl border border-line bg-surface2/60 p-4">
                    <div className="font-display font-bold text-[15px] text-paper">{o.title}</div>
                    <div className="text-[12.5px] text-muted md:min-h-[34px]">{o.tagline}</div>
                    <ul className="flex flex-col gap-1.5 my-1">
                      {o.bullets.map((b) => (
                        <li key={b} className="flex gap-2 text-[12.5px] text-muted">
                          <span className="text-primary font-bold shrink-0">✓</span>{b}
                        </li>
                      ))}
                    </ul>
                    <a
                      href={salesHref(o, ent, t, tenantId)}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-auto min-h-[44px] flex items-center justify-center gap-1.5 rounded-full cta-grad text-[13.5px] font-semibold"
                    >
                      {t('upgrade.book_call')} →
                    </a>
                  </div>
                ))}
              </div>
              <p className="text-[11.5px] text-faint text-center mt-4">
                {t('upgrade.modal.footer')}
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// Nur die schlanke Dauer-Leiste ist noch inline gestylt; der Modal läuft komplett über Tailwind
// (full-screen auf Mobil, zentrierte Karte ab md).
const s: Record<string, React.CSSProperties> = {
  strip: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px',
    background: 'var(--surface-2, #f3f4f8)', borderBottom: '1px solid var(--border, #e4e6ee)',
    fontSize: 13, color: 'var(--text-2, #454a5a)',
  },
  stripDot: { width: 7, height: 7, borderRadius: 99, background: '#7C3AED', flex: '0 0 auto' },
  // Ein Marquee-Segment; margin-right hält den Abstand zwischen den beiden Kopien (nahtlose Schleife).
  stripSeg: { marginRight: 48 },
  stripBtn: {
    border: 'none', background: 'linear-gradient(to bottom right, #7C3AED, #6366F1)', color: '#fff',
    borderRadius: 9999, padding: '5px 13px', fontSize: 12, fontWeight: 600, cursor: 'pointer', flex: '0 0 auto',
    boxShadow: '0 8px 18px -8px rgba(124,58,237,.55)',
  },
}

export default UpgradeBanner
