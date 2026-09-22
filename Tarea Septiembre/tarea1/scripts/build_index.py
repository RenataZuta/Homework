#!/usr/bin/env python3
"""build_index.py — construye (o completa) el índice persistente a partir de data/processed/ (proceso OFFLINE).

Uso (desde tarea1/):
    python scripts/build_index.py                       # troceado y modelo activos de config.yaml
    python scripts/build_index.py --solo ley_32069      # solo un documento (los demás no se tocan)
Es idempotente y reanudable: si ya está todo, no embebe nada; Ctrl+C es seguro (se guarda por lotes).
Códigos de salida: 0 = bien, 1 = error, 130 = interrumpido (reanudable).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from indexing.build_index import construir_indice  # noqa: E402
from indexing.carga import chunk_desde_config, docs_paginas  # noqa: E402
from rag_engine.config import ConfigError, cargar_config  # noqa: E402
from rag_engine.embeddings.base import ErrorEmbeddings  # noqa: E402
from rag_engine.embeddings.factory import crear_embedder  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--solo", action="append", metavar="ID")
    ap.add_argument("--indice-dir", type=Path, default=None, help="directorio del índice (por defecto, paths.index); útil para pruebas")
    ap.add_argument("--chunking", default=None, help="nombre de la configuración de troceado (por defecto, chunking.activa)")
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config()
        chunk = chunk_desde_config(cfg, args.chunking)
        docs = docs_paginas(cfg, args.solo)
        if not docs:
            print("ERROR: no hay texto procesado en data/processed/. Ejecuta antes scripts/run_extraction.py.", file=sys.stderr)
            return 1
        emb = crear_embedder(cfg)
    except (ConfigError, ErrorEmbeddings, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Modelo: {emb.name} (dim {emb.dim}, máx. {emb.max_tokens} tokens) · troceado: {chunk.nombre} ({chunk.tamano}/{chunk.solapamiento})")
    r = construir_indice(emb, chunk, docs, (args.indice_dir or cfg.ruta("index")), cfg.get("indexacion.coleccion"), dict(cfg.get("chunking.articulo_maximo")),
                         cfg.get("indexacion.lote_upsert"))
    print(f"Colección {r.coleccion}: esperados={r.fragmentos_esperados} existentes={r.existentes} nuevos={r.nuevos} "
          f"actualizados={r.actualizados} eliminados={r.eliminados} · en el índice: {r.total_en_indice} ({r.segundos:.1f} s)")
    print("Por documento:", ", ".join(f"{k}={v}" for k, v in r.por_documento.items()))
    if r.interrumpido:
        print("\nInterrumpido con Ctrl+C. Lo guardado se conserva: vuelve a ejecutar el mismo comando para continuar.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
