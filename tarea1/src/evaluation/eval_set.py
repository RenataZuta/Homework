"""Carga y validación de eval/preguntas.csv (y de su archivo de evidencias eval/evidencia.yaml).

Formato de las columnas con varios documentos (se separan con "|", en el mismo orden en ambas columnas):
    documento_esperado = "ds_001_2026_ef|ds_009_2025_ef|ley_32069"
    paginas_esperadas  = "14|30|29"        (varias páginas de un mismo documento: "8;9|47")
Un fragmento recuperado ACIERTA si su (documento, página) está entre los esperados de la pregunta.
En las preguntas con modificada_2026 = true el PRIMER documento es siempre la modificatoria (DS 001-2026-EF):
permite medir aparte si el recuperador trae el texto vigente y no solo el original desactualizado.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

COLUMNAS = ("id", "pregunta", "tipo", "estilo", "modificada_2026", "documento_esperado", "paginas_esperadas", "notas")
TIPOS = ("in_domain", "out_of_domain")
ESTILOS = ("coloquial", "juridico")


@dataclass
class Pregunta:
    id: str
    pregunta: str
    tipo: str
    estilo: str
    modificada_2026: bool
    esperados: dict[str, list[int]] = field(default_factory=dict)   # documento -> páginas (en el orden del CSV)
    notas: str = ""

    @property
    def pares(self) -> set[tuple[str, int]]:
        return {(d, p) for d, ps in self.esperados.items() for p in ps}

    @property
    def documento_modificatoria(self) -> str | None:
        return next(iter(self.esperados), None) if self.modificada_2026 else None


def _parsear_esperados(docs: str, paginas: str) -> dict[str, list[int]]:
    if not docs.strip() and not paginas.strip():
        return {}
    ds = [d.strip() for d in docs.split("|")]
    ps = [p.strip() for p in paginas.split("|")]
    if len(ds) != len(ps):
        raise ValueError(f"documento_esperado tiene {len(ds)} elementos y paginas_esperadas {len(ps)}; deben coincidir")
    salida: dict[str, list[int]] = {}
    for d, p in zip(ds, ps):
        salida[d] = [int(x) for x in p.split(";") if x.strip()]
    return salida


def cargar_preguntas(ruta: Path) -> list[Pregunta]:
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        if tuple(lector.fieldnames or ()) != COLUMNAS:
            raise ValueError(f"Las columnas de {ruta.name} deben ser exactamente: {', '.join(COLUMNAS)}")
        preguntas = []
        for fila in lector:
            preguntas.append(Pregunta(
                id=fila["id"].strip(), pregunta=fila["pregunta"].strip(), tipo=fila["tipo"].strip(), estilo=fila["estilo"].strip(),
                modificada_2026=fila["modificada_2026"].strip().lower() == "true",
                esperados=_parsear_esperados(fila["documento_esperado"], fila["paginas_esperadas"]), notas=fila["notas"].strip()))
    return preguntas


def cargar_evidencia(ruta: Path) -> dict:
    return yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}


def paginas_procesadas(dir_processed: Path, doc_id: str) -> set[int]:
    return {int(p.stem[1:]) for p in (dir_processed / doc_id).glob("p[0-9][0-9][0-9][0-9].json")}


def validar(preguntas: list[Pregunta], evidencia: dict, documentos: dict[str, dict], dir_processed: Path,
            paginas_pdf: dict[str, int], requisitos: dict) -> tuple[list[str], dict]:
    """Devuelve (errores, estadísticas). `documentos`: id -> config del documento (con 'rol')."""
    errores: list[str] = []
    ids = [q.id for q in preguntas]
    for repetido in sorted({i for i in ids if ids.count(i) > 1}):
        errores.append(f"id repetido: {repetido}")
    textos = [q.pregunta.lower() for q in preguntas]
    for t in sorted({t for t in textos if textos.count(t) > 1}):
        errores.append(f"pregunta repetida: {t[:60]}")
    modificatorias = [d for d, c in documentos.items() if c["rol"] == "modificatoria"]

    for q in preguntas:
        pref = "q" if q.tipo == "in_domain" else "o"
        if q.tipo not in TIPOS:
            errores.append(f"{q.id}: tipo inválido '{q.tipo}'")
        elif not re.fullmatch(rf"{pref}\d{{2}}", q.id):
            errores.append(f"{q.id}: el id debe ser {pref}NN según el tipo")
        if q.estilo not in ESTILOS:
            errores.append(f"{q.id}: estilo inválido '{q.estilo}'")
        if not q.pregunta or not q.pregunta.endswith("?"):
            errores.append(f"{q.id}: la pregunta debe estar escrita y terminar en '?'")
        if not q.notas:
            errores.append(f"{q.id}: falta explicar en 'notas' el criterio")

        if q.tipo == "out_of_domain":
            if q.esperados:
                errores.append(f"{q.id}: una pregunta fuera de dominio no lleva documento ni páginas esperadas")
            if q.modificada_2026:
                errores.append(f"{q.id}: una pregunta fuera de dominio no puede ser modificada_2026")
            for item in (evidencia.get(q.id) or {}).get("fuera_del_indice", []):
                if item["pagina"] in paginas_procesadas(dir_processed, item["documento"]):
                    errores.append(f"{q.id}: la p. {item['pagina']} de {item['documento']} debe estar FUERA del índice pero está procesada")
            continue

        # ── in_domain ──
        if not q.esperados:
            errores.append(f"{q.id}: falta documento y página esperados")
        for doc, paginas in q.esperados.items():
            if doc not in documentos:
                errores.append(f"{q.id}: documento desconocido '{doc}'")
                continue
            for pag in paginas:
                if not 1 <= pag <= paginas_pdf.get(doc, 0):
                    errores.append(f"{q.id}: la p. {pag} no existe en {doc} ({paginas_pdf.get(doc)} páginas)")
                elif pag not in paginas_procesadas(dir_processed, doc):
                    errores.append(f"{q.id}: la p. {pag} de {doc} NO está en el subconjunto procesado; la pregunta no sería respondible con el índice")
        if q.modificada_2026 and q.documento_modificatoria not in modificatorias:
            errores.append(f"{q.id}: en una pregunta modificada_2026 el primer documento debe ser la modificatoria {modificatorias}")
        if not q.modificada_2026 and any(d in modificatorias for d in q.esperados):
            errores.append(f"{q.id}: espera páginas de la modificatoria pero no está marcada modificada_2026")

        ev = evidencia.get(q.id)
        if not isinstance(ev, list) or not ev:
            errores.append(f"{q.id}: no tiene evidencia en evidencia.yaml")
            continue
        pares_ev = {(e["documento"], e["pagina"]) for e in ev}
        if pares_ev != q.pares:
            errores.append(f"{q.id}: las páginas del CSV {sorted(q.pares)} no coinciden con las de evidencia.yaml {sorted(pares_ev)}")
        for e in ev:
            if not e.get("ancla") or not e.get("dato"):
                errores.append(f"{q.id}: la evidencia de {e.get('documento')} p.{e.get('pagina')} necesita 'ancla' y 'dato'")

    en = [q for q in preguntas if q.tipo == "in_domain"]
    fuera = [q for q in preguntas if q.tipo == "out_of_domain"]
    stats = {"in_domain": len(en), "out_of_domain": len(fuera), "modificadas_2026": sum(q.modificada_2026 for q in en),
             "coloquiales_in_domain": sum(q.estilo == "coloquial" for q in en), "juridicas_in_domain": sum(q.estilo == "juridico" for q in en),
             "paginas_distintas": len({p for q in en for p in q.pares})}
    for clave, real in (("in_domain", stats["in_domain"]), ("out_of_domain", stats["out_of_domain"]),
                        ("modificadas_2026", stats["modificadas_2026"]), ("coloquiales", stats["coloquiales_in_domain"])):
        if real < requisitos[clave]:
            errores.append(f"faltan preguntas: '{clave}' tiene {real} y el mínimo es {requisitos[clave]}")
    return errores, stats
