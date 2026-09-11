import { useEffect, useRef, useState } from 'react'
import { api, HttpError } from '../api'
import { CnodeMark } from './CnodeLogo'
import { useT } from '../i18n'
import LanguageSwitcher from './LanguageSwitcher'

// ─────────────────────────────────────────────────────────────────────────────
// Spinning data globe (canvas) — Tiefe/Atmosphäre wie auf der Landingpage, hell.
// Punkte auf einer Fibonacci-Kugel, um die Y-Achse rotierend, perspektivisch projiziert,
// nahe Punkte verbunden. Respektiert prefers-reduced-motion (statisches Bild).
// ─────────────────────────────────────────────────────────────────────────────
function DataGlobe() {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    let raf = 0
    let w = 0, h = 0
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const N = 620
    const pts: { x: number; y: number; z: number }[] = []
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2
      const r = Math.sqrt(1 - y * y)
      const phi = i * Math.PI * (3 - Math.sqrt(5))
      pts.push({ x: Math.cos(phi) * r, y, z: Math.sin(phi) * r })
    }
    function resize() {
      w = cv!.clientWidth; h = cv!.clientHeight
      cv!.width = w * dpr; cv!.height = h * dpr
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const onR = () => resize()
    window.addEventListener('resize', onR)
    let t = 0
    function frame() {
      t -= 0.0015   // rechts rum (im Uhrzeigersinn)
      const cx = w / 2, cy = h * 0.5
      const R = Math.min(w, h) * 0.9            // sehr groß → Kugel füllt den Hintergrund
      ctx!.clearRect(0, 0, w, h)
      const cos = Math.cos(t), sin = Math.sin(t)
      const proj = pts.map((p) => {
        const x = p.x * cos - p.z * sin
        const z = p.x * sin + p.z * cos
        const persp = 1 / (1.9 - z)
        return { sx: cx + x * R * persp, sy: cy + p.y * R * persp, depth: (z + 1) / 2 }
      })
      ctx!.lineWidth = 1
      for (let i = 0; i < proj.length; i += 2) {
        const a = proj[i]
        if (a.depth < 0.45) continue
        for (let j = i + 1; j < proj.length; j += 7) {
          const b = proj[j]
          const dx = a.sx - b.sx, dy = a.sy - b.sy
          if (dx * dx + dy * dy < 70 * 70 && b.depth > 0.4) {
            ctx!.strokeStyle = `rgba(99,79,220,${0.07 * a.depth})`
            ctx!.beginPath(); ctx!.moveTo(a.sx, a.sy); ctx!.lineTo(b.sx, b.sy); ctx!.stroke()
          }
        }
      }
      for (const p of proj) {
        const rad = 0.7 + p.depth * 2.0
        ctx!.fillStyle = `rgba(${118 - p.depth * 30},${90 - p.depth * 20},${230},${0.10 + p.depth * 0.5})`
        ctx!.beginPath(); ctx!.arc(p.sx, p.sy, rad, 0, Math.PI * 2); ctx!.fill()
      }
      if (!reduce) raf = requestAnimationFrame(frame)
    }
    frame()
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', onR) }
  }, [])
  return <canvas ref={ref} className="absolute inset-0 w-full h-full" aria-hidden />
}

// ─────────────────────────────────────────────────────────────────────────────
// Altcha — Proof-of-Work-Botschutz, komplett clientseitig gelöst (keine Dritt-Lib,
// kein externes Widget → keine CSP-Sorgen). Der Server signiert die Challenge; wir
// brute-forcen die Zahl, für die SHA-256(salt+number) == challenge gilt, und schicken
// die base64-kodierte Lösung im Signup mit. Der Server verifiziert PoW + HMAC + Replay.
async function solveAltcha(c: {
  algorithm: string; challenge: string; maxnumber: number; salt: string; signature: string
}): Promise<string> {
  const enc = new TextEncoder()
  const max = c.maxnumber || 50000
  for (let n = 0; n <= max; n++) {
    const buf = await crypto.subtle.digest('SHA-256', enc.encode(c.salt + n))
    const hex = Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('')
    if (hex === c.challenge) {
      const payload = { algorithm: c.algorithm, challenge: c.challenge, number: n, salt: c.salt, signature: c.signature }
      return btoa(JSON.stringify(payload))
    }
  }
  throw new Error('Altcha: keine Lösung gefunden')
}

