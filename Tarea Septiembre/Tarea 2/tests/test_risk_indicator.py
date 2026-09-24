"""Pruebas de risk_indicator.por_grupo (Fase 5) con datos sintéticos: no toca el parquet real."""
from __future__ import annotations

import pandas as pd

from risk_indicator import _con_postor_unico, por_grupo


def _df():
    return pd.DataFrame([
        {"ocid": "a", "departamento": "LIMA", "comprador_nombre": "MUNI A", "n_adjudicaciones": 1, "n_postores_unicos": 1, "monto_adjudicado": 1000.0},
        {"ocid": "b", "departamento": "LIMA", "comprador_nombre": "MUNI A", "n_adjudicaciones": 1, "n_postores_unicos": 3, "monto_adjudicado": 2000.0},
        {"ocid": "c", "departamento": "CUSCO", "comprador_nombre": "MUNI B", "n_adjudicaciones": 0, "n_postores_unicos": 1, "monto_adjudicado": None},
        {"ocid": "d", "departamento": "CUSCO", "comprador_nombre": "MUNI B", "n_adjudicaciones": 1, "n_postores_unicos": 1, "monto_adjudicado": 500.0},
    ])


def test_solo_cuenta_procesos_adjudicados():
    adj = _con_postor_unico(_df())
    assert len(adj) == 3           # el ocid "c" (n_adjudicaciones=0) queda fuera
    assert set(adj["ocid"]) == {"a", "b", "d"}


def test_postor_unico_marca_correctamente():
    adj = _con_postor_unico(_df())
    marcados = dict(zip(adj["ocid"], adj["postor_unico"]))
    assert marcados == {"a": True, "b": False, "d": True}


def test_share_por_departamento():
    adj = _con_postor_unico(_df())
    g = por_grupo(adj, "departamento").set_index("departamento")
    assert g.loc["LIMA", "procesos_adjudicados"] == 2
    assert g.loc["LIMA", "postor_unico"] == 1
    assert g.loc["LIMA", "share_postor_unico"] == 0.5
    assert g.loc["CUSCO", "share_postor_unico"] == 1.0


def test_minimo_filtra_muestra_pequena():
    adj = _con_postor_unico(_df())
    g = por_grupo(adj, "comprador_nombre", minimo=2)
    assert list(g["comprador_nombre"]) == ["MUNI A"]     # MUNI B tiene solo 1 proceso adjudicado: queda fuera
