"""Lectura del texto ya procesado (data/processed/) y de la configuración de troceado. Solo lo usa el proceso OFFLINE."""
from __future__ import annotations

from extraction import store
from indexing.chunking import ConfigChunk
from rag_engine.config import Config


def chunk_desde_config(cfg: Config, nombre: str | None = None) -> ConfigChunk:
    nombre = nombre or cfg.get("chunking.activa")
    for c in cfg.get("chunking.configuraciones"):
        if c["nombre"] == nombre:
            return ConfigChunk(nombre=c["nombre"], tamano=c["tamano"], solapamiento=c["solapamiento"],
                               contexto_encabezado=c.get("contexto_encabezado", cfg.get("chunking.contexto_encabezado")),
                               unidad=cfg.get("chunking.unidad"))
    raise ValueError(f"No existe la configuración de troceado '{nombre}' en config.yaml")


def docs_paginas(cfg: Config, solo: list[str] | None = None) -> dict[str, tuple[dict, list[dict]]]:
    """{doc_id: (config del documento, entradas por página)} para los documentos pedidos (o todos)."""
    salida = {}
    for d in cfg.documentos:
        if solo and d["id"] not in solo:
            continue
        paginas = store.listar_paginas(cfg.ruta("processed") / d["id"])
        if paginas:
            salida[d["id"]] = (d, paginas)
    return salida
