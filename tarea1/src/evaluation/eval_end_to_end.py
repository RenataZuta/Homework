"""eval_end_to_end.py — pasa el set de evaluación por el motor COMPLETO (con LLM) y mide qué ocurre de verdad.

A diferencia de run_eval (que no llama al LLM), esto usa el proveedor de generación configurado (llm.provider; hoy la capa gratuita de Gemini,
costo real 0): el set entero son ~27 llamadas, espaciadas según llm.limites.rpm. Sirve para saber si el modelo es una segunda línea de defensa
útil: ¿se abstiene el LLM (contexto_suficiente=false) en las preguntas fuera de dominio que pasaron la compuerta? ¿Cita las páginas correctas
en las del dominio?
CACHÉ (eval.cache_llm): las respuestas se guardan por hash de (proveedor, modelo, prompts, esquema). Repetir la evaluación no repite llamadas ni
gasta cuota; si algo cambia (prompt, umbral que trae otros fragmentos, modelo) esa pregunta se llama de nuevo. Si la cuota se agota a mitad
de camino, las respuestas ya obtenidas quedan en la caché y basta volver a ejecutar para continuar. `--sin-cache` fuerza llamadas reales.
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.eval_end_to_end [--umbral 0.0] [--sin-cache]
Escribe eval/results/e2e_umbral_<u>.csv y .md; las llamadas reales quedan además en logs/llm_calls.jsonl (las de la caché no).
"""
from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass

from evaluation.eval_set import Pregunta, cargar_preguntas
from evaluation.informes import aviso_set, escribir_atomico, escribir_csv, tabla_markdown
from rag_engine.config import Config, cargar_config

PARAR_EN = ("cuota_agotada", "autenticacion")        # seguir preguntando no serviría de nada: se corta y se informa


@dataclass
class FilaE2E:
    id: str
    tipo: str
    estilo: str
    modificada: bool
    desenlace: str            # respondida | abstuvo_umbral | abstuvo_llm | error | no_ejecutada
    cita_correcta: bool | None
    mejor_similitud: float
    costo_usd_real: float
    costo_usd_referencia: float
    tokens_in: int
    tokens_out: int
    latencia_ms: float
    advertencias: int
    desde_cache: bool
    error_tipo: str
    respuesta: str


def clasificar(r) -> str:
    if r.error:
        return "error"
    if r.abstuvo:
        return "abstuvo_umbral" if r.motivo_abstencion == "umbral" else "abstuvo_llm"
    return "respondida"


def ejecutar(motor, preguntas: list[Pregunta], parar_en: tuple[str, ...] = PARAR_EN) -> list[FilaE2E]:
    filas: list[FilaE2E] = []
    corte: str | None = None
    for q in preguntas:
        if corte:
            filas.append(FilaE2E(q.id, q.tipo, q.estilo, q.modificada_2026, "no_ejecutada", None, 0.0, 0.0, 0.0, 0, 0, 0.0, 0, False, corte,
                                 f"No se ejecutó: la evaluación se detuvo por «{corte}»."))
            continue
        r = motor.responder(q.pregunta)
        citadas = {(f.documento, f.pagina) for f in r.fuentes if f.citada}
        cita_ok = (bool(citadas & q.pares) if r.respuesta and not r.abstuvo and not r.error else False) if q.tipo == "in_domain" else None
        filas.append(FilaE2E(q.id, q.tipo, q.estilo, q.modificada_2026, clasificar(r), cita_ok, round(r.mejor_similitud, 4), r.costo_usd_real, r.costo_usd_referencia,
                             r.tokens_entrada, r.tokens_salida, r.latencia_ms, len(r.advertencias_version), r.desde_cache, r.error_tipo or "",
                             (r.respuesta or r.error or "")))
        if r.error_tipo in parar_en:
            corte = r.error_tipo
    return filas


def resumir(filas: list[FilaE2E]) -> dict:
    en = [f for f in filas if f.tipo == "in_domain"]
    fuera = [f for f in filas if f.tipo == "out_of_domain"]
    con_llm = [f for f in filas if f.tokens_in > 0]
    reales = [f for f in con_llm if not f.desde_cache]
    return {
        "in_domain": len(en), "in_domain_respondidas": sum(f.desenlace == "respondida" for f in en),
        "in_domain_con_cita_correcta": sum(bool(f.cita_correcta) for f in en),
        "in_domain_abstenciones_incorrectas": sum(f.desenlace in ("abstuvo_umbral", "abstuvo_llm") for f in en),
        "in_domain_errores": sum(f.desenlace == "error" for f in en),
        "fuera_de_dominio": len(fuera), "fuera_abstenciones_por_umbral": sum(f.desenlace == "abstuvo_umbral" for f in fuera),
        "fuera_abstenciones_por_llm": sum(f.desenlace == "abstuvo_llm" for f in fuera),
        "fuera_respuestas_indebidas": sum(f.desenlace == "respondida" for f in fuera), "fuera_errores": sum(f.desenlace == "error" for f in fuera),
        "no_ejecutadas": sum(f.desenlace == "no_ejecutada" for f in filas),
        "llamadas_al_llm": len(con_llm), "llamadas_reales": len(reales), "respuestas_de_cache": len(con_llm) - len(reales),
        "costo_real_total_usd": round(sum(f.costo_usd_real for f in filas), 6),
        "costo_referencia_total_usd": round(sum(f.costo_usd_referencia for f in filas), 6),
        "costo_referencia_medio_por_llamada_usd": round(sum(f.costo_usd_referencia for f in con_llm) / max(1, len(con_llm)), 6),
        "tokens_in_total": sum(f.tokens_in for f in filas), "tokens_out_total": sum(f.tokens_out for f in filas),
    }


