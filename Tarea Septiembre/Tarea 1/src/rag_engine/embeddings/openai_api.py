"""Embeddings por API de OpenAI (text-embedding-3-small). Requiere OPENAI_API_KEY y red; se cobra por token."""
from __future__ import annotations

import numpy as np

from rag_engine.embeddings.base import Embedder, ErrorEmbeddings
from rag_engine.llm.cost_log import sanear


def _tipo_error(exc: Exception) -> str:
    """Clasifica un error del SDK de OpenAI. ``cuota_insuficiente`` = la cuenta no tiene crédito (código ``insufficient_quota``): NO se reintenta ni se cobra."""
    codigo, nombre, texto = getattr(exc, "code", None), type(exc).__name__, str(exc).lower()
    if codigo == "insufficient_quota" or "insufficient_quota" in texto or "exceeded your current quota" in texto:
        return "cuota_insuficiente"
    if nombre == "RateLimitError" or getattr(exc, "status_code", None) == 429:
        return "limite_de_tasa"
    if nombre in ("AuthenticationError", "PermissionDeniedError"):
        return "autenticacion"
    if nombre in ("APIConnectionError", "APITimeoutError"):
        return "red"
    return "otro"


class OpenAIEmbeddings(Embedder):
    def __init__(self, modelo: str, api_key: str | None = None, precio_usd_por_millon: float | None = None,
                 dimensiones: int | None = None, prefijo_consulta: str = "", prefijo_pasaje: str = "", batch: int = 32,
                 normalizar: bool = True, max_tokens: int = 8191, cliente=None):
        super().__init__(batch, normalizar)
        self.name = modelo
        self.max_tokens = max_tokens
        self.precio = precio_usd_por_millon              # None = precio sin verificar: el costo queda en None
        self.dimensiones = dimensiones
        self.prefijo_consulta, self.prefijo_pasaje = prefijo_consulta, prefijo_pasaje
        if cliente is None:
            if not api_key:
                raise ErrorEmbeddings("Falta OPENAI_API_KEY para usar embeddings de OpenAI.", tipo="autenticacion", solicitud_enviada=False)
            from openai import OpenAI
            cliente = OpenAI(api_key=api_key)
        self._c = cliente
        self.dim = dimensiones or 1536                    # dimensión por defecto de text-embedding-3-small

    def contar_tokens(self, textos: list[str], es_consulta: bool = False) -> list[int]:
        # Solo una estimación (~4 caracteres por token en español); los tokens REALES vienen en la respuesta de la API.
        return [max(1, len(t) // 4) for t in textos]

    def _codificar(self, textos: list[str], es_consulta: bool):
        p = self.prefijo_consulta if es_consulta else self.prefijo_pasaje
        try:
            args = {"model": self.name, "input": [p + t for t in textos]}
            if self.dimensiones:
                args["dimensions"] = self.dimensiones
            r = self._c.embeddings.create(**args)
        except Exception as exc:
            raise ErrorEmbeddings(f"Falló la llamada a la API de embeddings ({type(exc).__name__}): {sanear(str(exc))}", tipo=_tipo_error(exc)) from exc
        matriz = np.array([d.embedding for d in sorted(r.data, key=lambda d: d.index)], dtype=np.float32)
        tokens = int(getattr(r.usage, "total_tokens", 0) or 0)
        costo = None if self.precio is None else tokens * self.precio / 1_000_000
        self.dim = matriz.shape[1]
        return matriz, tokens, costo
