"""Indexación: idempotencia, reanudación y aislamiento entre documentos (las tres pruebas que exige el issue), más recuperación."""
import numpy as np
import pytest

from fakes import EmbedderFalso
from indexing.build_index import construir_indice
from indexing.chunking import ConfigChunk, trocear_documento
from rag_engine.retrieval.indice import IndiceNoDisponible, abrir_cliente, abrir_para_lectura, nombre_coleccion
from rag_engine.retrieval.semantic import buscar
from rag_engine.config import cargar_config

MAX = {"ley": 100, "reglamento": 389}
CH = ConfigChunk("t300_o50", 300, 50)
PREF = "normas"


def doc(id_, rol="norma_base"):
    return {"id": id_, "version": f"v_{id_}", "rol": rol}


def paginas(tema, n=6):
    """n páginas con vocabulario propio del `tema` (cada una con ~3 fragmentos)."""
    salida = []
    for p in range(1, n + 1):
        cuerpo = "\n\n".join(f"{p}.{k}. " + " ".join(f"{tema}p{p}k{k}w{w}" for w in range(30)) + "." for k in range(1, 4))
        salida.append({"pagina": p, "texto": f"Artículo {p}. Título {tema}{p}\n\n{cuerpo}", "origen": "texto"})
    return salida


def corpus(*ids):
    return {i: (doc(i), paginas(i)) for i in ids}


def construir(tmp_path, docs, embedder=None, lote=5, **kw):
    e = embedder or EmbedderFalso()
    return e, construir_indice(e, CH, docs, tmp_path / "index", PREF, MAX, lote_upsert=lote, mostrar=lambda *_: None, **kw)


def coleccion(tmp_path, embedder_name=EmbedderFalso.name):
    return abrir_cliente(tmp_path / "index").get_collection(nombre_coleccion(PREF, CH.nombre, embedder_name))


def instantanea(col, doc_id=None):
    r = col.get(where={"documento": doc_id} if doc_id else None, include=["metadatas", "embeddings", "documents"])
    return {i: (m["hash_texto"], tuple(np.round(v, 5)), d) for i, m, v, d in zip(r["ids"], r["metadatas"], r["embeddings"], r["documents"])}


# ── (a) idempotencia ──

def test_construir_dos_veces_da_el_mismo_conteo_y_la_segunda_no_embebe_nada(tmp_path):
    e, r1 = construir(tmp_path, corpus("aaa", "bbb"))
    assert r1.total_en_indice == r1.fragmentos_esperados == r1.nuevos > 20
    antes = instantanea(coleccion(tmp_path))
    e2, r2 = construir(tmp_path, corpus("aaa", "bbb"))
    assert r2.total_en_indice == r1.total_en_indice and (r2.nuevos, r2.actualizados, r2.eliminados) == (0, 0, 0)
    assert r2.existentes == r1.fragmentos_esperados and e2.textos_embebidos == [] and e2.contabilidad.llamadas == 0
    assert instantanea(coleccion(tmp_path)) == antes


# ── (b) reanudación ──

def test_interrumpir_a_mitad_y_relanzar_da_el_mismo_resultado(tmp_path):
    ref = tmp_path / "ref"
    ref.mkdir()
    _, completo = construir(ref, corpus("aaa", "bbb"))
    esperado = instantanea(coleccion(ref))

    class Interrumpe(EmbedderFalso):
        def _codificar(self, textos, es_consulta):
            if self.contabilidad.llamadas >= 2:            # Ctrl+C durante el 3.er lote
                raise KeyboardInterrupt
            return super()._codificar(textos, es_consulta)

    e1 = Interrumpe(batch=5)
    _, parcial = construir(tmp_path, corpus("aaa", "bbb"), embedder=e1, lote=5)
    assert parcial.interrumpido and 0 < parcial.total_en_indice < completo.total_en_indice
    guardados = parcial.total_en_indice

    e2, resumen = construir(tmp_path, corpus("aaa", "bbb"), lote=5)
    assert not resumen.interrumpido and resumen.total_en_indice == completo.total_en_indice
    assert resumen.existentes == guardados and resumen.nuevos == completo.total_en_indice - guardados
    assert len(e2.textos_embebidos) == resumen.nuevos                      # solo embebió lo que faltaba
    assert instantanea(coleccion(tmp_path)) == esperado                   # idéntico a una corrida sin interrupción


