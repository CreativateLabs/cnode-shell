import type { NBA } from '../types'
import { useT } from '../i18n'

// "Next Best Actions" — proaktive Vorschlagskarten (gelbe Akzent-Karten, "weil …"-Begründung, CTA).
// Datenquelle: BFF GET /nba, sonst client-seitige Heuristik (siehe App.buildFallbackNba).
export default function NBACards({
  items,
  onRun,
  variant = 'grid',
}: {
  items: NBA[]
  onRun: (nba: NBA) => void
  variant?: 'grid' | 'strip'
}) {
  const t = useT()
  if (!items.length) return null

  if (variant === 'strip') {
    return (
      <div className="flex items-center gap-2 overflow-x-auto pb-1 -mx-1 px-1">
        <span className="text-[10px] font-mono uppercase tracking-wider text-faint shrink-0 pr-1">
          {t('nba.suggestions')}
        </span>
        {items.map((n) => (
          <button
            key={n.id}
            onClick={() => onRun(n)}
            title={n.reason}
            className="shrink-0 inline-flex items-center gap-1.5 pl-2.5 pr-3 py-1.5 rounded-full bg-primary/10 border border-primary/30 text-[11.5px] text-paper hover:bg-primary/20 hover:border-primary/50 transition"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
            <span className="truncate max-w-[220px]">{n.title}</span>
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="w-full max-w-xl">
      <div className="flex items-center gap-2 mb-2">
        <svg width="14" height="14" viewBox="0 0 16 16" className="text-primary">
          <path
            d="M8 1.5l1.6 3.7 4 .35-3 2.65.9 3.9L8 10.1l-3.5 2 .9-3.9-3-2.65 4-.35L8 1.5z"
            fill="currentColor"
          />
        </svg>
        <span className="text-[11px] font-mono uppercase tracking-wider text-faint">
          {t('nba.title')}
        </span>
      </div>
      <div className="grid sm:grid-cols-2 gap-2">
        {items.map((n) => (
          <button
            key={n.id}
            onClick={() => onRun(n)}
            className="group text-left rounded-xl bg-primary/[0.06] border border-primary/25 p-3.5 hover:border-primary/60 hover:bg-primary/10 transition"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-[13px] font-semibold text-paper leading-snug">{n.title}</span>
              <svg
                width="14"
                height="14"
                viewBox="0 0 14 14"
                className="text-primary/60 group-hover:text-primary shrink-0 mt-0.5 transition"
              >
                <path
                  d="M3.5 7h7M7 3.5L10.5 7 7 10.5"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <p className="text-[11.5px] text-muted mt-1.5 leading-snug">
              <span className="text-primary/80 font-medium">{t('nba.because')}</span>
              {n.reason}
            </p>
            {n.cta && (
              <span className="inline-block mt-2 text-[11px] font-medium text-primary">
                {n.cta} →
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}
