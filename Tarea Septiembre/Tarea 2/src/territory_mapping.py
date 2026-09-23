"""Fase 2b — Normalización territorial a los 25 departamentos del Perú (24 + Callao).

Uso:
    python src/territory_mapping.py     # corre los casos de prueba y muestra la cobertura sobre procesos.parquet
(validation.py importa `assign_department` y lo aplica dentro del pipeline completo.)

Regla (la tabla completa está en config/departamentos.yaml):
  0. clean_text(): MAYÚSCULAS, sin tildes (JUNÍN → JUNIN, pero Ñ se conserva: CAÑETE), espacios colapsados,
     sin prefijos tipo "DEPARTAMENTO DE" / "REGIÓN" / "PROVINCIA DE". Si el texto perdió la Ñ
     (CAÑETE → CANETE) se acepta igual, solo cuando no hay ambigüedad.
  1. ¿Es un departamento o alias?  → ese departamento.
  2. ¿Es una provincia?            → su departamento (corrige provincias puestas como departamento).
  3. Nada coincide                 → NO_UBICADO (se cuenta en el reporte; nunca se adivina).

Para cada proceso se prueban, en orden, tres campos del COMPRADOR (la entidad que compra):
  a) departamento_raw  (address.department)   → metodo = "departamento" o "provincia_en_campo_departamento"
  b) provincia_raw     (address.region; en SEACE contiene la PROVINCIA) → metodo = "provincia"
  c) comprador_nombre  ("GOBIERNO REGIONAL DE X", "MUNICIPALIDAD PROVINCIAL DE X") → metodo = "nombre_entidad"
Además se marca `territorio_inconsistente` cuando la provincia declarada pertenece a OTRO departamento
que el declarado (p. ej. departamento=CUSCO y provincia=HUARI, que es de Áncash).
"""
from __future__ import annotations

import re
import sys
import unicodedata
from functools import lru_cache

import pandas as pd
import yaml

from common import ROOT, get_logger, load_config

log = get_logger("territory_mapping")
NO_UBICADO = "NO_UBICADO"

# Patrones para extraer el lugar del NOMBRE de la entidad (solo entidades con alcance territorial claro).
ENTITY_PATTERNS = [
    re.compile(r"GOBIERNO REGIONAL (?:DE |DEL )?(?:LA REGION |REGION )?(?P<lugar>[A-Z Ñ]+?)(?: SEDE| -|$)"),
    re.compile(r"MUNICIPALIDAD PROVINCIAL (?:DE |DEL )?(?P<lugar>[A-Z Ñ]+?)(?: -|$)"),
]


