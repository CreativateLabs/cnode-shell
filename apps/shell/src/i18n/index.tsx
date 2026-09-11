import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

/**
 * Dependency-freie i18n für die c:node-Shell (DE/EN/FR).
 *
 * Warum eigenbau statt react-i18next: die Shell ist eine geschlossene App mit statischen
 * UI-Strings — ein winziger Context + `t(key)` reicht, spart eine npm-Abhängigkeit (die
 * Shared-node_modules bleiben unangetastet) und hält den Bundle schlank + CSP-neutral.
 *
 * Kataloge: je Komponenten-Namespace eine Fragment-Datei unter `catalog/<ns>.ts`
 * (`export default { de:{…}, en:{…}, fr:{…} }`). Sie werden hier via import.meta.glob
 * AUTOMATISCH eingesammelt und zu je einer flachen Map pro Sprache gemerged — eine neue
 * Komponente legt einfach ihr Fragment ab, ohne diese Datei anzufassen.
 *
 * Keys sind flach + gepunktet: `namespace.key`. Interpolation via `{{var}}`.
 * Startsprache: localStorage → navigator.language → 'de' (Fallback-Kette auch beim Lookup).
 */

export type Lang = 'de' | 'en' | 'fr'
export const LANGS: { code: Lang; label: string; flag: string }[] = [
  { code: 'de', label: 'Deutsch', flag: '🇩🇪' },
  { code: 'en', label: 'English', flag: '🇬🇧' },
  { code: 'fr', label: 'Français', flag: '🇫🇷' },
]
const LANG_CODES: Lang[] = ['de', 'en', 'fr']
const STORAGE_KEY = 'cnode.lang'

type Fragment = { de?: Record<string, string>; en?: Record<string, string>; fr?: Record<string, string> }

// Alle Katalog-Fragmente eager einsammeln + pro Sprache zu einer flachen Map mergen.
const FRAGMENTS = import.meta.glob<{ default: Fragment }>('./catalog/*.ts', { eager: true })
const CATALOG: Record<Lang, Record<string, string>> = { de: {}, en: {}, fr: {} }
for (const mod of Object.values(FRAGMENTS)) {
  const frag = mod.default || {}
  for (const lang of LANG_CODES) Object.assign(CATALOG[lang], frag[lang] || {})
}

function detectLang(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && LANG_CODES.includes(stored as Lang)) return stored as Lang
  } catch { /* private mode / disabled storage */ }
  try {
    const nav = (navigator.language || '').slice(0, 2).toLowerCase()
    if (LANG_CODES.includes(nav as Lang)) return nav as Lang
  } catch { /* no navigator */ }
  return 'de'
}

function interpolate(str: string, vars?: Record<string, string | number>): string {
  if (!vars) return str
  return str.replace(/\{\{(\w+)\}\}/g, (_, k) => (k in vars ? String(vars[k]) : `{{${k}}}`))
}

export type TFn = (key: string, vars?: Record<string, string | number>) => string

const I18nCtx = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: TFn }>({
  lang: 'de',
  setLang: () => {},
  t: (k) => k,
})

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang)

  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    try { localStorage.setItem(STORAGE_KEY, l) } catch { /* ignore */ }
    try { document.documentElement.lang = l } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    try { document.documentElement.lang = lang } catch { /* ignore */ }
  }, [lang])

  // Lookup mit Fallback-Kette: aktuelle Sprache → Deutsch → nackter Key (nie leer/Absturz).
  const t = useCallback<TFn>((key, vars) => {
    const hit = CATALOG[lang][key] ?? CATALOG.de[key] ?? key
    return interpolate(hit, vars)
  }, [lang])

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t])
  return <I18nCtx.Provider value={value}>{children}</I18nCtx.Provider>
}

/** Übersetzungs-Hook: `const t = useT()` → `t('composer.send')`. */
export function useT(): TFn {
  return useContext(I18nCtx).t
}

/** Aktuelle Sprache + Umschalter (für den Sprachwähler). */
export function useLang(): { lang: Lang; setLang: (l: Lang) => void } {
  const { lang, setLang } = useContext(I18nCtx)
  return { lang, setLang }
}
