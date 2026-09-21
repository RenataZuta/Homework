"""Utilidades de compare_embeddings (sin modelos ni red)."""
import pytest

from evaluation.compare_embeddings import estimar_tokens_openai, tamano_dir_mb


def test_tamano_de_un_directorio_suma_todos_los_archivos(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 1_048_576)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"y" * 524_288)
    assert tamano_dir_mb(tmp_path) == 1.5


def test_la_estimacion_de_tokens_es_una_cota_razonable():
    pytest.importorskip("tiktoken")
    n = estimar_tokens_openai(["El pago se realiza en un plazo máximo de diez días hábiles"] * 10, "text-embedding-3-small")
    assert n is None or 100 < n < 300                       # ~16 tokens por frase x 10 (None si el tokenizador no pudo descargarse)


def test_un_modelo_desconocido_no_rompe_la_estimacion():
    assert estimar_tokens_openai(["hola"], "modelo-que-no-existe-xyz") is None
