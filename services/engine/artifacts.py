"""Artefakt-Generierung (§2.3) — kind-spezifische Prompts + deterministische Templates.

Kinds: dialog_protocol | memo | proposal | one_pager. Grounding kommt aus der NEN AI
(belegte Fakten); die Formung übernimmt das LLM. Ist beides offline, greift ein
deterministisches Markdown-Template (Demo bleibt stabil).
"""
from __future__ import annotations

KIND_TITLES = {
    "dialog_protocol": "Dialog-Protokoll",
    "memo": "Memo",
    "proposal": "Proposal",
    "one_pager": "One-Pager",
}

KIND_INSTRUCTIONS = {
    "dialog_protocol": (
        "Erstelle ein strukturiertes DIALOG-PROTOKOLL des bisherigen Gesprächs/Kontexts. "
        "Abschnitte: Teilnehmer & Kontext, Diskussionsverlauf (chronologisch), Ergebnisse & "
        "Entscheidungen, offene Punkte, nächste Schritte (mit Verantwortlichen soweit ableitbar)."
    ),
    "memo": (
        "Erstelle ein prägnantes ENTSCHEIDUNGS-MEMO. Abschnitte: Betreff, Ausgangslage, "
        "Analyse (belegt durch die Fakten), Optionen mit Abwägung, Empfehlung, Risiken."
    ),
    "proposal": (
        "Erstelle ein professionelles PROPOSAL/Angebot. Abschnitte: Executive Summary, "
        "Problem/Bedarf, Lösungsansatz, Leistungsumfang, Zeitplan & Meilensteine, "
        "Investition (soweit ableitbar), Nächste Schritte."
    ),
    "one_pager": (
        "Erstelle einen kompakten ONE-PAGER (max. eine Seite). Abschnitte: Kernaussage, "
        "3-5 wichtigste Fakten (als Bullet-Points, belegt), Nutzen/Impact, Call-to-Action."
    ),
}


def kind_title(kind: str) -> str:
    return KIND_TITLES.get(kind, "Artefakt")


def build_prompt(kind: str, context: str, facts: str) -> tuple[str, str]:
    """Returns (system, prompt) für die kind-spezifische LLM-Generierung."""
    instruction = KIND_INSTRUCTIONS.get(kind, KIND_INSTRUCTIONS["memo"])
    system = (
        "Du bist ein präziser Business-Assistent von c:node (geerdet auf NENA). Du erstellst belegbare "
        "Artefakte auf Deutsch in sauberem Markdown. Nutze AUSSCHLIESSLICH die gelieferten "
        "Fakten aus dem Wissensgraphen und den Gesprächskontext. Erfinde keine Zahlen. "
        "Beginne direkt mit einer Markdown-Überschrift (##)."
    )
    prompt = (
        f"{instruction}\n\n"
        f"### Gesprächskontext\n{context or '(kein zusätzlicher Kontext übergeben)'}\n\n"
        f"### Belegte Fakten aus dem Wissensgraphen\n{facts or '(keine Fakten verfügbar)'}\n\n"
        f"Erzeuge jetzt das Artefakt als Markdown:"
    )
    return system, prompt


def deterministic_markdown(kind: str, context: str, facts: str, client_id: str) -> str:
    """Deterministisches Fallback-Template ohne LLM."""
    title = kind_title(kind)
    facts_block = facts or "- (Keine belegten Fakten verfügbar — NEN-AI/LLM offline)"
    ctx = context or "(kein Kontext übergeben)"
    return (
        f"## {title}\n\n"
        f"_Mandant: **{client_id}** · deterministisch erzeugt (LLM/NEN-AI offline)_\n\n"
        f"### Kontext\n{ctx}\n\n"
        f"### Belegte Fakten\n{facts_block}\n\n"
        f"### Hinweis\nDieses Artefakt wurde als stabiler Fallback erzeugt. Sobald NEN AI "
        f"und das lokale LLM verfügbar sind, wird ein vollständig ausformuliertes "
        f"{title} mit Quellnachweis generiert."
    )


def facts_from_sources(sources: list[dict]) -> str:
    """Formt normalisierte Sources zu einem Fakten-Block für den Prompt.

    Nimmt den beschreibenden Inhalt aus den Props mit (summary/content/reason etc.),
    nicht nur das Label — sonst hat das LLM nur Namen und driftet/verweigert."""
    lines = []
    for s in sources:
        label = s.get("label") or ""
        props = s.get("props") or {}
        summary = (props.get("summary") or props.get("content") or props.get("beschreibung")
                   or props.get("reason") or props.get("text") or "")
        if isinstance(summary, str):
            summary = summary.strip()
        prov = s.get("provenance") or ""
        if not label and not summary:
            continue
        line = f"- {label}" if label else "-"
        if summary and summary.lower() != (label or "").lower():
            line += f": {summary}"
        if prov:
            line += f"  _(Quelle: {prov})_"
        lines.append(line)
    return "\n".join(lines)
