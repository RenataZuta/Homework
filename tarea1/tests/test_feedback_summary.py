"""feedback_summary.py: resume votos sin romperse cuando no hay bot.db, y su lógica de agregación."""
from datetime import datetime, timezone

from evaluation.feedback_summary import main, resumir
from fakes import cfg_con
from interfaces import bot_store
from rag_engine.config import cargar_config

BASE = cargar_config(cargar_env=False)


def test_resumir_cuenta_positivos_negativos_y_calificaciones_de_abstenciones_y_errores():
    filas = [{"valor": 1, "abstuvo": 0, "error": None}, {"valor": 1, "abstuvo": 1, "error": None}, {"valor": -1, "abstuvo": 0, "error": "x"}]
    r = resumir(filas)
    assert (r["votos"], r["positivos"], r["negativos"], r["abstenciones_calificadas"], r["errores_calificados"]) == (3, 2, 1, 1, 1)
    assert r["pct_positivo"] == round(2 / 3, 3)


def test_resumir_sin_filas_no_divide_entre_cero():
    assert resumir([])["pct_positivo"] is None and resumir([])["votos"] == 0


def test_sin_bot_db_no_falla_y_no_escribe_nada(tmp_path, capsys):
    cfg = cfg_con(BASE, **{"paths.bot_db": str(tmp_path / "no_existe.db"), "paths.eval_results": str(tmp_path / "res")})
    import evaluation.feedback_summary as mod
    original = mod.cargar_config
    mod.cargar_config = lambda cargar_env=True: cfg
    try:
        assert main() == 0
    finally:
        mod.cargar_config = original
    assert "No hay" in capsys.readouterr().out and not (tmp_path / "res").exists()


def test_con_votos_reales_escribe_el_resumen(tmp_path):
    from rag_engine.engine import Fuente, ResultadoRAG
    ruta_db, res = tmp_path / "bot.db", tmp_path / "res"
    conn = bot_store.abrir_db(ruta_db)
    r = ResultadoRAG(respuesta="ok [Ley 32069, p. 1].", fuentes=[Fuente("ley_32069", "v", 1, 0.9, "id", "texto", citada=True)], timestamp="t")
    cid = bot_store.registrar_consulta(conn, 1, "¿algo?", r, datetime(2026, 9, 21, tzinfo=timezone.utc))
    bot_store.registrar_feedback(conn, cid, 1, 1, datetime(2026, 9, 21, tzinfo=timezone.utc))
    cfg = cfg_con(BASE, **{"paths.bot_db": str(ruta_db), "paths.eval_results": str(res)})
    import evaluation.feedback_summary as mod
    original = mod.cargar_config
    mod.cargar_config = lambda cargar_env=True: cfg
    try:
        assert main() == 0
    finally:
        mod.cargar_config = original
    assert (res / "feedback_resumen.csv").is_file() and "1 votos" in (res / "feedback_resumen.md").read_text(encoding="utf-8")
