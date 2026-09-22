"""Recuperación semántica: la consulta se convierte en vector y se buscan los fragmentos más cercanos (coseno).

BÚSQUEDA EXACTA (``retrieval.busqueda: exacta``, por defecto). Con ~1 700 vectores una multiplicación de matrices tarda menos de 1 ms, y la
búsqueda aproximada HNSW de Chroma NO era fiable a esta escala: medido el 2026-09-21, para la pregunta ``o01`` el fragmento más parecido (p. 96) aparecía
o no según el proceso (la búsqueda aproximada difería de la exacta en 2 de 3 procesos), lo que hacía irreproducibles las métricas y las
respuestas. La exacta es determinista: mismos vectores + misma consulta = mismo resultado, con desempate por ID. Chroma sigue guardando vectores,
textos y metadatos; solo se prescinde de su índice de vecinos aproximados. ``busqueda: aproximada`` conserva la consulta HNSW original.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

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
    puntaje: float | None = None      # puntaje propio del modo que ordenó (BM25 o RRF); None en el semántico, donde el orden ES la similitud


class _Matriz:
    """Todos los vectores (normalizados), textos y metadatos de una colección, ordenados por ID para que los empates sean deterministas."""

    def __init__(self, coleccion):
        d = coleccion.get(include=["embeddings", "documents", "metadatas"])
        orden = sorted(range(len(d["ids"])), key=lambda i: d["ids"][i])
        self.ids = [d["ids"][i] for i in orden]
        self.textos = [d["documents"][i] for i in orden]
        self.metas = [d["metadatas"][i] for i in orden]
        m = np.asarray([d["embeddings"][i] for i in orden], dtype=np.float32).reshape(len(orden), -1)
        normas = np.linalg.norm(m, axis=1, keepdims=True)
        self.vectores = m / np.where(normas == 0, 1.0, normas)


_CACHE: dict[tuple[str, int], _Matriz] = {}
_LIMPIADORES: list = []               # otros módulos (BM25) registran aquí cómo descartar sus cachés derivadas de la misma colección


def registrar_limpiador(funcion) -> None:
    if funcion not in _LIMPIADORES:
        _LIMPIADORES.append(funcion)


def olvidar_matrices() -> None:
    """Descarta las matrices en memoria (la indexación lo llama al terminar para que ninguna consulta use datos viejos)."""
    _CACHE.clear()
    for f in _LIMPIADORES:
        f()


def _matriz(coleccion) -> _Matriz:
    clave = (str(coleccion.id), coleccion.count())
    if clave not in _CACHE:
        _CACHE[clave] = _Matriz(coleccion)
    return _CACHE[clave]


def matriz_de(coleccion) -> _Matriz:
    return _matriz(coleccion)


def similitudes(coleccion, vector: np.ndarray) -> tuple[_Matriz, np.ndarray]:
    """Coseno de la consulta contra TODOS los fragmentos (exacto). Lo usan los tres modos: el semántico ordena por él; BM25 y el híbrido lo conservan como
    ``similitud`` de cada fragmento, que es lo que compara la compuerta del umbral (los puntajes de BM25 no son cosenos)."""
    m = _matriz(coleccion)
    v = np.asarray(vector, dtype=np.float32)
    return m, m.vectores @ (v / (np.linalg.norm(v) or 1.0))


def recuperado_en(m: _Matriz, i: int, sim: float, puntaje: float | None = None) -> Recuperado:
    return Recuperado(id=m.ids[i], documento=m.metas[i]["documento"], version=m.metas[i]["version"], pagina=int(m.metas[i]["pagina"]),
                      similitud=float(sim), texto=m.textos[i], metadatos=m.metas[i], puntaje=puntaje)


def _coincide(meta: dict, donde: dict) -> bool:
    return all(meta.get(k) == v for k, v in donde.items())


def _es_igualdad_simple(donde: dict) -> bool:
    return all(not str(k).startswith("$") and not isinstance(v, (dict, list)) for k, v in donde.items())


def buscar(coleccion, embedder: Embedder, consulta: str, k: int, donde: dict | None = None, exacta: bool = True) -> list[Recuperado]:
    """Los `k` fragmentos más similares, de mayor a menor similitud. `donde` filtra por metadatos (p. ej. {"documento": "..."})."""
    vector = embedder.embed_query(consulta)
    if exacta and (not donde or _es_igualdad_simple(donde)):
        return _buscar_exacta(coleccion, vector, k, donde)
    return _buscar_aproximada(coleccion, vector, k, donde)


def _buscar_exacta(coleccion, vector: np.ndarray, k: int, donde: dict | None) -> list[Recuperado]:
    m = _matriz(coleccion)
    v = np.asarray(vector, dtype=np.float32)
    v = v / (np.linalg.norm(v) or 1.0)
    sims = m.vectores @ v
    candidatos = [i for i in range(len(m.ids)) if not donde or _coincide(m.metas[i], donde)]
    orden = sorted(candidatos, key=lambda i: (-float(sims[i]), m.ids[i]))[:k]              # desempate por ID: resultado determinista
    return [Recuperado(id=m.ids[i], documento=m.metas[i]["documento"], version=m.metas[i]["version"], pagina=int(m.metas[i]["pagina"]),
                       similitud=float(sims[i]), texto=m.textos[i], metadatos=m.metas[i]) for i in orden]


def _buscar_aproximada(coleccion, vector: np.ndarray, k: int, donde: dict | None) -> list[Recuperado]:
    args = {"query_embeddings": [vector.tolist()], "n_results": min(k, coleccion.count()), "include": ["documents", "metadatas", "distances"]}
    if donde:
        args["where"] = donde
    r = coleccion.query(**args)
    salida = []
    for id_, doc, meta, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0]):
        salida.append(Recuperado(id=id_, documento=meta["documento"], version=meta["version"], pagina=int(meta["pagina"]),
                                 similitud=1.0 - float(dist), texto=doc, metadatos=meta))
    return sorted(salida, key=lambda x: -x.similitud)
