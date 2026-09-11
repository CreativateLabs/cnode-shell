"""
Web-Scraping / URL-Ingest (WS-DATA2) — SCOPE v2 §Web-Scraping.

POST /scrape {url, client_id, levels}:
  1. Allowlist-Prüfung (nur erlaubte Domains + Subdomains)
  2. SSRF-Schutz (nur http/https, keine internen/privaten IPs, kein localhost)
  3. HTML holen (httpx, Timeout + Größenlimit), Redirects manuell + re-validiert
  4. Haupttext extrahieren (readability-lite: <article>/<main> bevorzugt,
     script/style/nav/footer raus; selectolax falls vorhanden, sonst stdlib)
  5. Engine /ingest mit `levels` aufrufen -> {ingested, graph_delta, chars}

Stub-first (SCOPE §4): bei Fehler/Nicht-Allowlist/SSRF-Block liefert der Service
einen sauberen {ok:false, reason:...} — HTTP 200, kein Crash.

Allowlist wird in /seed/allowlist.json (Bind-Mount, persistent) gehalten;
GET/PUT /scrape/allowlist verwaltet sie.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

# --------------------------------------------------------------------------- config
_TIMEOUT = float(os.getenv("SCRAPE_TIMEOUT", "12.0"))
_MAX_BYTES = int(os.getenv("SCRAPE_MAX_BYTES", str(3 * 1024 * 1024)))  # 3 MB
_MAX_REDIRECTS = int(os.getenv("SCRAPE_MAX_REDIRECTS", "3"))
_MAX_DEPTH = int(os.getenv("SCRAPE_MAX_DEPTH", "0"))  # MVP: nur die eine Seite
_ENGINE_URL = os.getenv("ENGINE_URL", "http://localhost:8020").rstrip("/")
_USER_AGENT = os.getenv(
    "SCRAPE_USER_AGENT",
    "cnode-AssetsBot/0.1 (+https://creativate.tech; EU-sovereign)",
)

# Allowlist-Datei: erste beschreibbare Kandidatin gewinnt (Bind-Mount /seed persistiert)
_ALLOWLIST_CANDIDATES = [
    os.getenv("ALLOWLIST_PATH", ""),
    "/seed/allowlist.json",
    "/app/seed/allowlist.json",
    str(Path(__file__).resolve().parent / "seed" / "allowlist.json"),
    "./seed/allowlist.json",
]

_DEFAULT_DOMAINS = [
    "de.wikipedia.org",
    "en.wikipedia.org",
    "eur-lex.europa.eu",
    "bmwk.de",
    "foerderdatenbank.de",
    "gesetze-im-internet.de",
    "bundesregierung.de",
    "europa.eu",
]


# --------------------------------------------------------------------------- allowlist store
def _first_existing(paths: list[str]) -> Optional[str]:
    for p in paths:
        if p and Path(p).is_file():
            return str(Path(p).resolve())
    return None


def _first_writable(paths: list[str]) -> Optional[str]:
    """Erste Datei/Verzeichnis, in das wir schreiben können."""
    for p in paths:
        if not p:
            continue
        path = Path(p)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Testweise anfassen (append-safe)
            with open(path, "a", encoding="utf-8"):
                pass
            return str(path.resolve())
        except Exception:
            continue
    return None


def _normalize_domain(d: str) -> str:
    d = (d or "").strip().lower()
    # Schema/Pfad wegputzen, falls jemand eine volle URL einträgt
    if "://" in d:
        d = urlparse(d).netloc or d
    d = d.split("/")[0].split("@")[-1]
    if ":" in d:
        d = d.split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d.strip(".")


class Allowlist:
    def __init__(self) -> None:
        self._path = _first_existing(_ALLOWLIST_CANDIDATES)
        self._domains: list[str] = []
        if self._path:
            try:
                doc = json.loads(Path(self._path).read_text(encoding="utf-8"))
                self._domains = [
                    _normalize_domain(x) for x in doc.get("domains", []) if x
                ]
            except Exception:
                self._domains = []
        if not self._domains:
            self._domains = [_normalize_domain(x) for x in _DEFAULT_DOMAINS]

    @property
    def domains(self) -> list[str]:
        return sorted(set(d for d in self._domains if d))

    @property
    def store_path(self) -> Optional[str]:
        return self._path

    def contains(self, host: str) -> bool:
        # Leere Allowlist = permissiv: alle öffentlichen Hosts erlaubt. Der SSRF-Guard
        # (localhost/private IPs blockiert) bleibt der harte Schutz. Sobald Domains
        # explizit gepflegt sind, gilt wieder die strikte Whitelist.
        if not self._domains:
            return True
        host = _normalize_domain(host)
        for d in self._domains:
            if host == d or host.endswith("." + d):
                return True
        return False

    def replace(self, domains: list[str]) -> list[str]:
        cleaned = sorted(set(_normalize_domain(x) for x in (domains or []) if x))
        cleaned = [d for d in cleaned if d]
        self._domains = cleaned
        self._persist()
        return self.domains

    def _persist(self) -> None:
        target = self._path or _first_writable(_ALLOWLIST_CANDIDATES)
        if not target:
            return
        try:
            Path(target).write_text(
                json.dumps({"domains": self.domains}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._path = str(Path(target).resolve())
        except Exception:
            pass


_ALLOWLIST: Optional[Allowlist] = None


def get_allowlist() -> Allowlist:
    global _ALLOWLIST
    if _ALLOWLIST is None:
        _ALLOWLIST = Allowlist()
    return _ALLOWLIST


# --------------------------------------------------------------------------- SSRF-Schutz
def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _ssrf_check(url: str) -> Optional[str]:
    """Gibt None zurück wenn ok, sonst einen Fehlergrund (str)."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return f"scheme_not_allowed:{scheme or 'none'}"
    host = parsed.hostname
    if not host:
        return "no_host"

    lowered = host.lower()
    if lowered in ("localhost", "localhost.localdomain") or lowered.endswith(".localhost"):
        return "localhost_blocked"

    # Literale IP direkt prüfen
    try:
        ipaddress.ip_address(host)
        if not _is_public_ip(host):
            return f"private_ip_blocked:{host}"
        return None
    except ValueError:
        pass  # kein Literal -> DNS auflösen

    # DNS-Auflösung: ALLE aufgelösten Adressen müssen öffentlich sein
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except Exception as e:  # noqa: BLE001
        return f"dns_error:{type(e).__name__}"
    if not infos:
        return "dns_no_records"
    for info in infos:
        ip = info[4][0]
        if not _is_public_ip(ip):
            return f"private_ip_blocked:{ip}"
    return None


