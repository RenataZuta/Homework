"""Orquestador de extracción: caché, reanudación tras Ctrl+C, prioridad, subconjunto y re-limpieza.
Usa un motor de OCR falso (cuenta llamadas) y PDFs sintéticos: no depende de Tesseract ni de los PDFs oficiales."""
import importlib.util
import io
import sys
from pathlib import Path

import pymupdf
import pytest
import yaml
from PIL import Image

from extraction import store
from rag_engine.config import RUTA_CONFIG_POR_DEFECTO, cargar_config

RUTA = Path(__file__).resolve().parents[1] / "scripts" / "run_extraction.py"
spec = importlib.util.spec_from_file_location("run_extraction", RUTA)
re_ = importlib.util.module_from_spec(spec)
sys.modules["run_extraction"] = re_
spec.loader.exec_module(re_)


def _png(ancho=200, alto=300):
    b = io.BytesIO()
    Image.new("RGB", (ancho, alto), "white").save(b, "PNG")
    return b.getvalue()


class MotorFalso:
    """Devuelve una cabecera (y=0.05) y un cuerpo (y=0.20). Cuenta llamadas; puede simular Ctrl+C en la k-ésima."""
    nombre = "falso"

    def __init__(self, interrumpir_en: int | None = None):
        self.llamadas = 0
        self.interrumpir_en = interrumpir_en

    def reconocer(self, imagen):
        self.llamadas += 1
        if self.interrumpir_en == self.llamadas:
            raise KeyboardInterrupt
        lineas = [[0.05, 1, "NORMAS LEGALES basura de cabecera", 0.1], [0.20, 2, f"Artículo {self.llamadas}. Texto del cuerpo de la página", 0.1]]
        return "\n\n".join(l[2] for l in lineas), 88.0, 10, lineas


