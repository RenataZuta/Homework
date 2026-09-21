"""Utilidades de compare_embeddings (sin modelos ni red) y la traducción de errores a estados de fila."""
import sys

import pytest

from evaluation.compare_embeddings import estado_por_error, estimar_tokens_openai, tamano_dir_mb
from rag_engine.embeddings.base import ErrorEmbeddings


def test_tamano_de_un_directorio_suma_todos_los_archivos(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 1_048_576)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"y" * 524_288)
    assert tamano_dir_mb(tmp_path) == 1.5


class _TiktokenFalso:
    """Doble de tiktoken: sin red (el real descarga su vocabulario la primera vez y puede colgarse si falla el DNS)."""

    class _Codificador:
        def encode(self, texto):
            return texto.split()                             # 1 «token» por palabra

    @staticmethod
    def encoding_for_model(modelo):
        if modelo != "text-embedding-3-small":
            raise KeyError(modelo)
        return _TiktokenFalso._Codificador()


def test_la_estimacion_de_tokens_suma_los_tokens_de_cada_texto(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", _TiktokenFalso)
    assert estimar_tokens_openai(["uno dos tres", "cuatro cinco"], "text-embedding-3-small") == 5


def test_un_modelo_desconocido_o_sin_tokenizador_no_rompe_la_estimacion(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", _TiktokenFalso)
    assert estimar_tokens_openai(["hola"], "modelo-que-no-existe-xyz") is None
    monkeypatch.setitem(sys.modules, "tiktoken", None)       # import imposible
    assert estimar_tokens_openai(["hola"], "text-embedding-3-small") is None


def test_insufficient_quota_deja_la_fila_no_ejecutada_por_costo_sin_pedir_credito():
    e = estado_por_error(ErrorEmbeddings("You exceeded your current quota", tipo="cuota_insuficiente"), "openai")
    assert e.startswith("no ejecutada por costo") and "insufficient_quota" in e and "no se cargó crédito" in e


@pytest.mark.parametrize("tipo", ["cuota_agotada", "limite_de_tasa"])
def test_la_cuota_gratuita_agotada_es_no_completada_no_error_ni_costo(tipo):
    e = estado_por_error(ErrorEmbeddings("se agotó", tipo=tipo), "gemini")
    assert e.startswith("no completada") and "costo" not in e.split(":")[0]


def test_clave_invalida_y_otros_errores_tienen_su_propio_estado():
    assert estado_por_error(ErrorEmbeddings("API key not valid", tipo="autenticacion"), "gemini").startswith("error: clave inválida")
    assert estado_por_error(ErrorEmbeddings("caído", tipo="servidor"), "gemini") == "error: caído"
