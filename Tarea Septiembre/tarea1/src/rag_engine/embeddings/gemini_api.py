"""Embeddings por API de Google Gemini (``gemini-embedding-2``), con capa gratuita. Requiere GEMINI_API_KEY y red.

Contrato REST (documentación oficial, verificada el 2026-09-21): ``POST {url_base}/models/{modelo}:batchEmbedContents`` con
``{"requests": [{"model": "models/<modelo>", "content": {"parts": [{"text": ...}]}, "outputDimensionality": N}, ...]}`` y respuesta
``{"embeddings": [{"values": [...]}, ...]}``. Cada texto va en SU PROPIA petición del lote: varias ``parts`` en un mismo ``content`` se
agregarían en un solo vector. Este modelo no usa ``task_type``: la tarea se indica en el propio texto con las plantillas de la guía
(consulta ``task: search result | query: …``, pasaje ``title: none | text: …``), que vienen de config.yaml.
La respuesta NO informa tokens: se declara con ``tokens_reportados = False`` y el costo real es 0 en la capa gratuita.
Throttle por RPM y reintentos con backoff (ver limites.py); la cuota agotada sale como ``ErrorEmbeddings`` estructurado, nunca como vectores falsos.
"""
from __future__ import annotations

import numpy as np

from rag_engine.embeddings.base import Embedder, ErrorEmbeddings
from rag_engine.limites import ErrorProveedor, Limitador, PoliticaReintentos
from rag_engine.llm.google import URL_BASE_POR_DEFECTO, clasificar_http_google
from rag_engine.llm.transporte import Transporte, post_json


class GeminiEmbeddings(Embedder):
    tokens_reportados = False

    def __init__(self, modelo: str, api_key: str | None = None, dimensiones: int = 768, prefijo_consulta: str = "", prefijo_pasaje: str = "",
                 batch: int = 32, normalizar: bool = True, max_tokens: int = 8192, url_base: str = URL_BASE_POR_DEFECTO, timeout_s: float = 60.0,
                 nivel: str = "gratuito", precio_usd_por_millon: float | None = None, limitador: Limitador | None = None,
                 politica: PoliticaReintentos | None = None, transporte: Transporte = post_json, env_clave: str = "GEMINI_API_KEY"):
        super().__init__(batch, normalizar)
        if not api_key:
            raise ErrorEmbeddings(f"Falta {env_clave} para usar embeddings de Gemini (clave gratuita de Google AI Studio).", tipo="autenticacion", solicitud_enviada=False)
        self.name, self.dim, self.max_tokens = modelo, dimensiones, max_tokens
        self.prefijo_consulta, self.prefijo_pasaje = prefijo_consulta, prefijo_pasaje
        self.nivel, self.precio = nivel, precio_usd_por_millon             # el precio de pago solo sirve de referencia: no hay tokens que multiplicar
        self._clave, self._url_base, self._timeout, self._transporte, self._env = api_key, url_base.rstrip("/"), timeout_s, transporte, env_clave
        self.limitador, self.politica = limitador, politica or PoliticaReintentos(4, 4.0, 2.0, 60.0, 0.25)

    def contar_tokens(self, textos: list[str], es_consulta: bool = False) -> list[int]:
        # Solo una estimación (~4 caracteres por token en español): la API no devuelve conteos ni publicamos un tokenizador de Google.
        return [max(1, len(t) // 4) for t in textos]

    def _una_peticion(self, textos: list[str], es_consulta: bool) -> np.ndarray:
        p = self.prefijo_consulta if es_consulta else self.prefijo_pasaje
        pedidos = [{"model": f"models/{self.name}", "content": {"parts": [{"text": p + t}]}, "outputDimensionality": self.dim} for t in textos]
        try:
            estado, datos, cabeceras = self._transporte(f"{self._url_base}/models/{self.name}:batchEmbedContents", {"x-goog-api-key": self._clave},
                                                        {"requests": pedidos}, self._timeout)
        except ErrorProveedor as exc:
            raise ErrorEmbeddings(exc.mensaje, tipo=exc.tipo) from exc
        if estado != 200:
            tipo, mensaje, espera = clasificar_http_google(estado, datos, cabeceras, self._env)
            raise ErrorEmbeddings(mensaje, tipo=tipo, espera_sugerida_s=espera)
        vectores = [e.get("values") for e in (datos or {}).get("embeddings", []) if isinstance(e, dict)]
        if len(vectores) != len(textos) or any(not v for v in vectores):
            raise ErrorEmbeddings(f"Gemini devolvió {len(vectores)} vectores para {len(textos)} textos.", tipo="respuesta_malformada")
        matriz = np.array(vectores, dtype=np.float32)
        if matriz.shape[1] != self.dim:
            raise ErrorEmbeddings(f"Gemini devolvió vectores de {matriz.shape[1]} dimensiones y se pidieron {self.dim}.", tipo="respuesta_malformada")
        return matriz

    def _codificar(self, textos: list[str], es_consulta: bool):
        matriz = self.politica.ejecutar(lambda: self._una_peticion(textos, es_consulta), self.limitador)
        return matriz, 0, (0.0 if self.nivel == "gratuito" else None)       # tokens no informados; costo real 0 solo en la capa gratuita
