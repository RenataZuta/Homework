"""Embeddings locales con sentence-transformers (CPU). Cuesta USD 0 y no necesita internet ni claves tras la primera descarga."""
from __future__ import annotations

import numpy as np

from rag_engine.embeddings.base import Embedder, ErrorEmbeddings


class LocalSentenceTransformers(Embedder):
    def __init__(self, modelo: str, prefijo_consulta: str = "", prefijo_pasaje: str = "", batch: int = 32,
                 normalizar: bool = True, dispositivo: str = "cpu", modelo_cargado=None):
        super().__init__(batch, normalizar)
        self.name = modelo
        self.prefijo_consulta, self.prefijo_pasaje = prefijo_consulta, prefijo_pasaje
        if modelo_cargado is None:
            try:
                from sentence_transformers import SentenceTransformer
                modelo_cargado = SentenceTransformer(modelo, device=dispositivo)
            except Exception as exc:                                  # descarga, disco, nombre inválido…
                raise ErrorEmbeddings(f"No se pudo cargar el modelo local '{modelo}': {exc}") from exc
        self._m = modelo_cargado
        self.dim = int(self._m.get_sentence_embedding_dimension())
        # longitud máxima REAL del modelo (la de su sentence_bert_config), no la que diga la config
        self.max_tokens = int(self._m.max_seq_length)

    def _con_prefijo(self, textos: list[str], es_consulta: bool) -> list[str]:
        p = self.prefijo_consulta if es_consulta else self.prefijo_pasaje
        return [p + t for t in textos]

    def contar_tokens(self, textos: list[str], es_consulta: bool = False) -> list[int]:
        enc = self._m.tokenizer(self._con_prefijo(textos, es_consulta), add_special_tokens=True, truncation=False)["input_ids"]
        return [len(x) for x in enc]

    def _codificar(self, textos: list[str], es_consulta: bool):
        entrada = self._con_prefijo(textos, es_consulta)
        matriz = self._m.encode(entrada, batch_size=self.batch, convert_to_numpy=True, normalize_embeddings=False,
                                show_progress_bar=False)
        tokens = sum(min(n, self.max_tokens) for n in self.contar_tokens(textos, es_consulta))
        return np.asarray(matriz), tokens, 0.0