# ── (c) agregar un documento no toca los demás ──

def test_agregar_un_documento_no_cambia_los_fragmentos_de_los_demas(tmp_path):
    construir(tmp_path, corpus("aaa", "bbb"))
    col = coleccion(tmp_path)
    antes = {d: instantanea(col, d) for d in ("aaa", "bbb")}

    e, r = construir(tmp_path, corpus("aaa", "bbb", "ccc"))
    despues = {d: instantanea(col, d) for d in ("aaa", "bbb")}
    assert despues == antes                                               # mismos IDs, hashes, vectores y textos
    assert r.nuevos == r.por_documento["ccc"] and r.eliminados == 0 and r.actualizados == 0
    assert e.textos_embebidos and all("cccp" in t for t in e.textos_embebidos)     # solo se embebió el documento nuevo
    assert not any("aaap" in t or "bbbp" in t for t in e.textos_embebidos)
    assert set(instantanea(col, "ccc")) and len(instantanea(col)) == sum(r.por_documento.values())


def test_construir_solo_un_documento_no_borra_los_otros(tmp_path):
    construir(tmp_path, corpus("aaa", "bbb"))
    total = coleccion(tmp_path).count()
    construir(tmp_path, corpus("aaa"))                                    # se reconstruye solo aaa
    assert coleccion(tmp_path).count() == total


# ── contenido que cambia ──

def test_si_cambia_una_pagina_solo_se_reembeben_sus_fragmentos(tmp_path):
    docs = corpus("aaa", "bbb")
    construir(tmp_path, docs)
    col = coleccion(tmp_path)
    antes = instantanea(col)
    docs["aaa"][1][2]["texto"] = docs["aaa"][1][2]["texto"].replace("aaap3k1w0", "TEXTO_NUEVO_CORREGIDO")
    e, r = construir(tmp_path, docs)
    assert r.actualizados >= 1 and r.nuevos == 0 and r.eliminados == 0
    assert any("TEXTO_NUEVO_CORREGIDO" in t for t in e.textos_embebidos) and len(e.textos_embebidos) == r.actualizados
    despues = instantanea(col)
    cambiados = {i for i in antes if antes[i][0] != despues[i][0]}
    assert len(cambiados) == r.actualizados and all(i.split(":")[2] == "p0003" for i in cambiados)


def test_si_una_pagina_produce_menos_fragmentos_se_borran_los_obsoletos_solo_de_ese_documento(tmp_path):
    docs = corpus("aaa", "bbb")
    construir(tmp_path, docs)
    n_bbb = len(instantanea(coleccion(tmp_path), "bbb"))
    docs["aaa"] = (docs["aaa"][0], docs["aaa"][1][:3])                    # aaa pierde tres páginas
    _, r = construir(tmp_path, docs)
    assert r.eliminados > 0 and r.nuevos == 0 and r.actualizados == 0
    col = coleccion(tmp_path)
    assert len(instantanea(col, "bbb")) == n_bbb
    assert max(int(m["pagina"]) for m in col.get(where={"documento": "aaa"}, include=["metadatas"])["metadatas"]) == 3


# ── estructura del índice ──

def test_ids_y_metadatos_del_indice(tmp_path):
    docs = corpus("aaa", "bbb")
    construir(tmp_path, docs)
    esperados = {f.id for d, (dc, ps) in docs.items() for f in trocear_documento(dc, ps, CH, MAX)}
    col = coleccion(tmp_path)
    r = col.get(include=["metadatas"])
    assert set(r["ids"]) == esperados and len(esperados) == len(r["ids"])
    m = r["metadatas"][0]
    assert {"documento", "version", "pagina", "es_ocr", "posicion", "articulos_ley", "articulos_reglamento", "hash_texto"} <= set(m)


