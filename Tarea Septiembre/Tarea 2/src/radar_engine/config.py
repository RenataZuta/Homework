"""Config con acceso por ruta punteada (``"retrieval.top_k"``), compatible con la interfaz que esperan
``rag_engine.embeddings.factory.crear_embedder`` y ``rag_engine.llm.factory.crear_cliente_llm`` de la Tarea 1
(``.get(ruta, defecto)`` y ``.requerir_env(nombre, para=...)``): así esas dos fábricas se reutilizan TAL CUAL,
sin ningún ``if`` que distinga "config de la Tarea 1" de "config de la Tarea 2".

No reimplementa la validación completa de ``rag_engine.config`` (esa lista de claves es de la Tarea 1: habla
de "documentos", "chunking.articulo_maximo.ley", etc., que no existen aquí). ``validar()`` solo comprueba las
claves que de verdad usa el motor de la Tarea 2.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

RUTA_CONFIG_POR_DEFECTO = Path(__file__).resolve().parents[2] / "config.yaml"

CLAVES_REQUERIDAS = (
    "paths.processed", "paths.outputs", "paths.logs", "paths.index", "paths.eval_radar",
    "paths.eval_radar_resultados", "paths.llm_calls_log", "paths.pricing", "paths.riesgo_json", "paths.riesgo_md",
    "validation.output_file",
    "embeddings.proveedor", "embeddings.batch", "embeddings.normalizar",
    "indexacion.coleccion", "indexacion.version_esquema", "indexacion.lote_upsert", "indexacion.campos_texto",
    "retrieval.top_k", "retrieval.umbral_similitud", "retrieval.busqueda",
    "llm.provider", "llm.nivel", "llm.max_tokens", "llm.timeout_segundos",
    "llm.limites.rpm", "llm.limites.reintentos", "llm.limites.espera_inicial_s", "llm.limites.factor_espera",
    "llm.limites.espera_max_s", "llm.limites.jitter",
    "prompts.sistema", "prompts.usuario", "prompts.herramienta_nombre", "prompts.herramienta_descripcion",
    "prompts.etiqueta_proceso", "prompts.herramienta_campos",
    "mensajes.abstencion", "mensajes.abstencion_sin_candidatos", "mensajes.error_generico", "mensajes.indice_faltante",
    "risk.min_procesos_adjudicados", "risk.top_n",
    "eval.ks",
    "territory.geojson_file", "territory.geojson_key",
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


def _validar(datos: dict[str, Any]) -> list[str]:
    errores = []
    for ruta in CLAVES_REQUERIDAS:
        valor = _buscar(datos, ruta)
        if valor is _FALTA:
            errores.append(f"falta la clave '{ruta}'")
        elif valor is None:
            errores.append(f"la clave '{ruta}' está vacía (null)")
    proveedor = _buscar(datos, "embeddings.proveedor")
    if proveedor not in (_FALTA, None) and (_buscar(datos, f"embeddings.{proveedor}.modelo") in (_FALTA, None)):
        errores.append(f"falta 'embeddings.{proveedor}.modelo' (es el proveedor activo)")
    prov_llm = _buscar(datos, "llm.provider")
    if prov_llm not in (_FALTA, None):
        for campo in ("modelo", "env_clave"):
            if _buscar(datos, f"llm.proveedores.{prov_llm}.{campo}") in (_FALTA, None):
                errores.append(f"falta 'llm.proveedores.{prov_llm}.{campo}' (es el proveedor activo)")
    umbral = _buscar(datos, "retrieval.umbral_similitud")
    if umbral not in (_FALTA, None) and not (isinstance(umbral, (int, float)) and 0.0 <= umbral <= 1.0):
        errores.append(f"'retrieval.umbral_similitud' debe ser un número entre 0 y 1, no {umbral!r}")
    return errores


@dataclass(frozen=True)
class Config:
    datos: dict[str, Any]
    archivo: Path

    @property
    def base(self) -> Path:
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
        """Ruta absoluta de ``paths.<nombre>`` (relativa a la carpeta que contiene config.yaml)."""
        relativa = self.get(f"paths.{nombre}")
        return (self.base / relativa).resolve()

    @staticmethod
    def env(nombre: str) -> str | None:
        valor = os.environ.get(nombre, "").strip()
        return valor or None

    def requerir_env(self, nombre: str, para: str = "") -> str:
        valor = self.env(nombre)
        if valor is None:
            motivo = f" (necesaria para {para})" if para else ""
            raise ConfigError(
                f"Falta la variable de entorno {nombre}{motivo}. Copia .env.example a .env y complétala "
                f"en tu máquina (puedes reutilizar el mismo .env de la Tarea 1); nunca la pongas en config.yaml."
            )
        return valor


def cargar_config(ruta: str | Path | None = None, cargar_env: bool = True) -> Config:
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
        # Primero el .env PROPIO de la Tarea 2; si falta una clave, se completa con el de la Tarea 1
        # (mismas variables, ver .env.example). override=False: el que se cargó primero manda.
        load_dotenv(archivo.parent / ".env", override=False)
        load_dotenv(archivo.parent.parent / "Tarea 1" / ".env", override=False)
    return Config(datos=datos, archivo=archivo)


@lru_cache(maxsize=1)
def obtener_config() -> Config:
    return cargar_config()