def clean_text(value) -> str | None:
    """Normaliza un texto para compararlo: 'Junín ' → 'JUNIN', 'Cañete' → 'CAÑETE'."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return None
    s = str(value).upper().strip()
    # Quitar tildes SIN perder la Ñ: se protege la Ñ, se descompone (Í = I + ´) y se borran los acentos.
    s = s.replace("Ñ", "\0")
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if unicodedata.category(ch) != "Mn")
    s = s.replace("\0", "Ñ")
    # Mojibake típico de UTF-8 leído como Latin-1 (JUNÃ\x8dN) o caracteres de reemplazo: se reporta como texto raro.
    s = re.sub(r"[^A-ZÑ0-9 .\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


@lru_cache(maxsize=1)
def load_rules() -> dict:
    cfg = load_config()
    with open(ROOT / cfg["territory"]["mapping_file"], encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    departments = {clean_text(d): d for d in rules["departamentos"]}
    assert len(departments) == 25, "Deben ser exactamente 25 departamentos (24 + Callao)"
    aliases = {clean_text(k): v for k, v in rules["alias"].items()}
    provinces = {}
    for dep, provs in rules["provincias"].items():
        for p in provs:
            key = clean_text(p)
            if key in provinces and provinces[key] != dep:
                raise ValueError(f"Provincia ambigua en el YAML: {p} ({provinces[key]} y {dep})")
            provinces[key] = dep
    prefixes = sorted((clean_text(p) + " " for p in rules["prefijos_a_quitar"]), key=len, reverse=True)
    # Respaldo para textos que perdieron la Ñ por problemas de encoding (CAÑETE → CANETE):
    # solo se usa si el nombre "sin Ñ" apunta a UN único departamento.
    folded: dict[str, set] = {}
    for table in (departments, aliases, provinces):
        for k, dep in table.items():
            folded.setdefault(k.replace("Ñ", "N"), set()).add(dep)
    folded = {k: next(iter(v)) for k, v in folded.items() if len(v) == 1}
    return {"departments": departments, "aliases": aliases, "provinces": provinces, "prefixes": prefixes,
            "folded": folded, "provinces_folded": {k.replace("Ñ", "N") for k in provinces}}


def strip_prefixes(s: str) -> str:
    for p in load_rules()["prefixes"]:
        if s.startswith(p):
            return s[len(p):].strip()
    return s


def map_value(value) -> tuple[str, str]:
    """Devuelve (departamento, regla_usada). regla_usada ∈ {departamento, alias, provincia, sin_coincidencia, vacio}."""
    s = clean_text(value)
    if s is None:
        return NO_UBICADO, "vacio"
    s = strip_prefixes(s)
    r = load_rules()
    if s in r["departments"]:
        return r["departments"][s], "departamento"
    if s in r["aliases"]:
        return r["aliases"][s], "alias"
    if s in r["provinces"]:
        return r["provinces"][s], "provincia"
    if s in r["folded"]:  # mismo nombre pero con la Ñ perdida (N)
        return r["folded"][s], "provincia" if s in r["provinces_folded"] else "alias"
    return NO_UBICADO, "sin_coincidencia"


def province_department(value) -> str | None:
    """Departamento al que pertenece una PROVINCIA (solo mira la tabla de provincias)."""
    s = clean_text(value)
    return load_rules()["provinces"].get(strip_prefixes(s)) if s else None


def from_entity_name(name) -> tuple[str, str]:
    s = clean_text(name)
    if not s:
        return NO_UBICADO, "vacio"
    for pat in ENTITY_PATTERNS:
        m = pat.search(s)
        if m:
            dep, rule = map_value(m.group("lugar"))
            if dep != NO_UBICADO:
                return dep, rule
    return NO_UBICADO, "sin_coincidencia"


def assign_department(df: pd.DataFrame) -> pd.DataFrame:
    """Añade: departamento, departamento_metodo, departamento_raw_limpio, territorio_inconsistente."""
    out = df.copy()
    deps, methods = [], []
    for dep_raw, prov_raw, name in zip(out["departamento_raw"], out["provincia_raw"], out["comprador_nombre"]):
        dep, rule = map_value(dep_raw)
        if dep != NO_UBICADO:
            deps.append(dep)
            methods.append("provincia_en_campo_departamento" if rule == "provincia" else "departamento")
            continue
        dep, rule = map_value(prov_raw)
        if dep != NO_UBICADO:
            deps.append(dep); methods.append("provincia")
            continue
        dep, rule = from_entity_name(name)
        deps.append(dep); methods.append("nombre_entidad" if dep != NO_UBICADO else NO_UBICADO)
    out["departamento"] = deps
    out["departamento_metodo"] = methods
    out["departamento_raw_limpio"] = out["departamento_raw"].map(clean_text)
    # Inconsistencia: la provincia existe en la tabla pero pertenece a otro departamento.
    prov_dep = out["provincia_raw"].map(province_department)
    out["territorio_inconsistente"] = prov_dep.notna() & (out["departamento"] != NO_UBICADO) & \
        (prov_dep != out["departamento"])
    out["departamento_segun_provincia"] = prov_dep
    return out


# Casos difíciles que la regla DEBE resolver bien (sirven de prueba y de ejemplo para el video).
TEST_CASES = [
    ("JUNÍN", "JUNIN"), ("Junin", "JUNIN"), ("  junín  ", "JUNIN"),
    ("ÁNCASH", "ANCASH"), ("Apurímac", "APURIMAC"), ("HUÁNUCO", "HUANUCO"), ("San Martín", "SAN MARTIN"),
    ("Departamento de Piura", "PIURA"), ("REGIÓN CUSCO", "CUSCO"), ("Cuzco", "CUSCO"),
    ("LIMA METROPOLITANA", "LIMA"), ("Lima Provincias", "LIMA"),
    ("Provincia Constitucional del Callao", "CALLAO"), ("CALLAO", "CALLAO"),
    ("HUAURA", "LIMA"), ("Cañete", "LIMA"), ("CANETE", "LIMA"),   # Ñ perdida por encoding
    ("FERRENAFE", "LAMBAYEQUE"), ("DATEM DEL MARANON", "LORETO"),
    ("TRUJILLO", "LA LIBERTAD"), ("LA CONVENCION", "CUSCO"), ("MARISCAL NIETO", "MOQUEGUA"),
    ("CORONEL PORTILLO", "UCAYALI"), ("UCAYALI", "UCAYALI"),       # departamento gana a la provincia homónima de Loreto
    ("Provincia de Maynas", "LORETO"), ("NAZCA", "ICA"),
    ("", NO_UBICADO), (None, NO_UBICADO), ("EXTRANJERO", NO_UBICADO), ("MIRAFLORES", NO_UBICADO),
]


def run_tests() -> bool:
    ok = True
    for raw, expected in TEST_CASES:
        got, rule = map_value(raw)
        flag = "OK " if got == expected else "ERR"
        ok &= got == expected
        log.info("  %s %-40r → %-13s (regla: %s)", flag, raw, got, rule)
    for name, expected in [("GOBIERNO REGIONAL DE PIURA SEDE CENTRAL", "PIURA"),
                           ("MUNICIPALIDAD PROVINCIAL DE HUARI", "ANCASH"),
                           ("GOBIERNO REGIONAL DE LA REGION JUNÍN", "JUNIN"),
                           ("MINISTERIO DE SALUD", NO_UBICADO)]:
        got, _ = from_entity_name(name)
        flag = "OK " if got == expected else "ERR"
        ok &= got == expected
        log.info("  %s nombre %-45r → %s", flag, name, got)
    return ok


def main() -> int:
    log.info("Casos de prueba de la regla territorial:")
    ok = run_tests()
    cfg = load_config()
    df = pd.read_parquet(ROOT / cfg["validation"]["input_file"])
    res = assign_department(df)
    log.info("Distribución por método:\n%s", res["departamento_metodo"].value_counts().to_string())
    log.info("Departamentos distintos: %d (+ NO_UBICADO=%d) | inconsistentes provincia↔departamento: %d",
             res.loc[res["departamento"] != NO_UBICADO, "departamento"].nunique(),
             (res["departamento"] == NO_UBICADO).sum(), res["territorio_inconsistente"].sum())
    raw_variants = res.groupby("departamento")["departamento_raw"].unique()
    for dep, variants in raw_variants.items():
        vs = [v for v in variants if isinstance(v, str)]
        if len(vs) > 1:
            log.info("  %s ← variantes: %s", dep, vs)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
