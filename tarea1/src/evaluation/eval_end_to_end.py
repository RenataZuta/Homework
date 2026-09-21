"""eval_end_to_end.py — pasa el set de evaluación por el motor COMPLETO (con LLM) y mide qué ocurre de verdad.

A diferencia de run_eval (que no llama al LLM), esto cuesta unos centavos: el set entero son ~27 llamadas. Sirve para saber si el modelo
es una segunda línea de defensa útil: ¿se abstiene el LLM (contexto_suficiente=false) en las preguntas fuera de dominio que pasaron
la compuerta? ¿Cita las páginas correctas en las del dominio?
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.eval_end_to_end [--umbral 0.0]
Escribe eval/results/e2e_umbral_<u>.csv y .md; los costos reales quedan además en logs/llm_calls.jsonl.
"""
from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass

from evaluation.eval_set import Pregunta, cargar_preguntas
from evaluation.informes import aviso_set, escribir_atomico, escribir_csv, tabla_markdown
from rag_engine.config import Config, cargar_config


@dataclass
class FilaE2E:
    id: str
    tipo: str
    estilo: str
    modificada: bool
    desenlace: str            # respondida | abstuvo_umbral | abstuvo_llm | error
    cita_correcta: bool | None
    mejor_similitud: float
    costo_usd: float
    tokens_in: int
    tokens_out: int
    latencia_ms: float
    advertencias: int
    respuesta: str


def clasificar(r) -> str:
    if r.error:
        return "error"
    if r.abstuvo:
        return "abstuvo_umbral" if r.motivo_abstencion == "umbral" else "abstuvo_llm"
    return "respondida"


def ejecutar(motor, preguntas: list[Pregunta]) -> list[FilaE2E]:
    filas = []
    for q in preguntas:
        r = motor.responder(q.pregunta)
        citadas = {(f.documento, f.pagina) for f in r.fuentes if f.citada}
        cita_ok = (bool(citadas & q.pares) if r.respuesta and not r.abstuvo and not r.error else False) if q.tipo == "in_domain" else None
        filas.append(FilaE2E(q.id, q.tipo, q.estilo, q.modificada_2026, clasificar(r), cita_ok, round(r.mejor_similitud, 4), r.costo_usd,
                             r.tokens_entrada, r.tokens_salida, r.latencia_ms, len(r.advertencias_version), (r.respuesta or r.error or "")))
    return filas


def resumir(filas: list[FilaE2E]) -> dict:
    en = [f for f in filas if f.tipo == "in_domain"]
    fuera = [f for f in filas if f.tipo == "out_of_domain"]
    return {
        "in_domain": len(en), "in_domain_respondidas": sum(f.desenlace == "respondida" for f in en),
        "in_domain_con_cita_correcta": sum(bool(f.cita_correcta) for f in en),
        "in_domain_abstenciones_incorrectas": sum(f.desenlace in ("abstuvo_umbral", "abstuvo_llm") for f in en),
        "in_domain_errores": sum(f.desenlace == "error" for f in en),
        "fuera_de_dominio": len(fuera), "fuera_abstenciones_por_umbral": sum(f.desenlace == "abstuvo_umbral" for f in fuera),
        "fuera_abstenciones_por_llm": sum(f.desenlace == "abstuvo_llm" for f in fuera),
        "fuera_respuestas_indebidas": sum(f.desenlace == "respondida" for f in fuera), "fuera_errores": sum(f.desenlace == "error" for f in fuera),
        "llamadas_al_llm": sum(f.tokens_in > 0 for f in filas), "costo_total_usd": round(sum(f.costo_usd for f in filas), 6),
        "costo_medio_por_llamada_usd": round(sum(f.costo_usd for f in filas) / max(1, sum(f.tokens_in > 0 for f in filas)), 6),
    }


def con_umbral(cfg: Config, umbral: float) -> Config:
    datos = copy.deepcopy(cfg.datos)
    datos["retrieval"]["umbral_similitud"] = umbral
    return Config(datos=datos, archivo=cfg.archivo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--umbral", type=float, default=None, help="umbral a usar (por defecto, el de config.yaml)")
    args = ap.parse_args(argv)
    from rag_engine.engine import MotorRAG

    cfg = cargar_config()
    umbral = cfg.get("retrieval.umbral_similitud") if args.umbral is None else args.umbral
    motor = MotorRAG.desde_config(con_umbral(cfg, umbral))
    preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
    filas = ejecutar(motor, preguntas)
    s = resumir(filas)
    salida = cfg.ruta("eval_results")
    etiqueta = f"{umbral:.3f}"
    escribir_csv(salida / f"e2e_umbral_{etiqueta}.csv", [{**f.__dict__, "respuesta": " ".join(f.respuesta.split())[:600]} for f in filas])
    cols = [("id", "Id", ""), ("tipo", "Tipo", ""), ("desenlace", "Desenlace", ""), ("cita_correcta", "Cita correcta", ""), ("mejor_similitud", "Mejor sim.", ".3f"),
            ("costo_usd", "Costo USD", ".5f"), ("latencia_ms", "Latencia ms", ".0f"), ("advertencias", "Avisos versión", "")]
    md = [f"# Evaluación de punta a punta (con LLM), umbral {etiqueta}", "", aviso_set(cfg) +
          f"Modelo `{cfg.get('llm.modelo')}`. Cada pregunta pasa por el motor completo. Resumen:", "",
          f"- **In_domain ({s['in_domain']}):** {s['in_domain_respondidas']} respondidas, de ellas **{s['in_domain_con_cita_correcta']} citando una página esperada**; "
          f"{s['in_domain_abstenciones_incorrectas']} abstenciones incorrectas; {s['in_domain_errores']} errores.",
          f"- **Fuera de dominio ({s['fuera_de_dominio']}):** {s['fuera_abstenciones_por_umbral']} abstenciones por umbral, **{s['fuera_abstenciones_por_llm']} por el LLM**, "
          f"{s['fuera_respuestas_indebidas']} respuestas indebidas, {s['fuera_errores']} errores.",
          f"- **Costo real:** {s['llamadas_al_llm']} llamadas al LLM, USD {s['costo_total_usd']:.4f} en total (USD {s['costo_medio_por_llamada_usd']:.5f} por llamada).", "",
          tabla_markdown([f.__dict__ for f in filas], cols), ""]
    escribir_atomico(salida / f"e2e_umbral_{etiqueta}.md", "\n".join(md))
    print(f"Escrito {salida / f'e2e_umbral_{etiqueta}.md'}")
    for k, v in s.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
