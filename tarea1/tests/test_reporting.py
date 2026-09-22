"""Datos de las pestañas de la interfaz: leen archivos ya generados y nunca inventan cifras cuando faltan."""
import csv
import json

import pytest

from fakes import cfg_con
from rag_engine.config import cargar_config
from rag_engine.llm.cost_log import registrar_llamada
from reporting import datos

BASE = cargar_config(cargar_env=False)


def cfg_en(tmp_path, **extra):
    return cfg_con(BASE, **{"paths.processed": str(tmp_path / "proc"), "paths.eval_results": str(tmp_path / "res"), "paths.llm_calls_log": str(tmp_path / "log.jsonl"),
                            "paths.docs": str(tmp_path / "docs"), **extra})


def escribir_csv(ruta, filas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)


# ── lectura básica ──

def test_los_archivos_que_faltan_dan_vacio_no_error(tmp_path):
    assert datos.leer_csv(tmp_path / "no.csv") == [] and datos.leer_json(tmp_path / "no.json") is None and datos.leer_md(tmp_path / "no.md") is None


def test_leer_csv_convierte_numeros_y_deja_vacios_en_none(tmp_path):
    escribir_csv(tmp_path / "a.csv", [{"n": "3", "x": "0.905", "t": "hola", "v": ""}])
    assert datos.leer_csv(tmp_path / "a.csv") == [{"n": 3, "x": 0.905, "t": "hola", "v": None}]


def test_un_json_danado_no_rompe_la_lectura(tmp_path):
    (tmp_path / "r.json").write_text("{ roto", encoding="utf-8")
    assert datos.leer_json(tmp_path / "r.json") is None


def test_el_markdown_se_muestra_sin_imagenes_de_ruta_relativa(tmp_path):
    (tmp_path / "n.md").write_text("# Título\n\n![gráfico](img/a.png)\n\ntexto", encoding="utf-8")
    assert "img/a.png" not in datos.leer_md(tmp_path / "n.md") and "texto" in datos.leer_md(tmp_path / "n.md")


# ── extracción ──

def test_la_extraccion_resume_cada_documento(tmp_path):
    cfg = cfg_en(tmp_path)
    (tmp_path / "proc").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ocr_subset.md").write_text("# OCR\n![x](a.png)", encoding="utf-8")
    reporte = {"documentos": [{"documento": "ds_009", "version": "v", "generado": "2026-09-21", "paginas": {"total_pdf": 100, "procesadas": 75, "por_origen": {"texto": 0, "ocr": 75}, "excluidas": 25},
                               "caracteres": {"por_pagina": {"mediana": 3000}}, "paginas_con_poco_texto": [3, 4], "indicador_calidad": {"pct_alfabeticos_medio": 0.9, "confianza_ocr_media": 84.0},
                               "limpieza": {"lineas_de_cabecera_eliminadas": 12}}]}
    (tmp_path / "proc" / "reporte_calidad.json").write_text(json.dumps(reporte), encoding="utf-8")
    e = datos.extraccion(cfg)
    f = e["documentos"][0]
    assert (f["documento"], f["páginas del PDF"], f["con OCR"], f["páginas con poco texto"], f["confianza OCR"]) == ("ds_009", 100, 75, 2, 84.0)
    assert e["notas"] == {"ocr_subset.md": "# OCR\n"} and e["generado"] == "2026-09-21"


def test_sin_reporte_de_extraccion_no_hay_filas(tmp_path):
    assert datos.extraccion(cfg_en(tmp_path))["documentos"] == []


# ── evaluación ──

def fila_e2e(id_, tipo, desenlace, cita=""):
    return {"id": id_, "tipo": tipo, "desenlace": desenlace, "cita_correcta": cita}


def test_resumen_e2e_cuenta_cada_desenlace():
    filas = [fila_e2e("q1", "in_domain", "respondida", "True"), fila_e2e("q2", "in_domain", "respondida", "False"), fila_e2e("q3", "in_domain", "abstuvo_llm", "False"),
             fila_e2e("q4", "in_domain", "abstuvo_umbral", "False"), fila_e2e("o1", "out_of_domain", "abstuvo_llm"), fila_e2e("o2", "out_of_domain", "respondida"),
             fila_e2e("o3", "out_of_domain", "abstuvo_umbral"), fila_e2e("o4", "out_of_domain", "error")]
    s = datos.resumen_e2e(filas)
    assert (s["in_domain"], s["in_domain_respondidas"], s["in_domain_con_cita_correcta"], s["in_domain_abstenciones"]) == (4, 2, 1, 2)
    assert (s["fuera_de_dominio"], s["fuera_abstenciones"], s["fuera_abstenciones_por_llm"], s["fuera_respondidas"], s["errores"]) == (4, 2, 1, 1, 1)


