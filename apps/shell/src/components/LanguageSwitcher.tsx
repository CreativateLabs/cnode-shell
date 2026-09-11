import { LANGS, useLang } from '../i18n'

/**
 * Sprachwähler (DE/EN/FR). Zwei Darstellungen:
 *  - variant="segmented": kompakte Segment-Leiste (für Settings / Dropdown-Menüs).
 *  - variant="inline": Flaggen-Buttons in einer Reihe (für den Login-Screen o.ä.).
 * Die Auswahl wird im Context gehalten + in localStorage persistiert (siehe i18n/index).
 */
export default function LanguageSwitcher({ variant = 'segmented' }: { variant?: 'segmented' | 'inline' }) {
  const { lang, setLang } = useLang()

  if (variant === 'inline') {
    // Wird auf der HELLEN Login-Karte genutzt → eigene, kontraststarke Farben statt Dark-Tokens.
    return (
      <div className="flex items-center gap-1">
        {LANGS.map((l) => (
          <button
            key={l.code}
            onClick={() => setLang(l.code)}
            aria-pressed={lang === l.code}
            title={l.label}
            className={`px-2 py-1 rounded-full text-[12px] font-semibold transition ${
              lang === l.code
                ? 'bg-primary/15 text-primary'
                : 'text-gray-500 hover:text-gray-900 hover:bg-black/5'
            }`}
          >
            <span className="mr-1">{l.flag}</span>{l.code.toUpperCase()}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="inline-flex items-center gap-0.5 p-0.5 rounded-full bg-surface2 border border-line">
      {LANGS.map((l) => (
        <button
          key={l.code}
          onClick={() => setLang(l.code)}
          aria-pressed={lang === l.code}
          title={l.label}
          className={`px-2.5 py-1 rounded-full text-[12px] font-semibold transition ${
            lang === l.code ? 'bg-surface text-paper shadow-sm' : 'text-muted hover:text-paper'
          }`}
        >
          {l.code.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
