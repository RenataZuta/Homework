"""run_eval.py — evalúa la RECUPERACIÓN y la COMPUERTA DEL UMBRAL sin llamar al LLM (cuesta USD 0 y corre en cada push).

Mide dos cosas distintas, en dos etapas distintas del pipeline:
  * Recall@1/3/5: ¿el fragmento correcto (documento y página esperados) está entre los k más similares? Evalúa la RECUPERACIÓN
    (troceado + embeddings + índice). En las preguntas de versiones se mide además si aparece el fragmento de la MODIFICATORIA.
  * Tasa de abstención: con el umbral de config.yaml, ¿se abstiene el sistema cuando debe (fuera de dominio) y responde cuando puede
    (dentro del dominio)? Evalúa la COMPUERTA del umbral.
Ninguna evalúa la GENERACIÓN (la calidad del texto que produce el LLM): eso requiere llamadas al modelo (evaluation/eval_end_to_end.py).

Salida: eval/results/run_eval.json (resumen + detalle por pregunta), run_eval_resumen.csv, run_eval_preguntas.csv y run_eval.md.
Código de salida: 0 si Recall@3 >= eval.min_recall_at_3; si no, eval.codigo_salida_fallo (lo usa el CI para fallar el build).
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.run_eval [--min-recall-3 0.8]
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Callable

from evaluation.eval_set import Pregunta, cargar_preguntas
from evaluation.informes import aviso_set, escribir_atomico, escribir_csv, tabla_markdown
from evaluation.metrics import evaluar_recuperacion
from rag_engine.config import cargar_config


def tasa(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def evaluar(preguntas: list[Pregunta], recuperar: Callable, ks: tuple[int, ...], umbral: float) -> dict:
    """Recuperación + compuerta del umbral sobre el set completo. `recuperar(texto, k)` devuelve los k fragmentos más similares."""
    ev = evaluar_recuperacion(preguntas, recuperar, ks)
    en = [r for r in ev.por_pregunta if r.tipo == "in_domain"]
    fuera = [r for r in ev.por_pregunta if r.tipo == "out_of_domain"]
    se_abstiene = lambda r: r.mejor_similitud < umbral                       # misma regla que el motor: abstiene si es MENOR que el umbral
    abst_incorrectas = sum(se_abstiene(r) for r in en)
    abst_correctas = sum(se_abstiene(r) for r in fuera)
    return {
        "recuperacion": ev.resumen(),
        "abstencion": {
            "umbral": umbral,
            "in_domain": len(en), "in_domain_respondidas": len(en) - abst_incorrectas, "abstenciones_incorrectas": abst_incorrectas,
            "tasa_abstencion_incorrecta": tasa(abst_incorrectas, len(en)),
            "out_of_domain": len(fuera), "abstenciones_correctas": abst_correctas, "respuestas_indebidas": len(fuera) - abst_correctas,
            "tasa_abstencion_correcta": tasa(abst_correctas, len(fuera)),
            "tasa_abstencion_global": tasa(abst_incorrectas + abst_correctas, len(ev.por_pregunta)),
        },
        "por_pregunta": [{"id": r.id, "tipo": r.tipo, "estilo": r.estilo, "modificada_2026": r.modificada_2026, "rango_acierto": r.rango_acierto,
                          "rango_modificatoria": r.rango_modificatoria if r.modificada_2026 else None, "mejor_similitud": round(r.mejor_similitud, 4),
                          "se_abstiene": se_abstiene(r), "primero": f"{r.recuperados[0][0]} p.{r.recuperados[0][1]}" if r.recuperados else ""}
                         for r in ev.por_pregunta],
    }


def codigo_de_salida(resultado: dict, minimo: float, codigo_fallo: int) -> tuple[int, str]:
    """(código, mensaje). Falla si Recall@3 es menor que el mínimo; el mensaje dice por cuánto."""
    r3 = resultado["recuperacion"]["recall@3"]
    if r3 is None or r3 < minimo:
        return codigo_fallo, f"FALLA: Recall@3 = {'—' if r3 is None else format(r3, '.3f')} es menor que el mínimo exigido {minimo}"
    return 0, f"OK: Recall@3 = {r3:.3f} >= mínimo {minimo}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--min-recall-3", type=float, default=None, help="mínimo de Recall@3 (por defecto, eval.min_recall_at_3)")
    args = ap.parse_args(argv)
    from rag_engine.embeddings.factory import crear_embedder
    from rag_engine.retrieval.indice import abrir_para_lectura
    from rag_engine.retrieval.semantic import buscar

    cfg = cargar_config()
    preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
    emb, col = crear_embedder(cfg), abrir_para_lectura(cfg)
    ks = tuple(cfg.get("eval.ks"))
    r = evaluar(preguntas, lambda t, k: buscar(col, emb, t, k), ks, cfg.get("retrieval.umbral_similitud"))
    r["configuracion"] = {"modelo": emb.name, "troceado": cfg.get("chunking.activa"), "modo": cfg.get("retrieval.modo"), "top_k": cfg.get("retrieval.top_k"),
                          "set_validado": cfg.get("eval.set_validado"), "fragmentos_en_indice": col.count()}
    minimo = cfg.get("eval.min_recall_at_3") if args.min_recall_3 is None else args.min_recall_3
    codigo, mensaje = codigo_de_salida(r, minimo, cfg.get("eval.codigo_salida_fallo"))
    r["veredicto"] = {"minimo_recall_3": minimo, "codigo_de_salida": codigo, "mensaje": mensaje}

    salida = cfg.ruta("eval_results")
    escribir_atomico(salida / "run_eval.json", json.dumps(r, ensure_ascii=False, indent=1) + "\n")
    rec, ab = r["recuperacion"], r["abstencion"]
    escribir_csv(salida / "run_eval_resumen.csv", [{"metrica": k, "valor": v} for k, v in {**rec, **{f"abstencion_{k}": v for k, v in ab.items()}}.items()])
    escribir_csv(salida / "run_eval_preguntas.csv", r["por_pregunta"])
    f = lambda v: "—" if v is None else f"{v:.3f}"
    md = ["# Evaluación sin LLM: recuperación y compuerta del umbral", "", aviso_set(cfg) +
          f"Modelo `{emb.name}` · troceado `{cfg.get('chunking.activa')}` · {col.count()} fragmentos · umbral {ab['umbral']}.", "",
          "## Recuperación (Recall@k)", "",
          tabla_markdown([{"k": k, "todas": rec[f"recall@{k}"], "coloquiales": rec[f"recall@{k}_coloquial"], "juridicas": rec[f"recall@{k}_juridico"],
                           "modificatoria": rec[f"recall@{k}_modificatoria"]} for k in ks],
                         [("k", "k", ""), ("todas", "Todas", ".3f"), ("coloquiales", "Coloquiales", ".3f"), ("juridicas", "Jurídicas", ".3f"), ("modificatoria", "Versiones: trae el DS 001", ".3f")]), "",
          f"MRR = {rec['mrr']:.3f}. «Versiones: trae el DS 001» exige el fragmento de la modificatoria entre los k primeros; traer solo el texto original desactualizado no cuenta.", "",
          "## Compuerta del umbral", "",
          f"- **Dentro del dominio ({ab['in_domain']}):** {ab['in_domain_respondidas']} pasan la compuerta; **{ab['abstenciones_incorrectas']} abstenciones incorrectas** (tasa {f(ab['tasa_abstencion_incorrecta'])}).",
          f"- **Fuera de dominio ({ab['out_of_domain']}):** **{ab['abstenciones_correctas']} abstenciones correctas** (tasa {f(ab['tasa_abstencion_correcta'])}); {ab['respuestas_indebidas']} pasan la compuerta y dependerían del LLM.", "",
          f"**Veredicto:** {mensaje}", ""]
    escribir_atomico(salida / "run_eval.md", "\n".join(md))
    print(mensaje)
    print(f"Recall@1/3/5 = {rec['recall@1']:.3f} / {rec['recall@3']:.3f} / {rec['recall@5']:.3f} · abstenciones correctas {ab['abstenciones_correctas']}/{ab['out_of_domain']}, "
          f"incorrectas {ab['abstenciones_incorrectas']}/{ab['in_domain']}")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
