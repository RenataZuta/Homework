"""sweep_threshold_e2e.py — calibra el umbral de similitud con los resultados REALES de punta a punta (con LLM), sin hacer más llamadas.

Parte de ``eval/results/e2e_umbral_0.000.csv`` (evaluación con umbral 0: TODAS las preguntas pasan por el LLM; ver eval_end_to_end.py). Para un umbral t,
una pregunta queda «respondida» si su mejor similitud es >= t Y el LLM la respondió; en cualquier otro caso hay abstención (por la compuerta o por el LLM).
Así se mide lo que de verdad ocurre con las dos defensas juntas, no solo la similitud.
Criterio (explícito, distinto del barrido solo-recuperación de sweep_threshold.py):
  1. Se calcula F-β (β = eval.barrido_umbral.beta) igual que en el barrido de recuperación.
  2. Como el LLM ya rechaza casi todo lo ajeno, F-β queda PLANO en todo el tramo de umbrales bajos: la compuerta no mejora la calidad ahí, solo AHORRA
     llamadas (y cuota). Por eso se toma el umbral MÁS ALTO de esa meseta (el que más llamadas ahorra sin perder ninguna respuesta buena) MENOS un margen
     de seguridad (``--margen``, por defecto 0,005): el centro de la meseta sería absurdo (0,4) y el borde exacto es frágil.
LIMITACIÓN: se calibra con el mismo set de 27 preguntas; el margen es la única protección frente a preguntas nuevas.
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.sweep_threshold_e2e [--margen 0.005] [--aplicar]
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

from evaluation.informes import aviso_set, escribir_atomico, escribir_csv, tabla_markdown
from evaluation.sweep_threshold import Punto, barrido
from rag_engine.config import cargar_config

ANTERIOR = 0.865                     # umbral que había elegido el barrido solo con recuperación (Fase 5, primera versión)


def puntos_desde_csv(ruta: Path) -> list[Punto]:
    """Un Punto por pregunta. Si el LLM NO respondió, la similitud se pone en -1: nunca cuenta como respondida, cualquiera que sea el umbral."""
    if not ruta.is_file():
        raise FileNotFoundError(f"Falta {ruta.name}. Ejecuta antes: PYTHONPATH=src python -m evaluation.eval_end_to_end --umbral 0")
    filas = list(csv.DictReader(ruta.open(encoding="utf-8")))
    if any(f["desenlace"] in ("abstuvo_umbral", "no_ejecutada", "error") for f in filas):
        raise ValueError(f"{ruta.name} no sirve para calibrar: hay preguntas que no llegaron al LLM (¿se ejecutó con umbral > 0 o se agotó la cuota?). Repite con --umbral 0.")
    puntos = []
    for f in filas:
        respondida = f["desenlace"] == "respondida"
        puntos.append(Punto(f["tipo"], float(f["mejor_similitud"]) if respondida else -1.0, f["cita_correcta"] == "True"))
    return puntos


def elegir_conservador(filas: list[dict], margen: float, paso: float) -> tuple[float, float, float]:
    """(umbral elegido, tope de la meseta, F-β máximo): el umbral más alto con F-β máximo, menos ``margen``, redondeado al paso del barrido."""
    maximo = max(f["fbeta"] for f in filas)
    tope = max(f["umbral"] for f in filas if abs(f["fbeta"] - maximo) < 1e-9)
    elegido = max(0.0, round(round((tope - margen) / paso) * paso, 6))
    return elegido, tope, maximo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--margen", type=float, default=0.005, help="margen de seguridad bajo el tope de la meseta")
    ap.add_argument("--aplicar", action="store_true", help="escribe el umbral elegido en config.yaml")
    args = ap.parse_args(argv)
    cfg = cargar_config(cargar_env=False)
    salida = cfg.ruta("eval_results")
    puntos = puntos_desde_csv(salida / "e2e_umbral_0.000.csv")
    b = cfg.get("eval.barrido_umbral")
    filas = barrido(puntos, b["desde"], b["hasta"], b["paso"], b["beta"])
    elegido, tope, maximo = elegir_conservador(filas, args.margen, b["paso"])
    f = next(x for x in filas if abs(x["umbral"] - elegido) < 1e-9)
    ant = next(x for x in filas if abs(x["umbral"] - ANTERIOR) < 1e-9)
    escribir_csv(salida / "umbral_e2e_barrido.csv", filas)

    sims = sorted(p.similitud for p in puntos if p.similitud >= 0)
    cerca = [x for x in filas if abs(x["umbral"] - elegido) <= 0.03 and round((x["umbral"] - filas[0]["umbral"]) / b["paso"]) % 2 == 0]
    cols = [("umbral", "Umbral", ".3f"), ("correctas", "Correctas", ""), ("erroneas", "Erróneas", ""), ("abstenciones_incorrectas", "Abst. incorrectas", ""),
            ("abstenciones_correctas", "Abst. correctas", ""), ("indebidas", "Indebidas", ""), ("precision", "Precisión", ".3f"), ("cobertura", "Cobertura", ".3f"), ("fbeta", "F-β", ".3f")]
    md = ["# Calibración del umbral con el LLM real (punta a punta)", "", aviso_set(cfg) +
          f"Modelo `{cfg.get('llm.provider')}/{cfg.get('llm.proveedores.' + cfg.get('llm.provider') + '.modelo')}`. "
          "Se parte de la evaluación con umbral 0 (las 27 preguntas pasan por el LLM); para cada umbral, una pregunta cuenta como respondida solo si su mejor similitud "
          "lo alcanza **y** el LLM la respondió.", "",
          f"## Umbral elegido: **{elegido:.3f}**", "",
          f"F-β (β = {b['beta']}) máximo = {maximo:.3f}, plano hasta {tope:.3f}: mientras el umbral no pase de {tope:.3f} no se pierde ninguna respuesta buena, y el LLM rechaza por sí solo "
          f"las preguntas ajenas que la compuerta deja pasar. Se toma el tope menos un margen de {args.margen} → **{elegido:.3f}**. En ese umbral: {f['correctas']} respuestas correctas, "
          f"{f['erroneas']} erróneas, {f['abstenciones_incorrectas']} abstenciones incorrectas, {f['abstenciones_correctas']} abstenciones correctas, {f['indebidas']} respuestas indebidas "
          f"(precisión {f['precision']}, cobertura {f['cobertura']}).", "",
          f"## Por qué el umbral anterior ({ANTERIOR}) era peor", "",
          f"El barrido solo con recuperación (`umbral_resumen.md`) eligió {ANTERIOR} porque solo veía la similitud. Con el LLM real, ese umbral da {ant['correctas']} respuestas correctas "
          f"(frente a {f['correctas']} en {elegido:.3f}), {ant['abstenciones_incorrectas']} abstenciones incorrectas (frente a {f['abstenciones_incorrectas']}) y {ant['indebidas']} respuestas indebidas "
          f"(frente a {f['indebidas']}): descarta respuestas buenas y no evita ninguna mala, porque el LLM ya rechaza por sí solo {sum(1 for p in puntos if p.tipo == 'out_of_domain' and p.similitud < 0)} de las "
          f"{sum(1 for p in puntos if p.tipo == 'out_of_domain')} preguntas ajenas y las que responde superan cualquier umbral razonable. "
          "La compuerta se conserva por **costo y latencia** (cada abstención por umbral es una llamada menos) y como defensa si el LLM fallara, no como filtro de calidad.", "",
          "## Alrededor del umbral elegido", "", tabla_markdown(cerca, cols), "",
          f"Similitudes de las preguntas que el LLM respondió: de {sims[0]:.3f} a {sims[-1]:.3f}. La tabla completa (0 a 1) está en `umbral_e2e_barrido.csv`.", "",
          "**Limitación:** calibrado con el mismo set de 27 preguntas y un solo modelo; con preguntas nuevas la similitud más baja de una buena respuesta puede ser menor que la de q01 (0,843). "
          "Vuelve a ejecutar este script si cambian el modelo, el troceado o el prompt.", ""]
    escribir_atomico(salida / "umbral_e2e_resumen.md", "\n".join(md))
    print(f"Umbral elegido: {elegido:.3f} (meseta de F-β={maximo:.3f} hasta {tope:.3f}; margen {args.margen}); correctas={f['correctas']} indebidas={f['indebidas']} "
          f"abst_incorrectas={f['abstenciones_incorrectas']}")
    if args.aplicar:
        p = cfg.archivo
        s = p.read_text(encoding="utf-8")
        s, n1 = re.subn(r"(?m)^(  umbral_similitud: )[0-9.]+(.*)$", rf"\g<1>{elegido:.3f}   # CALIBRADO con el LLM real (Fase 5, provisional hasta validar el set): ver eval/results/umbral_e2e_resumen.md", s, count=1)
        assert n1 == 1 and len(s) > 1000
        tmp = p.with_suffix(".yaml.tmp"); tmp.write_text(s, encoding="utf-8"); os.replace(tmp, p)
        print("config.yaml actualizado (retrieval.umbral_similitud).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
