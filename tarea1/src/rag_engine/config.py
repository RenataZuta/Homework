"""Carga y validación de la configuración del proyecto.

- ``config.yaml`` (versionado): rutas, modelos, umbrales, prompts y mensajes.
- ``.env`` (NO versionado): credenciales; se leen bajo demanda con ``requerir_env``.

Si falta algo se lanza ``ConfigError`` con un mensaje que dice QUÉ falta y CÓMO
arreglarlo, en lugar de fallar más adelante con un ``KeyError`` opaco.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# tarea1/src/rag_engine/config.py  ->  parents[2] == tarea1/
DIRECTORIO_PROYECTO = Path(__file__).resolve().parents[2]
RUTA_CONFIG_POR_DEFECTO = DIRECTORIO_PROYECTO / "config.yaml"

MODOS_RETRIEVAL = ("semantico", "bm25", "hibrido")
PROVEEDORES_EMBEDDINGS = ("local", "openai", "gemini")
PROVEEDORES_LLM = ("gemini", "anthropic")
NIVELES = ("gratuito", "pago")

# Claves que deben existir y no ser nulas. (Es estructura, no valores: los valores viven en config.yaml.)
CLAVES_REQUERIDAS = (
    "paths.raw", "paths.manifest", "paths.processed", "paths.articulos_modificados",
    "paths.index", "paths.index_cmp", "paths.eval_preguntas", "paths.eval_results", "paths.logs",
    "paths.llm_calls_log", "paths.pricing", "paths.bot_db", "paths.docs",
    "descarga.user_agent", "descarga.timeout_segundos", "descarga.reintentos",
    "descarga.espera_reintento_segundos", "descarga.aviso_tamano_mb",
    "extraccion.umbral_caracteres_ocr", "extraccion.dpi", "extraccion.idioma_ocr",
    "extraccion.motor_ocr", "extraccion.rangos_paginas", "extraccion.ocr.banda_cabecera", "extraccion.prioridad_ocr",
    "extraccion.codigo_fin_norma", "extraccion.mapeo.motor", "extraccion.mapeo.dpi",
    "chunking.unidad", "chunking.configuraciones", "chunking.activa", "chunking.contexto_encabezado",
    "chunking.articulo_maximo.ley", "chunking.articulo_maximo.reglamento", "indexacion.coleccion", "indexacion.lote_upsert",
    "embeddings.proveedor", "embeddings.batch", "embeddings.normalizar",
    "retrieval.modo", "retrieval.top_k", "retrieval.umbral_similitud", "retrieval.umbral_calibrado", "retrieval.versiones.activo", "retrieval.versiones.max_fragmentos_forzados", "retrieval.versiones.max_originales_forzados",
    "llm.provider", "llm.nivel", "llm.max_tokens", "llm.timeout_segundos",
    "llm.limites.rpm", "llm.limites.reintentos", "llm.limites.espera_inicial_s", "llm.limites.factor_espera", "llm.limites.espera_max_s", "llm.limites.jitter",
    "embeddings.limites.rpm", "embeddings.limites.reintentos", "embeddings.limites.espera_inicial_s", "embeddings.limites.factor_espera",
    "embeddings.limites.espera_max_s", "embeddings.limites.jitter", "paths.cache_llm", "eval.cache_llm", "mensajes.aviso_privacidad", "mensajes.error_cuota",
    "pricing.archivo",
    "prompts.sistema", "prompts.usuario", "prompts.herramienta_nombre",
    "prompts.herramienta_descripcion", "prompts.etiqueta_fragmento",
    "mensajes.abstencion", "mensajes.error_generico", "mensajes.error_config",
    "mensajes.indice_faltante", "mensajes.aviso_version",
    "mensajes.limite_sesion", "mensajes.limite_global",
    "eval.ks", "eval.barrido_umbral.desde", "eval.barrido_umbral.hasta", "eval.barrido_umbral.paso", "eval.barrido_umbral.beta", "eval.set_validado", "eval.requisitos_set.in_domain", "eval.requisitos_set.out_of_domain", "eval.requisitos_set.modificadas_2026", "eval.requisitos_set.coloquiales", "eval.min_recall_at_3", "eval.codigo_salida_fallo",
    "bot.modo", "bot.limite_consultas_por_usuario_dia", "bot.zona_horaria_limite",
    "deploy.topes.consultas_por_sesion", "deploy.topes.consultas_globales_por_dia",
)

_FALTA = object()


class ConfigError(Exception):
    """Configuración ausente o inválida. El mensaje está pensado para mostrarse tal cual."""


def _buscar(datos: dict[str, Any], ruta: str) -> Any:
    actual: Any = datos
    for parte in ruta.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return _FALTA
        actual = actual[parte]
    return actual


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _validar(datos: dict[str, Any]) -> list[str]:
    """Devuelve la lista de problemas encontrados (vacía si todo está bien)."""
    errores: list[str] = []

    for ruta in CLAVES_REQUERIDAS:
        valor = _buscar(datos, ruta)
        if valor is _FALTA:
            errores.append(f"falta la clave '{ruta}'")
        elif valor is None:
            errores.append(f"la clave '{ruta}' está vacía (null)")

    # ── documentos ──
    documentos = datos.get("documentos")
    ids: list[str] = []
    if not isinstance(documentos, list) or not documentos:
        errores.append("'documentos' debe ser una lista con al menos un documento")
    else:
        for i, doc in enumerate(documentos):
            if not isinstance(doc, dict):
                errores.append(f"documentos[{i}] debe ser un mapa")
                continue
            for campo in ("id", "nombre", "archivo", "url", "version", "rol"):
                if not doc.get(campo):
                    errores.append(f"documentos[{i}] no tiene '{campo}'")
            if doc.get("id"):
                ids.append(doc["id"])
        repetidos = sorted({x for x in ids if ids.count(x) > 1})
        if repetidos:
            errores.append(f"ids de documento repetidos: {', '.join(repetidos)}")
        for doc in documentos:
            if isinstance(doc, dict) and doc.get("modifica") and doc["modifica"] not in ids:
                errores.append(f"documento '{doc.get('id')}' modifica a '{doc['modifica']}', que no está en 'documentos'")
        rangos = _buscar(datos, "extraccion.rangos_paginas")
        if isinstance(rangos, dict):
            for doc_id in ids:
                if doc_id not in rangos:
                    errores.append(f"'extraccion.rangos_paginas' no tiene el documento '{doc_id}' (usa null para todas las páginas)")

    # ── chunking ──
    configs = _buscar(datos, "chunking.configuraciones")
    if configs is not _FALTA and configs is not None:
        if not isinstance(configs, list) or not configs:
            errores.append("'chunking.configuraciones' debe ser una lista no vacía")
        else:
            nombres = []
            for i, c in enumerate(configs):
                if not isinstance(c, dict) or not c.get("nombre"):
                    errores.append(f"chunking.configuraciones[{i}] necesita 'nombre'")
                    continue
                nombres.append(c["nombre"])
                tamano, solape = c.get("tamano"), c.get("solapamiento")
                if not _es_numero(tamano) or tamano <= 0:
                    errores.append(f"chunking '{c['nombre']}': 'tamano' debe ser un número > 0")
                elif not _es_numero(solape) or not (0 <= solape < tamano):
                    errores.append(f"chunking '{c['nombre']}': 'solapamiento' debe estar entre 0 y menos que 'tamano'")
            activa = _buscar(datos, "chunking.activa")
            if activa not in (_FALTA, None) and activa not in nombres:
                errores.append(f"'chunking.activa' ('{activa}') no coincide con ninguna configuración: {', '.join(nombres)}")

    # ── valores acotados ──
    modo = _buscar(datos, "retrieval.modo")
    if modo not in (_FALTA, None) and modo not in MODOS_RETRIEVAL:
        errores.append(f"'retrieval.modo' debe ser uno de {MODOS_RETRIEVAL}, no '{modo}'")

    proveedor = _buscar(datos, "embeddings.proveedor")
    if proveedor not in (_FALTA, None):
        if proveedor not in PROVEEDORES_EMBEDDINGS:
            errores.append(f"'embeddings.proveedor' debe ser uno de {PROVEEDORES_EMBEDDINGS}, no '{proveedor}'")
        elif not _buscar(datos, f"embeddings.{proveedor}.modelo") or _buscar(datos, f"embeddings.{proveedor}.modelo") is _FALTA:
            errores.append(f"falta 'embeddings.{proveedor}.modelo' (es el proveedor activo)")

    # ── proveedor de LLM: el activo debe tener modelo y nombre de variable; Anthropic no tiene capa gratuita ──
    prov_llm, nivel_llm = _buscar(datos, "llm.provider"), _buscar(datos, "llm.nivel")
    if prov_llm not in (_FALTA, None):
        if prov_llm not in PROVEEDORES_LLM:
            errores.append(f"'llm.provider' debe ser uno de {PROVEEDORES_LLM}, no '{prov_llm}'")
        else:
            for campo in ("modelo", "env_clave"):
                if not _buscar(datos, f"llm.proveedores.{prov_llm}.{campo}") or _buscar(datos, f"llm.proveedores.{prov_llm}.{campo}") is _FALTA:
                    errores.append(f"falta 'llm.proveedores.{prov_llm}.{campo}' (es el proveedor activo)")
    if nivel_llm not in (_FALTA, None):
        if nivel_llm not in NIVELES:
            errores.append(f"'llm.nivel' debe ser uno de {NIVELES}, no '{nivel_llm}'")
        elif nivel_llm == "gratuito" and prov_llm == "anthropic":
            errores.append("'llm.nivel: gratuito' no es válido con 'llm.provider: anthropic': Anthropic no ofrece capa gratuita (usa nivel: pago)")
    for grupo in ("llm.limites", "embeddings.limites"):
        for campo, minimo in (("rpm", 0), ("espera_inicial_s", 0), ("espera_max_s", 0)):
            v = _buscar(datos, f"{grupo}.{campo}")
            if v not in (_FALTA, None) and not (_es_numero(v) and v > minimo):
                errores.append(f"'{grupo}.{campo}' debe ser un número > {minimo}, no {v!r}")
        v = _buscar(datos, f"{grupo}.reintentos")
        if v not in (_FALTA, None) and not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
            errores.append(f"'{grupo}.reintentos' debe ser un entero >= 0, no {v!r}")
        v = _buscar(datos, f"{grupo}.factor_espera")
        if v not in (_FALTA, None) and not (_es_numero(v) and v >= 1):
            errores.append(f"'{grupo}.factor_espera' debe ser un número >= 1, no {v!r}")
        v = _buscar(datos, f"{grupo}.jitter")
        if v not in (_FALTA, None) and not (_es_numero(v) and 0 <= v <= 1):
            errores.append(f"'{grupo}.jitter' debe ser un número entre 0 y 1, no {v!r}")

    for ruta, minimo, maximo in (
        ("retrieval.umbral_similitud", 0.0, 1.0),
        ("eval.min_recall_at_3", 0.0, 1.0),
        ("llm.temperatura", 0.0, 1.0),
    ):
        valor = _buscar(datos, ruta)
        if valor not in (_FALTA, None) and not (_es_numero(valor) and minimo <= valor <= maximo):
            errores.append(f"'{ruta}' debe ser un número entre {minimo} y {maximo}, no {valor!r}")

    for ruta in ("retrieval.top_k", "llm.max_tokens", "embeddings.batch"):
        valor = _buscar(datos, ruta)
        if valor not in (_FALTA, None) and not (isinstance(valor, int) and not isinstance(valor, bool) and valor >= 1):
            errores.append(f"'{ruta}' debe ser un entero >= 1, no {valor!r}")

    return errores


@dataclass(frozen=True)
class Config:
    """Configuración cargada y validada, con acceso por ruta punteada (``"retrieval.top_k"``)."""

    datos: dict[str, Any]
    archivo: Path

    @property
    def base(self) -> Path:
        """Carpeta que contiene config.yaml; contra ella se resuelven las rutas relativas."""
        return self.archivo.parent

    def get(self, ruta: str, defecto: Any = _FALTA) -> Any:
        valor = _buscar(self.datos, ruta)
        if valor is _FALTA:
            if defecto is _FALTA:
                raise ConfigError(f"Falta la clave '{ruta}' en {self.archivo.name}.")
            return defecto
        return valor

    def __getitem__(self, ruta: str) -> Any:
        return self.get(ruta)

    def ruta(self, nombre: str) -> Path:
        """Ruta absoluta de ``paths.<nombre>`` (las rutas del YAML son relativas a ``base``)."""
        relativa = self.get(f"paths.{nombre}")
        return (self.base / relativa).resolve()

    @property
    def documentos(self) -> list[dict[str, Any]]:
        return list(self.datos["documentos"])

    def documento(self, doc_id: str) -> dict[str, Any]:
        for doc in self.datos["documentos"]:
            if doc["id"] == doc_id:
                return doc
        disponibles = ", ".join(d["id"] for d in self.datos["documentos"])
        raise ConfigError(f"El documento '{doc_id}' no está en config.yaml. Disponibles: {disponibles}")

    @property
    def chunking_activo(self) -> dict[str, Any]:
        activa = self.get("chunking.activa")
        for c in self.get("chunking.configuraciones"):
            if c["nombre"] == activa:
                return c
        raise ConfigError(f"'chunking.activa' ('{activa}') no existe en 'chunking.configuraciones'.")

    @staticmethod
    def env(nombre: str) -> str | None:
        """Valor de una variable de entorno, o None si no existe o está vacía."""
        valor = os.environ.get(nombre, "").strip()
        return valor or None

    def requerir_env(self, nombre: str, para: str = "") -> str:
        """Como ``env`` pero falla con un mensaje claro. Nunca imprime valores."""
        valor = self.env(nombre)
        if valor is None:
            motivo = f" (necesaria para {para})" if para else ""
            raise ConfigError(
                f"Falta la variable de entorno {nombre}{motivo}. "
                f"Copia .env.example a .env y complétala en tu máquina; "
                f"nunca la pongas en config.yaml ni en el repositorio."
            )
        return valor


def cargar_config(ruta: str | Path | None = None, cargar_env: bool = True) -> Config:
    """Lee y valida config.yaml; con ``cargar_env`` también lee el ``.env`` de la misma carpeta."""
    archivo = Path(ruta).resolve() if ruta else RUTA_CONFIG_POR_DEFECTO
    if not archivo.is_file():
        raise ConfigError(f"No se encontró el archivo de configuración: {archivo}")
    try:
        datos = yaml.safe_load(archivo.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{archivo.name} no es un YAML válido ({archivo}): {exc}") from exc
    if not isinstance(datos, dict):
        raise ConfigError(f"{archivo.name} está vacío o no es un mapa YAML ({archivo}).")
    errores = _validar(datos)
    if errores:
        detalle = "\n".join(f"  - {e}" for e in errores)
        raise ConfigError(f"Configuración inválida en {archivo}:\n{detalle}")
    if cargar_env:
        load_dotenv(archivo.parent / ".env", override=False)
    return Config(datos=datos, archivo=archivo)


@lru_cache(maxsize=1)
def obtener_config() -> Config:
    """Configuración por defecto, cargada una sola vez por proceso."""
    return cargar_config()
