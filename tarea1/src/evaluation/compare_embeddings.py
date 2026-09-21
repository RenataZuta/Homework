"""compare_embeddings.py — modelo LOCAL frente a modelos por API (OpenAI text-embedding-3-small y Gemini gemini-embedding-2) con los MISMOS fragmentos.

Construye un índice por modelo con exactamente los mismos fragmentos (se verifica comparando IDs y hashes de contenido, no se supone) y
reporta por modelo: Recall@1/3/5, tiempo de indexación, costo en USD, latencia promedio por consulta, dimensión del vector y almacenamiento.
Sin llamar al LLM de generación. Los candidatos salen de ``embeddings.comparar`` en config.yaml.
Regla de costo: NO se carga crédito. Cada candidato termina en uno de estos estados (nunca se inventan cifras):
  * ``medido``                        — se ejecutó de verdad.
  * ``pendiente: falta X en .env``     — no hay clave; basta agregarla y volver a ejecutar.
  * ``no ejecutada por costo: …``      — la API respondió ``insufficient_quota`` (cuenta sin crédito): no se paga, la fila queda preparada.
  * ``no completada: cuota agotada``   — se agotó la cuota gratuita a medio camino; se puede repetir más tarde.
  * ``error: …``                       — otro fallo (clave inválida, red…).
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.compare_embeddings
Escribe eval/results/embeddings_comparacion.{csv,json,md}; la app Streamlit lee la tabla.
"""
from __future__ import annotations

import json
import shutil
import statistics
import sys
import time
from pathlib import Path

import yaml

from evaluation.eval_set import cargar_preguntas
from evaluation.informes import aviso_set, escribir_atomico, escribir_csv, tabla_markdown
from evaluation.metrics import evaluar_recuperacion
from indexing.build_index import construir_indice
from indexing.carga import chunk_desde_config, docs_paginas
from indexing.chunking import trocear_documento
from rag_engine.config import ConfigError, cargar_config
from rag_engine.embeddings.base import ErrorEmbeddings
from rag_engine.embeddings.factory import crear_embedder
from rag_engine.retrieval.indice import abrir_cliente
from rag_engine.retrieval.semantic import buscar

ETIQUETAS = {"local": "local", "openai": "API (OpenAI)", "gemini": "API (Gemini)"}
BLOQUE_PRECIOS = {"openai": "openai_embeddings", "gemini": "gemini_embeddings"}


def tamano_dir_mb(ruta: Path) -> float:
    return round(sum(f.stat().st_size for f in ruta.rglob("*") if f.is_file()) / 1_048_576, 2)


def estimar_tokens_openai(textos: list[str], modelo: str) -> int | None:
    """Estimación previa con el tokenizador de OpenAI (los tokens REALES vienen en la respuesta de la API)."""
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model(modelo)
        return sum(len(enc.encode(t)) for t in textos)
    except Exception:
        return None


def estado_por_error(exc: ErrorEmbeddings, proveedor: str) -> str:
    """Traduce un error del proveedor al estado de la fila. Sin crédito NO se paga: la fila queda 'no ejecutada por costo'."""
    if exc.tipo == "cuota_insuficiente":
        return (f"no ejecutada por costo: {ETIQUETAS.get(proveedor, proveedor)} respondió insufficient_quota (la cuenta no tiene crédito) "
                "y no se cargó crédito; la fila queda preparada")
    if exc.tipo in ("cuota_agotada", "limite_de_tasa"):
        return f"no completada: cuota agotada del proveedor ({exc.mensaje[:110]}); repetir más tarde"
    if exc.tipo == "autenticacion":
        return f"error: clave inválida o sin permisos ({exc.mensaje[:90]})"
    return f"error: {exc.mensaje[:120]}"


