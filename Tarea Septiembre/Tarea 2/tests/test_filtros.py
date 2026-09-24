"""Pruebas de radar_engine.filtros: extracción de filtros territoriales/numéricos desde lenguaje natural.

No necesitan el índice ni el modelo de embeddings (son reglas puras): corren rápido y sin red.
"""
from __future__ import annotations

import pytest

from radar_engine.config import cargar_config
from radar_engine.filtros import Filtros, combinar, extraer_filtros_pregunta


@pytest.fixture(scope="module")
def cfg():
    return cargar_config()


def test_extrae_departamento_simple(cfg):
    assert extraer_filtros_pregunta("obras de saneamiento en Cusco", cfg).departamento == "CUSCO"


def test_extrae_departamento_alias(cfg):
    assert extraer_filtros_pregunta("compras en Lima Metropolitana", cfg).departamento == "LIMA"


def test_no_extrae_departamento_si_no_hay(cfg):
    assert extraer_filtros_pregunta("compra de uniformes institucionales", cfg).departamento is None


def test_extrae_categoria_works(cfg):
    assert extraer_filtros_pregunta("construcción de una obra de pistas y veredas", cfg).categoria == "works"


def test_extrae_categoria_goods(cfg):
    assert extraer_filtros_pregunta("adquisición de uniformes y materiales", cfg).categoria == "goods"


def test_extrae_categoria_services(cfg):
    assert extraer_filtros_pregunta("servicio de vigilancia y limpieza", cfg).categoria == "services"


def test_extrae_monto_mayor_millon(cfg):
    f = extraer_filtros_pregunta("obras por encima de un millon de soles", cfg)
    assert f.monto_min == 1_000_000
    assert f.monto_max is None


def test_extrae_monto_menor_mil(cfg):
    f = extraer_filtros_pregunta("compras de menos de 500 mil soles", cfg)
    assert f.monto_max == 500_000
    assert f.monto_min is None


def test_extrae_monto_hasta(cfg):
    assert extraer_filtros_pregunta("obras hasta 500 mil soles", cfg).monto_max == 500_000


def test_hasta_un_anio_no_se_confunde_con_monto(cfg):
    """"hasta 2026" es una fecha (un año de 4 cifras sin "mil"/"millón"), no un monto: no debe generar monto_max=2026."""
    f = extraer_filtros_pregunta("procesos convocados hasta 2026", cfg)
    assert f.monto_max is None


def test_pregunta_del_enunciado_combina_los_tres(cfg):
    f = extraer_filtros_pregunta("obras de agua y saneamiento en Cusco por encima de un millon de soles", cfg)
    assert f.departamento == "CUSCO"
    assert f.categoria == "works"
    assert f.monto_min == 1_000_000


def test_combinar_explicito_gana_sobre_extraido():
    explicitos = Filtros(departamento="LIMA")
    extraidos = Filtros(departamento="CUSCO", categoria="works")
    r = combinar(explicitos, extraidos)
    assert r.departamento == "LIMA"          # explícito gana
    assert r.categoria == "works"            # no había explícito: se usa lo extraído


def test_combinar_monto_cero_no_se_confunde_con_ausente():
    # monto_min=0 es un valor válido (no "sin filtro"); el explícito debe distinguirse de None.
    explicitos = Filtros(monto_min=0.0)
    extraidos = Filtros(monto_min=500.0)
    assert combinar(explicitos, extraidos).monto_min == 0.0


def test_filtros_vacio():
    assert Filtros().esta_vacio()
    assert not Filtros(departamento="LIMA").esta_vacio()
