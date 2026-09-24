"""Índice y recuperación híbrida sobre procesos de contratación (una entrada = un ``ocid``).

Reutiliza de ``rag_engine.retrieval.indice`` (Tarea 1) las funciones GENÉRICAS de acceso a ChromaDB
(``abrir_cliente``, ``crear_o_abrir``, ``nombre_coleccion``): no conocen "documento/página", solo abren una
colección persistente con distancia coseno. El resto de ``rag_engine.retrieval`` (``semantic.py``,
``modos.py``, ``versions.py``) SÍ está acoplado a esos metadatos legales y no se reutiliza aquí.

Búsqueda EXACTA (mismo criterio de diseño que la Tarea 1, ver su README): con ~20 000 vectores una
multiplicación de matrices tarda unos pocos milisegundos en CPU, así que se calcula el coseno contra TODOS
los procesos que pasan los filtros estructurados, en vez de usar el índice aproximado HNSW de Chroma. Es
determinista (mismos vectores + misma consulta = mismo resultado) y evita el problema que la Tarea 1 midió:
la búsqueda aproximada puede dar resultados distintos entre corridas para la misma pregunta.

Filtros ANTES del coseno, nunca después: ``filtros.py`` decide qué procesos son candidatos (departamento,
categoría, rango de monto, rango de fecha) y aquí solo se calcula similitud entre esos candidatos. Así un
proceso fuera del departamento pedido nunca puede "ganar" por tener una descripción muy parecida.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from radar_engine.bootstrap_t1 import asegurar_import_tarea1
from radar_engine.config import Config
from radar_engine.embeddings import Embedder
from radar_engine.filtros import Filtros

asegurar_import_tarea1()

from rag_engine.retrieval.indice import abrir_cliente, crear_o_abrir  # noqa: E402

SIN_MONTO = -1.0        # sentinela de metadatos Chroma (no admite null): ver monto_conocido para no confundirlo con "monto = -1"
SIN_FECHA = ""


class IndiceNoDisponible(Exception):
    """El índice no existe o está vacío. El mensaje dice cómo construirlo."""


def nombre_coleccion(cfg: Config, modelo: str | None = None) -> str:
    """Un nombre por (versión de esquema, modelo): dos índices con configuraciones distintas coexisten sin pisarse."""
    modelo = modelo or cfg.get(f"embeddings.{cfg.get('embeddings.proveedor')}.modelo")
    prefijo, version = cfg.get("indexacion.coleccion"), cfg.get("indexacion.version_esquema")
    return f"{prefijo}_{version}_{hashlib.sha1(modelo.encode()).hexdigest()[:6]}"


def abrir_para_lectura(cfg: Config, nombre: str | None = None):
    ruta = cfg.ruta("index")
    nombre = nombre or nombre_coleccion(cfg)
    instrucciones = cfg.get("mensajes.indice_faltante").format(ruta=ruta)
    if not ruta.is_dir():
        raise IndiceNoDisponible(instrucciones)
    try:
        col = abrir_cliente(ruta).get_collection(nombre)
    except Exception as exc:
        raise IndiceNoDisponible(f"{instrucciones} (colección '{nombre}' no encontrada)") from exc
    if col.count() == 0:
        raise IndiceNoDisponible(f"{instrucciones} (la colección '{nombre}' está vacía)")
    return col


@dataclass
class Proceso:
    """Una fila (un ``ocid``) tal como se guarda en el índice: metadatos estructurados + el texto citable."""

    ocid: str
    comprador: str
    departamento: str
    categoria: str
    tipo_procedimiento: str
    monto_pen: float
    monto_conocido: bool
    fecha: str                # YYYY-MM-DD, o "" si se desconoce
    fecha_conocida: bool
    nomenclatura: str
    texto: str                 # lo que se muestra y se cita (descripción; si falta, la nomenclatura)
    texto_embedding: str = ""  # lo que se convierte en vector (nomenclatura + descripción; ver build_index_radar.py)
    hash_texto: str = ""

    def metadatos(self) -> dict:
        """Solo tipos escalares (str/int/float/bool): lo único que admite ChromaDB en metadatos."""
        return {"ocid": self.ocid, "comprador": self.comprador or "", "departamento": self.departamento,
                "categoria": self.categoria or "", "tipo_procedimiento": self.tipo_procedimiento or "",
                "monto_pen": self.monto_pen, "monto_conocido": self.monto_conocido,
                "fecha": self.fecha, "fecha_conocida": self.fecha_conocida,
                "nomenclatura": self.nomenclatura or "", "hash_texto": self.hash_texto}


@dataclass
class Recuperado:
    ocid: str
    similitud: float
    texto: str
    metadatos: dict = field(default_factory=dict)


class _Matriz:
    """Todos los vectores (normalizados), textos y metadatos de la colección, ordenados por ocid (empates deterministas)."""

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


def olvidar_matriz() -> None:
    """La indexación lo llama al terminar para que ninguna consulta posterior use datos viejos en memoria."""
    _CACHE.clear()


def _matriz(coleccion) -> _Matriz:
    clave = (str(coleccion.id), coleccion.count())
    if clave not in _CACHE:
        _CACHE[clave] = _Matriz(coleccion)
    return _CACHE[clave]


def _pasa_filtros(meta: dict, filtros: Filtros) -> bool:
    if filtros.departamento and meta["departamento"] != filtros.departamento:
        return False
    if filtros.categoria and meta["categoria"] != filtros.categoria:
        return False
    if (filtros.monto_min is not None or filtros.monto_max is not None) and not meta["monto_conocido"]:
        return False        # un monto reservado/desconocido nunca "pasa" un filtro de monto: no se adivina
    if filtros.monto_min is not None and meta["monto_pen"] < filtros.monto_min:
        return False
    if filtros.monto_max is not None and meta["monto_pen"] > filtros.monto_max:
        return False
    if (filtros.fecha_desde or filtros.fecha_hasta) and not meta["fecha_conocida"]:
        return False
    if filtros.fecha_desde and meta["fecha"] < filtros.fecha_desde:
        return False
    if filtros.fecha_hasta and meta["fecha"] > filtros.fecha_hasta:
        return False
    return True


def candidatos(coleccion, filtros: Filtros) -> int:
    """Cuántos procesos pasan los filtros ANTES de aplicar similitud (para el mensaje de abstención)."""
    m = _matriz(coleccion)
    return sum(1 for meta in m.metas if _pasa_filtros(meta, filtros))


def buscar(coleccion, embedder: Embedder, pregunta: str, k: int, filtros: Filtros | None = None) -> list[Recuperado]:
    """Los ``k`` procesos más similares a ``pregunta`` entre los que pasan ``filtros``, de mayor a menor similitud."""
    filtros = filtros or Filtros()
    m = _matriz(coleccion)
    idx = [i for i, meta in enumerate(m.metas) if _pasa_filtros(meta, filtros)]
    if not idx:
        return []
    vector = embedder.embed_query(pregunta)
    v = np.asarray(vector, dtype=np.float32)
    v = v / (np.linalg.norm(v) or 1.0)
    sims = m.vectores[idx] @ v
    orden = sorted(range(len(idx)), key=lambda j: (-float(sims[j]), m.ids[idx[j]]))[:k]     # desempate por ocid: determinista
    return [Recuperado(ocid=m.metas[idx[j]]["ocid"], similitud=float(sims[j]), texto=m.textos[idx[j]], metadatos=m.metas[idx[j]]) for j in orden]
