"""Fábrica: crea el embedder que indica config.yaml (embeddings.proveedor). Cambiar de modelo = editar la config."""
from __future__ import annotations

from rag_engine.config import Config
from rag_engine.embeddings.base import Embedder, ErrorEmbeddings
from rag_engine.llm.pricing import cargar_precio_embedding

PROVEEDORES = ("local", "openai", "gemini")


def crear_embedder(cfg: Config, proveedor: str | None = None, sobreescribir: dict | None = None) -> Embedder:
    """`proveedor` y `sobreescribir` (modelo, prefijos…) permiten a los scripts de comparación probar candidatos."""
    proveedor = proveedor or cfg.get("embeddings.proveedor")
    if proveedor not in PROVEEDORES:
        raise ErrorEmbeddings(f"Proveedor de embeddings desconocido: '{proveedor}'. Opciones: {', '.join(PROVEEDORES)}.")
    ajustes = {**cfg.get(f"embeddings.{proveedor}"), **(sobreescribir or {})}
    comunes = {"batch": cfg.get("embeddings.batch"), "normalizar": cfg.get("embeddings.normalizar")}
    prefijos = {"prefijo_consulta": ajustes.get("prefijo_consulta", ""), "prefijo_pasaje": ajustes.get("prefijo_pasaje", "")}

    if proveedor == "local":
        from rag_engine.embeddings.local_st import LocalSentenceTransformers
        return LocalSentenceTransformers(modelo=ajustes["modelo"], dispositivo=ajustes.get("dispositivo", "cpu"), **prefijos, **comunes)

    if proveedor == "gemini":
        from rag_engine.embeddings.gemini_api import GeminiEmbeddings
        from rag_engine.limites import Limitador, PoliticaReintentos
        lim = cfg.get("embeddings.limites")
        return GeminiEmbeddings(
            modelo=ajustes["modelo"], api_key=cfg.requerir_env(ajustes["env_clave"], para="embeddings por API de Gemini"), dimensiones=ajustes["dimensiones"], max_tokens=ajustes.get("max_tokens", 8192), url_base=ajustes["url_base"],
            timeout_s=float(ajustes["timeout_segundos"]), nivel=ajustes["nivel"], env_clave=ajustes["env_clave"],
            precio_usd_por_millon=cargar_precio_embedding(cfg.ruta("pricing"), ajustes["modelo"], "gemini_embeddings"),
            limitador=Limitador(lim["rpm"]), politica=PoliticaReintentos(lim["reintentos"], lim["espera_inicial_s"], lim["factor_espera"], lim["espera_max_s"], lim["jitter"]),
            **prefijos, **comunes)

    from rag_engine.embeddings.openai_api import OpenAIEmbeddings
    return OpenAIEmbeddings(
        modelo=ajustes["modelo"], api_key=cfg.requerir_env("OPENAI_API_KEY", para="embeddings por API"),
        precio_usd_por_millon=cargar_precio_embedding(cfg.ruta("pricing"), ajustes["modelo"]), dimensiones=ajustes.get("dimensiones"),
        max_tokens=ajustes.get("max_tokens", 8191), **prefijos, **comunes)
