"""Fase 3 — Construcción del índice híbrido (proceso OFFLINE, se corre a mano cuando cambian los datos).

Uso:
    python src/build_index_radar.py

Lee ``data/processed/procesos_validados.parquet`` (Fases 1-2) y crea/actualiza una colección ChromaDB con UNA
entrada por ``ocid``: el texto embebido es ``nomenclatura``. ``descripcion`` (``indexacion.campos_texto`` en
config.yaml); no se trocea (una descripción de proceso cabe entera en el límite del modelo, ver el aviso al
final de esta corrida). Los metadatos (departamento, categoría, monto, fecha, comprador) quedan junto al
vector para que ``radar_engine/store.py`` pueda filtrar antes de calcular similitud.

Garantías (idénticas en espíritu a ``indexing/build_index.py`` de la Tarea 1, adaptadas a "un ocid = una
entrada" en vez de "una página = varios fragmentos"):
  * Idempotente: correrlo dos veces deja el mismo índice y la segunda vez no reembebe nada (se compara el
    hash del texto embebido de cada ocid antes de decidir si hace falta).
  * Reanudable: se hace upsert por lotes (``indexacion.lote_upsert``); una interrupción (Ctrl+C) pierde a lo
    sumo el lote en curso y la siguiente corrida continúa con lo que falta.
  * Un ocid que YA NO está en el parquet (p. ej. porque cambiaron los meses de ``bulk.months``) se borra del
    índice y se reporta como eliminado: nunca queda un proceso "fantasma" citable que ya no existe en los datos.
"""
from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from radar_engine.config import cargar_config  # noqa: E402
from radar_engine.embeddings import crear_embedder  # noqa: E402
from radar_engine.store import SIN_FECHA, SIN_MONTO, Proceso, nombre_coleccion, olvidar_matriz  # noqa: E402
from radar_engine.bootstrap_t1 import asegurar_import_tarea1  # noqa: E402

asegurar_import_tarea1()
from rag_engine.retrieval.indice import abrir_cliente, crear_o_abrir  # noqa: E402


@dataclass
class ResumenIndice:
    coleccion: str = ""
    total_parquet: int = 0
    existentes: int = 0        # ya estaban con el mismo contenido: no se reembeben
    nuevos: int = 0
    actualizados: int = 0      # mismo ocid, contenido distinto (p. ej. se corrigió una descripción)
    eliminados: int = 0        # ocid que ya no está en el parquet
    total_en_indice: int = 0
    interrumpido: bool = False
    segundos: float = 0.0
    embeddings: dict = field(default_factory=dict)
    max_tokens_modelo: int = 0
    truncados: int = 0          # textos cuyo texto_embedding excede max_tokens_modelo (se truncan en silencio dentro del modelo)
    tokens_promedio: float = 0.0
    tokens_maximo: int = 0


def _fila_a_proceso(row: pd.Series, campos_texto: list[str]) -> Proceso:
    partes = [str(row[c]).strip() for c in campos_texto if pd.notna(row.get(c)) and str(row[c]).strip()]
    texto_embedding = ". ".join(partes)
    descripcion = str(row["descripcion"]).strip() if pd.notna(row.get("descripcion")) and str(row["descripcion"]).strip() else ""
    texto_mostrado = descripcion or str(row.get("nomenclatura") or "").strip() or "(sin descripción ni nomenclatura)"
    monto = row.get("monto_referencial_pen")
    monto_conocido = pd.notna(monto)
    fecha_raw = row.get("fecha_convocatoria")
    fecha_conocida = pd.notna(fecha_raw) and bool(str(fecha_raw).strip())
    fecha = str(fecha_raw)[:10] if fecha_conocida else SIN_FECHA
    return Proceso(
        ocid=row["ocid"], comprador=str(row.get("comprador_nombre") or ""), departamento=str(row.get("departamento") or ""),
        categoria=str(row.get("categoria") or ""), tipo_procedimiento=str(row.get("tipo_procedimiento") or ""),
        monto_pen=float(monto) if monto_conocido else SIN_MONTO, monto_conocido=bool(monto_conocido), fecha=fecha,
        fecha_conocida=bool(fecha_conocida), nomenclatura=str(row.get("nomenclatura") or ""), texto=texto_mostrado,
        texto_embedding=texto_embedding or texto_mostrado, hash_texto=hashlib.sha1(texto_embedding.encode()).hexdigest()[:12],
    )


