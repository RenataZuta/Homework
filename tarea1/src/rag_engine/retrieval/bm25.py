"""BM25 (Okapi, variante de Lucene) sobre los MISMOS fragmentos del índice, con preprocesamiento en español.

Por qué BM25 además de embeddings: los embeddings se equivocan cuando la persona usa un vocabulario distinto al de la ley y aciertan menos en
coincidencias exactas (números de artículo, siglas, términos legales); BM25 hace lo contrario. Se implementa aquí (sin ``rank_bm25``) porque son ~60 líneas,
no añade una dependencia y evita el IDF negativo de algunas implementaciones.
Preprocesamiento: minúsculas, sin tildes, tokenización alfanumérica (los números de artículo son términos), sin stopwords y, opcionalmente, un stemmer LIGERO
de plurales (``retrieval.bm25.stemming``). El texto que se indexa es el encabezado del fragmento (p. ej. «Artículo 66. Adelantos») más su texto, igual que el
contexto que reciben los embeddings.
IMPORTANTE: el puntaje de BM25 NO es un coseno. El ``similitud`` de cada fragmento devuelto sigue siendo su coseno con la consulta (exacto), y es lo que usa la
compuerta del umbral; el puntaje de BM25 solo ordena (``Recuperado.puntaje``).
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict

import numpy as np

from rag_engine.embeddings.base import Embedder
from rag_engine.retrieval.semantic import Recuperado, matriz_de, recuperado_en, registrar_limpiador, similitudes

# Stopwords del español (sin tildes, como quedan tras normalizar). Se conservan «no» y los números; las palabras vacías no discriminan artículos.
STOPWORDS = frozenset("""
a al algo algunas algunos ante antes aqui asi aun aunque bajo cada como con contra cual cuales cuando cuyo de del desde donde durante e el ella ellas ello ellos en entre era eran es esa esas ese eso esos esta
estaba estan estar este esto estos fue fueron ha han hasta hay la las le les lo los mas me mi mis mucho muy nada ni nos nosotros o os otra otras otro otros para pero poco por porque que quien quienes se sea
sean segun ser si sido siempre sin sobre su sus tal tambien tan tanto te tiene tienen todo todos tu tus un una uno unos y ya yo
""".split())

_RE_TOKEN = re.compile(r"[a-z0-9]+")


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes (ñ -> n): «Garantía» y «garantia» son el mismo término."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def stem_ligero(t: str) -> str:
    """Plurales del español, sin diccionario: «contratos»->«contrato», «entidades»->«entidad», «garantías»->«garantia»->«garantia», «contrataciones»->«contratacion»."""
    if len(t) <= 3 or t.isdigit():
        return t
    if t.endswith("ciones"):
        return t[:-2]
    if t.endswith("es") and len(t) > 4 and t[-3] not in "aeiou":
        return t[:-2]
    if t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def tokenizar(texto: str, stemming: bool = False) -> list[str]:
    tokens = [t for t in _RE_TOKEN.findall(normalizar(texto)) if t not in STOPWORDS]
    return [stem_ligero(t) for t in tokens] if stemming else tokens


class IndiceBM25:
    """Índice invertido en memoria. ``documentos`` en el mismo orden que la matriz semántica (IDs ordenados)."""

    def __init__(self, documentos: list[str], k1: float = 1.5, b: float = 0.75, stemming: bool = False):
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 necesita k1 > 0 y 0 <= b <= 1")
        self.k1, self.b, self.stemming, self.n = k1, b, stemming, len(documentos)
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.largos = np.zeros(self.n, dtype=np.float32)
        for i, doc in enumerate(documentos):
            tokens = tokenizar(doc, stemming)
            self.largos[i] = len(tokens)
            for termino, tf in Counter(tokens).items():
                self.postings[termino].append((i, tf))
        self.promedio = float(self.largos.mean()) if self.n else 0.0

    def idf(self, termino: str) -> float:
        n_t = len(self.postings.get(termino, ()))
        return math.log(1.0 + (self.n - n_t + 0.5) / (n_t + 0.5))            # siempre >= 0

    def puntuar(self, consulta: str) -> np.ndarray:
        """Puntaje BM25 de la consulta contra cada documento (0 si no comparten ningún término)."""
        puntajes = np.zeros(self.n, dtype=np.float32)
        for termino in set(tokenizar(consulta, self.stemming)):
            idf = self.idf(termino)
            for i, tf in self.postings.get(termino, ()):
                norm = tf + self.k1 * (1 - self.b + self.b * self.largos[i] / (self.promedio or 1.0))
                puntajes[i] += idf * tf * (self.k1 + 1) / norm
        return puntajes


_CACHE: dict[tuple, IndiceBM25] = {}
registrar_limpiador(_CACHE.clear)


def indice_de(coleccion, k1: float, b: float, stemming: bool, usar_encabezado: bool) -> IndiceBM25:
    """El índice BM25 de la colección (se construye una vez por proceso y parámetros; no toca el índice vectorial)."""
    m = matriz_de(coleccion)
    clave = (str(coleccion.id), coleccion.count(), k1, b, stemming, usar_encabezado)
    if clave not in _CACHE:
        docs = [f"{meta.get('encabezado', '')} {texto}" if usar_encabezado else texto for meta, texto in zip(m.metas, m.textos)]
        _CACHE[clave] = IndiceBM25(docs, k1, b, stemming)
    return _CACHE[clave]


def ranking_bm25(puntajes: np.ndarray, ids: list[str], k: int) -> list[int]:
    """Posiciones de los k mejores con puntaje > 0, de mayor a menor; empate -> por ID (determinista)."""
    positivos = [i for i in np.flatnonzero(puntajes > 0)]
    return sorted(positivos, key=lambda i: (-float(puntajes[i]), ids[i]))[:k]


def buscar_bm25(coleccion, embedder: Embedder, consulta: str, k: int, *, k1: float = 1.5, b: float = 0.75, stemming: bool = False,
                usar_encabezado: bool = True) -> list[Recuperado]:
    """Los k fragmentos de mayor puntaje BM25. Si la consulta no comparte ningún término con el corpus, devuelve [] (no hay coincidencia léxica)."""
    m, cosenos = similitudes(coleccion, embedder.embed_query(consulta))
    idx = indice_de(coleccion, k1, b, stemming, usar_encabezado)
    puntajes = idx.puntuar(consulta)
    return [recuperado_en(m, i, cosenos[i], float(puntajes[i])) for i in ranking_bm25(puntajes, m.ids, k)]
