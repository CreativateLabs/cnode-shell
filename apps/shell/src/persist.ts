// Lokale Persistenz kleiner UI-Zustände, die den Chat-Verlauf überdauern müssen:
//  - in die Bibliothek gespeicherte Artefakte (CTA darf nicht erneut erscheinen)
//  - bereits ausgeführte Aktionen (ActionCard darf nicht erneut „Bestätigen" anbieten)
// Rein clientseitig (localStorage), überlebt Reopen & Reload. Defensiv gegen
// blockierten/kaputten Storage (private Fenster, gelöschte Site-Daten).

const SAVED_KEY = 'cnode.savedArtifacts'
const ACTION_KEY = 'cnode.doneActions'

function readSet(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return new Set()
    const arr = JSON.parse(raw)
    return new Set(Array.isArray(arr) ? arr.filter((x) => typeof x === 'string') : [])
  } catch {
    return new Set()
  }
}

function writeSet(key: string, s: Set<string>) {
  try {
    localStorage.setItem(key, JSON.stringify([...s]))
  } catch {
    /* Storage nicht verfügbar — Zustand bleibt nur im Speicher. */
  }
}

// ── Bibliothek-Saves ────────────────────────────────────────────────
export function isArtifactSaved(id?: string): boolean {
  if (!id) return false
  return readSet(SAVED_KEY).has(id)
}

export function markArtifactSaved(id?: string) {
  if (!id) return
  const s = readSet(SAVED_KEY)
  s.add(id)
  writeSet(SAVED_KEY, s)
}

// ── Ausgeführte Aktionen (id → Ergebnismeldung) ─────────────────────
function readActions(): Record<string, string> {
  try {
    const raw = localStorage.getItem(ACTION_KEY)
    const obj = raw ? JSON.parse(raw) : {}
    return obj && typeof obj === 'object' ? obj : {}
  } catch {
    return {}
  }
}

export function getDoneAction(id?: string): string | null {
  if (!id) return null
  const obj = readActions()
  return typeof obj[id] === 'string' ? obj[id] : null
}

export function markActionDone(id: string | undefined, message: string) {
  if (!id) return
  const obj = readActions()
  obj[id] = message
  try {
    localStorage.setItem(ACTION_KEY, JSON.stringify(obj))
  } catch {
    /* Storage nicht verfügbar. */
  }
}
