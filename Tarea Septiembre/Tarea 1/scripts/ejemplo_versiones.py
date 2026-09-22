#!/usr/bin/env python3
"""ejemplo_versiones.py — muestra el manejo de versiones con DATOS REALES, sin llamar al LLM.

Para cada pregunta de versiones del set de evaluación enseña: qué recupera el índice, la advertencia de versión, los fragmentos del
DS 001-2026-EF que el motor FUERZA en el contexto y cómo queda ordenado el prompt. Escribe docs/ejemplo_versiones.md.
Uso (desde tarea1/):  python scripts/ejemplo_versiones.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluation.eval_set import cargar_preguntas  # noqa: E402
from rag_engine.config import cargar_config  # noqa: E402
from rag_engine.engine import MotorRAG  # noqa: E402
from rag_engine.retrieval.semantic import buscar  # noqa: E402


def corto(t: str, n: int = 260) -> str:
    return re.sub(r"\s+", " ", t)[:n] + ("…" if len(t) > n else "")


def main() -> int:
    cfg = cargar_config()
    motor = MotorRAG.desde_config(cfg)
    preguntas = [q for q in cargar_preguntas(cfg.ruta("eval_preguntas")) if q.modificada_2026]
    L = ["# Ejemplo de manejo de versiones (datos reales, sin llamar al LLM)", "",
         "Generado por `scripts/ejemplo_versiones.py`. Para cada pregunta que depende de un artículo modificado por el DS 001-2026-EF se muestra lo que "
         "hace el motor **antes** de llamar al modelo: recuperar, marcar el texto original como posiblemente desactualizado, **forzar** los fragmentos de "
         "la modificatoria y ordenar el contexto con la modificatoria primero.", ""]
    k = cfg.get("retrieval.top_k")
    resumen = []
    for q in preguntas:
        vector = motor.embedder.embed_query(q.pregunta)
        rec = buscar(motor.coleccion, motor.embedder, q.pregunta, k)
        forz, avisos, marcados = motor.versiones.procesar(vector, rec)
        ya_ds001 = [r for r in rec if r.documento == motor.doc_modificatoria]
        resumen.append((q.id, len(avisos), len(forz), len(ya_ds001)))
        L += [f"## {q.id} — {q.pregunta}", "", f"Esperado: {', '.join(f'`{d}` p. {ps}' for d, ps in q.esperados.items())}", "",
              f"**Recuperados (top-{k}):**", ""]
        L += [f"{i}. `{r.documento}` p. {r.pagina} · versión `{r.version}` · similitud {r.similitud:.3f} — {corto(r.texto, 130)}" for i, r in enumerate(rec, 1)]
        L += ["", f"**Artículos del Reglamento mencionados y modificados:** {marcados or 'ninguno'}", ""]
        if avisos:
            L += ["**Advertencias de versión que recibe la interfaz:**", ""] + [f"- {a}" for a in avisos] + [""]
        if forz:
            L += [f"**Fragmentos FORZADOS en el contexto ({len(forz)}):**", ""]
            L += [f"- {'DS 001-2026-EF (modificatoria)' if r.metadatos.get('origen') == 'version' else 'Reglamento ORIGINAL'} · `{r.documento}` p. {r.pagina} "
                  f"(similitud {r.similitud:.3f}): {corto(r.texto)}" for r in forz] + [""]
        else:
            L += ["No hizo falta forzar nada: el contexto recuperado ya trae lo necesario.", ""]
        L += ["---", ""]
    L += ["## Resumen", "", "| Pregunta | Advertencias | Fragmentos forzados | DS 001 ya recuperado |", "|---|---:|---:|---:|"] + \
         [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in resumen] + [""]
    ruta = cfg.ruta("docs") / "ejemplo_versiones.md"
    tmp = ruta.with_suffix(".md.tmp")
    tmp.write_text("\n".join(L), encoding="utf-8")
    os.replace(tmp, ruta)
    print(f"Escrito {ruta}")
    for a, b, c, d in resumen:
        print(f"  {a}: advertencias={b} forzados={c} ds001_ya_recuperado={d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
