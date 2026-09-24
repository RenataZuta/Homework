"""Fase 3/4 — Evaluación de recuperación (sin LLM, costo USD 0).

Uso:
    python -m evaluation.run_eval_radar          (desde Tarea 2/, con 'src' en PYTHONPATH: ver pytest.ini o activa el venv)

Calcula Recall@1/3/5 y la abstención (correcta/incorrecta) con el umbral ACTUAL de config.yaml, usando
``eval/preguntas_radar.csv``. No llama al LLM: mide solo troceado+embeddings+índice+filtros (radar_engine.store),
que es la etapa que de verdad decide qué llega al modelo. Guarda el resultado en
``data/outputs/eval_radar_resultados.json`` (lo lee el panel "Calidad" del dashboard, Fase 4).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar_engine.config import cargar_config  # noqa: E402
from radar_engine.embeddings import crear_embedder  # noqa: E402
from radar_engine.filtros import Filtros, combinar, extraer_filtros_pregunta  # noqa: E402
from radar_engine.store import abrir_para_lectura, buscar, candidatos  # noqa: E402
from evaluation.eval_set_radar import Pregunta, cargar_preguntas  # noqa: E402
from evaluation.metrics_radar import evaluar_abstencion, evaluar_recuperacion  # noqa: E402


def main() -> int:
    cfg = cargar_config()
    preguntas = cargar_preguntas(cfg.ruta("eval_radar"))
    embedder = crear_embedder(cfg)
    coleccion = abrir_para_lectura(cfg)

    def recuperar(q: Pregunta, k: int):
        filtros = combinar(q.filtros, extraer_filtros_pregunta(q.pregunta, cfg))
        return buscar(coleccion, embedder, q.pregunta, k, filtros), candidatos(coleccion, filtros)

    ev = evaluar_recuperacion(preguntas, recuperar, ks=tuple(cfg.get("eval.ks")))
    umbral = cfg.get("retrieval.umbral_similitud")
    ab = evaluar_abstencion(ev, umbral)

    resumen = ev.resumen()
    print(f"Preguntas: {len(preguntas)} ({ab.in_domain} in_domain, {ab.out_of_domain} out_of_domain)")
    for k in ev.ks:
        print(f"  Recall@{k}: {resumen[f'recall@{k}']:.3f}")
    print(f"  MRR: {resumen['mrr']:.3f}")
    print(f"  Umbral actual ({umbral:.3f}): respondidas correctas {ab.respondidas_correctas}/{ab.in_domain} | "
          f"abstenciones incorrectas {ab.abstenciones_incorrectas}/{ab.in_domain} | "
          f"abstenciones correctas {ab.abstenciones_correctas}/{ab.out_of_domain} | indebidas {ab.indebidas}/{ab.out_of_domain}")
    fallos = ev.fallos(max(ev.ks))
    if fallos:
        print(f"\nPreguntas in_domain sin acierto en Recall@{max(ev.ks)}: " + ", ".join(f.id for f in fallos))

    salida = {"generado_con_umbral": umbral, "ks": list(ev.ks), "resumen": resumen, "abstencion": ab.como_dict(),
              "por_pregunta": [{"id": r.id, "tipo": r.tipo, "estilo": r.estilo, "rango_acierto": r.rango_acierto,
                                "mejor_similitud": r.mejor_similitud, "n_candidatos": r.n_candidatos, "recuperados": r.recuperados}
                               for r in ev.por_pregunta]}
    ruta = cfg.ruta("eval_radar_resultados")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
