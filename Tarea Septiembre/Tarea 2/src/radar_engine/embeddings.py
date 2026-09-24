"""Embeddings: reutiliza ``rag_engine.embeddings.factory.crear_embedder`` de la Tarea 1 TAL CUAL.

``crear_embedder(cfg)`` de la Tarea 1 solo necesita ``cfg.get(...)`` y, si el proveedor fuera por API,
``cfg.requerir_env(...)``: nuestro ``radar_engine.config.Config`` implementa exactamente esa interfaz (ver ese
módulo), así que no hace falta ningún adaptador extra. Esto es lo que garantiza la Fase 3 de la Tarea 2:
"mismo modelo de embeddings local que la Tarea 1" no es una promesa en el README, es el mismo código.
"""
from __future__ import annotations

from radar_engine.bootstrap_t1 import asegurar_import_tarea1
from radar_engine.config import Config

asegurar_import_tarea1()

from rag_engine.embeddings.base import Embedder, ErrorEmbeddings  # noqa: E402
from rag_engine.embeddings.factory import crear_embedder as _crear_embedder  # noqa: E402

__all__ = ["Embedder", "ErrorEmbeddings", "crear_embedder"]


def crear_embedder(cfg: Config) -> Embedder:
    return _crear_embedder(cfg)
