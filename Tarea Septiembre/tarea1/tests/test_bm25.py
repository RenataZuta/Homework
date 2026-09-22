"""BM25, híbrido (RRF) y despacho por modo: matemática comprobada a mano, determinismo y la regla de que el umbral compara COSENOS."""
import math

import numpy as np
import pytest

from fakes import EmbedderFalso, LLMFalso, cfg_con, escribir_modificaciones, paginas_sinteticas
from indexing.build_index import construir_indice
from indexing.chunking import ConfigChunk
from rag_engine.config import cargar_config
from rag_engine.engine import MotorRAG
from rag_engine.retrieval import bm25, modos
from rag_engine.retrieval.bm25 import IndiceBM25, normalizar, ranking_bm25, stem_ligero, tokenizar
from rag_engine.retrieval.hybrid import buscar_hibrido, fusion_rrf
from rag_engine.retrieval.indice import abrir_cliente, nombre_coleccion
from rag_engine.retrieval.semantic import olvidar_matrices
from rag_engine.retrieval.versions import Modificaciones

BASE = cargar_config(cargar_env=False)
DOCS = {d["id"]: d for d in BASE.documentos}


# ── preprocesamiento ──

def test_normalizar_quita_tildes_y_mayusculas_y_unifica_la_enie():
    assert normalizar("Garantía de Fiel Cumplimiento — AÑO") == "garantia de fiel cumplimiento — ano"


def test_los_numeros_de_articulo_son_terminos_y_las_stopwords_se_quitan():
    assert tokenizar("El artículo 114 de la Ley y el 149.1") == ["articulo", "114", "ley", "149", "1"]


def test_el_stemmer_ligero_unifica_plurales_sin_tocar_numeros_ni_palabras_cortas():
    assert [stem_ligero(t) for t in ("contratos", "entidades", "garantias", "contrataciones", "ley", "114", "mas", "clase")] == \
           ["contrato", "entidad", "garantia", "contratacion", "ley", "114", "mas", "clase"]
    assert tokenizar("Las garantías y la garantía", stemming=True) == ["garantia", "garantia"]
    assert tokenizar("Las garantías", stemming=False) == ["garantias"]


# ── BM25 ──

CORPUS = ["pago plazo diez dias habiles conformidad", "penalidad mora retraso injustificado dias", "garantia fiel cumplimiento retencion pago micro empresa", "recurso apelacion garantia"]


def test_bm25_coincide_con_la_formula_calculada_a_mano():
    idx = IndiceBM25(CORPUS, k1=1.5, b=0.75)
    n, n_t = 4, 2                                                   # «garantia» está en 2 de 4 documentos
    idf = math.log(1 + (n - n_t + 0.5) / (n_t + 0.5))
    avgdl = np.mean([6, 5, 7, 3])                              # largos tras quitar stopwords
    esperado = idf * 1 * 2.5 / (1 + 1.5 * (1 - 0.75 + 0.75 * 3 / avgdl))       # documento 3 (largo 3), tf = 1
    assert idx.idf("garantia") == pytest.approx(idf) and idx.puntuar("garantia")[3] == pytest.approx(esperado, rel=1e-5)


def test_un_termino_raro_pesa_mas_que_uno_comun_y_el_idf_nunca_es_negativo():
    idx = IndiceBM25(CORPUS + ["dias dias dias"] * 3)
    assert idx.idf("apelacion") > idx.idf("dias") > 0 and idx.idf("inexistente") > 0


def test_el_documento_mas_corto_gana_con_el_mismo_tf_y_b_controla_el_efecto():
    docs = ["garantia", "garantia " + "relleno " * 20]
    con_b, sin_b = IndiceBM25(docs, b=0.75).puntuar("garantia"), IndiceBM25(docs, b=0.0).puntuar("garantia")
    assert con_b[0] > con_b[1] and sin_b[0] == pytest.approx(sin_b[1])


