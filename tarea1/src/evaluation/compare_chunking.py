"""compare_chunking.py — compara configuraciones de tamaño/solapamiento con el modelo local activo.

Un índice por configuración (temporal, en data/index_cmp/chunking), Recall@1/3/5 sin llamar al LLM, y la elección de la ganadora:
mayor Recall@3; empate -> mayor Recall@5; empate -> menos fragmentos. Escribe eval/results/chunking_comparacion.{csv,md}.
Con --aplicar deja la ganadora en config.yaml (chunking.activa).
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.compare_chunking [--aplicar]
"""
from __future__ import annotations

import argparse
import gc
import shutil
import statistics
import sys

from evaluation.eval_set import cargar_preguntas
from evaluation.informes import aviso_set, escribir_atomico, escribir_csv, tabla_markdown
from evaluation.metrics import evaluar_recuperacion
from indexing.build_index import construir_indice
from indexing.carga import chunk_desde_config, docs_paginas
from indexing.chunking import trocear_documento
from rag_engine.config import cargar_config
from rag_engine.embeddings.factory import crear_embedder
from rag_engine.retrieval.indice import abrir_cliente
from rag_engine.retrieval.semantic import buscar


def percentil(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true", help="escribe la ganadora en config.yaml")
    args = ap.parse_args(argv)
    cfg = cargar_config()
    preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
    docs, maximo, ks = docs_paginas(cfg), dict(cfg.get("chunking.articulo_maximo")), tuple(cfg.get("eval.ks"))
    emb = crear_embedder(cfg)
    dir_cmp = cfg.ruta("index_cmp") / "chunking"
    shutil.rmtree(dir_cmp, ignore_errors=True)
    filas = []
    rangos: dict[str, dict[str, int | None]] = {}          # pregunta -> config -> rango del primer acierto
    for c in cfg.get("chunking.configuraciones"):
        chunk = chunk_desde_config(cfg, c["nombre"])
        frag = [f for d, ps in docs.values() for f in trocear_documento(d, ps, chunk, maximo)]
        largos = [len(f.texto) for f in frag]
        tokens = emb.contar_tokens([f.texto_embedding for f in frag])
        emb.contabilidad.__init__()                                   # contabilidad por configuración
        res = construir_indice(emb, chunk, docs, dir_cmp, cfg.get("indexacion.coleccion"), maximo, cfg.get("indexacion.lote_upsert"),
                               mostrar=lambda *_: None)
        col = abrir_cliente(dir_cmp).get_collection(res.coleccion)
        ev = evaluar_recuperacion(preguntas, lambda t, k: buscar(col, emb, t, k), ks)
        fila = {"config": c["nombre"], "tamano": c["tamano"], "solapamiento": c["solapamiento"],
                "contexto_encabezado": chunk.contexto_encabezado, "fragmentos": len(frag), "mediana_car": int(statistics.median(largos)),
                "p95_car": int(percentil(largos, 95)), "menores_150_car": sum(x < 150 for x in largos),
                "pct_truncados": round(100 * sum(t > emb.max_tokens for t in tokens) / len(tokens), 1), "indexacion_s": round(res.segundos, 1),
                **{f"recall@{k}": round(ev.recall(k), 3) for k in ks}, "recall@3_modificatoria": round(ev.recall_modificatoria(3), 3),
                "mrr": round(ev.mrr(), 3)}
        filas.append(fila)
        for x in ev.por_pregunta:
            if x.tipo == "in_domain":
                rangos.setdefault(x.id, {})[c["nombre"]] = x.rango_acierto
        print({k: fila[k] for k in ("config", "fragmentos", "pct_truncados", "recall@1", "recall@3", "recall@5")}, flush=True)
        del col
        gc.collect()

    ganadora = sorted(filas, key=lambda f: (-f["recall@3"], -f["recall@5"], f["fragmentos"]))[0]
    salida = cfg.ruta("eval_results")
    escribir_csv(salida / "chunking_comparacion.csv", filas)
    escribir_csv(salida / "chunking_por_pregunta.csv", [{"pregunta": q, **{k: (v if v is not None else "") for k, v in r.items()}} for q, r in rangos.items()])
    cols = [("config", "Configuración", ""), ("tamano", "Tamaño", ""), ("solapamiento", "Solape", ""), ("contexto_encabezado", "Encab. contexto", ""),
            ("fragmentos", "Fragmentos", ""), ("mediana_car", "Mediana car.", ""), ("menores_150_car", "< 150 car.", ""),
            ("pct_truncados", "% truncados", ".1f"), ("indexacion_s", "Indexación (s)", ".1f"), ("recall@1", "R@1", ".3f"),
            ("recall@3", "R@3", ".3f"), ("recall@5", "R@5", ".3f"), ("recall@3_modificatoria", "R@3 modif.", ".3f"), ("mrr", "MRR", ".3f")]
    md = ["# Comparación de tamaño y solapamiento de fragmentos", "", aviso_set(cfg) +
          f"Modelo: `{emb.name}` (máx. {emb.max_tokens} tokens). Un índice por configuración; {sum(q.tipo == 'in_domain' for q in preguntas)} preguntas in_domain; "
          "sin llamar al LLM.", "", tabla_markdown(filas, cols), "",
          f"**Ganadora: `{ganadora['config']}`** (criterio: mayor Recall@3; empate, mayor Recall@5; empate, menos fragmentos).", ""]
    escribir_atomico(salida / "chunking_comparacion.md", "\n".join(md))
    print(f"Ganadora: {ganadora['config']}  -> {salida / 'chunking_comparacion.md'}")
    if args.aplicar:
        import os, pathlib, re
        p = cfg.archivo
        s = p.read_text(encoding="utf-8")
        s2, n = re.subn(r"(?m)^(  activa: )\S+(.*)$", rf"\g<1>{ganadora['config']}\g<2>", s, count=1)
        assert n == 1 and len(s2) > 1000
        tmp = p.with_suffix(".yaml.tmp"); tmp.write_text(s2, encoding="utf-8"); os.replace(tmp, p)
        print("config.yaml actualizado: chunking.activa =", ganadora["config"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
