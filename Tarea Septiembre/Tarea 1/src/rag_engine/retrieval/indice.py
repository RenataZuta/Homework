"""Acceso al índice persistente (ChromaDB). Lo comparten la indexación OFFLINE y la recuperación ONLINE.

Por qué ChromaDB (decisión documentada en el README): persiste en disco sin servidor, guarda junto a cada vector el texto y
los metadatos (documento, versión, página…) que necesitamos para citar, permite upsert por ID (base de la idempotencia) y
filtrar por metadatos, y su índice HNSW con distancia coseno resuelve el corpus (~1 000 fragmentos) en milisegundos.
FAISS sería más rápido pero no guarda metadatos ni texto; para este tamaño la diferencia no se nota y costaría más código.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import chromadb
from chromadb.config import Settings

from rag_engine.config import Config


class IndiceNoDisponible(Exception):
    """El índice no existe o está vacío. El mensaje dice cómo construirlo."""


def abrir_cliente(dir_index: Path) -> chromadb.ClientAPI:
    # anonymized_telemetry=False: Chroma envía telemetría por defecto; aquí no sale nada del equipo.
    return chromadb.PersistentClient(path=str(dir_index), settings=Settings(anonymized_telemetry=False))


def nombre_coleccion(prefijo: str, nombre_chunking: str, modelo: str) -> str:
    """Un nombre por (troceado, modelo): dos índices con configuraciones distintas coexisten sin pisarse."""
    return f"{prefijo}_{nombre_chunking}_{hashlib.sha1(modelo.encode()).hexdigest()[:6]}"


def nombre_coleccion_de_config(cfg: Config, modelo: str | None = None) -> str:
    proveedor = cfg.get("embeddings.proveedor")
    modelo = modelo or cfg.get(f"embeddings.{proveedor}.modelo")
    return nombre_coleccion(cfg.get("indexacion.coleccion"), cfg.get("chunking.activa"), modelo)


def crear_o_abrir(cliente: chromadb.ClientAPI, nombre: str, meta: dict):
    return cliente.get_or_create_collection(name=nombre, metadata={"hnsw:space": "cosine", **meta})


def abrir_para_lectura(cfg: Config, dir_index: Path | None = None, nombre: str | None = None):
    """Abre la colección del índice ya construido; si falta, lanza IndiceNoDisponible con instrucciones."""
    ruta = dir_index or cfg.ruta("index")
    nombre = nombre or nombre_coleccion_de_config(cfg)
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
