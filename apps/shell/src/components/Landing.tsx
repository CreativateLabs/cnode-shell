// c:node Landing-Page — öffentlicher Einstieg vor dem Login. Header-Nav mit EINER CTA
// „App starten". Brand hardcoded (c:node) — White-Label ist ein bezahltes Modell.
// Botschaft: belegbare KI auf einem wachsenden Gedächtnis, EU-souverän.
import { useT } from '../i18n'

function Bracket() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
      <rect x="1.5" y="1.5" width="29" height="29" rx="8" fill="none" stroke="currentColor" strokeWidth="1.6" opacity=".35" />
      <path d="M22 10.5a7.2 7.2 0 100 11" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="22.5" cy="16" r="2.4" className="fill-cmint" />
    </svg>
  )
}

function Card({ title, desc, icon }: { title: string; desc: string; icon: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-surface2/60 p-5">
      <span className="inline-grid h-9 w-9 place-items-center rounded-lg bg-primary/12 text-primary border border-primary/25">{icon}</span>
      <h3 className="mt-3 text-[15px] font-semibold text-paper tracking-[-0.01em]">{title}</h3>
      <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted">{desc}</p>
    </div>
  )
}

export default function Landing({ onStart }: { onStart: () => void }) {
  const t = useT()
  return (
    <div className="min-h-screen bg-ink text-paper flex flex-col">
      {/* Header — nur eine CTA */}
      <header className="flex items-center gap-3 px-6 sm:px-10 h-16 border-b border-line/60">
        <span className="flex items-center gap-2.5 text-primary">
          <Bracket />
          <span className="font-semibold text-[18px] tracking-[-0.02em] text-paper">c:node</span>
        </span>
        <span className="ml-1 rounded-full border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">{t('common.sandbox')}</span>
        <nav className="ml-auto">
          <button
            onClick={onStart}
            className="rounded-full bg-primary px-5 py-2.5 text-[14px] font-semibold text-white transition hover:opacity-90"
          >
            {t('landing.cta')}
          </button>
        </nav>
      </header>

      {/* Hero */}
      <main className="flex-1">
        <section className="mx-auto max-w-[64rem] px-6 sm:px-10 pt-20 pb-14 text-center">
          <p className="inline-flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.16em] text-cmint">
            <span className="h-1.5 w-1.5 rounded-full bg-cmint" /> {t('landing.eyebrow')}
          </p>
          <h1 className="mx-auto mt-5 max-w-[18ch] text-[clamp(2.3rem,5.5vw,3.7rem)] font-semibold leading-[1.03] tracking-[-0.03em] text-balance">
            {t('landing.h1_a')}<span className="text-primary">{t('landing.h1_mem')}</span>{t('landing.h1_b')}
          </h1>
          <p className="mx-auto mt-6 max-w-[56ch] text-[clamp(1.02rem,2vw,1.2rem)] leading-relaxed text-muted">
            {t('landing.hero_a')}<span className="text-paper/85">{t('landing.hero_mem')}</span>{t('landing.hero_b')}
          </p>
          <div className="mt-9 flex items-center justify-center gap-3">
            <button
              onClick={onStart}
              className="rounded-full bg-primary px-7 py-3 text-[15px] font-semibold text-white transition hover:opacity-90"
            >
              {t('landing.cta')}
            </button>
            <span className="font-mono text-[12px] text-faint">{t('landing.cta_note')}</span>
          </div>
        </section>

        {/* Value */}
        <section className="mx-auto max-w-[64rem] px-6 sm:px-10 pb-24">
          <div className="grid gap-4 sm:grid-cols-3">
            <Card
              title={t('landing.card1_title')}
              desc={t('landing.card1_desc')}
              icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l7 3v5c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6z" /><path d="M9 12l2 2 4-4" /></svg>}
            />
            <Card
              title={t('landing.card2_title')}
              desc={t('landing.card2_desc')}
              icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3h6l1 4H8zM8 7h8v13H8z" /><path d="M10.5 11h3M10.5 14h3" /></svg>}
            />
            <Card
              title={t('landing.card3_title')}
              desc={t('landing.card3_desc')}
              icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="6" cy="6" r="2.4" /><circle cx="18" cy="8" r="2.4" /><circle cx="10" cy="18" r="2.4" /><path d="M8 7l8 1M8.5 8l1.5 8" /></svg>}
            />
          </div>
        </section>
      </main>

      <footer className="border-t border-line/60 px-6 sm:px-10 py-6 text-[12px] text-faint">
        <span className="font-semibold text-paper">c:node</span>{t('landing.footer')}
      </footer>
    </div>
  )
}