def medir(cfg, proveedor: str, preguntas, docs, chunk, dir_cmp: Path, fragmentos_ids: dict[str, str]) -> dict:
    ajustes = cfg.get(f"embeddings.{proveedor}")
    etiqueta = ETIQUETAS.get(proveedor, proveedor)
    base = {"proveedor": proveedor, "tipo": etiqueta, "modelo": ajustes["modelo"]}
    try:
        emb = crear_embedder(cfg, proveedor)
    except ConfigError as exc:                                     # p. ej. falta la clave: la fila queda PENDIENTE, sin cifras inventadas
        faltante = next((w for w in str(exc).split() if w.isupper() and "_" in w), "una variable de entorno")
        return {**base, "estado": f"pendiente: falta {faltante} en .env"}
    except ErrorEmbeddings as exc:
        return {**base, "estado": estado_por_error(exc, proveedor)}
    ks = tuple(cfg.get("eval.ks"))
    try:
        res = construir_indice(emb, chunk, docs, dir_cmp, cfg.get("indexacion.coleccion"), dict(cfg.get("chunking.articulo_maximo")),
                               cfg.get("indexacion.lote_upsert"), mostrar=lambda *_: None)
        col = abrir_cliente(dir_cmp).get_collection(res.coleccion)
        meta = col.get(include=["metadatas"])
        ids_modelo = {i: m["hash_texto"] for i, m in zip(meta["ids"], meta["metadatas"])}
        lat = []
        for q in preguntas:                                       # latencia de UNA consulta: embedding de la pregunta + búsqueda
            t0 = time.perf_counter()
            buscar(col, emb, q.pregunta, 5)
            lat.append((time.perf_counter() - t0) * 1000)
        ev = evaluar_recuperacion(preguntas, lambda t, k: buscar(col, emb, t, k), ks)
    except ErrorEmbeddings as exc:
        return {**base, "estado": estado_por_error(exc, proveedor)}
    c = emb.contabilidad
    tokens_ok = getattr(emb, "tokens_reportados", True)
    return {**base, "modelo": emb.name, "estado": "medido", "dim": emb.dim, "fragmentos": col.count(),
            "mismos_fragmentos": ids_modelo == fragmentos_ids, "tokens_indexados": c.tokens if tokens_ok else None,
            "tokens_nota": "" if tokens_ok else "no informado por la API", "nivel": getattr(emb, "nivel", "local" if proveedor == "local" else "pago"),
            "indexacion_s": round(res.segundos, 1), "costo_usd": c.costo_usd, "consulta_ms_media": round(statistics.mean(lat), 1),
            "consulta_ms_p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 1),
            "almacenamiento_vectores_mb": round(col.count() * emb.dim * 4 / 1_048_576, 2), "almacenamiento_indice_mb": tamano_dir_mb(dir_cmp),
            **{f"recall@{k}": round(ev.recall(k), 3) for k in ks}, "recall@3_modificatoria": round(ev.recall_modificatoria(3), 3), "mrr": round(ev.mrr(), 3)}


def seccion_costos(cfg, fragmentos) -> tuple[list[str], dict]:
    """Precios (con fuente y fecha) de cada candidato por API. Solo hay estimación previa de tokens para OpenAI (tiktoken)."""
    todos = yaml.safe_load(cfg.ruta("pricing").read_text(encoding="utf-8"))
    md, info = ["## Costo", ""], {}
    for proveedor in cfg.get("embeddings.comparar"):
        if proveedor not in BLOQUE_PRECIOS:
            continue
        bloque = todos[BLOQUE_PRECIOS[proveedor]]
        modelo = cfg.get(f"embeddings.{proveedor}.modelo")
        precio = bloque["modelos"][modelo]["usd_por_millon_tokens"]
        linea = (f"- **{ETIQUETAS[proveedor]}, `{modelo}`:** precio de pago USD {precio} por millón de tokens de entrada, verificado el "
                 f"{bloque['fecha_verificacion']} en {bloque['fuente']}.")
        info[proveedor] = {"modelo": modelo, "precio_usd_por_millon_tokens": precio, "fuente": bloque["fuente"], "fecha_verificacion": str(bloque["fecha_verificacion"])}
        if proveedor == "openai":
            est = estimar_tokens_openai([f.texto_embedding for f in fragmentos], modelo)
            if est:
                linea += f" Estimación previa con el tokenizador de OpenAI: {est:,} tokens = **USD {est * precio / 1e6:.4f}** para indexar el corpus (estimación, no medición)."
                info[proveedor].update(tokens_estimados=est, costo_estimado_corpus_usd=round(est * precio / 1e6, 6))
        else:
            linea += (" Tiene capa gratuita («Free of charge»): el costo real es 0 y en ella Google puede usar el contenido para mejorar sus productos "
                      "(solo se envían fragmentos de normas públicas). La API no informa tokens, así que no se calcula un costo de referencia.")
        md.append(linea)
    return md + [""], info