def _hashes_existentes(col, ids: list[str]) -> dict[str, str]:
    salida: dict[str, str] = {}
    for i in range(0, len(ids), 500):
        r = col.get(ids=ids[i:i + 500], include=["metadatas"])
        salida.update({id_: m.get("hash_texto", "") for id_, m in zip(r["ids"], r["metadatas"])})
    return salida


def _todos_los_ids(col) -> list[str]:
    salida: list[str] = []
    lote = 5000
    offset = 0
    while True:
        r = col.get(limit=lote, offset=offset, include=[])
        if not r["ids"]:
            break
        salida += r["ids"]
        offset += lote
    return salida


def construir(cfg=None, mostrar=print) -> ResumenIndice:
    cfg = cfg or cargar_config()
    t0 = time.perf_counter()
    df = pd.read_parquet(cfg.base / cfg.get("validation.output_file"))
    assert df["ocid"].is_unique, "procesos_validados.parquet debe tener una fila por ocid (lo garantiza la Fase 1c)"

    campos_texto = cfg.get("indexacion.campos_texto")
    esperados = {row["ocid"]: _fila_a_proceso(row, campos_texto) for _, row in df.iterrows()}

    embedder = crear_embedder(cfg)

    # Cuántos textos exceden max_tokens del modelo (se truncarían EN SILENCIO dentro de sentence-transformers):
    # se mide una sola vez por corrida (tokenizar es barato, no requiere GPU/CPU intensiva como codificar).
    conteos = embedder.contar_tokens([p.texto_embedding for p in esperados.values()], es_consulta=False)
    truncados = sum(1 for n in conteos if n > embedder.max_tokens)

    nombre = nombre_coleccion(cfg, embedder.name)
    col = crear_o_abrir(abrir_cliente(cfg.ruta("index")), nombre, {"modelo": embedder.name, "esquema": cfg.get("indexacion.version_esquema"), "dim": embedder.dim})
    res = ResumenIndice(coleccion=nombre, total_parquet=len(esperados))

    previos = set(_todos_los_ids(col))
    obsoletos = sorted(previos - set(esperados))
    if obsoletos:
        col.delete(ids=obsoletos)
        res.eliminados = len(obsoletos)
        mostrar(f"  eliminados (ya no están en el parquet): {len(obsoletos)}")

    ya = _hashes_existentes(col, list(esperados))
    pendientes: list[Proceso] = []
    for ocid, p in esperados.items():
        if ocid not in ya:
            res.nuevos += 1
            pendientes.append(p)
        elif ya[ocid] != p.hash_texto:
            res.actualizados += 1
            pendientes.append(p)
        else:
            res.existentes += 1

    lote_upsert = cfg.get("indexacion.lote_upsert")
    try:
        for i in range(0, len(pendientes), lote_upsert):
            lote = pendientes[i:i + lote_upsert]
            vectores = embedder.embed_passages([p.texto_embedding for p in lote])
            col.upsert(ids=[p.ocid for p in lote], embeddings=vectores.tolist(), documents=[p.texto for p in lote],
                      metadatas=[p.metadatos() for p in lote])
            mostrar(f"  lote {i // lote_upsert + 1}/{-(-len(pendientes) // lote_upsert)}: {len(lote)} procesos guardados")
    except KeyboardInterrupt:
        res.interrumpido = True

    olvidar_matriz()
    res.total_en_indice = col.count()
    res.segundos = time.perf_counter() - t0
    res.embeddings = embedder.contabilidad.como_dict()
    res.max_tokens_modelo, res.truncados = embedder.max_tokens, truncados
    res.tokens_promedio, res.tokens_maximo = sum(conteos) / len(conteos), max(conteos)
    return res


def main() -> int:
    cfg = cargar_config()
    print(f"Indexando {cfg.get('validation.output_file')} -> colección ChromaDB en {cfg.ruta('index')}")
    res = construir(cfg)
    print(f"\nResumen: {res.total_parquet} procesos en el parquet | nuevos {res.nuevos} | actualizados {res.actualizados} | "
          f"ya existían {res.existentes} | eliminados (obsoletos) {res.eliminados} | total en el índice {res.total_en_indice}")
    print(f"Tiempo: {res.segundos:.1f} s | Embeddings: {res.embeddings}")
    print(f"Tokens por texto: promedio {res.tokens_promedio:.1f}, máximo {res.tokens_maximo} (límite del modelo: {res.max_tokens_modelo}). "
          f"Textos truncados: {res.truncados} de {res.total_parquet}.")
    if res.interrumpido:
        print("\nInterrumpido (Ctrl+C): vuelve a correr el script, continuará donde quedó (es idempotente y reanudable).")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
