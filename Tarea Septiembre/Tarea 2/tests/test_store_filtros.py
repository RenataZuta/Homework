"""Pruebas de radar_engine.store._pasa_filtros: la parte que decide qué procesos son "candidatos" antes de
calcular similitud. No necesita ChromaDB ni el modelo de embeddings.
"""
from __future__ import annotations

from radar_engine.filtros import Filtros
from radar_engine.store import SIN_FECHA, SIN_MONTO, _pasa_filtros

BASE = {"ocid": "x", "departamento": "CUSCO", "categoria": "works", "monto_pen": 1_500_000.0, "monto_conocido": True,
        "fecha": "2026-07-15", "fecha_conocida": True}


def test_sin_filtros_pasa_todo():
    assert _pasa_filtros(BASE, Filtros())


def test_departamento_distinto_no_pasa():
    assert not _pasa_filtros(BASE, Filtros(departamento="LIMA"))


def test_departamento_igual_pasa():
    assert _pasa_filtros(BASE, Filtros(departamento="CUSCO"))


def test_categoria_distinta_no_pasa():
    assert not _pasa_filtros(BASE, Filtros(categoria="goods"))


def test_monto_dentro_del_rango_pasa():
    assert _pasa_filtros(BASE, Filtros(monto_min=1_000_000, monto_max=2_000_000))


def test_monto_fuera_del_rango_no_pasa():
    assert not _pasa_filtros(BASE, Filtros(monto_min=2_000_000))
    assert not _pasa_filtros(BASE, Filtros(monto_max=1_000_000))


def test_monto_desconocido_nunca_pasa_filtro_de_monto():
    """Un monto reservado/no publicado NO puede "adivinarse" como dentro de un rango: se excluye siempre que se filtre por monto."""
    meta = {**BASE, "monto_pen": SIN_MONTO, "monto_conocido": False}
    assert not _pasa_filtros(meta, Filtros(monto_min=0))
    assert not _pasa_filtros(meta, Filtros(monto_max=10_000_000))
    assert _pasa_filtros(meta, Filtros())          # sin filtro de monto, sí pasa


def test_fecha_dentro_del_rango_pasa():
    assert _pasa_filtros(BASE, Filtros(fecha_desde="2026-06-01", fecha_hasta="2026-08-31"))


def test_fecha_fuera_del_rango_no_pasa():
    assert not _pasa_filtros(BASE, Filtros(fecha_desde="2026-08-01"))


def test_fecha_desconocida_nunca_pasa_filtro_de_fecha():
    meta = {**BASE, "fecha": SIN_FECHA, "fecha_conocida": False}
    assert not _pasa_filtros(meta, Filtros(fecha_desde="2026-01-01"))
    assert _pasa_filtros(meta, Filtros())
