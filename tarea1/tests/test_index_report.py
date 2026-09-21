"""Histograma del reporte del índice: clases coherentes y archivo generado (claro y oscuro)."""
import pytest

matplotlib = pytest.importorskip("matplotlib")

from evaluation.index_report import TEMAS, histograma, percentil


def test_las_clases_suman_todos_los_fragmentos_y_no_se_solapan(tmp_path):
    largos = [100, 150, 400, 420, 430, 800, 810, 820, 830, 1000]
    clases = histograma(largos, tmp_path / "h.png", "claro", "Título", bins=5)
    assert sum(n for _, _, n in clases) == len(largos)
    assert all(clases[i][1] < clases[i + 1][0] for i in range(len(clases) - 1))
    assert clases[0][0] == min(largos) and clases[-1][1] >= max(largos)


def test_genera_png_en_los_dos_temas(tmp_path):
    for tema in TEMAS:
        ruta = tmp_path / f"{tema}.png"
        histograma(list(range(100, 1000, 7)), ruta, tema, "Título", bins=12)
        assert ruta.stat().st_size > 5_000 and ruta.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_los_dos_temas_tienen_los_mismos_roles_de_color():
    assert set(TEMAS["claro"]) == set(TEMAS["oscuro"]) == {"superficie", "serie", "tinta", "tinta_2"}


def test_percentil():
    assert percentil(list(range(1, 101)), 95) in (95, 96) and percentil([7], 95) == 7