def con_umbral(cfg: Config, umbral: float) -> Config:
    datos = copy.deepcopy(cfg.datos)
    datos["retrieval"]["umbral_similitud"] = umbral
    return Config(datos=datos, archivo=cfg.archivo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--umbral", type=float, default=None, help="umbral a usar (por defecto, el de config.yaml)")
    ap.add_argument("--sin-cache", action="store_true", help="ignora la caché de respuestas y hace llamadas reales")
    args = ap.parse_args(argv)
    from rag_engine.engine import MotorRAG
    from rag_engine.llm.cache import ClienteConCache
    from rag_engine.llm.factory import ajustes_llm, crear_cliente_llm

    cfg = cargar_config()
    umbral = cfg.get("retrieval.umbral_similitud") if args.umbral is None else args.umbral
    cfg_u = con_umbral(cfg, umbral)
    motor = MotorRAG.desde_config(cfg_u)
    usa_cache = bool(cfg.get("eval.cache_llm")) and not args.sin_cache
    if usa_cache:
        aj = ajustes_llm(cfg_u)
        motor.usar_cliente_llm(ClienteConCache(lambda: crear_cliente_llm(cfg_u), cfg.ruta("cache_llm"), aj["provider"], aj["modelo"], aj.get("temperatura"), aj["max_tokens"]))
    preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
    filas = ejecutar(motor, preguntas)
    s = resumir(filas)
    salida = cfg.ruta("eval_results")
    etiqueta = f"{umbral:.3f}"
    escribir_csv(salida / f"e2e_umbral_{etiqueta}.csv", [{**f.__dict__, "respuesta": " ".join(f.respuesta.split())[:600]} for f in filas])
    cols = [("id", "Id", ""), ("tipo", "Tipo", ""), ("desenlace", "Desenlace", ""), ("cita_correcta", "Cita correcta", ""), ("mejor_similitud", "Mejor sim.", ".3f"),
            ("costo_usd_referencia", "Costo ref. USD", ".6f"), ("latencia_ms", "Latencia ms", ".0f"), ("advertencias", "Avisos versión", ""), ("desde_cache", "Caché", "")]
    aj = ajustes_llm(cfg_u)
    md = [f"# Evaluación de punta a punta (con LLM), umbral {etiqueta}", "", aviso_set(cfg) +
          f"Proveedor `{aj['provider']}`, modelo `{aj['modelo']}`, nivel `{aj['nivel']}`. Cada pregunta pasa por el motor completo. Resumen:", "",
          f"- **In_domain ({s['in_domain']}):** {s['in_domain_respondidas']} respondidas, de ellas **{s['in_domain_con_cita_correcta']} citando una página esperada**; "
          f"{s['in_domain_abstenciones_incorrectas']} abstenciones incorrectas; {s['in_domain_errores']} errores.",
          f"- **Fuera de dominio ({s['fuera_de_dominio']}):** {s['fuera_abstenciones_por_umbral']} abstenciones por umbral, **{s['fuera_abstenciones_por_llm']} por el LLM**, "
          f"{s['fuera_respuestas_indebidas']} respuestas indebidas, {s['fuera_errores']} errores.",
          f"- **Llamadas:** {s['llamadas_reales']} reales al proveedor + {s['respuestas_de_cache']} reutilizadas de la caché; {s['no_ejecutadas']} preguntas no ejecutadas.",
          f"- **Costo REAL:** USD {s['costo_real_total_usd']:.4f} (en la capa gratuita se cobra 0). **Costo de REFERENCIA** (precio de pago del modelo, pricing.yaml): "
          f"USD {s['costo_referencia_total_usd']:.4f} en total = USD {s['costo_referencia_medio_por_llamada_usd']:.6f} por llamada "
          f"({s['tokens_in_total']:,} tokens de entrada, {s['tokens_out_total']:,} de salida).", "",
          tabla_markdown([f.__dict__ for f in filas], cols), ""]
    if s["no_ejecutadas"]:
        motivo = next(f.error_tipo for f in filas if f.desenlace == "no_ejecutada")
        md.insert(3, f"> **EVALUACIÓN INCOMPLETA:** se detuvo por `{motivo}`; {s['no_ejecutadas']} preguntas no se ejecutaron. Vuelve a ejecutar cuando se restablezca la cuota: "
                     "las respuestas ya obtenidas están en la caché y no se repiten.\n")
    escribir_atomico(salida / f"e2e_umbral_{etiqueta}.md", "\n".join(md))
    print(f"Escrito {salida / f'e2e_umbral_{etiqueta}.md'}")
    for k, v in s.items():
        print(f"  {k}: {v}")
    return 3 if s["no_ejecutadas"] else 0


if __name__ == "__main__":
    sys.exit(main())
