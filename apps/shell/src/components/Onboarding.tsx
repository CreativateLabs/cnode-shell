import { useState } from 'react'
import type { OnboardingHint } from '../types'
import { useT } from '../i18n'

// In-Chat Onboarding-Karten für einen neuen/leeren Thread.
// Schritt 1: "Einfach beraten lassen" vs. "An konkretem Fall arbeiten".
// Schritt 2 (scoped + wenig Daten): "Daten bereitstellen" / "Connector vorschlagen".
export default function Onboarding({
  hint,
  lowData,
  escalationTarget,
  onGeneral,
  onScoped,
  onRequestData,
  onSuggestConnector,
}: {
  hint?: OnboardingHint | null
  lowData: boolean
  escalationTarget: string // z.B. "Admin" oder "Super-Admin"
  onGeneral: () => void
  onScoped: () => void
  onRequestData: () => Promise<boolean>
  onSuggestConnector: () => Promise<boolean>
}) {
  const t = useT()
  const [step, setStep] = useState<'choose' | 'scoped' | 'done'>('choose')
  const [requested, setRequested] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const gaps = hint?.data_gaps ?? hint?.gaps ?? []

  if (step === 'done') return null

  const Card = ({
    icon,
    title,
    desc,
    onClick,
    accent,
    disabled,
  }: {
    icon: React.ReactNode
    title: string
    desc: string
    onClick: () => void
    accent?: boolean
    disabled?: boolean
  }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex-1 text-left rounded-xl border p-3.5 transition disabled:opacity-50 disabled:cursor-not-allowed ${
        accent
          ? 'bg-primary/8 border-primary/40 hover:bg-primary/12'
          : 'bg-surface2 border-line hover:border-primary/40'
      }`}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className={`w-7 h-7 grid place-items-center rounded-lg ${accent ? 'bg-primary/15 text-primary' : 'bg-surface3 text-muted'}`}>
          {icon}
        </span>
        <span className="text-[13px] font-medium text-paper">{title}</span>
      </div>
      <p className="text-[11.5px] text-muted leading-snug">{desc}</p>
    </button>
  )

  return (
    <div className="w-full max-w-xl mx-auto mb-6 animate-fade-up">
      <div className="rounded-2xl border border-line bg-surface/60 p-3.5">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-6 h-6 rounded-lg bg-primary flex items-center justify-center text-ink font-display font-extrabold text-[12px]">K</span>
          <span className="text-[12.5px] text-paper font-medium">{t('onboarding.how_start')}</span>
        </div>

        {step === 'choose' && (
          <div className="flex flex-col sm:flex-row gap-2">
            <Card
              icon={
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                  <path d="M3 4a1 1 0 011-1h8a1 1 0 011 1v6a1 1 0 01-1 1H6l-3 2.5V4z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
                </svg>
              }
              title={t('onboarding.general_title')}
              desc={t('onboarding.general_desc')}
              onClick={() => {
                setStep('done')
                onGeneral()
              }}
            />
            <Card
              icon={
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                  <path d="M2.5 5.5h11M2.5 5.5l1-2h9l1 2M2.5 5.5V12a1 1 0 001 1h9a1 1 0 001-1V5.5" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
                </svg>
              }
              title={t('onboarding.case_title')}
              desc={t('onboarding.case_desc')}
              accent
              onClick={() => {
                onScoped()
                if (lowData) setStep('scoped')
                else setStep('done')
              }}
            />
          </div>
        )}

        {step === 'scoped' && (
          <div className="animate-fade-in">
            <p className="text-[11.5px] text-muted mb-2.5">
              {t('onboarding.low_data', {
                gaps: gaps.length > 0 ? ` (${gaps.slice(0, 3).join(', ')})` : '',
              })}
            </p>
            {requested ? (
              <div className="rounded-xl border border-cmint/30 bg-cmint/10 px-3.5 py-3 text-[12px] text-cmint">
                {requested}
              </div>
            ) : (
              <div className="flex flex-col sm:flex-row gap-2">
                <Card
                  icon={
                    <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                      <path d="M8 11V3M8 3L5 6M8 3l3 3M3 11v2a1 1 0 001 1h8a1 1 0 001-1v-2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  }
                  title={t('onboarding.provide_data_title')}
                  desc={t('onboarding.provide_data_desc', { target: escalationTarget })}
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true)
                    const ok = await onRequestData()
                    setBusy(false)
                    if (ok) setRequested(t('onboarding.data_requested', { target: escalationTarget }))
                    else setStep('done')
                  }}
                />
                <Card
                  icon={
                    <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                      <path d="M6.5 9.5l-2 2a2 2 0 002.8 2.8l2-2M9.5 6.5l2-2a2 2 0 00-2.8-2.8l-2 2M6 10l4-4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
                    </svg>
                  }
                  title={t('onboarding.suggest_connector_title')}
                  desc={t('onboarding.suggest_connector_desc', { target: escalationTarget })}
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true)
                    const ok = await onSuggestConnector()
                    setBusy(false)
                    if (ok) setRequested(t('onboarding.connector_requested', { target: escalationTarget }))
                    else setStep('done')
                  }}
                />
              </div>
            )}
            <button
              onClick={() => setStep('done')}
              className="mt-2.5 text-[11.5px] text-faint hover:text-muted transition"
            >
              {t('onboarding.later')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
