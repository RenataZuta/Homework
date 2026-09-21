"""Dobles de prueba compartidos. El embedder falso es determinista, rápido y algo "semántico": las palabras compartidas
entre consulta y fragmento suben la similitud (bolsa de palabras hasheada), lo que permite probar la recuperación sin modelos."""
import hashlib
import re
import unicodedata

import numpy as np

from rag_engine.embeddings.base import Embedder


def _palabras(t: str) -> list[str]:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]{3,}", t)


class EmbedderFalso(Embedder):
    name = "falso/bolsa-de-palabras"
    max_tokens = 512

    def __init__(self, dim: int = 128, batch: int = 8, normalizar: bool = True):
        super().__init__(batch, normalizar)
        self.dim = dim
        self.textos_embebidos: list[str] = []          # para comprobar QUÉ se volvió a embeber

    def contar_tokens(self, textos, es_consulta=False):
        return [len(_palabras(t)) for t in textos]

    def _codificar(self, textos, es_consulta):
        m = np.zeros((len(textos), self.dim), dtype=np.float32)
        for i, t in enumerate(textos):
            for w in _palabras(t):
                m[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        if not es_consulta:
            self.textos_embebidos += list(textos)
        return m, sum(self.contar_tokens(textos)), 0.0
