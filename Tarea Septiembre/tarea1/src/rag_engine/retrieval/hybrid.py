"""Búsqueda híbrida: Reciprocal Rank Fusion (RRF) de la lista semántica (coseno) y la léxica (BM25).

RRF suma, para cada fragmento, ``1 / (rrf_k + rango)`` en cada lista donde aparece (rango desde 1). No usa los puntajes, solo las posiciones, así que no
importa que BM25 y el coseno estén en escalas distintas. ``rrf_k`` = 60 es el valor de la publicación original (Cormack et al., 2009); ``candidatos`` es cuántos
fragmentos de cada lista entran a la fusión.
COMPUERTA DEL UMBRAL: el ``similitud`` de cada fragmento devuelto sigue siendo su COSENO con la consulta; el motor abstiene según el mayor coseno entre los
recuperados. Así el umbral calibrado sigue significando lo mismo aunque el orden lo decida BM25. El puntaje RRF va en ``Recuperado.puntaje``.
"""
from __future__ import annotations

from rag_engine.embeddings.base import Embedder
from rag_engine.retrieval.bm25 import indice_de, ranking_bm25
from rag_engine.retrieval.semantic import Recuperado, recuperado_en, similitudes


def fusion_rrf(listas: list[list[int]], rrf_k: int = 60) -> dict[int, float]:
    """{posición: puntaje RRF} para varias listas ordenadas de posiciones."""
    puntaje: dict[int, float] = {}
    for lista in listas:
        for rango, i in enumerate(lista, start=1):
            puntaje[i] = puntaje.get(i, 0.0) + 1.0 / (rrf_k + rango)
    return puntaje


def buscar_hibrido(coleccion, embedder: Embedder, consulta: str, k: int, *, rrf_k: int = 60, candidatos: int = 50, k1: float = 1.5, b: float = 0.75,
                   stemming: bool = False, usar_encabezado: bool = True) -> list[Recuperado]:
    m, cosenos = similitudes(coleccion, embedder.embed_query(consulta))
    semantica = sorted(range(len(m.ids)), key=lambda i: (-float(cosenos[i]), m.ids[i]))[:candidatos]
    puntajes = indice_de(coleccion, k1, b, stemming, usar_encabezado).puntuar(consulta)
    lexica = ranking_bm25(puntajes, m.ids, candidatos)
    fusion = fusion_rrf([semantica, lexica], rrf_k)
    orden = sorted(fusion, key=lambda i: (-fusion[i], -float(cosenos[i]), m.ids[i]))[:k]              # empate de RRF -> el de mayor coseno
    return [recuperado_en(m, i, cosenos[i], fusion[i]) for i in orden]
