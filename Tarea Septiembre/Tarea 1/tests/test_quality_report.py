"""Reporte de calidad por documento."""
from extraction.quality_report import reporte_a_markdown, reporte_documento

DOC = {"id": "d", "nombre": "Doc de prueba", "version": "v1"}


def entrada(n, origen="texto", car=1000, **kw):
    e = {"pagina": n, "origen": origen, "caracteres": car, "texto": f"texto de la página {n}", "texto_crudo": "x",
         "calidad": {"pct_alfabeticos": 0.9, "pct_palabras_conocidas": None, "confianza_ocr": None},
         "ocr_segundos": None, "confianza_ocr": None, "ocr_motor": None, "ocr_dpi": None, "limpieza": {}}
    e.update(kw)
    return e


def test_reporte_de_documento_con_texto():
    entradas = [entrada(1, car=1000, limpieza={"cabecera_eliminada": ["33", "NORMAS LEGALES"]}),
                entrada(2, car=3000, limpieza={"cabecera_eliminada": ["34"], "pie_eliminado": ["Firmado por: X"]}),
                entrada(3, car=100, limpieza={"lineas_fuera_de_norma": 141, "reglas": ["R3_fin_de_norma"]})]
    r = reporte_documento(DOC, entradas, paginas_pdf=3)
    assert r["paginas"] == {"total_pdf": 3, "procesadas": 3, "por_origen": {"texto": 3, "ocr": 0}, "excluidas": 0, "excluidas_por_motivo": {}}
    assert r["caracteres"]["total"] == 4100 and r["caracteres"]["por_pagina"]["mediana"] == 1000
    assert r["limpieza"] == {"paginas_con_cabecera_eliminada": 2, "lineas_de_cabecera_eliminadas": 3, "paginas_con_sello_de_firma": 1,
                             "paginas_recortadas_por_fin_de_norma": 1, "lineas_de_otras_normas_descartadas": 141}
    assert r["paginas_con_poco_texto"] == [{"pagina": 3, "caracteres": 100, "origen": "texto"}]
    assert r["ocr"] is None and r["muestra_del_medio"]["pagina"] == 2


def test_reporte_con_ocr_y_exclusiones_con_motivo():
    entradas = [entrada(2, "ocr", 6000, ocr_segundos=4.0, confianza_ocr=88.0, ocr_motor="tesseract", ocr_dpi=200,
                        calidad={"pct_alfabeticos": 0.95, "pct_palabras_conocidas": 0.9, "confianza_ocr": 88.0}),
                entrada(3, "ocr", 7000, ocr_segundos=6.0, confianza_ocr=90.0, ocr_motor="tesseract", ocr_dpi=200,
                        calidad={"pct_alfabeticos": 0.95, "pct_palabras_conocidas": 0.8, "confianza_ocr": 90.0})]
    plan = {"decisiones": [{"pagina": 1, "incluida": False, "motivos": ["escasa_lectura: portada"]},
                           {"pagina": 4, "incluida": False, "motivos": ["menor prioridad (puesto 1)"]},
                           {"pagina": 2, "incluida": True, "motivos": []}, {"pagina": 3, "incluida": True, "motivos": []}]}
    r = reporte_documento(DOC, entradas, paginas_pdf=4, plan=plan)
    assert r["paginas"]["excluidas"] == 2 and r["paginas"]["por_origen"] == {"texto": 0, "ocr": 2}
    assert r["paginas"]["excluidas_por_motivo"] == {"escasa_lectura (portada, formulario o tabla)": [1], "menor prioridad (fuera del subconjunto de OCR)": [4]}
    assert r["ocr"]["segundos_por_pagina"] == {"media": 5.0, "mediana": 5.0, "min": 4.0, "max": 6.0} and r["ocr"]["segundos_total"] == 10.0
    assert r["indicador_calidad"]["confianza_ocr_media"] == 89.0 and r["indicador_calidad"]["pct_palabras_conocidas_medio_ocr"] == 0.85


def test_markdown_incluye_los_indicadores_y_la_muestra():
    r = reporte_documento(DOC, [entrada(1), entrada(2)], paginas_pdf=2)
    md = reporte_a_markdown(r)
    assert "# Reporte de calidad de extracción — Doc de prueba" in md and "Muestra del medio" in md and "texto de la página 2" in md
    assert "2 con capa de texto" in md


def test_documento_sin_entradas_no_falla():
    r = reporte_documento(DOC, [], paginas_pdf=5)
    assert r["paginas"]["procesadas"] == 0 and r["paginas"]["excluidas"] == 5 and r["muestra_del_medio"] is None