def main() -> int:
    cfg = cargar_config()
    preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
    chunk, docs = chunk_desde_config(cfg), docs_paginas(cfg)
    maximo = dict(cfg.get("chunking.articulo_maximo"))
    fragmentos = [f for d, ps in docs.values() for f in trocear_documento(d, ps, chunk, maximo)]
    ids_esperados = {f.id: f.hash_texto for f in fragmentos}
    dir_cmp = cfg.ruta("index_cmp") / "embeddings"
    shutil.rmtree(dir_cmp, ignore_errors=True)
    filas = []
    for proveedor in cfg.get("embeddings.comparar"):
        print(f"== {proveedor} ==", flush=True)
        fila = medir(cfg, proveedor, preguntas, docs, chunk, dir_cmp, ids_esperados)
        filas.append(fila)
        print({k: fila.get(k) for k in ("modelo", "estado", "dim", "indexacion_s", "costo_usd", "consulta_ms_media", "recall@1", "recall@3", "recall@5")}, flush=True)

    medidas = [f for f in filas if f["estado"] == "medido"]
    if medidas and not all(f["mismos_fragmentos"] for f in medidas):
        print("ERROR: los índices NO tienen los mismos fragmentos; la comparación no es válida.", file=sys.stderr)
        return 1

    salida = cfg.ruta("eval_results")
    columnas = ["tipo", "modelo", "estado", "nivel", "dim", "fragmentos", "mismos_fragmentos", "tokens_indexados", "tokens_nota", "indexacion_s", "costo_usd",
                "consulta_ms_media", "consulta_ms_p95", "almacenamiento_vectores_mb", "almacenamiento_indice_mb", "recall@1", "recall@3", "recall@5",
                "recall@3_modificatoria", "mrr"]
    escribir_csv(salida / "embeddings_comparacion.csv", [{c: f.get(c) for c in columnas} for f in filas])
    costos_md, costos_info = seccion_costos(cfg, fragmentos)
    escribir_atomico(salida / "embeddings_comparacion.json", json.dumps({"filas": filas, "fragmentos": len(fragmentos), "precios": costos_info},
                                                                        ensure_ascii=False, indent=1) + "\n")
    cols = [("tipo", "Tipo", ""), ("modelo", "Modelo", ""), ("estado", "Estado", ""), ("nivel", "Nivel", ""), ("dim", "Dim", ""), ("indexacion_s", "Indexación (s)", ".1f"),
            ("costo_usd", "Costo real USD", ".6f"), ("consulta_ms_media", "Consulta (ms)", ".1f"), ("almacenamiento_vectores_mb", "Vectores (MB)", ".2f"),
            ("recall@1", "R@1", ".3f"), ("recall@3", "R@3", ".3f"), ("recall@5", "R@5", ".3f"), ("recall@3_modificatoria", "R@3 modif.", ".3f")]
    md = ["# Embeddings local frente a API", "", aviso_set(cfg) +
          f"Los MISMOS {len(fragmentos)} fragmentos (troceado `{chunk.nombre}`; se verificó que los índices medidos tienen los mismos IDs y hashes de contenido) y las "
          f"{sum(q.tipo == 'in_domain' for q in preguntas)} preguntas in_domain. Sin llamar al LLM de generación. No se cargó crédito en ningún proveedor.", "",
          tabla_markdown(filas, cols), ""]
    pendientes = [f for f in filas if f["estado"] != "medido"]
    if pendientes:
        md += ["> **Filas no medidas:** " + "; ".join(f"`{f['modelo']}` — {f['estado']}" for f in pendientes) + ". No se estiman recall, tiempos ni costo reales sin la llamada real.", ""]
    escribir_atomico(salida / "embeddings_comparacion.md", "\n".join(md + costos_md))
    print(f"Escrito {salida / 'embeddings_comparacion.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
