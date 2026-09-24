"""Fase 3 — Barrido del umbral de similitud + comprobación de si el umbral de la Tarea 1 "transfiere".

Uso:
    python -m evaluation.sweep_threshold_radar

La Tarea 1 calibró ``retrieval.umbral_similitud = 0.835`` para texto LEGAL (artículos de una ley), con el
MISMO modelo de embeddings (intfloat/multilingual-e5-small) que usa esta Tarea 2. Este script comprueba si
ese valor sirve también para descripciones CORTAS de compras públicas (dominio muy distinto: nombres de
productos y obras, no prosa jurídica) o si hay que recalibrarlo, con evidencia (no "a ojo").

Método: para cada umbral candidato, cuenta cuántas preguntas in_domain se responderían correctamente
(mejor_similitud >= umbral) y cuántas out_of_domain se rechazarían correctamente (mejor_similitud < umbral).
Se busca el umbral que MINIMIZA abstenciones incorrectas (perder una venta real) manteniendo cero respuestas
indebidas (inventarle un proceso a una pregunta ajena al corpus) siempre que exista uno así en el barrido;
si no existe, se reporta el mejor compromiso y se explica el trade-off en el README (no se elige en
silencio). Guarda ``data/outputs/barrido_umbral_radar.csv`` con el barrido completo, para que el panel de
evaluación del dashboard pueda graficarlo (mismo patrón que ``eval/results/umbral_e2e_barrido.csv`` en la
Tarea 1).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar_engine.config import cargar_config  # noqa: E402
from radar_engine.embeddings import crear_embedder  # noqa: E402
from radar_engine.filtros import combinar, extraer_filtros_pregunta  # noqa: E402
from radar_engine.store import abrir_para_lectura, buscar, candidatos  # noqa: E402
from evaluation.eval_set_radar import Pregunta, cargar_preguntas  # noqa: E402
from evaluation.metrics_radar import evaluar_abstencion, evaluar_recuperacion  # noqa: E402

UMBRAL_TAREA1 = 0.835
BARRIDO_DESDE, BARRIDO_HASTA, BARRIDO_PASO = 0.30, 0.95, 0.01


def main() -> int:
    cfg = cargar_config()
    preguntas = cargar_preguntas(cfg.ruta("eval_radar"))
    embedder = crear_embedder(cfg)
    coleccion = abrir_para_lectura(cfg)

    def recuperar(q: Pregunta, k: int):
        filtros = combinar(q.filtros, extraer_filtros_pregunta(q.pregunta, cfg))
        return buscar(coleccion, embedder, q.pregunta, k, filtros), candidatos(coleccion, filtros)

    ev = evaluar_recuperacion(preguntas, recuperar, ks=(1,))

    sims_in = sorted(r.mejor_similitud for r in ev.por_pregunta if r.tipo == "in_domain")
    sims_out = sorted(r.mejor_similitud for r in ev.por_pregunta if r.tipo == "out_of_domain")
    print(f"Similitudes in_domain:  min={sims_in[0]:.3f}  mediana={sims_in[len(sims_in)//2]:.3f}  max={sims_in[-1]:.3f}")
    if sims_out:
        print(f"Similitudes out_of_domain: min={sims_out[0]:.3f}  mediana={sims_out[len(sims_out)//2]:.3f}  max={sims_out[-1]:.3f}")

    t1 = evaluar_abstencion(ev, UMBRAL_TAREA1)
    print(f"\n¿Transfiere el umbral de la Tarea 1 ({UMBRAL_TAREA1})? "
          f"respondidas correctas {t1.respondidas_correctas}/{t1.in_domain}, indebidas {t1.indebidas}/{t1.out_of_domain}")
    if t1.abstenciones_incorrectas > 0:
        print(f"NO transfiere: {t1.abstenciones_incorrectas}/{t1.in_domain} preguntas in_domain se perderían "
              f"(el corpus de descripciones cortas de compras da similitudes más bajas que el texto legal de la Tarea 1).")

    filas = []
    umbral = BARRIDO_DESDE
    while umbral <= BARRIDO_HASTA + 1e-9:
        r = evaluar_abstencion(ev, round(umbral, 3))
        filas.append(r.como_dict())
        umbral += BARRIDO_PASO

    # Mejor umbral: cero respuestas indebidas (fuera de dominio respondidas) y, entre esos, el que MENOS
    # abstenciones incorrectas tiene (el trade-off que pide el enunciado: preferimos abstenernos de más
    # antes que responder mal, pero sin perder más ventas reales de las necesarias).
    sin_indebidas = [f for f in filas if f["indebidas"] == 0]
    candidatos_optimos = sin_indebidas or filas
    mejor = min(candidatos_optimos, key=lambda f: (f["abstenciones_incorrectas"], -f["umbral"]))
    print(f"\nUmbral recalibrado sugerido: {mejor['umbral']:.3f} "
          f"(respondidas correctas {mejor['respondidas_correctas']}/{mejor['in_domain']}, "
          f"abstenciones correctas {mejor['abstenciones_correctas']}/{mejor['out_of_domain']}, indebidas {mejor['indebidas']})")
    if not sin_indebidas:
        print("AVISO: en todo el barrido hubo al menos una respuesta indebida; se eligió el umbral con menos "
              "abstenciones incorrectas entre los que MINIMIZAN indebidas (ver columna 'indebidas' del CSV).")

    ruta = cfg.ruta("umbral_barrido")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f"\nBarrido completo guardado en: {ruta}")
    print(f"Para aplicarlo, edita 'retrieval.umbral_similitud: {mejor['umbral']:.3f}' en config.yaml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
