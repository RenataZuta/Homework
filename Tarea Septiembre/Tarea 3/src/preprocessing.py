"""Paso 6 — Limpieza del texto OCR y enmascarado de frases que delatan la etiqueta (años de experiencia / edad).

Por cada JSON de data/ocr:
  1. reconstruye el texto por filas de lectura, descartando líneas con confianza < CONF_THRESHOLD
  2. une líneas rotas y palabras partidas con guion de fin de línea
  3. quita nombre, email, teléfono, URLs y dirección (regex)
  4. ENMASCARA con "[MASKED]": "X years of experience", "X+ years", variantes, edad y fecha de nacimiento
  5. NO toca fechas de trabajos ni de graduación
Salida: data/processed/clean_texts.csv (id, clean_text, was_masked)
        output/metrics/preprocessing_report.json, output/tables/masking_examples.csv

Los regex se diseñaron tras revisar textos OCR al azar: ``python -m src.preprocessing --sample-read 50``.
El umbral de confianza se elige con ``python -m src.preprocessing --analyze-threshold``.

Uso (desde Tarea 3/):  python -m src.preprocessing
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter

import pandas as pd

from src import utils as U
from src.ocr_extraction import lines_to_text
from src.ocr_quality import error_rates, years_in

MASK = "[MASKED]"

# Umbral de confianza por línea. Ver ``--analyze-threshold`` y el README: se fija con el análisis sobre datos reales.
CONF_THRESHOLD = 0.5

# ── Números ──────────────────────────────────────────────────────────────────
_WORD_NUM = (r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
             r"seventeen|eighteen|nineteen|twenty(?:[- ]?(?:one|two|three|four|five|six|seven|eight|nine))?|"
             r"thirty|forty|fifty")
NUM = rf"(?<![\d.])(?:\d{{1,2}}(?:\.\d)?|{_WORD_NUM})(?![\d])"
YRS = r"(?:years?|yrs?\b\.?)"
APPROX = r"(?:(?:over|more\s+than|nearly|almost|around|approximately|approx\.?|about|close\s+to|in\s+excess\s+of|up\s+to|plus)\s+)"
EXP_WORDS = r"(?:experience|exp\b\.?|expertise|background|track\s+record)"
ADJ = (r"(?:(?:professional|relevant|work|working|related|combined|total|overall|hands-on|progressive|extensive|"
       r"solid|proven|practical|industry|field|clinical|teaching|nursing|accounting|construction|software|"
       r"development|managerial|supervisory|diverse|dedicated|direct|full-time|real-world|proficient|"
       r"comprehensive|valuable|strong|combined)\s+){0,3}")

# (nombre, regex) — el orden importa: los patrones más largos primero.
EXPERIENCE_PATTERNS: list[tuple[str, re.Pattern]] = [
    # "10+ years of relevant experience", "8 years' experience", "over five yrs professional experience"
    ("years_of_experience", re.compile(
        rf"{APPROX}?{NUM}\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*{NUM}\s*)?{YRS}\s*(?:['’]s?|of|in|with)?\s*{ADJ}{EXP_WORDS}",
        re.I)),
    # "experience: 8 years", "career spanning over 12 years", "Years of experience - 6"
    ("experience_then_years", re.compile(
        rf"(?:(?:total|overall)\s+)?(?:experience|exp\b\.?|career|tenure|history|track\s+record)\s*"
        rf"(?:of|:|-|–|for|spanning|span(?:s|ning)?|over|totaling|totalling|is|=)?\s*{APPROX}?{NUM}\s*\+?\s*{YRS}", re.I)),
    ("years_of_experience_label", re.compile(
        rf"{YRS}\s+of\s+{EXP_WORDS}\s*(?:[:\-–=]\s*){APPROX}?{NUM}\s*\+?", re.I)),
    # "20-year career", "15 year veteran"
    ("n_year_compound", re.compile(
        rf"{NUM}[- ]year(?:s)?[- ](?:career|veteran|experience|track\s+record|professional|history)", re.I)),
    # "8+ years", "10 plus years"
    ("n_plus_years", re.compile(rf"{NUM}\s*(?:\+|plus)\s*{YRS}", re.I)),
    # "over a decade of experience", "two decades"
    ("decades", re.compile(
        r"(?:(?:over|more\s+than|nearly|almost)\s+)?(?:a|one|two|three|several)\s+decades?"
        rf"(?:\s+of\s+(?:\w+\s+){{0,2}}{EXP_WORDS})?", re.I)),
]

_DATE_FORMS = (r"(?:[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4}|"
               r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}|[A-Za-z]{3,9}\.?\s+\d{4}|\d{4})")
AGE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("age_label", re.compile(rf"\b(?:age|aged)\b\s*[:\-–]?\s*\d{{2}}\b(?:\s*{YRS}(?:\s+old)?)?", re.I)),
    ("years_old", re.compile(rf"(?<![\d.])\d{{2}}\s*[- ]?\s*{YRS}[- ]\s*old\b", re.I)),
    ("birth_date", re.compile(
        rf"\b(?:date\s+of\s+birth|d\.?\s?o\.?\s?b\.?|birth\s*date|birthday|born(?:\s+on|\s+in)?)\s*[:\-–]?\s*{_DATE_FORMS}",
        re.I)),
]

# ── PII ──────────────────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin|github|facebook|twitter|instagram)\.com/?\S*", re.I)
PHONE_RE = re.compile(
    r"(?:\b(?:phone|tel|telephone|mobile|cell|mob|fax)\b\.?\s*[:\-–]?\s*)?"
    r"(?<![\d/])(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.\-])\d{3}[\s.\-]\d{4}(?!\d)"
    r"|(?:\b(?:phone|tel|mobile|cell)\b\.?\s*[:\-–]?\s*)(?<![\d/])\+?\d{10,13}(?!\d)", re.I)
_STREET = (r"(?i:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct|place|pl|highway|hwy|"
           r"parkway|pkwy|circle|cir|terrace|trail)")
ADDRESS_RE = re.compile(
    rf"\b\d{{1,5}}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][A-Za-z]*\.?\s+){{1,4}}{_STREET}\b\.?"
    r"(?:,?\s+(?i:apt|suite|ste|unit|#)\.?\s*\w+)?"
    r"(?:,?\s+[A-Z][A-Za-z .]+,?\s+[A-Z]{2}\.?\s+\d{5}(?:-\d{4})?)?")
CITY_STATE_ZIP_RE = re.compile(r"\b[A-Z][A-Za-z .]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
LABEL_LINE_RE = re.compile(r"(?im)^\s*(?:name|address|e-?mail|phone|contact|nationality)\s*:.*$")

TITLE_WORDS = {  # una primera línea con alguna de estas palabras es un título/sección, no un nombre
    "resume", "curriculum", "vitae", "cv", "profile", "summary", "objective", "experience", "education", "skills",
    "contact", "nurse", "registered", "engineer", "developer", "software", "teacher", "elementary", "school",
    "accountant", "auditor", "laborer", "construction", "manager", "assistant", "senior", "junior", "technician",
    "specialist", "analyst", "professional", "certified", "cpa", "rn", "bsn", "middle", "worker", "foreman",
}
_NAME_TOKEN = re.compile(r"^[A-Z][A-Za-z'’\-]+\.?$|^[A-Z]{2,}$|^[A-Z]\.?$")  # incluye iniciales ("A.")


def looks_like_name(line: str) -> bool:
    toks = line.split()
    if not 2 <= len(toks) <= 4:
        return False
    if any(t.lower().strip(".,") in TITLE_WORDS for t in toks):
        return False
    return all(_NAME_TOKEN.match(t) for t in toks)


# ── Pasos de limpieza ────────────────────────────────────────────────────────
def rebuild_text(lines: list[dict], threshold: float) -> str:
    kept = [ln for ln in lines if ln["confidence"] >= threshold]
    return lines_to_text(kept)


_DATE = r"(?:19|20)\d{2}\.\d{2}"
DATE_RANGE_RE = re.compile(rf"(?<!\d)({_DATE})\s*[-–—]?\s*({_DATE})(?!\d)")
TRUNCATED_RANGE_RE = re.compile(rf"(?<!\d)({_DATE})\s*[-–—]\s*(?:19|20)\d{{2}}\.?(?!\.?\d)")


def normalize_date_ranges(text: str) -> str:
    """Unifica «2020.11-2023.01», «2020.11—2023.01» y el pegado «2020.112023.01» como «2020.11–2023.01».

    Solo toca el separador entre las dos fechas; ninguna fecha se elimina ni se modifica.
    """
    return DATE_RANGE_RE.sub(r"\1–\2", text)


def fix_broken_lines(text: str) -> str:
    """Une palabras partidas con guion al final de línea y líneas cortadas a media oración."""
    text = re.sub(r"(?<=[A-Za-z])-[ \t]*\n[ \t]*(?=[a-z])", "", text)
    out: list[str] = []
    for line in (ln.strip() for ln in text.split("\n")):
        if not line:
            continue
        starts_lower = line[0].islower()
        prev = out[-1] if out else ""
        prev_open = prev and not re.search(r"[.:;!?]$", prev) and not prev.isupper() and not re.match(r"^[•\-*▪●·]", line)
        if out and starts_lower and prev_open:
            out[-1] = f"{prev} {line}"
        else:
            out.append(line)
    return re.sub(r"[ \t]{2,}", " ", "\n".join(out))


SECTION_RE = re.compile(r"^\s*(?:work history|experience|work experience|professional experience|employment history|"
                        r"education|summary|profile|objective|skills)\s*:?\s*$", re.I)


def drop_header_block(lines: list[str]) -> list[str]:
    """Si la primera sección aparece en las primeras 4 líneas, lo anterior es la cabecera (nombre, ubicación,
    contacto) y se elimina completo. En PopResume siempre es: NOMBRE / «ST, USA | teléfono | email»."""
    for i, ln in enumerate(lines[:5]):
        if SECTION_RE.match(ln):
            return lines[i:]
    return lines


def remove_pii(text: str) -> str:
    raw = [ln for ln in text.split("\n") if ln.strip()]
    lines = drop_header_block(raw)
    if len(lines) == len(raw):  # no se encontró bloque de cabecera: heurístico de nombre en la 1.ª línea
        first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
        if first is not None and not SECTION_RE.match(lines[first]) and looks_like_name(lines[first].strip()):
            lines[first] = ""
    # línea de contacto («PA, USA | +1-356-988-1156 | katrina.kim@example.com»): se elimina completa
    lines = ["" if (EMAIL_RE.search(ln) or PHONE_RE.search(ln)) else ln for ln in lines]
    text = "\n".join(lines)
    text = LABEL_LINE_RE.sub("", text)
    for rx in (EMAIL_RE, URL_RE, PHONE_RE, ADDRESS_RE, CITY_STATE_ZIP_RE):
        text = rx.sub(" ", text)
    return text


def mask_leaks(text: str, counter: Counter | None = None) -> str:
    """Reemplaza por [MASKED] las frases de experiencia, edad y fecha de nacimiento."""
    for name, rx in AGE_PATTERNS + EXPERIENCE_PATTERNS:
        def _sub(m, name=name):
            if counter is not None:
                counter[name] += 1
            return MASK
        text = rx.sub(_sub, text)
    return re.sub(rf"(?:{re.escape(MASK)}\s*)+(?={re.escape(MASK)})", "", text)  # [MASKED] [MASKED] → [MASKED]


def tidy(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?m)^[ |,;·•\-]+$", "", text)         # restos de separadores tras quitar email/teléfono
    text = re.sub(r"(?m)^[ |,;]+|[ |,;]+$", "", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


RESIDUAL_RE = re.compile(rf"{NUM}\s*\+?\s*{YRS}", re.I)


def clean_one(lines: list[dict], threshold: float = CONF_THRESHOLD, counter: Counter | None = None) -> tuple[str, bool]:
    text = rebuild_text(lines, threshold)
    text = normalize_date_ranges(fix_broken_lines(text))
    text = remove_pii(text)
    masked = mask_leaks(text, counter)
    return tidy(masked), MASK in masked


# ── Utilidades de análisis ───────────────────────────────────────────────────
def _context(text: str, rx_list, width: int = 45):
    for name, rx in rx_list:
        m = rx.search(text)
        if m:
            a, b = max(0, m.start() - width), min(len(text), m.end() + width)
            return name, text[a:b].replace("\n", " ⏎ "), m.group(0)
    return None


def sample_read(n: int, seed: int) -> None:
    ids = sorted(p.stem for p in U.OCR_DIR.glob("*.json"))
    random.Random(seed).shuffle(ids)
    for cv_id in ids[:n]:
        print(f"\n######## {cv_id} ########")
        print(U.read_json(U.OCR_DIR / f"{cv_id}.json")["full_text"])


def analyze_threshold(n: int = 300, thresholds=(0.0, 0.5, 0.8, 0.9, 0.95, 0.97, 0.98, 0.99)) -> pd.DataFrame:
    """Para cada umbral: % de líneas descartadas, % de las descartadas que SÍ eran correctas y CER resultante."""
    ref = pd.read_csv(U.REFERENCE_TEXTS_CSV, dtype={"id": str}).set_index("id")["text"]
    ids = [i for i in sorted(p.stem for p in U.OCR_DIR.glob("*.json")) if i in ref.index]
    random.Random(U.RANDOM_SEED).shuffle(ids)
    docs = [(U.read_json(U.OCR_DIR / f"{i}.json")["lines"], U.normalize_text(ref[i]), ref[i]) for i in ids[:n]]
    rows = []
    for thr in thresholds:
        total = dropped = dropped_ok = 0
        cers = []
        for lines, ref_norm, ref_raw in docs:
            for ln in lines:
                total += 1
                if ln["confidence"] < thr:
                    dropped += 1
                    norm = U.normalize_text(ln["text"])
                    dropped_ok += bool(norm) and norm in ref_norm
            cers.append(error_rates(ref_raw, rebuild_text(lines, thr))[0])
        rows.append({"threshold": thr, "pct_lines_dropped": round(100 * dropped / total, 2) if total else 0,
                     "pct_dropped_that_were_correct": round(100 * dropped_ok / dropped, 1) if dropped else 0.0,
                     "mean_cer": round(float(pd.Series(cers).mean()), 4)})
    df = pd.DataFrame(rows)
    df.to_csv(U.TABLES_DIR / "confidence_threshold_analysis.csv", index=False)
    return df


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=float, default=CONF_THRESHOLD)
    ap.add_argument("--sample-read", type=int, metavar="N", help="imprime N textos OCR al azar para revisarlos")
    ap.add_argument("--analyze-threshold", action="store_true")
    ap.add_argument("--seed", type=int, default=U.RANDOM_SEED)
    args = ap.parse_args(argv)
    U.ensure_dirs()

    if args.sample_read:
        sample_read(args.sample_read, args.seed)
        return 0
    if args.analyze_threshold:
        print(analyze_threshold().to_string(index=False))
        return 0

    meta = pd.read_csv(U.METADATA_CSV, dtype={"id": str})
    rows, examples = [], []
    counter: Counter = Counter()
    residual = truncated = years_lost = 0
    n_lines = n_dropped = 0
    for cv_id in meta["id"]:
        p = U.OCR_DIR / f"{cv_id}.json"
        if not p.exists():
            continue
        lines = U.read_json(p)["lines"]
        n_lines += len(lines)
        n_dropped += sum(ln["confidence"] < args.threshold for ln in lines)
        raw_text = fix_broken_lines(rebuild_text(lines, args.threshold))
        clean, was_masked = clean_one(lines, args.threshold, counter)
        residual += bool(RESIDUAL_RE.search(clean))
        truncated += bool(TRUNCATED_RANGE_RE.search(clean))
        body = "\n".join(drop_header_block([ln for ln in raw_text.split("\n") if ln.strip()]))
        years_lost += sorted(years_in(body)) != sorted(years_in(clean))  # ninguna fecha debe perderse
        rows.append({"id": cv_id, "clean_text": clean, "was_masked": was_masked})
        if was_masked and len(examples) < 40:
            hit = _context(remove_pii(raw_text), AGE_PATTERNS + EXPERIENCE_PATTERNS)
            if hit:
                examples.append({"id": cv_id, "pattern": hit[0], "matched": hit[2], "context": hit[1]})

    out = pd.DataFrame(rows)
    out.to_csv(U.CLEAN_TEXTS_CSV, index=False)
    pd.DataFrame(examples).to_csv(U.TABLES_DIR / "masking_examples.csv", index=False)
    report = {
        "cvs": int(len(out)),
        "conf_threshold": args.threshold,
        "pct_lines_dropped_by_confidence": round(100 * n_dropped / n_lines, 2) if n_lines else None,
        "cvs_masked": int(out["was_masked"].sum()),
        "pct_cvs_masked": round(100 * float(out["was_masked"].mean()), 2),
        "matches_by_pattern": dict(counter),
        "cvs_with_residual_n_years_phrase": int(residual),
        "cvs_with_truncated_date_range": int(truncated),
        "cvs_that_lost_a_year_in_cleaning": int(years_lost),
    }
    with open(U.METRICS_DIR / "preprocessing_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("══ PREPROCESAMIENTO ══")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("\nEjemplos de enmascarado:")
    for ex in examples[:8]:
        print(f"  [{ex['pattern']}] «{ex['matched']}» …{ex['context']}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