// ─────────────────────────────────────────────────────────────────────────────
type Panel = 'login' | 'code' | 'magic' | 'signup'
// Geführter Signup: ein Feld pro Schritt (kein „alles auf einmal" → mobil kompakt).
// Reihenfolge = die Schritte; Bestätigen bündelt DSGVO + Altcha + Absenden.
type SignupStep = 'name' | 'email' | 'company' | 'password' | 'confirm'
const SIGNUP_STEPS: SignupStep[] = ['name', 'email', 'company', 'password', 'confirm']

export default function LoginScreen({ onAuthed }: { onAuthed: () => void }) {
  const t = useT()
  const [panel, setPanel] = useState<Panel>('login')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [name, setName] = useState('')
  const [company, setCompany] = useState('')
  const [dsgvo, setDsgvo] = useState(false)
  const [altcha, setAltcha] = useState<string | null>(null)   // gelöste PoW-Lösung (base64)
  const [altchaBusy, setAltchaBusy] = useState(false)
  const [emailExists, setEmailExists] = useState<boolean | null>(null)  // null = noch nicht geprüft
  const [sstep, setSstep] = useState(0)                                  // aktueller Signup-Schritt

  async function runAltcha() {
    if (altchaBusy || altcha) return
    setAltchaBusy(true); setErr(null)
    try {
      const c = await api.altchaChallenge()
      setAltcha(await solveAltcha(c))
    } catch {
      setErr(t('login.err_bot_load'))
      setAltcha(null)
    } finally { setAltchaBusy(false) }
  }

  async function checkEmail() {
    const e = email.trim()
    if (!e || !e.includes('@')) { setEmailExists(null); return }
    try { const r = await api.authExists(e); setEmailExists(r.exists) }
    catch { setEmailExists(null) }
  }
  function onEmail(v: string) { setEmail(v); setEmailExists(null) }

  // Altcha wie ein echtes Widget: löst sich automatisch, sobald der Bestätigen-Schritt erreicht ist.
  useEffect(() => {
    if (panel === 'signup' && SIGNUP_STEPS[sstep] === 'confirm' && !altcha && !altchaBusy) runAltcha()
  }, [panel, sstep])  // eslint-disable-line react-hooks/exhaustive-deps

  // Ein Schritt weiter — validiert nur das aktuelle Feld; E-Mail wird dabei auf Existenz geprüft.
  async function advanceStep() {
    if (busy) return
    setErr(null)
    const key = SIGNUP_STEPS[sstep]
    if (key === 'name' && !name.trim()) return
    if (key === 'email') {
      const e = email.trim()
      if (!e || !e.includes('@')) { setErr(t('login.err_email_invalid')); return }
      setBusy(true)
      try {
        const r = await api.authExists(e)
        if (r.exists) { setEmailExists(true); setBusy(false); return }  // bereits registriert → nicht weiter
        setEmailExists(false)
      } catch { /* Netz-/Serverfehler → Existenzprüfung überspringen, Signup validiert serverseitig */ }
      setBusy(false)
    }
    if (key === 'password' && password.length < 8) { setErr(t('login.err_password_short')); return }
    setSstep((s) => Math.min(s + 1, SIGNUP_STEPS.length - 1))
  }
  // Zurück — vom ersten Schritt zurück zur Anmeldung, sonst ein Feld zurück.
  function backStep() {
    setErr(null)
    if (sstep === 0) { go('login'); return }
    setSstep((s) => s - 1)
  }

  const [otpPhase, setOtpPhase] = useState<'email' | 'code'>('email')
  const [otp, setOtp] = useState('')
  const [magicPhase, setMagicPhase] = useState<'email' | 'verify'>('email')
  const [token, setToken] = useState('')

  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  function reset() { setErr(null); setNote(null) }
  function go(p: Panel) { setPanel(p); reset(); setEmailExists(null); setAltcha(null); setSstep(0); setOtpPhase('email'); setMagicPhase('email'); setOtp(''); setToken('') }
  function tokenFrom(raw?: string) {
    if (!raw) return ''
    const m = raw.match(/[?&]token=([^&\s]+)/)
    return m ? decodeURIComponent(m[1]) : raw.trim()
  }

  async function submitLogin() {
    const e = email.trim()
    if (!e || !password || busy) return
    setBusy(true); reset()
    try { await api.login(e, password); onAuthed() }
    catch (ex: any) {
      const s = ex instanceof HttpError ? ex.status : 0
      setErr(s === 401 ? t('login.err_login_wrong')
        : s === 400 ? t('login.err_no_password')
        : t('login.err_login_failed', { error: ex.message }))
    } finally { setBusy(false) }
  }

  async function submitSignup() {
    const e = email.trim()
    if (!e || busy) return
    if (password.length < 8) { setErr(t('login.err_password_short')); return }
    if (!dsgvo) { setErr(t('login.err_dsgvo')); return }
    if (!altcha) { setErr(t('login.err_bot_wait')); return }
    setBusy(true); reset()
    try {
      await api.signup({ email: e, password, name: name.trim() || undefined, company: company.trim() || undefined, altcha })
      onAuthed()
    } catch (ex: any) {
      const s = ex instanceof HttpError ? ex.status : 0
      setErr(s === 409 ? t('login.err_email_registered')
        : t('login.err_signup_failed', { error: ex.message }))
    } finally { setBusy(false) }
  }

  async function requestCode() {
    const e = email.trim()
    if (!e || busy) return
    setBusy(true); reset()
    try {
      const r = await api.requestCode(e)
      if (r.dev_code) setOtp(r.dev_code)
      setOtpPhase('code')
      setNote(r.dev_code ? t('login.dev_code') : t('login.code_sent'))
    } catch (ex: any) {
      const s = ex instanceof HttpError ? ex.status : 0
      setErr(s === 404 ? t('login.err_no_account')
        : t('login.err_code_request', { error: ex.message }))
    } finally { setBusy(false) }
  }
  async function verifyCode() {
    if (otp.trim().length < 6 || busy) return
    setBusy(true); reset()
    try { await api.verifyCode(email.trim(), otp.trim()); onAuthed() }
    catch (ex: any) {
      const s = ex instanceof HttpError ? ex.status : 0
      setErr(s === 400 ? t('login.err_code_wrong') : t('login.err_login_failed', { error: ex.message }))
    } finally { setBusy(false) }
  }

  async function requestLink() {
    const e = email.trim()
    if (!e || busy) return
    setBusy(true); reset()
    try {
      const r = await api.requestLink(e)
      const tk = tokenFrom(r.dev_token) || tokenFrom(r.dev_link)
      if (tk) setToken(tk)
      setMagicPhase('verify')
      setNote(tk ? t('login.dev_token') : t('login.link_sent'))
    } catch (ex: any) {
      const s = ex instanceof HttpError ? ex.status : 0
      setErr(s === 404 ? t('login.err_no_account')
        : t('login.err_link_request', { error: ex.message }))
    } finally { setBusy(false) }
  }
  async function verifyLink() {
    const tk = tokenFrom(token)
    if (!tk || busy) return
    setBusy(true); reset()
    try { await api.verify(tk); onAuthed() }
    catch (ex: any) { setErr(t('login.err_verify_failed', { error: ex.message })) }
    finally { setBusy(false) }
  }

  const input =
    'w-full rounded-xl bg-slate-50 border border-slate-200 px-3.5 py-2.5 text-[14px] text-slate-900 ' +
    'placeholder:text-slate-400 outline-none focus:border-violet-400 focus:bg-white transition disabled:opacity-60'
  const label = 'text-[11px] font-mono uppercase tracking-wider text-slate-500'
  const primaryBtn =
    'w-full py-2.5 rounded-full bg-gradient-to-br from-[#7C3AED] to-[#6366F1] text-white font-semibold text-[14px] ' +
    'disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition shadow-lg shadow-violet-300/50'
  const title =
    panel === 'signup' ? t('login.title_signup') : panel === 'code' ? t('login.title_code')
    : panel === 'magic' ? t('login.title_magic') : t('login.title_login')

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#F4F5FA] text-slate-900 flex items-center justify-center">
      {/* Tiefe: sanfte violette/blaue Glows + großer Globe (hell) */}
      <div aria-hidden className="absolute inset-0"
        style={{ background: 'radial-gradient(120% 90% at 50% 6%, rgba(124,58,237,0.14), transparent 55%), radial-gradient(90% 85% at 82% 100%, rgba(99,102,241,0.12), transparent 55%)' }} />
      <div aria-hidden className="absolute inset-0"><DataGlobe /></div>

      {/* Karte mit Shadow */}
      <div className="relative w-full max-w-sm mx-6 rounded-2xl border border-slate-200 bg-white/90 backdrop-blur-xl shadow-2xl shadow-slate-400/25 p-6 animate-fade-up">
        {/* Sprachwähler — oben rechts in der Karte (erste Fläche, die der Nutzer sieht) */}
        <div className="absolute right-3 top-3 z-10">
          <LanguageSwitcher variant="inline" />
        </div>
        {/* Header — nur das C-Logo */}
        <div className="flex flex-col items-center text-center mb-5">
          <CnodeMark size={46} />
          <h1 className="font-display font-bold text-[17px] mt-4">{title}</h1>
          <p className="text-[12px] text-slate-500 mt-1 max-w-xs">
            {t('login.subtitle')}
          </p>
        </div>

        {/* ── Login (Passwort, default) ── */}
        {panel === 'login' && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label className={label}>{t('login.email_label')}</label>
              <input type="email" autoFocus value={email} placeholder={t('login.email_ph')} className={input}
                onChange={(e) => onEmail(e.target.value)} onBlur={checkEmail}
                onKeyDown={(e) => e.key === 'Enter' && submitLogin()} />
              {emailExists === false && (
                <p className="text-[11.5px] text-slate-500">
                  {t('login.no_account_pre')}
                  <button onClick={() => go('signup')} className="text-violet-600 font-medium hover:underline">{t('login.register_now')}</button>.
                </p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <label className={label}>{t('login.password_label')}</label>
              <div className="relative">
                <input type={showPw ? 'text' : 'password'} value={password} placeholder="••••••••" className={input + ' pr-14'}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && submitLogin()} />
                <button type="button" tabIndex={-1} onClick={() => setShowPw((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[10.5px] font-mono uppercase tracking-wider text-slate-400 hover:text-slate-700 transition px-1.5">
                  {showPw ? t('login.pw_hide') : t('login.pw_show')}
                </button>
              </div>
            </div>
            <button onClick={submitLogin} disabled={busy || !email.trim() || !password} className={primaryBtn}>
              {busy ? t('login.signing_in') : t('login.login')}
            </button>
            <div className="flex items-center justify-center gap-3 text-[12px] text-slate-500">
              <button onClick={() => go('code')} className="hover:text-slate-900 transition">{t('login.with_code')}</button>
              <span className="w-px h-3 bg-slate-300" />
              <button onClick={() => go('magic')} className="hover:text-slate-900 transition">{t('login.magic_link')}</button>
            </div>
          </div>
        )}

        {/* ── Code (OTP) ── */}
        {panel === 'code' && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label className={label}>{t('login.email_label')}</label>
              <input type="email" autoFocus value={email} disabled={otpPhase === 'code'} placeholder={t('login.email_ph')} className={input}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && otpPhase === 'email' && requestCode()} />
            </div>
            {otpPhase === 'email' ? (
              <button onClick={requestCode} disabled={busy || !email.trim()} className={primaryBtn}>
                {busy ? t('login.sending_code') : t('login.send_code')}
              </button>
            ) : (
              <>
                <label className={label}>{t('login.code_label')}</label>
                <input inputMode="numeric" autoFocus maxLength={6} value={otp} placeholder="••••••"
                  className={input + ' text-center tracking-[0.5em] font-mono text-[18px]'}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  onKeyDown={(e) => e.key === 'Enter' && verifyCode()} />
                <button onClick={verifyCode} disabled={busy || otp.trim().length < 6} className={primaryBtn}>
                  {busy ? t('login.signing_in') : t('login.login')}
                </button>
              </>
            )}
            <button onClick={() => go('login')} className="text-[12px] text-slate-500 hover:text-slate-900 transition">← {t('common.back')}</button>
          </div>
        )}

        {/* ── Magic-Link ── */}
        {panel === 'magic' && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label className={label}>{t('login.email_label')}</label>
              <input type="email" autoFocus value={email} disabled={magicPhase === 'verify'} placeholder={t('login.email_ph')} className={input}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && magicPhase === 'email' && requestLink()} />
            </div>
            {magicPhase === 'email' ? (
              <button onClick={requestLink} disabled={busy || !email.trim()} className={primaryBtn}>
                {busy ? t('login.sending_link') : t('login.send_link')}
              </button>
            ) : (
              <>
                <label className={label}>{t('login.token_label')}</label>
                <textarea value={token} rows={2} placeholder={t('login.token_ph')}
                  className="w-full resize-none rounded-xl bg-slate-50 border border-slate-200 px-3.5 py-2.5 text-[12.5px] font-mono text-slate-900 placeholder:text-slate-400 outline-none focus:border-violet-400 transition break-all"
                  onChange={(e) => setToken(e.target.value)} />
                <button onClick={verifyLink} disabled={busy || !token.trim()} className={primaryBtn}>
                  {busy ? t('login.verifying') : t('login.login')}
                </button>
              </>
            )}
            <button onClick={() => go('login')} className="text-[12px] text-slate-500 hover:text-slate-900 transition">← {t('common.back')}</button>
          </div>
        )}

        {/* ── Signup ── */}
        {panel === 'signup' && (() => {
          const sk = SIGNUP_STEPS[sstep]
          const canNext =
            sk === 'name' ? !!name.trim()
            : sk === 'email' ? !!email.trim()
            : sk === 'password' ? password.length >= 8
            : true  // company ist optional
          const backCls = 'px-4 py-2.5 rounded-xl border border-slate-200 text-slate-600 text-[13px] font-medium hover:bg-slate-50 hover:border-slate-300 transition shrink-0'
          return (
            // key={sk} → sanfter Einblendeffekt bei jedem Schrittwechsel (kein Fortschritts-Dots).
            <div key={sk} className="flex flex-col gap-3 animate-fade-up">

              {sk === 'name' && (
                <div className="flex flex-col gap-1.5">
                  <label className={label}>{t('login.step_name_label')}</label>
                  <input type="text" autoFocus value={name} placeholder={t('login.step_name_ph')} className={input}
                    onChange={(e) => setName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && advanceStep()} />
                </div>
              )}

              {sk === 'email' && (
                <div className="flex flex-col gap-1.5">
                  <label className={label}>{t('login.step_email_label')}</label>
                  <input type="email" autoFocus value={email} placeholder={t('login.email_ph')} className={input}
                    onChange={(e) => onEmail(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && advanceStep()} />
                  {emailExists === true && (
                    <p className="text-[11.5px] text-slate-500">
                      {t('login.email_exists_pre')}
                      <button onClick={() => go('login')} className="text-violet-600 font-medium hover:underline">{t('login.signin')}</button>.
                    </p>
                  )}
                </div>
              )}

              {sk === 'company' && (
                <div className="flex flex-col gap-1.5">
                  <label className={label}>{t('login.step_company_label')}</label>
                  <input type="text" autoFocus value={company} placeholder={t('login.step_company_ph')} className={input}
                    onChange={(e) => setCompany(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && advanceStep()} />
                  <p className="text-[11.5px] text-slate-400">{t('login.company_hint')}</p>
                </div>
              )}

              {sk === 'password' && (
                <div className="flex flex-col gap-1.5">
                  <label className={label}>{t('login.step_password_label')}</label>
                  <div className="relative">
                    <input type={showPw ? 'text' : 'password'} autoFocus value={password} placeholder={t('login.password_ph')} className={input + ' pr-14'}
                      onChange={(e) => setPassword(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && advanceStep()} />
                    <button type="button" tabIndex={-1} onClick={() => setShowPw((v) => !v)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-[10.5px] font-mono uppercase tracking-wider text-slate-400 hover:text-slate-700 transition px-1.5">
                      {showPw ? t('login.pw_hide') : t('login.pw_show')}
                    </button>
                  </div>
                </div>
              )}

              {sk === 'confirm' && (
                <div className="flex flex-col gap-3">
                  <p className="text-[12.5px] text-slate-500">{name.trim() ? t('login.confirm_intro_named', { name: name.trim().split(' ')[0] }) : t('login.confirm_intro')}</p>
                  <label className="flex items-start gap-2.5 text-[12px] text-slate-600 cursor-pointer">
                    <input type="checkbox" checked={dsgvo} onChange={(e) => setDsgvo(e.target.checked)}
                      className="mt-0.5 w-4 h-4 shrink-0 accent-violet-600" />
                    <span>{t('login.dsgvo_pre')}<a href="https://c-node.ai/datenschutz" target="_blank" rel="noreferrer" className="text-violet-600 hover:underline">{t('login.dsgvo_link')}</a>{t('login.dsgvo_post')}</span>
                  </label>
                  {/* Altcha — Proof-of-Work-Botschutz (löst sich clientseitig, kein Klick nötig) */}
                  <button type="button" onClick={runAltcha} disabled={!!altcha || altchaBusy}
                    className={'flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 text-[12px] transition ' +
                      (altcha ? 'border-emerald-300 bg-emerald-50 text-emerald-700 cursor-default'
                        : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-violet-300 cursor-pointer')}>
                    {altcha ? (
                      <><svg width="16" height="16" viewBox="0 0 20 20" className="shrink-0" aria-hidden><path fill="currentColor" d="M8.1 13.3 5 10.2l-1.2 1.2 4.3 4.3 8.1-8.1-1.2-1.2z"/></svg>
                        <span>{t('login.altcha_verified')}</span></>
                    ) : altchaBusy ? (
                      <><svg width="16" height="16" viewBox="0 0 24 24" className="shrink-0 animate-spin" aria-hidden><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray="42" strokeLinecap="round" opacity="0.9"/></svg>
                        <span>{t('login.altcha_checking')}</span></>
                    ) : (
                      <><span className="w-4 h-4 shrink-0 rounded border border-slate-300" />
                        <span>{t('login.altcha_idle')}</span></>
                    )}
                  </button>
                </div>
              )}

              {/* Navigation: Zurück + Weiter/Absenden — ein Feld folgt aufs nächste, keine Dots */}
              <div className="flex gap-2">
                <button onClick={backStep} className={backCls}>← {t('common.back')}</button>
                <div className="flex-1">
                  {sk === 'confirm' ? (
                    <button onClick={submitSignup} disabled={busy || !dsgvo || !altcha} className={primaryBtn}>
                      {busy ? t('login.creating') : t('login.create_account')}
                    </button>
                  ) : (
                    <button onClick={advanceStep} disabled={busy || !canNext} className={primaryBtn}>
                      {busy && sk === 'email' ? t('login.checking') : t('common.next')}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )
        })()}

        {(note || err) && (
          <p className={`text-[11.5px] leading-snug mt-3 ${err ? 'text-rose-600' : 'text-emerald-600'}`}>{err || note}</p>
        )}

        {/* Google SSO — immer sichtbar */}
        <div className="flex items-center gap-3 my-4">
          <div className="flex-1 h-px bg-slate-200" />
          <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400">{t('login.or')}</span>
          <div className="flex-1 h-px bg-slate-200" />
        </div>
        <button onClick={() => (window.location.href = api.ssoGoogleLoginUrl())}
          className="w-full py-2.5 rounded-full bg-white border border-slate-200 text-slate-800 font-medium text-[13.5px] flex items-center justify-center gap-2.5 hover:bg-slate-50 hover:border-slate-300 transition">
          <svg width="17" height="17" viewBox="0 0 18 18" aria-hidden>
            <path fill="#4285F4" d="M17.6 9.2c0-.6-.05-1.2-.15-1.7H9v3.4h4.8a4.1 4.1 0 0 1-1.8 2.7v2.2h2.9c1.7-1.6 2.7-3.9 2.7-6.6z"/>
            <path fill="#34A853" d="M9 18c2.4 0 4.5-.8 6-2.2l-2.9-2.2c-.8.5-1.8.9-3.1.9-2.4 0-4.4-1.6-5.1-3.8H.9v2.3A9 9 0 0 0 9 18z"/>
            <path fill="#FBBC05" d="M3.9 10.7a5.4 5.4 0 0 1 0-3.4V5H.9a9 9 0 0 0 0 8l3-2.3z"/>
            <path fill="#EA4335" d="M9 3.6c1.3 0 2.5.5 3.4 1.3l2.6-2.6A9 9 0 0 0 .9 5l3 2.3C4.6 5.2 6.6 3.6 9 3.6z"/>
          </svg>
          {t('login.google')}
        </button>

        {/* Signup / Login Umschalter unten */}
        <p className="text-[12px] text-slate-500 text-center mt-5">
          {panel === 'signup' ? (
            <>{t('login.have_account')}<button onClick={() => go('login')} className="text-violet-600 font-medium hover:text-violet-700 transition">{t('login.login')}</button></>
          ) : (
            <>{t('login.no_account')}<button onClick={() => go('signup')} className="text-violet-600 font-medium hover:text-violet-700 transition">{t('login.register')}</button></>
          )}
        </p>
      </div>
    </div>
  )
}