@pytest.fixture
def entorno(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    txt = pymupdf.open()                                           # documento con capa de texto: 3 páginas
    for i in range(3):
        txt.new_page().insert_textbox(pymupdf.Rect(50, 50, 545, 700), f"Artículo {i + 1}. Texto legible de la página {i + 1}. " * 15)
    txt.save(raw / "doc_txt.pdf")
    esc = pymupdf.open()                                           # documento escaneado: 8 páginas
    for _ in range(8):
        pag = esc.new_page()
        pag.insert_image(pag.rect, stream=_png(), keep_proportion=False)
    esc.save(raw / "doc_esc.pdf")

    datos = yaml.safe_load(RUTA_CONFIG_POR_DEFECTO.read_text(encoding="utf-8"))
    datos["documentos"] = [
        {"id": "doc_txt", "nombre": "T", "archivo": "doc_txt.pdf", "url": "x", "url_pdf": None, "version": "v1", "rol": "norma_base"},
        {"id": "doc_esc", "nombre": "E", "archivo": "doc_esc.pdf", "url": "x", "url_pdf": None, "version": "v2", "rol": "reglamento"},
    ]
    datos["extraccion"]["rangos_paginas"] = {"doc_txt": None, "doc_esc": "2-6"}
    datos["extraccion"]["prioridad_ocr"] = {"doc_esc": [5]}
    datos["extraccion"]["codigo_fin_norma"] = {}
    datos["paths"]["raw"], datos["paths"]["processed"] = "raw", "processed"
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    cfg = cargar_config(tmp_path / "config.yaml", cargar_env=False)
    return cfg, dict(cfg.get("extraccion"))


def correr(cfg, ajustes, doc_id, motor=None, **kw):
    return re_.procesar_documento(cfg, cfg.documento(doc_id), ajustes, motor=motor, mostrar=lambda *_: None, **kw)


def paginas_guardadas(cfg, doc_id):
    return [e["pagina"] for e in store.listar_paginas(cfg.ruta("processed") / doc_id)]


# ── documento con texto ──

def test_documento_con_texto_guarda_una_entrada_por_pagina_con_su_numero(entorno):
    cfg, aj = entorno
    r = correr(cfg, aj, "doc_txt")
    assert (r.texto, r.ocr) == (3, 0) and paginas_guardadas(cfg, "doc_txt") == [1, 2, 3]
    e = store.leer_pagina(cfg.ruta("processed") / "doc_txt", 2)
    assert e["pagina"] == 2 and e["documento"] == "doc_txt" and e["version"] == "v1" and e["origen"] == "texto"
    assert "Artículo 2." in e["texto"] and e["ocr_segundos"] is None and e["calidad"]["pct_alfabeticos"] > 0.5


def test_segunda_corrida_de_texto_usa_la_cache(entorno):
    cfg, aj = entorno
    correr(cfg, aj, "doc_txt")
    r = correr(cfg, aj, "doc_txt")
    assert (r.texto, r.en_cache) == (0, 3)


# ── OCR: subconjunto, prioridad, cache y reanudación ──

def test_ocr_solo_procesa_el_subconjunto_y_reporta_lo_excluido(entorno):
    cfg, aj = entorno
    m = MotorFalso()
    r = correr(cfg, aj, "doc_esc", m)
    assert m.llamadas == 5 and paginas_guardadas(cfg, "doc_esc") == [2, 3, 4, 5, 6] and r.excluidas == 3


def test_las_paginas_prioritarias_se_procesan_primero():
    assert re_.orden_de_proceso([2, 3, 4, 5, 6], [5]) == [5, 2, 3, 4, 6]
    assert re_.orden_de_proceso([2, 3, 4], [9, 4, 4, 2]) == [4, 2, 3]     # ignora no disponibles y duplicados


def test_la_prioridad_se_refleja_en_el_orden_real_de_ocr(entorno):
    cfg, aj = entorno
    m = MotorFalso()
    correr(cfg, aj, "doc_esc", m, max_paginas=1)
    assert paginas_guardadas(cfg, "doc_esc") == [5]          # una corrida parcial ya deja lo más representativo


def test_segunda_corrida_completa_hace_cero_ocr(entorno):
    cfg, aj = entorno
    correr(cfg, aj, "doc_esc", MotorFalso())
    m2 = MotorFalso()
    r = correr(cfg, aj, "doc_esc", m2)
    assert m2.llamadas == 0 and r.ocr == 0 and r.en_cache == 5


def test_ctrl_c_a_mitad_y_reanudacion_continua_donde_quedo(entorno):
    cfg, aj = entorno
    m1 = MotorFalso(interrumpir_en=3)                        # Ctrl+C durante el OCR de la 3.ª página
    r1 = correr(cfg, aj, "doc_esc", m1)
    assert r1.interrumpido and r1.ocr == 2
    assert paginas_guardadas(cfg, "doc_esc") == [2, 5]       # 5 (prioritaria) y 2; la 3.ª NO quedó a medias
    assert not list((cfg.ruta("processed") / "doc_esc").glob("*.tmp"))

    m2 = MotorFalso()
    r2 = correr(cfg, aj, "doc_esc", m2)
    assert m2.llamadas == 3 and r2.en_cache == 2 and not r2.interrumpido      # solo las 3 que faltaban
    assert paginas_guardadas(cfg, "doc_esc") == [2, 3, 4, 5, 6]

    m3 = MotorFalso()
    correr(cfg, aj, "doc_esc", m3)
    assert m3.llamadas == 0


def test_restos_de_una_escritura_interrumpida_se_limpian(entorno):
    cfg, aj = entorno
    d = cfg.ruta("processed") / "doc_esc"
    d.mkdir(parents=True)
    (d / "p0003.json.tmp").write_text("{}", encoding="utf-8")
    correr(cfg, aj, "doc_esc", MotorFalso())
    assert not list(d.glob("*.tmp"))


def test_cambiar_el_dpi_invalida_el_cache_del_ocr(entorno):
    cfg, aj = entorno
    correr(cfg, aj, "doc_esc", MotorFalso())
    m = MotorFalso()
    correr(cfg, dict(aj, dpi=aj["dpi"] + 50), "doc_esc", m)
    assert m.llamadas == 5


def test_forzar_repite_el_ocr(entorno):
    cfg, aj = entorno
    correr(cfg, aj, "doc_esc", MotorFalso())
    m = MotorFalso()
    correr(cfg, aj, "doc_esc", m, forzar=True)
    assert m.llamadas == 5


def test_pagina_escaneada_sin_motor_falla_con_mensaje_claro(entorno):
    cfg, aj = entorno
    with pytest.raises(Exception, match="escaneo"):
        correr(cfg, aj, "doc_esc", None)


# ── limpieza de OCR y re-limpieza ──

def test_entrada_de_ocr_guarda_crudo_limpio_y_geometria(entorno):
    cfg, aj = entorno
    correr(cfg, aj, "doc_esc", MotorFalso())
    e = store.leer_pagina(cfg.ruta("processed") / "doc_esc", 5)
    assert "NORMAS LEGALES basura" in e["texto_crudo"] and "NORMAS LEGALES" not in e["texto"]      # antes / después
    assert e["limpieza"]["cabecera_eliminada"] == ["NORMAS LEGALES basura de cabecera"] and e["limpieza"]["reglas"] == ["R1o_banda_cabecera"]
    assert e["ocr_lineas"][0][0] == 0.05 and e["origen"] == "ocr" and e["ocr_motor"] == "falso" and e["confianza_ocr"] == 88.0
    assert e["ocr_segundos"] >= 0 and e["pagina"] == 5


def test_relimpiar_cambia_el_texto_sin_repetir_el_ocr(entorno):
    cfg, aj = entorno
    m = MotorFalso()
    correr(cfg, aj, "doc_esc", m)
    llamadas = m.llamadas
    ajustes_nuevos = dict(aj, ocr={"banda_cabecera": 0.30})           # ahora la banda también se traga el cuerpo (y=0.20)
    r = correr(cfg, ajustes_nuevos, "doc_esc", None, relimpiar=True)  # sin motor: no puede haber OCR
    assert r.relimpiadas == 5 and m.llamadas == llamadas
    e = store.leer_pagina(cfg.ruta("processed") / "doc_esc", 5)
    assert e["texto"] == "" and "Texto del cuerpo" in e["texto_crudo"] and e["ocr_segundos"] is not None
