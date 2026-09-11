"""StartupScout-Adapter — findet Früh-Phase-Startups über öffentliche, rechtssichere Quellen.

Basierend auf dem PoC (startupscout.creativate.tech): Multi-Source-Discovery, ICP-Scoring
0–100 + Begründung, quellenbelegte Kontaktdaten. Primäre LIVE-Quelle hier: die **GitHub-
Such-API** (frei, ohne Vertrag; optional GITHUB_TOKEN für höhere Limits) — technische
Startups/Orgs über Code-Aktivität, oft Jahre vor der ersten Funding-Runde sichtbar.

Suchkriterien-Flow: aus dem Freitext-ICP werden echte Such-Qualifier abgeleitet
(Sprache/Tech, Topics, Mindest-Sterne, Aktualität/Phase, Region) und in eine
GitHub-Query übersetzt — der Scout sucht also gezielt, nicht nur nach Stichwort-Overlap.
`find()` gibt die angewandten Kriterien + die rohe Query zurück, damit der Chat-Flow
sichtbar machen kann, WONACH gesucht wurde.

Contract (wie LeadScout): find(icp, client_id, limit) → {"targets": [...], "criteria": {...},
"query": "…", "source": "github-live|stub", "count": n}. Ist GitHub nicht erreichbar
(air-gapped/Sandbox), greift ein deterministischer Stub aus seed/startups.json.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

_GH_API = "https://api.github.com"
_GH_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
# Demo-Fallback (Seed-Katalog) erlauben? In strengen Prod-Deployments auf 0 → nie Demo-Daten.
_ALLOW_STUB = os.getenv("STARTUPSCOUT_ALLOW_STUB", "1").strip().lower() not in ("0", "false", "no")
_SEED_CANDIDATES = [
    os.getenv("STARTUPS_SEED_PATH", ""),
    "/app/seed/startups.json",
    str(Path(__file__).resolve().parent / "seed" / "startups.json"),
    "/seed/startups.json",
]
_WORD_RE = re.compile(r"[a-zäöüß0-9]+", re.IGNORECASE)
# Impressum-Kontakt (öffentlich, §5 TMG): E-Mail + DE/int. Telefonnummer.
# Telefon nur mit erkennbarer Gruppierung (Separator Pflicht) → keine nackten Zahlenläufe.
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+49|0049|0)\s?\(?\d{2,5}\)?[\s/\-]\d{2,4}[\s/\-]?\d{2,6}")
# Assets/CDN/Tracking-Mails, die kein echter Kontakt sind → verwerfen.
_EMAIL_BLOCK = ("example.", "sentry.", "@2x", ".png", ".jpg", ".svg", "wixpress",
                "godaddy", "@github", "noreply@github")
_STOP = {"und", "der", "die", "das", "für", "mit", "von", "the", "and", "for", "startup",
         "startups", "unternehmen", "firma", "gmbh", "inc", "ltd", "suche", "finde",
         "phase", "frühe", "junge", "aus", "im", "in", "bereich", "thema", "rund",
         "stage", "min", "tech", "star", "stars", "stern", "sterne", "spinoffs"}

# Freitext-Sprach-/Tech-Nennung → GitHub `language:` Qualifier.
_LANG_MAP = {
    "python": "Python", "rust": "Rust", "typescript": "TypeScript", "ts": "TypeScript",
    "javascript": "JavaScript", "js": "JavaScript", "go": "Go", "golang": "Go",
    "java": "Java", "kotlin": "Kotlin", "swift": "Swift", "c++": "C++", "cpp": "C++",
    "solidity": "Solidity", "scala": "Scala", "elixir": "Elixir", "ruby": "Ruby",
}
# Themen, die als GitHub-`topic:` besonders trennscharf sind (Domänen-Signale).
_TOPIC_HINTS = {
    "ai", "ml", "llm", "genai", "nlp", "computer-vision", "robotics", "fintech",
    "healthtech", "biotech", "climate", "cleantech", "energy", "cybersecurity",
    "security", "blockchain", "web3", "iot", "saas", "devtools", "data", "analytics",
    "healthcare", "medtech", "agtech", "mobility", "logistics", "edtech",
}
# Region-Erkennung (nur ein grobes Set; erweiterbar). Wert = GitHub `location:`-Term.
_LOCATION_MAP = {
    # Städte
    "berlin": "Berlin", "münchen": "Munich", "munich": "Munich", "hamburg": "Hamburg",
    "köln": "Cologne", "cologne": "Cologne", "frankfurt": "Frankfurt", "stuttgart": "Stuttgart",
    "düsseldorf": "Düsseldorf", "duesseldorf": "Düsseldorf", "leipzig": "Leipzig",
    "dresden": "Dresden", "karlsruhe": "Karlsruhe", "heidelberg": "Heidelberg",
    "wien": "Vienna", "vienna": "Vienna", "zürich": "Zurich", "zurich": "Zurich",
    # Bundesländer/Regionen (werden als Region behandelt, NICHT als Such-Stichwort)
    "hessen": "Hesse", "bayern": "Bavaria", "bavaria": "Bavaria", "sachsen": "Saxony",
    "niedersachsen": "Lower Saxony", "nrw": "North Rhine-Westphalia",
    "nordrhein-westfalen": "North Rhine-Westphalia", "baden-württemberg": "Baden-Württemberg",
    "baden-wuerttemberg": "Baden-Württemberg", "brandenburg": "Brandenburg",
    "thüringen": "Thuringia", "rheinland-pfalz": "Rhineland-Palatinate",
    # Länder/übergreifend
    "deutschland": "Germany", "germany": "Germany", "österreich": "Austria", "austria": "Austria",
    "schweiz": "Switzerland", "switzerland": "Switzerland",
    "dach": "Germany", "europa": "Europe", "europe": "Europe",
}
_EARLY_HINTS = {"früh", "frueh", "early", "seed", "pre-seed", "preseed", "neu", "jung",
                "gründung", "ausgründung", "spin-off", "spinoff", "mvp", "prototyp"}
# „Kein Startup" — kuratierte Listen, Lernmaterial, Dotfiles etc. dominieren Star-Suchen,
# sind aber keine Unternehmen. Solche Kandidaten werden aussortiert (Relevanz > Sterne).
_NOISE_TOKENS = {"awesome", "awesome-list", "list", "lists", "cheatsheet", "cheat-sheet",
                 "roadmap", "tutorial", "tutorials", "course", "courses", "book", "books",
                 "interview", "interviews", "guide", "handbook", "curriculum", "learn",
                 "learning", "study", "notes", "dotfiles", "config", "configs", "boilerplate",
                 "template", "templates", "starter", "example", "examples", "sample", "samples",
                 "demo", "playground", "resources", "collection", "wiki", "docs",
                 "documentation", "papers", "paper", "freecodecamp", "coding-interview"}


def _first_existing(paths: list[str]) -> Optional[str]:
    for p in paths:
        if p and Path(p).is_file():
            return str(Path(p).resolve())
    return None


def _tokens(text: str) -> list[str]:
    seen, out = set(), []
    for t in _WORD_RE.findall((text or "").lower()):
        if len(t) > 2 and t not in _STOP and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _icp_to_text(icp: Any) -> str:
    if isinstance(icp, str):
        return icp
    if isinstance(icp, dict):
        parts: list[str] = []
        for v in icp.values():
            parts.append(" ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v))
        return " ".join(parts)
    return str(icp or "")


def _parse_criteria(icp: Any) -> dict[str, Any]:
    """Freitext-ICP → strukturierte Suchkriterien (der 'Flow' des Scouts)."""
    text = _icp_to_text(icp)
    low = text.lower()
    toks = _tokens(text)

    language = next((_LANG_MAP[t] for t in toks if t in _LANG_MAP), "")
    topics = [t for t in toks if t in _TOPIC_HINTS][:3]
    location = next((v for k, v in _LOCATION_MAP.items() if k in low), "")
    early = any(h in low for h in _EARLY_HINTS)

    # Mindest-Sterne aus Freitext ("min 50 sterne", "50+ stars", ">100").
    min_stars = 0
    m = re.search(r"(?:min(?:destens)?\s*|>=?\s*)?(\d{1,5})\s*\+?\s*(?:star|stern|⭐)", low)
    if m:
        min_stars = int(m.group(1))
    elif not early:
        min_stars = 3  # etwas Signal, wenn nicht explizit Früh-Phase gewünscht

    # Rest-Keywords (ohne die schon als Qualifier verbrauchten Terme).
    used = set(topics) | ({language.lower()} if language else set())
    used |= {k for k in _LOCATION_MAP if k in low} | _EARLY_HINTS
    keywords = [t for t in toks if t not in used and t not in _LANG_MAP][:4]

    return {
        "keywords": keywords, "language": language, "topics": topics,
        "location": location, "min_stars": min_stars, "stage": "early" if early else "any",
    }


def _build_repo_query(cr: dict[str, Any]) -> str:
    """Kriterien → GitHub-Repository-Suchquery (echte Qualifier)."""
    parts: list[str] = []
    # Region wird NICHT als Such-Stichwort injiziert: seltene Ortsnamen (z.B. „hessen") kämen
    # in kaum einem Repo-Text vor und würden die Suche auf 0 Treffer würgen → Stub-Fallback.
    # Echte Region-Filterung passiert über Owner-Location (nur mit GITHUB_TOKEN); sonst ist
    # Region ein weiches Kriterium (siehe criteria-Hinweis), aber nie ein harter Suchbegriff.
    kw = list(cr["keywords"])
    if kw:
        parts.append(" ".join(kw) + " in:name,description,readme")
    for tp in cr["topics"]:
        parts.append(f"topic:{tp}")
    if cr["language"]:
        parts.append(f"language:{cr['language']}")
    if cr["min_stars"] > 0:
        parts.append(f"stars:>={cr['min_stars']}")
    # Phase → Aktualitäts-/Erstellungsfenster.
    now = datetime.now(timezone.utc)
    if cr["stage"] == "early":
        since = (now - timedelta(days=548)).strftime("%Y-%m-%d")   # ~18 Monate: jung
        parts.append(f"created:>={since}")
    else:
        since = (now - timedelta(days=365)).strftime("%Y-%m-%d")   # aktiv im letzten Jahr
        parts.append(f"pushed:>={since}")
    # Ohne jegliches Signal: wenigstens etwas suchen.
    if not any(p for p in parts if "in:" in p or p.startswith("topic:")):
        parts.insert(0, "startup in:description")
    return " ".join(parts).strip()


def _is_noise(repo_name: str, login: str, desc: str, topics: list[str]) -> bool:
    """True für kuratierte Listen / Lernmaterial / Dotfiles etc. — kein Startup."""
    toks = set(_WORD_RE.findall(f"{repo_name} {login} {desc}".lower())) | {t.lower() for t in topics}
    if toks & _NOISE_TOKENS:
        return True
    low = f"{repo_name} {login}".lower()
    return any(k in low for k in ("awesome", "dotfiles", "cheat", "roadmap", "-list", "coding-interview"))


class StartupScout:
    def __init__(self) -> None:
        self.seed_path = _first_existing(_SEED_CANDIDATES)
        self._seed: list[dict[str, Any]] = []
        if self.seed_path:
            try:
                self._seed = (__import__("json").loads(
                    Path(self.seed_path).read_text(encoding="utf-8"))).get("startups", [])
            except Exception:
                self._seed = []
        self.live_enabled = True

    # --------------------------------------------------------------- live (GitHub)
    async def _try_github(self, cr: dict[str, Any], limit: int) -> tuple[Optional[list[dict[str, Any]]], str]:
        q = _build_repo_query(cr)
        headers = {"Accept": "application/vnd.github+json"}
        if _GH_TOKEN:
            headers["Authorization"] = f"Bearer {_GH_TOKEN}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{_GH_API}/search/repositories",
                                params={"q": q, "sort": "stars", "order": "desc", "per_page": 40},
                                headers=headers)
                if r.status_code != 200:
                    return None, q
                items = r.json().get("items", []) or []
                # Region-Filter: Owner-Location anreichern (nur mit Token — spart anon. Limit).
                owner_loc: dict[str, str] = {}
                if cr["location"] and _GH_TOKEN:
                    owner_loc = await self._enrich_locations(c, headers, items, limit)
        except Exception:
            return None, q

        want_loc = cr["location"].lower()
        seen: set[str] = set()
        cand: list[dict[str, Any]] = []
        for repo in items:
            owner = repo.get("owner") or {}
            login = owner.get("login") or ""
            if not login or login.lower() in seen:
                continue
            topics = repo.get("topics") or []
            desc = repo.get("description") or ""
            repo_name = repo.get("name") or ""
            # Rauschen aussortieren: kuratierte Listen/Lernmaterial/Dotfiles sind keine Startups.
            if _is_noise(repo_name, login, desc, topics):
                continue
            loc = owner_loc.get(login.lower(), "")
            # Region gewünscht + wir konnten Locations prüfen → nur passende behalten.
            if want_loc and owner_loc and want_loc not in loc.lower() and want_loc != "europe":
                continue
            seen.add(login.lower())
            is_org = owner.get("type") == "Organization"
            stars = int(repo.get("stargazers_count") or 0)
            has_web = bool(repo.get("homepage"))
            website = repo.get("homepage") or f"https://github.com/{login}"
            score = self._score(cr, name=f"{login} {repo_name}", desc=f"{desc} {' '.join(topics)}",
                                stars=stars, is_org=is_org, loc=loc, has_web=has_web,
                                topics=topics)
            reason = self._reason(cr, stars=stars, is_org=is_org, has_web=has_web,
                                  lang=repo.get("language") or "", loc=loc,
                                  pushed=repo.get("pushed_at", "")[:10])
            cand.append({
                "name": login,
                "segment": (repo.get("language") or (topics[0] if topics else "tech")),
                "score": score, "reason": reason, "website": website,
                "location": loc, "traction": f"{stars}★ GitHub",
                "source": "github", "contact": "",
            })
        # Nach kombiniertem Score sortieren (nicht mehr rein nach Sternen) und kappen.
        cand.sort(key=lambda x: x["score"], reverse=True)
        return (cand[:limit] or None), q

    async def _enrich_locations(self, c: httpx.AsyncClient, headers: dict, items: list,
                                limit: int) -> dict[str, str]:
        """Owner-Location für die Top-Kandidaten nachladen (max ~limit*2 Calls)."""
        out: dict[str, str] = {}
        logins: list[str] = []
        for repo in items:
            lg = (repo.get("owner") or {}).get("login") or ""
            if lg and lg.lower() not in {x.lower() for x in logins}:
                logins.append(lg)
            if len(logins) >= limit * 3:
                break
        for lg in logins:
            try:
                ur = await c.get(f"{_GH_API}/users/{lg}", headers=headers)
                if ur.status_code == 200:
                    out[lg.lower()] = (ur.json().get("location") or "")
            except Exception:
                continue
        return out

    # --------------------------------------------------------------- scoring
    def _score(self, cr: dict[str, Any], *, name: str, desc: str, stars: int,
               is_org: bool, loc: str, has_web: bool = False,
               topics: list[str] | None = None) -> float:
        """Unternehmens-Signal schlägt reine Stern-Zahl: Org + echte Homepage + Domänen-Fit
        dominieren; Traktion ist gedeckelt, damit Awesome-Listen/Popular-Repos nicht gewinnen."""
        hay = set(_tokens(f"{name} {desc}"))
        want = set(cr["keywords"]) | set(cr["topics"])
        overlap = len(want & hay)
        fit = 20 + min(overlap, 5) * 8               # 0..40 Themen-Fit (Basis niedriger)
        web_bonus = 16 if has_web else 0             # echte Homepage = Produkt-Signal
        org = 12 if is_org else 0
        domain = 8 if (topics and any(t in _TOPIC_HINTS for t in topics)) else 0
        traction = min(stars, 300) / 300 * 14        # 0..14 (gedeckelt — Sterne dominieren nicht)
        loc_bonus = 10 if (cr["location"] and cr["location"].lower() in (loc or "").lower()) else 0
        early_bonus = 6 if cr["stage"] == "early" and stars < 800 else 0
        solo_penalty = 0 if (is_org or has_web) else 12  # reiner Einzel-Account ohne Site
        score = fit + web_bonus + org + domain + traction + loc_bonus + early_bonus - solo_penalty
        return round(max(0.0, min(98.0, score)), 1)

    def _reason(self, cr: dict[str, Any], *, stars: int, is_org: bool, has_web: bool,
                lang: str, loc: str, pushed: str) -> str:
        bits = []
        if stars:
            bits.append(f"GitHub-Traktion ({stars}★)")
        if is_org:
            bits.append("Organisation, kein Einzel-Account")
        if loc and cr["location"] and cr["location"].lower() in loc.lower():
            bits.append(f"Region-Match: {loc}")
        elif loc:
            bits.append(loc)
        if cr["stage"] == "early":
            bits.append("junges Projekt (Früh-Phase-Signal)")
        if lang:
            bits.append(f"Tech: {lang}")
        if has_web:
            bits.append("eigene Website")
        return " · ".join(bits) or "früh-Phase-Signal über Code-Aktivität"

    # --------------------------------------------------------------- stub (Demo-Fallback)
    def _stub(self, cr: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        """Demo-/Beispiel-Fallback (offline/keine Live-Treffer). STRIKT kriterien-gefiltert:
        nur Einträge, die Thema/Stichwort UND — falls gewünscht — Region treffen. Sonst leer
        (kein themenfremdes Demo-Rauschen, das als echter Lead durchgeht)."""
        want = set(cr["keywords"]) | set(cr["topics"]) | (
            {cr["language"].lower()} if cr["language"] else set())
        loc = (cr.get("location") or "").lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for s in self._seed:
            hay = set(_tokens(" ".join([s.get("name", ""), s.get("segment", ""),
                                        " ".join(s.get("keywords", [])), s.get("reason", "")])))
            overlap = len(want & hay)
            # Themen-Bezug ist Pflicht, sobald der Nutzer Thema/Stichwort/Sprache angegeben hat.
            if want and overlap == 0:
                continue
            # Region ist Pflicht, sobald angegeben (Demo darf nie „hessen" mit Hamburg beantworten).
            if loc and loc not in (s.get("location", "").lower()):
                continue
            score = round(min(96.0, 45 + min(overlap, 5) * 9 + float(s.get("traction_score", 0))), 1)
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, s in scored[:limit]:
            out.append({
                "name": s.get("name", ""), "segment": s.get("segment", ""), "score": score,
                "reason": s.get("reason", ""), "website": s.get("website", ""),
                "location": s.get("location", ""), "traction": s.get("traction", ""),
                "source": "demo", "contact": s.get("contact", "")})
        return out

    # --------------------------------------------------------------- contact enrichment
    async def _enrich_contacts(self, targets: list[dict[str, Any]], max_n: int = 4) -> None:
        """Best-effort: Homepage (+ /impressum) der Top-Kandidaten holen und E-Mail/Telefon
        per Regex ziehen — rechtssicher (öffentliches Impressum, §5 TMG). In-place, mit
        knappem Zeitbudget; scheitert lautlos (Outreach bleibt so ansprechbar, nie erfunden)."""
        def _real_site(u: str) -> bool:
            # Nur echte Firmen-Homepages anfassen — nie GitHub selbst scrapen (Fehltreffer).
            return u.startswith("http") and "github.com" not in u and "github.io" not in u

        picks = [t for t in targets if _real_site(t.get("website") or "")][:max_n]
        if not picks:
            return
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True,
                                     headers={"User-Agent": "cNode-StartupScout/1.0"}) as c:
            for t in picks:
                base = t["website"].rstrip("/")
                for url in (base, base + "/impressum", base + "/kontakt"):
                    try:
                        r = await c.get(url)
                        if r.status_code != 200 or not r.text:
                            continue
                        html = r.text[:200_000]
                        parts = []
                        for m in _EMAIL_RE.finditer(html):
                            e = m.group(0).lower()
                            if not any(b in e for b in _EMAIL_BLOCK) and len(e) < 60:
                                parts.append(m.group(0))
                                break
                        phone = _PHONE_RE.search(html)
                        if phone and sum(ch.isdigit() for ch in phone.group(0)) >= 9:
                            parts.append(re.sub(r"\s+", " ", phone.group(0)).strip())
                        if parts:
                            t["contact"] = " · ".join(parts)
                            t["contact_source"] = url
                            break
                    except Exception:
                        continue

    # --------------------------------------------------------------- public
    async def find(self, icp: Any, client_id: str = "default", limit: int = 6,
                   enrich: bool = False) -> dict[str, Any]:
        cr = _parse_criteria(icp)
        live, query = await self._try_github(cr, limit)
        if live:
            if enrich:
                await self._enrich_contacts(live)
            return {"targets": live, "source": "github-live", "count": len(live),
                    "criteria": cr, "query": query}
        # Keine Live-Treffer. Demo-Fallback nur, wenn erlaubt (offline/Demo). In strengen
        # Deployments (STARTUPSCOUT_ALLOW_STUB=0) lieber ehrlich leer als Demo-Daten zeigen.
        if _ALLOW_STUB:
            stub = self._stub(cr, limit)
            if stub:
                return {"targets": stub, "source": "demo", "count": len(stub),
                        "criteria": cr, "query": query,
                        "note": "Demo-/Beispieldaten — keine Live-Treffer für diese Kriterien."}
        return {"targets": [], "source": "none", "count": 0, "criteria": cr, "query": query,
                "note": "Keine Live-Treffer für diese Kriterien (GitHub lieferte nichts). "
                        "Kriterien anpassen oder GITHUB_TOKEN für Region-Filter setzen."}


_SINGLETON: Optional[StartupScout] = None


def get_startupscout() -> StartupScout:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = StartupScout()
    return _SINGLETON