def test_la_evaluacion_usa_el_csv_del_umbral_configurado_o_avisa_del_alterno(tmp_path):
    res = tmp_path / "res"
    escribir_csv(res / "e2e_umbral_0.000.csv", [{"id": "q1", "tipo": "in_domain", "desenlace": "respondida", "cita_correcta": "True"}])
    e = datos.evaluacion(cfg_en(tmp_path, **{"retrieval.umbral_similitud": 0.835}))
    assert e["e2e_etiqueta"].startswith("umbral 0.000") and "no hay evaluación" in e["e2e_etiqueta"] and e["e2e_resumen"]["in_domain_respondidas"] == 1
    escribir_csv(res / "e2e_umbral_0.835.csv", [{"id": "q1", "tipo": "in_domain", "desenlace": "abstuvo_umbral", "cita_correcta": "False"}])
    e2 = datos.evaluacion(cfg_en(tmp_path, **{"retrieval.umbral_similitud": 0.835}))
    assert e2["e2e_etiqueta"] == "umbral 0.835" and e2["e2e_resumen"]["in_domain_abstenciones"] == 1


def test_sin_resultados_la_evaluacion_lo_dice_con_none_y_listas_vacias(tmp_path):
    e = datos.evaluacion(cfg_en(tmp_path))
    assert e["recuperacion"] is None and e["e2e"] == [] and e["e2e_resumen"] is None and e["embeddings"] == [] and e["retrievers"] == [] and e["barrido_e2e"] == []


def test_la_evaluacion_lee_las_metricas_de_recuperacion_y_la_marca_de_validacion(tmp_path):
    res = tmp_path / "res"
    res.mkdir()
    (res / "run_eval.json").write_text(json.dumps({"recuperacion": {"recall@3": 0.9}, "abstencion": {"umbral": 0.8}, "por_pregunta": [{"id": "q1"}]}), encoding="utf-8")
    e = datos.evaluacion(cfg_en(tmp_path))
    assert e["recuperacion"] == {"recall@3": 0.9} and e["por_pregunta"] == [{"id": "q1"}] and e["set_validado"] is False


# ── costos ──

def reg(ruta, **kw):
    base = dict(timestamp="2026-09-21T10:00:00-05:00", proveedor="gemini", modelo="gemini-3.5-flash-lite", nivel="gratuito", tokens_in=1000, tokens_out=100, latencia_ms=2000.0,
                costo_usd_real=0.0, costo_usd_referencia=0.001, intentos=1, exito=True)
    registrar_llamada(ruta, **{**base, **kw})


def test_sin_log_de_llamadas_no_hay_datos(tmp_path):
    assert datos.costos(cfg_en(tmp_path)) == {"hay_datos": False}


def test_los_costos_se_agregan_por_modelo_dia_y_error(tmp_path):
    log = tmp_path / "log.jsonl"
    reg(log)
    reg(log, timestamp="2026-09-22T09:00:00-05:00", tokens_in=3000, costo_usd_referencia=0.003, latencia_ms=4000.0, intentos=3)
    reg(log, exito=False, error="cuota_agotada: sin cuota", tokens_in=0, tokens_out=0, costo_usd_referencia=0.0)
    c = datos.costos(cfg_en(tmp_path))
    assert c["hay_datos"] and c["resumen"]["llamadas"] == 3 and c["resumen"]["exitosas"] == 2 and c["resumen"]["reintentos"] == 2
    assert c["resumen"]["costo_real_total_usd"] == 0.0 and c["resumen"]["costo_referencia_total_usd"] == pytest.approx(0.004)
    assert c["por_dia"] == [{"día": "2026-09-21", "llamadas": 2}, {"día": "2026-09-22", "llamadas": 1}] and c["errores"] == {"cuota_agotada": 1}
    m = c["por_modelo"][0]
    assert (m["modelo"], m["llamadas"], m["tokens_in"], m["nivel"]) == ("gemini-3.5-flash-lite", 3, 4000, "gratuito")
    assert c["proyeccion_referencia_1000_usd"] == pytest.approx(2.0) and c["muestra_proyeccion"] == 2 and c["aviso_nivel_gratuito"] is True
    assert c["ultimas"][0]["error"] and len(c["ultimas"]) == 3                    # la más reciente primero


def test_la_proyeccion_solo_usa_llamadas_exitosas_y_no_inventa_sin_ellas(tmp_path):
    log = tmp_path / "log.jsonl"
    reg(log, exito=False, error="x", tokens_in=0, tokens_out=0, costo_usd_referencia=0.0)
    assert datos.costos(cfg_en(tmp_path))["proyeccion_referencia_1000_usd"] is None


def test_los_datos_reales_del_repo_se_leen_sin_error():
    e, c, x = datos.evaluacion(BASE), datos.costos(BASE), datos.extraccion(BASE)
    assert e["recuperacion"] and e["e2e_resumen"] and x["documentos"]
    assert c["hay_datos"] and c["resumen"]["llamadas"] >= 1