def test_sin_terminos_en_comun_el_puntaje_es_cero():
    assert IndiceBM25(CORPUS).puntuar("zzz qqq").sum() == 0 and IndiceBM25(CORPUS).puntuar("de la y").sum() == 0


def test_saturacion_de_la_frecuencia_del_termino():
    idx = IndiceBM25(["pago " * n + "x" for n in (1, 2, 4, 8, 64)] + ["otro"] * 3)
    p = idx.puntuar("pago")[:5]
    assert all(p[i] < p[i + 1] for i in range(4)) and p[4] - p[3] < p[1] - p[0]             # crece, pero cada vez menos (k1)


@pytest.mark.parametrize("k1, b", [(0, 0.5), (-1, 0.5), (1.5, -0.1), (1.5, 1.1)])
def test_parametros_invalidos_fallan(k1, b):
    with pytest.raises(ValueError):
        IndiceBM25(CORPUS, k1=k1, b=b)


def test_el_ranking_excluye_ceros_y_desempata_por_id():
    p = np.array([0.0, 2.0, 2.0, 1.0], dtype=np.float32)
    assert ranking_bm25(p, ["a", "z", "b", "c"], 10) == [2, 1, 3] and ranking_bm25(p, ["a", "z", "b", "c"], 2) == [2, 1]


# ── sobre un índice real de juguete ──

@pytest.fixture
def col(tmp_path):
    olvidar_matrices()
    e = EmbedderFalso()
    docs = {i: (DOCS[i], ps) for i, ps in paginas_sinteticas().items()}
    construir_indice(e, ConfigChunk("t500", 500, 50), docs, tmp_path / "index", "normas", {"ley": 100, "reglamento": 389}, mostrar=lambda *_: None)
    c = abrir_cliente(tmp_path / "index").get_collection(nombre_coleccion("normas", "t500", e.name))
    c._e, c._tmp = e, tmp_path
    return c


def test_buscar_bm25_ordena_por_bm25_pero_la_similitud_es_el_coseno(col):
    r = bm25.buscar_bm25(col, col._e, "penalidad por mora en la ejecución de la prestación", 3)
    assert r and r[0].documento == "ds_009_2025_ef" and r[0].pagina == 31                     # coincidencia léxica exacta
    assert all(x.puntaje > 0 for x in r) and [x.puntaje for x in r] == sorted((x.puntaje for x in r), reverse=True)
    v = col._e.embed_query("penalidad por mora en la ejecución de la prestación")
    coseno = float(np.dot(v, np.asarray(col.get(ids=[r[0].id], include=["embeddings"])["embeddings"][0])))
    assert r[0].similitud == pytest.approx(coseno, abs=1e-5) and r[0].similitud != r[0].puntaje       # NO son lo mismo


def test_bm25_sin_coincidencias_lexicas_devuelve_lista_vacia(col):
    assert bm25.buscar_bm25(col, col._e, "zzz qqq xxx", 5) == []


def test_bm25_es_determinista_y_el_indice_se_construye_una_vez(col):
    a = [x.id for x in bm25.buscar_bm25(col, col._e, "retención de pago garantía", 5)]
    n_cache = len(bm25._CACHE)
    b = [x.id for x in bm25.buscar_bm25(col, col._e, "retención de pago garantía", 5)]
    assert a == b and len(bm25._CACHE) == n_cache == 1
    olvidar_matrices()
    assert len(bm25._CACHE) == 0                                                                # la indexación invalida también BM25


def test_el_encabezado_ayuda_a_encontrar_articulos_por_su_titulo(col):
    con = bm25.buscar_bm25(col, col._e, "Penalidad por mora", 1, usar_encabezado=True)
    assert con and con[0].pagina == 31


# ── RRF e híbrido ──

