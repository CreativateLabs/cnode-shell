"""Tenant Interactive Forms (FraBö) — deklaratives Framework für interaktive Artefakte.

Ein Tenant legt Fragebögen/Assessments als JSON unter `tenants/<slug>/forms/*.json` ab.
Der Core liest die validierten Specs (kein tenant-spezifischer Code): sie werden als Agent
verfügbar, via NL/Trigger gestartet, im Chat interaktiv durchlaufen, deterministisch
gescored und als Knoten in den Tenant-Graph persistiert.

Erweiterbar über `kind`: assessment (gescort, Sektionen) · survey · intake.
"""
from __future__ import annotations

import glob
import json
import os

from pydantic import BaseModel, Field


class Scale(BaseModel):
    min: int = 0
    max: int = 4
    labels: list[str] = Field(default_factory=list)   # Label je Stufe von min..max
    na_value: int = -1                                 # „nicht bewertbar" (aus Scoring ausgenommen)
    na_label: str = "Nicht bewertbar"


class InputField(BaseModel):
    """Ein erfasstes Datenfeld (für kind=reporting/intake). Score-Formulare nutzen
    stattdessen `questions`. `prev` zeigt eine Vorquartals-/Referenz-Anzeige read-only."""
    key: str
    label: str
    type: str = "number"                               # number | text | textarea | select
    unit: str = ""
    prev: str = ""                                     # Referenzwert (z.B. Vorquartal), nur Anzeige
    prev_label: str = ""                               # Beschriftung der prev-Spalte (z.B. „Q1-2026")
    placeholder: str = ""
    help: str = ""
    options: list[str] = Field(default_factory=list)   # für type=select


class Section(BaseModel):
    key: str                                           # kurz, z.B. "I" (Akronym-Buchstabe)
    title: str
    description: str = ""
    questions: list[str] = Field(default_factory=list) # Score-Modus (assessment)
    fields: list[InputField] = Field(default_factory=list)  # Erfassungs-Modus (reporting/intake)

    @property
    def is_fields(self) -> bool:
        return bool(self.fields)


class Scoring(BaseModel):
    per_section_max: int = 24                          # Ziel-Skala je Sektion
    normalize: bool = True                             # Rohsumme → per_section_max normalisieren
    total_max: int = 0                                 # 0 → len(sections)*per_section_max


class Report(BaseModel):
    intro: str = ""
    llm_narrative: bool = True                         # LLM formuliert Interpretation/Handlungsfelder


class FormSpec(BaseModel):
    id: str
    title: str
    kind: str = "assessment"                           # assessment | survey | intake
    description: str = ""
    triggers: list[str] = Field(default_factory=list)  # NL-Phrasen, die das Form starten
    subject_prompt: str = ""                           # optionaler Lead-in (z.B. „für welches Startup/Quartal?")
    scale: Scale = Field(default_factory=Scale)
    sections: list[Section] = Field(default_factory=list)
    scoring: Scoring = Field(default_factory=Scoring)
    report: Report = Field(default_factory=Report)

    @property
    def total_max(self) -> int:
        return self.scoring.total_max or (len(self.sections) * self.scoring.per_section_max)


def load_forms(config_dir: str) -> list[FormSpec]:
    """Alle Form-Specs eines Tenants aus <config_dir>/forms/*.json. Offline-sicher → []."""
    out: list[FormSpec] = []
    try:
        for path in sorted(glob.glob(os.path.join(config_dir, "forms", "*.json"))):
            try:
                with open(path, encoding="utf-8") as f:
                    out.append(FormSpec(**json.load(f)))
            except Exception:  # defektes Form darf den Start nicht kippen
                continue
    except Exception:
        pass
    return out


def score_submission(spec: FormSpec, answers: dict[str, list[int]]) -> dict:
    """Deterministisches Scoring. `answers` = {section_key: [werte in Fragen-Reihenfolge]}.
    na_value wird aus Zähler UND Nenner ausgenommen (kein Penalty). Sektion → per_section_max
    normalisiert; Gesamt = Summe der Sektions-Scores."""
    per_max = spec.scoring.per_section_max
    smax = spec.scale.max
    sections_out = []
    total = 0.0
    for sec in spec.sections:
        vals = [v for v in (answers.get(sec.key) or []) if v is not None and v != spec.scale.na_value]
        if vals:
            raw = sum(vals)
            denom = len(vals) * smax
            score = round((raw / denom) * per_max, 1) if spec.scoring.normalize else float(raw)
        else:
            score = 0.0
        sections_out.append({"key": sec.key, "title": sec.title, "score": score,
                             "max": per_max, "answered": len(vals), "questions": len(sec.questions)})
        total += score
    total = round(total, 1)
    tmax = spec.total_max
    return {
        "form_id": spec.id, "title": spec.title,
        "sections": sections_out,
        "total": total, "total_max": tmax,
        "percent": round(total / tmax * 100, 1) if tmax else 0.0,
    }


def is_scored(spec: FormSpec) -> bool:
    """Score-Formular (assessment) vs. Erfassungs-Formular (reporting/intake/survey)."""
    if spec.kind == "assessment":
        return True
    return any(sec.questions and not sec.fields for sec in spec.sections)


def collect_values(spec: FormSpec, values: dict) -> list[dict]:
    """Erfassungs-Formular: eingegebene Feldwerte je Sektion einsammeln (getypt, mit
    Label/Einheit/prev für Anzeige + Persistenz). Unbekannte Keys werden ignoriert."""
    out: list[dict] = []
    for sec in spec.sections:
        for f in sec.fields:
            raw = values.get(f.key, "")
            val: object = raw
            if f.type == "number" and str(raw).strip() != "":
                try:
                    val = float(raw) if ("." in str(raw) or "," in str(raw)) else int(raw)
                    if isinstance(val, str):
                        val = raw
                except Exception:
                    val = raw
            out.append({"section": sec.key, "section_title": sec.title, "key": f.key,
                        "label": f.label, "unit": f.unit, "type": f.type,
                        "prev": f.prev, "prev_label": f.prev_label, "value": val})
    return out


__all__ = ["Scale", "Section", "InputField", "Scoring", "Report", "FormSpec",
           "load_forms", "score_submission", "is_scored", "collect_values"]
