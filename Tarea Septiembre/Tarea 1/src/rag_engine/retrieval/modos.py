"""Despacha la búsqueda según ``retrieval.modo`` de config.yaml: semantico | bm25 | hibrido. Es lo único que llama el motor."""
from __future__ import annotations

from rag_engine.config import Config
from rag_engine.retrieval.bm25 import buscar_bm25
from rag_engine.retrieval.hybrid import buscar_hibrido
from rag_engine.retrieval.semantic import Recuperado, buscar as buscar_semantico


def buscar_por_modo(coleccion, embedder, consulta: str, cfg: Config, k: int | None = None) -> list[Recuperado]:
    modo, k = cfg.get("retrieval.modo"), k or cfg.get("retrieval.top_k")
    if modo == "semantico":
        return buscar_semantico(coleccion, embedder, consulta, k, exacta=cfg.get("retrieval.busqueda") == "exacta")
    lexico = {"k1": cfg.get("retrieval.bm25.k1"), "b": cfg.get("retrieval.bm25.b"), "stemming": cfg.get("retrieval.bm25.stemming"),
              "usar_encabezado": cfg.get("retrieval.bm25.usar_encabezado")}
    if modo == "bm25":
        return buscar_bm25(coleccion, embedder, consulta, k, **lexico)
    if modo == "hibrido":
        return buscar_hibrido(coleccion, embedder, consulta, k, rrf_k=cfg.get("retrieval.hibrido.rrf_k"), candidatos=cfg.get("retrieval.hibrido.candidatos"), **lexico)
    raise ValueError(f"Modo de recuperación desconocido: '{modo}'")
