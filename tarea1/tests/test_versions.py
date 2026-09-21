"""Manejo de versiones en las dos direcciones: original -> modificatoria y modificatoria -> original."""
import pytest

from fakes import EmbedderFalso, escribir_modificaciones, paginas_sinteticas
from indexing.build_index import construir_indice
from indexing.chunking import ConfigChunk
from rag_engine.config import cargar_config
from rag_engine.retrieval.indice import abrir_cliente, nombre_coleccion
from rag_engine.retrieval.semantic import buscar
from rag_engine.retrieval.versions import GestorVersiones, Modificaciones, articulos_de_metadato, parsear_encabezado

BASE = cargar_config(cargar_env=False)
DOCS = {d["id"]: d for d in BASE.documentos}
ROLES = {i: d["rol"] for i, d in DOCS.items()}
MAX = {"ley": 100, "reglamento": 389}
AVISO = BASE.get("mensajes.aviso_version")
Q_ORIGINAL = "retención de pago garantía micro pequeña empresa independencia del monto"          # las palabras del art. 114 ORIGINAL
Q_MODIF = "retención de pago primera mitad del número total de pagos prorrateada"                # las palabras del 114.2 (DS 001)


def montar(tmp_path, paginas=None):
    e = EmbedderFalso()
    paginas = paginas or paginas_sinteticas()
    construir_indice(e, ConfigChunk("t500", 500, 50), {i: (DOCS[i], ps) for i, ps in paginas.items()}, tmp_path / "index", "normas", MAX, mostrar=lambda *_: None)
    col = abrir_cliente(tmp_path / "index").get_collection(nombre_coleccion("normas", "t500", e.name))
    ruta = tmp_path / "mods.json"
    escribir_modificaciones(ruta)
    return e, col, Modificaciones.cargar(ruta)


def gestor(col, mods, max_mod=3, max_orig=2):
    return GestorVersiones(col, mods, ROLES, AVISO, max_mod, max_orig)


def procesar(tmp_path, consulta, k, paginas=None, **kw):
    e, col, mods = montar(tmp_path, paginas)
    rec = buscar(col, e, consulta, k)
    forz, avisos, marcados = gestor(col, mods, **kw).procesar(e.embed_query(consulta), rec)
    return rec, forz, avisos, marcados


# ── utilidades ──

def test_articulos_de_metadato_y_encabezado():
    assert articulos_de_metadato(",15,114,") == [15, 114] and articulos_de_metadato("") == [] and articulos_de_metadato(None) == []
    assert parsear_encabezado("Artículo 114. Retención de pago") == (114, "retencion de pago")
    assert parsear_encabezado("Artículo 143. Tipos de garantías contractuales") == (143, "tipos de garantias contractuales") and parsear_encabezado("") is None


# ── dirección 1: original -> modificatoria ──

def test_el_original_recuperado_dispara_el_aviso_y_fuerza_el_ds_001(tmp_path):
    rec, forz, avisos, marcados = procesar(tmp_path, Q_ORIGINAL, k=1)
    assert [r.documento for r in rec] == ["ds_009_2025_ef"] and marcados == [114]
    assert avisos == ["El artículo 114 del Reglamento fue modificado por el DS 001-2026-EF (numeral 114.2 (incorporado)); prevalece el texto de la modificatoria."]
    assert len(forz) == 1 and forz[0].documento == "ds_001_2026_ef" and forz[0].pagina == 14 and forz[0].metadatos["origen"] == "version" and "114.2" in forz[0].texto


def test_no_fuerza_lo_que_ya_estaba_recuperado(tmp_path):
    rec, forz, avisos, _ = procesar(tmp_path, Q_ORIGINAL, k=4)          # con 4 fragmentos entra todo el índice
    assert avisos and forz == [] and len({r.id for r in rec}) == len(rec)


def test_el_maximo_de_forzados_del_ds_001_se_respeta(tmp_path):
    _, forz, avisos, _ = procesar(tmp_path, Q_ORIGINAL, k=1, max_mod=0)
    assert forz == [] and avisos


# ── dirección 2: modificatoria -> original ──

def test_el_ds_001_recuperado_avisa_y_fuerza_el_texto_original(tmp_path):
    rec, forz, avisos, marcados = procesar(tmp_path, Q_MODIF, k=1)
    assert [r.documento for r in rec] == ["ds_001_2026_ef"] and marcados == [114] and len(avisos) == 1
    assert len(forz) == 1 and forz[0].documento == "ds_009_2025_ef" and forz[0].pagina == 30 and forz[0].metadatos["origen"] == "original"
    assert "independencia del monto" in forz[0].texto                       # el texto original completo que el DS 001 no transcribe


def test_el_original_se_enlaza_por_titulo_si_el_ocr_leyo_mal_el_numero(tmp_path):
    p = paginas_sinteticas()
    p["ds_009_2025_ef"][0]["texto"] = p["ds_009_2025_ef"][0]["texto"].replace("Artículo 114. Retención de pago", "Artículo 143. Retención de pago")     # 114 leído como 143
    _, forz, avisos, marcados = procesar(tmp_path, Q_MODIF, k=1, paginas=p)
    assert marcados == [114] and [r.pagina for r in forz] == [30] and forz[0].metadatos["origen"] == "original"


def test_el_maximo_de_originales_forzados_se_respeta(tmp_path):
    _, forz, avisos, _ = procesar(tmp_path, Q_MODIF, k=1, max_orig=0)
    assert forz == [] and avisos                                            # el aviso se da igual


def test_no_duplica_el_original_si_ya_estaba_recuperado(tmp_path):
    rec, forz, avisos, _ = procesar(tmp_path, Q_MODIF, k=3)
    assert {"ds_001_2026_ef", "ds_009_2025_ef"} <= {r.documento for r in rec} and forz == [] and avisos


# ── lo que NO debe pasar ──

def test_un_fragmento_de_la_ley_no_dispara_versiones_aunque_hable_del_articulo_114(tmp_path):
    p = paginas_sinteticas()
    p["ley_32069"] = [{"pagina": 5, "origen": "texto", "texto": "Artículo 114. Regla propia de la Ley\n\nEl artículo 114 de la Ley regula un asunto distinto del Reglamento."}]
    rec, forz, avisos, marcados = procesar(tmp_path, "Regla propia de la Ley asunto distinto del Reglamento", k=1, paginas=p)
    assert [r.documento for r in rec] == ["ley_32069"] and avisos == [] and forz == [] and marcados == []


def test_sin_articulos_modificados_no_hay_nada_que_hacer(tmp_path):
    _, forz, avisos, marcados = procesar(tmp_path, "penalidad por mora retraso injustificado día de atraso fórmula", k=1)
    assert (forz, avisos, marcados) == ([], [], [])


def test_el_detalle_resume_los_cambios_del_articulo():
    m = Modificaciones()
    from rag_engine.retrieval.versions import Cambio
    m.por_articulo[7] = [Cambio(7, "modifica", "numeral 7.1", 3), Cambio(7, "incorpora", "numeral 7.4", 9), Cambio(7, "modifica", "numeral 7.1", 3)]
    assert m.detalle(7) == "numeral 7.1 (modificado); numeral 7.4 (incorporado)"          # sin repetidos


def test_con_los_datos_reales_el_json_de_modificaciones_carga():
    from rag_engine.retrieval.versions import Modificaciones as M
    m = M.cargar(BASE.ruta("articulos_modificados"))
    assert len(m.por_articulo) == 105 and 114 in m.por_articulo and 42 in m.por_articulo and len(m.por_articulo[42]) == 2
