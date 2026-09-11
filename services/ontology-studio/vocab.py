"""Referenzvokabular für das Ontology-Studio.

Kuratierte Teilmenge etablierter Ontologien/Standards, gegen die vorgeschlagene
Typen gebenchmarkt werden — damit keine „Ontologien mit drei Beinen" entstehen,
sondern getypte Entitäten mit nachvollziehbarer Herkunft. Synonyme DE+EN.
"""
from __future__ import annotations

import re

# type → {onto, syn: [Spalten-/Begriffs-Synonyme]}
REFERENCE: dict[str, dict] = {
    "Organization":        {"onto": "schema.org", "syn": ["company", "firma", "organisation", "unternehmen", "org", "account", "kunde", "customer", "vendor", "lieferant", "arbeitgeber"]},
    "Person":              {"onto": "schema.org", "syn": ["person", "name", "contact", "ansprechpartner", "mitarbeiter", "employee", "vorname", "nachname", "first name", "last name", "kontakt"]},
    "Product":             {"onto": "schema.org", "syn": ["product", "produkt", "artikel", "item", "sku", "leistung"]},
    "Place":               {"onto": "schema.org", "syn": ["place", "ort", "location", "standort", "address", "adresse", "city", "stadt", "region", "plz"]},
    "Event":               {"onto": "schema.org", "syn": ["event", "termin", "meeting", "veranstaltung"]},
    "ContactPoint":        {"onto": "schema.org", "syn": ["email", "e-mail", "mail", "phone", "telefon", "tel", "website", "url", "web", "fax"]},
    "MonetaryAmount":      {"onto": "FIBO",        "syn": ["amount", "betrag", "preis", "price", "revenue", "umsatz", "cost", "kosten", "value", "wert", "volumen"]},
    "Currency":            {"onto": "ISO 4217",    "syn": ["currency", "währung", "waehrung"]},
    "Contract":            {"onto": "FIBO",        "syn": ["contract", "vertrag", "deal", "agreement", "auftrag"]},
    "FinancialInstrument": {"onto": "FIBO",        "syn": ["instrument", "security", "aktie", "bond", "anleihe", "fonds"]},
    "LegalEntity":         {"onto": "FIBO",        "syn": ["legal entity", "rechtsträger", "rechtstraeger", "gmbh", "ag", "legal", "hrb"]},
    "Identifier":          {"onto": "ISO",         "syn": ["id", "identifier", "nummer", "number", "code", "key", "ustid", "vat", "ust-idnr", "steuernummer"]},
    "Date":                {"onto": "ISO 8601",    "syn": ["date", "datum", "created", "erstellt", "updated", "zeit", "time", "year", "jahr", "frist"]},
    "Country":             {"onto": "ISO 3166",    "syn": ["country", "land", "nation", "staat"]},
    "Industry":            {"onto": "schema.org",  "syn": ["industry", "branche", "sektor", "sector", "segment"]},
}

# Entitäts-Typen (können Zeilen-Entitäten sein), Rest sind eher Attribute.
ENTITY_LIKE = {"Organization", "Person", "Product", "Place", "Event", "Contract",
               "FinancialInstrument", "LegalEntity"}

_TOK = re.compile(r"[^a-z0-9]+")


def _norm(s: str) -> str:
    return _TOK.sub(" ", (s or "").strip().lower()).strip()


def match_type(column: str) -> dict:
    """Spalte → bester Referenz-Typ mit Konfidenz + Ontologie-Herkunft.

    exakter Token-Treffer = 1.0, Teilstring = 0.7, sonst 0.0 (→ generisch 'Thing').
    """
    c = _norm(column)
    toks = set(c.split())
    best = {"type": "Thing", "onto": "generic", "confidence": 0.0, "role": "attribute"}
    for t, meta in REFERENCE.items():
        for syn in meta["syn"]:
            sn = _norm(syn)
            conf = 0.0
            if sn in toks or sn == c:
                conf = 1.0
            elif sn in c or c in sn:
                conf = 0.7
            if conf > best["confidence"]:
                best = {"type": t, "onto": meta["onto"], "confidence": conf,
                        "role": "entity" if t in ENTITY_LIKE else "attribute"}
    return best


def value_type(column: str) -> str:
    """Grobe Wert-Typ-Heuristik aus dem Spaltennamen (string|number|date|email|url)."""
    c = _norm(column)
    if any(k in c for k in ["email", "mail"]):
        return "email"
    if any(k in c for k in ["url", "web", "website"]):
        return "url"
    if any(k in c for k in ["date", "datum", "jahr", "year", "zeit", "time", "frist"]):
        return "date"
    if any(k in c for k in ["amount", "betrag", "preis", "price", "umsatz", "revenue", "wert", "value", "anzahl", "count", "nummer", "number"]):
        return "number"
    return "string"