def test_troceados_distintos_conviven_sin_pisarse(tmp_path):
    docs = corpus("aaa")
    construir(tmp_path, docs)
    otro = ConfigChunk("t600_o100", 600, 100)
    e = EmbedderFalso()
    construir_indice(e, otro, docs, tmp_path / "index", PREF, MAX, mostrar=lambda *_: None)
    c = abrir_cliente(tmp_path / "index")
    assert {x.name for x in c.list_collections()} == {nombre_coleccion(PREF, CH.nombre, e.name), nombre_coleccion(PREF, otro.nombre, e.name)}


# ── recuperación ──

def test_la_busqueda_devuelve_el_fragmento_correcto_con_su_pagina_y_similitud_ordenada(tmp_path):
    construir(tmp_path, corpus("aaa", "bbb"))
    col, e = coleccion(tmp_path), EmbedderFalso()
    r = buscar(col, e, "bbbp4k2w5 bbbp4k2w6 bbbp4k2w7 bbbp4k2w8", k=5)
    assert (r[0].documento, r[0].pagina) == ("bbb", 4) and r[0].version == "v_bbb"
    sims = [x.similitud for x in r]
    assert sims == sorted(sims, reverse=True) and 0.0 < sims[0] <= 1.0 + 1e-6 and len(r) == 5


def test_una_consulta_igual_al_texto_embebido_tiene_similitud_1(tmp_path):
    sin_contexto = ConfigChunk("sin_ctx", 300, 50, contexto_encabezado=False)     # así texto mostrado == texto embebido
    e = EmbedderFalso()
    construir_indice(e, sin_contexto, corpus("aaa"), tmp_path / "index", PREF, MAX, mostrar=lambda *_: None)
    col = abrir_cliente(tmp_path / "index").get_collection(nombre_coleccion(PREF, "sin_ctx", e.name))
    texto = col.get(limit=1, include=["documents"])["documents"][0]
    assert buscar(col, EmbedderFalso(), texto, k=1)[0].similitud == pytest.approx(1.0, abs=1e-4)      # distancia coseno = 0


def test_con_contexto_de_encabezado_el_vector_incluye_el_encabezado_pero_no_el_texto_mostrado(tmp_path):
    construir(tmp_path, corpus("aaa"))
    col = coleccion(tmp_path)
    r = col.get(limit=1, include=["documents", "metadatas"])
    assert r["metadatas"][0]["encabezado"].startswith("Artículo") and not r["documents"][0].startswith(r["metadatas"][0]["encabezado"] + "\n" + r["metadatas"][0]["encabezado"])
    sim = buscar(col, EmbedderFalso(), r["documents"][0], k=1)[0].similitud
    assert 0.5 < sim < 1.0                                                            # muy cercano, pero no idéntico


def test_filtro_por_metadatos(tmp_path):
    construir(tmp_path, corpus("aaa", "bbb"))
    r = buscar(coleccion(tmp_path), EmbedderFalso(), "aaap1k1w1 bbbp1k1w1", k=8, donde={"documento": "bbb"})
    assert r and all(x.documento == "bbb" for x in r)


def test_k_mayor_que_el_indice_no_falla(tmp_path):
    construir(tmp_path, {"aaa": (doc("aaa"), paginas("aaa", 1))})
    col = coleccion(tmp_path)
    assert len(buscar(col, EmbedderFalso(), "aaap1k1w1", k=500)) == col.count()


# ── índice ausente ──

def test_indice_inexistente_da_un_error_con_instrucciones(tmp_path):
    cfg = cargar_config(cargar_env=False)
    with pytest.raises(IndiceNoDisponible, match="build_index.py"):
        abrir_para_lectura(cfg, dir_index=tmp_path / "no_existe")


def test_coleccion_inexistente_o_vacia_da_error(tmp_path):
    cfg = cargar_config(cargar_env=False)
    abrir_cliente(tmp_path / "index")
    with pytest.raises(IndiceNoDisponible, match="no encontrada"):
        abrir_para_lectura(cfg, dir_index=tmp_path / "index")
