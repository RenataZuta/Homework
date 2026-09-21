"""Interfaz común de embeddings.

Contrato (lo que el resto del sistema puede asumir de cualquier implementación):
  * ``embed_passages(textos)`` y ``embed_query(texto)`` devuelven vectores NORMALIZADOS (norma 1) de dimensión ``dim``:
    el producto punto es la similitud coseno.
  * Los prefijos de consulta/pasaje que exija el modelo (p. ej. E5: «query: » / «passage: ») los aplica la implementación
    a partir de config.yaml; quien llama nunca los pone.
  * ``max_tokens`` es la longitud máxima REAL de entrada del modelo; lo que exceda se trunca en silencio, por eso existe
    ``contar_tokens`` (para medir cuántos fragmentos se truncarían).
  * ``contabilidad`` acumula llamadas, textos, tokens, segundos y costo en USD (None si el precio no está verificado).
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from rag_engine.limites import ErrorProveedor


class ErrorEmbeddings(ErrorProveedor):
    """Fallo del proveedor de embeddings (red, clave, cuota…). Se propaga como error, nunca como un vector falso.
    ``tipo``: autenticacion | limite_de_tasa | cuota_agotada | cuota_insuficiente (sin crédito en la cuenta) | red | servidor | solicitud | otro."""

    def __init__(self, mensaje: str, tipo: str = "otro", *, solicitud_enviada: bool = True, espera_sugerida_s: float | None = None):
        super().__init__(tipo, mensaje, solicitud_enviada=solicitud_enviada, espera_sugerida_s=espera_sugerida_s)


@dataclass
class Contabilidad:
    llamadas: int = 0
    textos: int = 0
    tokens: int = 0
    segundos: float = 0.0
    costo_usd: float | None = 0.0

    def registrar(self, textos: int, tokens: int, segundos: float, costo: float | None) -> None:
        self.llamadas += 1
        self.textos += textos
        self.tokens += tokens
        self.segundos += segundos
        if self.costo_usd is not None:
            self.costo_usd = None if costo is None else self.costo_usd + costo

    def como_dict(self) -> dict:
        return {"llamadas": self.llamadas, "textos": self.textos, "tokens": self.tokens,
                "segundos": round(self.segundos, 3), "costo_usd": self.costo_usd}


def normalizar_filas(m: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(normas == 0, 1.0, normas)


class Embedder(ABC):
    name: str
    dim: int
    max_tokens: int
    tokens_reportados: bool = True      # False si la API no informa los tokens usados (p. ej. Gemini): la contabilidad los deja en 0 y así se declara

    def __init__(self, batch: int = 32, normalizar: bool = True):
        self.batch = batch
        self.normalizar = normalizar
        self.contabilidad = Contabilidad()

    @abstractmethod
    def _codificar(self, textos: list[str], es_consulta: bool) -> tuple[np.ndarray, int, float | None]:
        """Devuelve (matriz n×dim, tokens usados, costo USD o None) para UN lote. Debe aplicar los prefijos."""

    @abstractmethod
    def contar_tokens(self, textos: list[str], es_consulta: bool = False) -> list[int]:
        """Tokens de cada texto TAL COMO llega al modelo (incluidos los prefijos)."""

    def _procesar(self, textos: list[str], es_consulta: bool) -> np.ndarray:
        if not textos:
            return np.zeros((0, self.dim), dtype=np.float32)
        partes = []
        for i in range(0, len(textos), self.batch):
            lote = textos[i:i + self.batch]
            t0 = time.perf_counter()
            matriz, tokens, costo = self._codificar(lote, es_consulta)
            self.contabilidad.registrar(len(lote), tokens, time.perf_counter() - t0, costo)
            partes.append(np.asarray(matriz, dtype=np.float32))
        m = np.vstack(partes)
        return normalizar_filas(m) if self.normalizar else m

    def embed_passages(self, textos: list[str]) -> np.ndarray:
        return self._procesar(list(textos), es_consulta=False)

    def embed_query(self, texto: str) -> np.ndarray:
        return self._procesar([texto], es_consulta=True)[0]
