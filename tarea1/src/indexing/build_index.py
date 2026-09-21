"""Construcción del índice (proceso OFFLINE). Idempotente y reanudable.

Garantías (probadas en tests/test_indexing.py):
  * Idempotente: correrlo dos veces deja el mismo índice y la segunda vez no embebe nada. Se hace upsert por ID y, ANTES de
    embeber, se descartan los IDs que ya existen con el mismo contenido (hash del texto).
  * Reanudable: se guarda por lotes (``lote_upsert``); una interrupción pierde a lo sumo un lote y la siguiente corrida
    continúa con lo que falta.
  * Aislado por documento: reconstruir o agregar un documento no toca los fragmentos de otro. Solo se borran fragmentos
    OBSOLETOS del propio documento (p. ej. si una página se volvió a procesar y ahora produce menos fragmentos).
  * Si el contenido de un ID cambió (mismo ID, distinto hash de texto), se re-embebe y se actualiza.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from indexing.chunking import ConfigChunk, Fragmento, trocear_documento
from rag_engine.embeddings.base import Embedder
from rag_engine.retrieval.indice import abrir_cliente, crear_o_abrir, nombre_coleccion
from rag_engine.retrieval.semantic import olvidar_matrices


@dataclass
class ResumenIndice:
    coleccion: str = ""
    fragmentos_esperados: int = 0
    existentes: int = 0               # ya estaban con el mismo contenido: no se embeben
    nuevos: int = 0
    actualizados: int = 0             # mismo ID, contenido distinto
    eliminados: int = 0               # obsoletos del mismo documento
    por_documento: dict[str, int] = field(default_factory=dict)
    total_en_indice: int = 0
    interrumpido: bool = False
    segundos: float = 0.0
    embeddings: dict = field(default_factory=dict)


def _hashes_existentes(col, ids: list[str]) -> dict[str, str]:
    salida: dict[str, str] = {}
    for i in range(0, len(ids), 500):
        r = col.get(ids=ids[i:i + 500], include=["metadatas"])
        salida.update({id_: m.get("hash_texto", "") for id_, m in zip(r["ids"], r["metadatas"])})
    return salida


def construir_indice(embedder: Embedder, chunk: ConfigChunk, docs_paginas: dict[str, tuple[dict, list[dict]]], dir_index: Path,
                     prefijo: str, maximo: dict[str, int], lote_upsert: int = 64, mostrar=print) -> ResumenIndice:
    """`docs_paginas`: {doc_id: (config_del_documento, [entradas por página])}. Solo se tocan los documentos indicados."""
    t0 = time.perf_counter()
    nombre = nombre_coleccion(prefijo, chunk.nombre, embedder.name)
    col = crear_o_abrir(abrir_cliente(dir_index), nombre,
                        {"modelo": embedder.name, "chunking": chunk.nombre, "chunking_hash": chunk.hash, "dim": embedder.dim})
    res = ResumenIndice(coleccion=nombre)

    pendientes: list[Fragmento] = []
    for doc_id, (doc, paginas) in docs_paginas.items():
        fragmentos = trocear_documento(doc, paginas, chunk, maximo)
        res.fragmentos_esperados += len(fragmentos)
        res.por_documento[doc_id] = len(fragmentos)
        esperados = {f.id: f for f in fragmentos}

        previos = col.get(where={"documento": doc_id}, include=["metadatas"])           # solo ESTE documento
        obsoletos = [i for i in previos["ids"] if i not in esperados]
        if obsoletos:
            col.delete(ids=obsoletos)
            res.eliminados += len(obsoletos)

        ya = _hashes_existentes(col, list(esperados))
        for f in fragmentos:
            if f.id not in ya:
                res.nuevos += 1
                pendientes.append(f)
            elif ya[f.id] != f.hash_texto:
                res.actualizados += 1
                pendientes.append(f)
            else:
                res.existentes += 1

    try:
        for i in range(0, len(pendientes), lote_upsert):
            lote = pendientes[i:i + lote_upsert]
            vectores = embedder.embed_passages([f.texto_embedding for f in lote])
            col.upsert(ids=[f.id for f in lote], embeddings=vectores.tolist(), documents=[f.texto for f in lote],
                       metadatas=[f.metadatos() for f in lote])
            mostrar(f"  lote {i // lote_upsert + 1}/{-(-len(pendientes) // lote_upsert)}: {len(lote)} fragmentos guardados")
    except KeyboardInterrupt:
        res.interrumpido = True
    olvidar_matrices()                       # ninguna consulta posterior debe usar la matriz en memoria de antes de esta indexación
    res.total_en_indice = col.count()
    res.segundos = time.perf_counter() - t0
    res.embeddings = embedder.contabilidad.como_dict()
    return res
