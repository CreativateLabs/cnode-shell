// Zentraler, tenant-konfigurierbarer Brand-Store. App setzt ihn aus /tenant/context;
// Komponenten lesen ihn beim Render (App-State-Change triggert Re-Render → aktualisiert).
type Brand = {
  wordmark: string
  assistantName: string
  assistantRole: string
  initial: string
  logoSvg: string   // echtes Marken-Logo (rohes SVG); leer → Initial-Icon-Fallback
}

let _brand: Brand = { wordmark: 'c:node', assistantName: 'c:node', assistantRole: '', initial: 'c', logoSvg: '' }

export function setBrand(b: Partial<Brand>) {
  _brand = { ..._brand, ...b }
  if (!b.initial && (b.wordmark || b.assistantName)) {
    _brand.initial = (_brand.wordmark || _brand.assistantName || 'K').trim().charAt(0).toUpperCase() || 'K'
  }
}

export function brand(): Brand {
  return _brand
}