def test_rrf_suma_reciprocos_de_rangos_a_mano():
    f = fusion_rrf([[10, 20, 30], [20, 30, 40]], rrf_k=60)
    assert f[20] == pytest.approx(1 / 62 + 1 / 61) and f[10] == pytest.approx(1 / 61) and f[40] == pytest.approx(1 / 63)
    assert max(f, key=f.get) == 20 and f[30] == pytest.approx(1 / 63 + 1 / 62)


def test_rrf_no_depende_de_la_escala_de_los_puntajes_solo_de_las_posiciones():
    assert fusion_rrf([[1, 2]], 60) == fusion_rrf([[1, 2]], 60) and fusion_rrf([[1, 2]], 1)[1] > fusion_rrf([[1, 2]], 60)[1]


def test_el_hibrido_incluye_lo_que_solo_uno_de_los_dos_encuentra(col):
    """Una consulta con términos exactos y sin similitud semántica útil (embedder de juguete): el híbrido trae lo léxico."""
    r = buscar_hibrido(col, col._e, "penalidad mora retraso", 5)
    assert any(x.pagina == 31 and x.documento == "ds_009_2025_ef" for x in r)
    assert [x.puntaje for x in r] == sorted((x.puntaje for x in r), reverse=True) and all(-1.0 <= x.similitud <= 1.0 for x in r)


def test_el_hibrido_devuelve_a_lo_sumo_k_y_sin_repetidos(col):
    r = buscar_hibrido(col, col._e, "garantía retención de pago", 4)
    assert len(r) <= 4 and len({x.id for x in r}) == len(r)


# ── despacho por modo ──

@pytest.mark.parametrize("modo, esperado", [("semantico", "sem"), ("bm25", "bm25"), ("hibrido", "hib")])
def test_el_motor_usa_el_modo_de_la_config(col, monkeypatch, modo, esperado):
    llamados = []
    monkeypatch.setattr(modos, "buscar_semantico", lambda *a, **k: llamados.append("sem") or [])
    monkeypatch.setattr(modos, "buscar_bm25", lambda *a, **k: llamados.append("bm25") or [])
    monkeypatch.setattr(modos, "buscar_hibrido", lambda *a, **k: llamados.append("hib") or [])
    modos.buscar_por_modo(col, col._e, "x", cfg_con(BASE, **{"retrieval.modo": modo}))
    assert llamados == [esperado]


def test_un_modo_desconocido_es_un_error(col):
    with pytest.raises(ValueError, match="magico"):
        modos.buscar_por_modo(col, col._e, "x", cfg_con(BASE, **{"retrieval.modo": "magico"}))


def test_los_parametros_de_bm25_vienen_de_la_config(col, monkeypatch):
    visto = {}
    monkeypatch.setattr(modos, "buscar_bm25", lambda c, e, q, k, **kw: visto.update(kw) or [])
    modos.buscar_por_modo(col, col._e, "x", cfg_con(BASE, **{"retrieval.modo": "bm25", "retrieval.bm25.k1": 1.2, "retrieval.bm25.b": 0.5, "retrieval.bm25.stemming": True}))
    assert visto == {"k1": 1.2, "b": 0.5, "stemming": True, "usar_encabezado": True}


# ── compuerta del umbral con BM25/híbrido ──

def motor_con(col, modo, umbral, llm):
    ruta = col._tmp / "m.json"
    escribir_modificaciones(ruta)
    from rag_engine.llm.pricing import cargar_tabla
    cfg = cfg_con(BASE, **{"retrieval.modo": modo, "retrieval.umbral_similitud": umbral, "retrieval.top_k": 3})
    return MotorRAG(cfg, col._e, col, Modificaciones.cargar(ruta), cargar_tabla(BASE.ruta("pricing"), "gemini"), cliente_llm=llm, ruta_log=col._tmp / "l.jsonl")


