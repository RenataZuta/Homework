"""select_local_model.py — compara los modelos locales candidatos (embeddings.candidatos_locales) con los MISMOS fragmentos.

Por modelo: parámetros, dimensión, longitud máxima REAL, % de fragmentos que se truncarían en silencio, tiempos de carga, de
indexación y por consulta, y Recall@1/3/5 sin llamar al LLM. Escribe eval/results/modelos_locales.{csv,md}.
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.select_local_model
"""
from __future__ import annotations

import gc
import shutil
import statistics
import sys
import time

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


def main() -> int:
    cfg = cargar_config()
    preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
    chunk, docs = chunk_desde_config(cfg), docs_paginas(cfg)
    maximo = dict(cfg.get("chunking.articulo_maximo"))
    ks = tuple(cfg.get("eval.ks"))
    fragmentos = [f for d, ps in docs.values() for f in trocear_documento(d, ps, chunk, maximo)]
    textos = [f.texto_embedding for f in fragmentos]
    dir_cmp = cfg.ruta("index_cmp") / "modelos"
    shutil.rmtree(dir_cmp, ignore_errors=True)
    filas = []
    for cand in cfg.get("embeddings.candidatos_locales"):
        print(f"\n=== {cand['modelo']} ===", flush=True)
        t0 = time.perf_counter()
        emb = crear_embedder(cfg, "local", sobreescribir=cand)
        t_carga = time.perf_counter() - t0
        tokens = emb.contar_tokens(textos)
        truncados = sum(t > emb.max_tokens for t in tokens)
        params = sum(p.numel() for p in emb._m.parameters())
        res = construir_indice(emb, chunk, docs, dir_cmp, cfg.get("indexacion.coleccion"), maximo, cfg.get("indexacion.lote_upsert"),
                               mostrar=lambda *_: None)
        col = abrir_cliente(dir_cmp).get_collection(res.coleccion)
        lat = []
        for q in preguntas:                                   # latencia de UNA consulta (embedding + búsqueda)
            t1 = time.perf_counter()
            buscar(col, emb, q.pregunta, 5)
            lat.append((time.perf_counter() - t1) * 1000)
        ev = evaluar_recuperacion(preguntas, lambda t, k: buscar(col, emb, t, k), ks)
        fila = {"modelo": cand["modelo"], "parametros_millones": round(params / 1e6), "dim": emb.dim, "max_tokens": emb.max_tokens,
                "prefijos": "sí" if cand.get("prefijo_pasaje") else "no", "tokens_medianos": int(statistics.median(tokens)),
                "tokens_max": max(tokens), "fragmentos_truncados": truncados, "pct_truncados": round(100 * truncados / len(tokens), 1),
                "carga_s": round(t_carga, 1), "indexacion_s": round(res.segundos, 1), "consulta_ms": round(statistics.mean(lat), 1),
                **{f"recall@{k}": round(ev.recall(k), 3) for k in ks}, "recall@3_modificatoria": round(ev.recall_modificatoria(3), 3),
                "mrr": round(ev.mrr(), 3)}
        filas.append(fila)
        print("  ", {k: fila[k] for k in ("dim", "max_tokens", "pct_truncados", "indexacion_s", "recall@1", "recall@3", "recall@5")}, flush=True)
        del emb, col
        gc.collect()

    salida = cfg.ruta("eval_results")
    escribir_csv(salida / "modelos_locales.csv", filas)
    cols = [("modelo", "Modelo", ""), ("parametros_millones", "Params (M)", ""), ("dim", "Dim", ""), ("max_tokens", "Máx. tokens", ""),
            ("prefijos", "Prefijos", ""), ("pct_truncados", "% truncados", ".1f"), ("indexacion_s", "Indexación (s)", ".1f"),
            ("consulta_ms", "Consulta (ms)", ".1f"), ("recall@1", "R@1", ".3f"), ("recall@3", "R@3", ".3f"), ("recall@5", "R@5", ".3f"),
            ("recall@3_modificatoria", "R@3 modif.", ".3f"), ("mrr", "MRR", ".3f")]
    md = ["# Comparación de modelos de embeddings locales", "", aviso_set(cfg) +
          f"Mismos {len(fragmentos)} fragmentos (troceado `{chunk.nombre}`: {chunk.tamano} caracteres, solape {chunk.solapamiento}) y las "
          f"{sum(q.tipo == 'in_domain' for q in preguntas)} preguntas in_domain del set de evaluación. Sin llamar al LLM. CPU, sin GPU.", "",
          tabla_markdown(filas, cols), "",
          "**% truncados** = fragmentos cuya longitud en tokens (con el prefijo) supera la longitud máxima real del modelo: lo que exceda se descarta "
          "en silencio al calcular el vector. **R@3 modif.** = Recall@3 de las preguntas de versiones exigiendo el fragmento del DS 001.", ""]
    escribir_atomico(salida / "modelos_locales.md", "\n".join(md))
    print(f"\nEscrito {salida / 'modelos_locales.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