# --------------------------------------------------------------------------- HTML -> Text
_DROP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe",
              "nav", "footer", "aside", "form", "header", "button"}
_PREFER_TAGS = ("article", "main")


class _TextExtractor(HTMLParser):
    """stdlib-Fallback: strippt Tags, bevorzugt <article>/<main>, droppt Rauschen."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._title_parts: list[str] = []
        self._in_title = False
        self._drop_depth = 0
        self._all: list[str] = []
        self._prefer: list[str] = []
        self._prefer_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "title":
            self._in_title = True
        if tag in _DROP_TAGS:
            self._drop_depth += 1
        if tag in _PREFER_TAGS:
            self._prefer_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _DROP_TAGS and self._drop_depth > 0:
            self._drop_depth -= 1
        if tag in _PREFER_TAGS and self._prefer_depth > 0:
            self._prefer_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._drop_depth > 0:
            return
        chunk = data.strip()
        if not chunk:
            return
        self._all.append(chunk)
        if self._prefer_depth > 0:
            self._prefer.append(chunk)

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._title_parts)).strip()

    @property
    def text(self) -> str:
        parts = self._prefer if self._prefer else self._all
        return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _extract_selectolax(html: str) -> Optional[tuple[str, str]]:
    """(title, text) via selectolax, oder None wenn nicht verfügbar."""
    try:
        from selectolax.parser import HTMLParser as SlxParser  # type: ignore
    except Exception:
        return None
    try:
        tree = SlxParser(html)
        title = ""
        tnode = tree.css_first("title")
        if tnode:
            title = re.sub(r"\s+", " ", tnode.text(deep=True)).strip()
        for sel in _DROP_TAGS:
            for node in tree.css(sel):
                node.decompose()
        root = None
        for pref in _PREFER_TAGS:
            root = tree.css_first(pref)
            if root:
                break
        if root is None:
            root = tree.body or tree.root
        text = re.sub(r"\s+", " ", root.text(deep=True)).strip() if root else ""
        return (title, text)
    except Exception:
        return None


def extract_main_text(html: str) -> tuple[str, str]:
    """Gibt (title, main_text) zurück. selectolax bevorzugt, sonst stdlib."""
    slx = _extract_selectolax(html)
    if slx is not None and slx[1]:
        return slx
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    return (parser.title, parser.text)


# --------------------------------------------------------------------------- fetch
async def _fetch(url: str) -> dict[str, Any]:
    """Holt eine URL sicher (Redirects manuell re-validiert, Größenlimit).

    Rückgabe: {ok, ...}. Bei Fehler ok=False + reason.
    """
    allow = get_allowlist()
    current = url
    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    ) as client:
        for _hop in range(_MAX_REDIRECTS + 1):
            # Pro Hop: Allowlist + SSRF neu prüfen (Redirect-Bypass-Schutz)
            host = urlparse(current).hostname or ""
            if not allow.contains(host):
                return {"ok": False, "reason": "not_allowlisted", "host": host, "url": current}
            ssrf = _ssrf_check(current)
            if ssrf:
                return {"ok": False, "reason": ssrf, "url": current}

            try:
                async with client.stream("GET", current) as resp:
                    if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            return {"ok": False, "reason": f"redirect_no_location:{resp.status_code}"}
                        current = str(httpx.URL(current).join(loc))
                        continue
                    if resp.status_code != 200:
                        return {"ok": False, "reason": f"http_{resp.status_code}", "url": current}
                    ctype = resp.headers.get("content-type", "").lower()
                    if ctype and "html" not in ctype and "text" not in ctype and "xml" not in ctype:
                        return {"ok": False, "reason": f"content_type_not_text:{ctype}", "url": current}

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > _MAX_BYTES:
                            return {"ok": False, "reason": "size_limit_exceeded",
                                    "limit_bytes": _MAX_BYTES, "url": current}
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    enc = resp.encoding or "utf-8"
                    try:
                        html = raw.decode(enc, errors="replace")
                    except (LookupError, Exception):  # noqa: BLE001
                        html = raw.decode("utf-8", errors="replace")
                    return {"ok": True, "html": html, "final_url": current, "bytes": total}
            except httpx.TimeoutException:
                return {"ok": False, "reason": "timeout", "url": current}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "reason": f"fetch_error:{type(e).__name__}", "url": current}
        return {"ok": False, "reason": "too_many_redirects", "url": current}


# --------------------------------------------------------------------------- ingest
async def _ingest(title: str, text: str, url: str, client_id: str,
                  levels: list[str]) -> dict[str, Any]:
    excerpt = re.sub(r"\s+", " ", text)[:800].strip()
    node = {
        "label": (title or url)[:160],
        "type": "Document",
        # Volltext (gekappt) als content → NEN extrahiert daraus einen verbundenen
        # Subgraphen statt eines isolierten Stub-Knotens.
        "content": re.sub(r"\s+", " ", text)[:8000].strip(),
        "props": {
            "source_url": url,
            "kind": "web",
            "chars": len(text),
            "excerpt": excerpt,
            "client_id": client_id,
            "levels": levels,
        },
        "links": [],
        "client_id": client_id,
        # Contract v2: Ingest trägt levels (Engine schreibt group_id=tenant/market).
        "levels": levels,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_ENGINE_URL}/ingest", json=node)
            if resp.status_code == 200:
                data = resp.json()
                delta = data.get("graph_delta") if isinstance(data, dict) else None
                return {"engine": "live", "graph_delta": delta or {"nodes": [], "edges": []}}
    except Exception:
        pass
    # Fallback ohne Engine (Stub-first): lokales Delta
    local_delta = {
        "nodes": [{
            "id": f"web_{abs(hash((url, len(text)))) % 10_000_000}",
            "label": node["label"],
            "type": "Document",
            "props": node["props"],
        }],
        "edges": [],
    }
    return {"engine": "fallback", "graph_delta": local_delta}


# --------------------------------------------------------------------------- public
def _norm_levels(levels: Any) -> list[str]:
    valid = ("client", "market")
    if isinstance(levels, str):
        levels = [levels]
    if not isinstance(levels, (list, tuple)) or not levels:
        return ["client"]
    out = [str(x).strip().lower() for x in levels if str(x).strip().lower() in valid]
    return out or ["client"]


async def scrape(url: str, client_id: str = "default",
                 levels: Any = None, depth: int = 0) -> dict[str, Any]:
    """URL scrapen -> Text extrahieren -> Engine /ingest.

    MVP: kein Crawl über die eine Seite hinaus (depth wird auf _MAX_DEPTH geklemmt);
    die Struktur ist aber für spätere Tiefe vorbereitet (siehe crawl-Notiz).
    """
    url = (url or "").strip()
    lvls = _norm_levels(levels)
    if not url:
        return {"ok": False, "reason": "empty_url"}
    if "://" not in url:
        url = "https://" + url  # bequeme Eingabe, SSRF/Allowlist prüfen danach

    depth = max(0, min(int(depth or 0), _MAX_DEPTH))

    fetched = await _fetch(url)
    if not fetched.get("ok"):
        # sauberer Fehler, kein Crash (HTTP 200 auf App-Ebene)
        return {"ok": False, "reason": fetched.get("reason", "fetch_failed"),
                "url": fetched.get("url", url), "host": fetched.get("host")}

    title, text = extract_main_text(fetched["html"])
    if not text:
        return {"ok": False, "reason": "no_text_extracted", "url": fetched["final_url"]}

    ing = await _ingest(title, text, fetched["final_url"], client_id, lvls)
    return {
        "ok": True,
        "ingested": True,
        "url": fetched["final_url"],
        "title": title,
        "text": text[:12000],
        "chars": len(text),
        "bytes": fetched.get("bytes", 0),
        "levels": lvls,
        "graph_delta": ing["graph_delta"],
        "engine": ing["engine"],
        # MVP-Hinweis: Tiefe > 0 wird derzeit nicht gecrawlt (Struktur vorhanden).
        "crawl": {"depth": depth, "max_depth": _MAX_DEPTH, "pages": 1},
    }


def status() -> dict[str, Any]:
    allow = get_allowlist()
    return {
        "allowlist_count": len(allow.domains),
        "allowlist_store": allow.store_path,
        "max_bytes": _MAX_BYTES,
        "timeout_s": _TIMEOUT,
        "max_depth": _MAX_DEPTH,
        "selectolax": _extract_selectolax("<html><main>x</main></html>") is not None,
    }
