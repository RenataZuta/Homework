"""Recuperación semántica: la consulta se convierte en vector y se buscan los fragmentos más cercanos (coseno)."""
from __future__ import annotations

from dataclasses import dataclass, field

from rag_engine.embeddings.base import Embedder


@dataclass
class Recuperado:
    id: str
    documento: str
    version: str
    pagina: int
    similitud: float                  # coseno, en [-1, 1]; para vectores normalizados = 1 - distancia
    texto: str
    metadatos: dict = field(default_factory=dict)


def buscar(coleccion, embedder: Embedder, consulta: str, k: int, donde: dict | None = None) -> list[Recuperado]:
    """Los `k` fragmentos más similares, de mayor a menor similitud. `donde` filtra por metadatos (p. ej. {"documento": "..."})."""
    vector = embedder.embed_query(consulta)
    args = {"query_embeddings": [vector.tolist()], "n_results": min(k, coleccion.count()), "include": ["documents", "metadatas", "distances"]}
    if donde:
        args["where"] = donde
    r = coleccion.query(**args)
    salida = []
    for id_, doc, meta, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0]):
        salida.append(Recuperado(id=id_, documento=meta["documento"], version=meta["version"], pagina=int(meta["pagina"]),
                                 similitud=1.0 - float(dist), texto=doc, metadatos=meta))
    return sorted(salida, key=lambda x: -x.similitud)