@pytest.mark.parametrize("modo", ["bm25", "hibrido"])
def test_la_compuerta_compara_cosenos_no_puntajes_de_bm25(col, modo):
    q = "penalidad por mora en la ejecución de la prestación"
    llm = LLMFalso()
    r = motor_con(col, modo, 0.0, llm).responder(q)
    assert r.error is None and not r.abstuvo and r.mejor_similitud == max(f.similitud for f in r.fuentes)
    assert r.mejor_similitud <= 1.0                                    # un puntaje BM25 típico (> 1) jamás se confunde con la similitud
    llm2 = LLMFalso()
    r2 = motor_con(col, modo, r.mejor_similitud + 0.01, llm2).responder(q)
    assert r2.abstuvo and r2.motivo_abstencion == "umbral" and llm2.llamadas == []


def test_el_mejor_coseno_es_el_maximo_aunque_el_primero_por_orden_no_lo_sea(col, monkeypatch):
    from rag_engine import engine as motor_mod
    from rag_engine.retrieval.semantic import Recuperado
    fijos = [Recuperado("a", "ley_32069", "v", 1, 0.40, "t", {}, 9.0), Recuperado("b", "ley_32069", "v", 2, 0.92, "t", {}, 1.0)]     # 1.º: BM25 alto, coseno bajo
    monkeypatch.setattr(motor_mod, "buscar_por_modo", lambda *a, **k: fijos)
    assert motor_con(col, "bm25", 0.9, LLMFalso()).responder("x").abstuvo is False and motor_con(col, "bm25", 0.95, LLMFalso()).responder("x").abstuvo is True


def test_si_bm25_no_encuentra_nada_se_abstiene_sin_llamar_al_llm(col):
    llm = LLMFalso()
    r = motor_con(col, "bm25", 0.0, llm).responder("zzz qqq xxx")
    assert r.abstuvo and r.motivo_abstencion == "umbral" and llm.llamadas == [] and r.fuentes == []


# ── evaluación ──

def test_la_evaluacion_usa_el_mayor_coseno_como_mejor_similitud_no_el_del_primer_lugar():
    from evaluation.eval_set import Pregunta
    from evaluation.metrics import evaluar_recuperacion
    from rag_engine.retrieval.semantic import Recuperado
    q = Pregunta(id="q1", pregunta="x", tipo="in_domain", estilo="coloquial", modificada_2026=False, esperados={"ley_32069": [5]})
    rec = [Recuperado("a", "ley_32069", "v", 5, 0.30, "t"), Recuperado("b", "ley_32069", "v", 6, 0.88, "t")]
    r = evaluar_recuperacion([q], lambda t, k: rec).por_pregunta[0]
    assert r.mejor_similitud == 0.88 and r.rango_acierto == 1


# ── sonda de números de artículo ──

def test_la_sonda_de_articulos_mide_aciertos_con_las_paginas_del_encabezado():
    from evaluation.compare_retrievers import sonda_articulos
    from rag_engine.retrieval.semantic import Recuperado
    articulos = {66: {("ley_32069", 32)}, 67: {("ley_32069", 33)}}

    def bueno(t, k):                                                  # siempre trae la página correcta primero
        n = int(t.split()[1])
        return [Recuperado("x", "ley_32069", "v", {66: 32, 67: 33}[n], 0.9, "t")]

    def malo(t, k):                                                   # trae la correcta en 3.er lugar para 66 y nunca para 67
        return [Recuperado("a", "ley_32069", "v", 1, 0.5, "t"), Recuperado("b", "ley_32069", "v", 2, 0.4, "t")] + ([Recuperado("c", "ley_32069", "v", 32, 0.3, "t")] if "66" in t else [])
    f = {x["variante"]: x for x in sonda_articulos({"bueno": bueno, "malo": malo}, articulos)}
    assert (f["bueno"]["recall@1"], f["bueno"]["recall@3"]) == (1.0, 1.0)
    assert (f["malo"]["recall@1"], f["malo"]["recall@3"], f["malo"]["recall@5"], f["malo"]["consultas"]) == (0.0, 0.5, 0.5, 2)
