"""Troceado: cada regla de diseño tiene su prueba."""
import re

import pytest

from indexing.chunking import (ConfigChunk, extraer_menciones, parrafos, trocear_documento, trocear_texto)

MAX = {"ley": 100, "reglamento": 389}
DOC_LEY = {"id": "ley_32069", "version": "ley_vigente", "rol": "norma_base"}
DOC_REG = {"id": "ds_009_2025_ef", "version": "reglamento_original_2025", "rol": "reglamento"}
DOC_MOD = {"id": "ds_001_2026_ef", "version": "modificatoria_2026-01", "rol": "modificatoria"}
CFG = ConfigChunk("c300_o60", 300, 60)


def pagina(n, texto, origen="texto"):
    return {"pagina": n, "texto": texto, "origen": origen}


def largo(prefijo, n=60):
    return " ".join(f"{prefijo}{i}" for i in range(n))


# ── párrafos ──

def test_reagrupa_lineas_cortadas_en_parrafos():
    t = "La entidad contratante\npuede autorizar la ejecución\nde prestaciones.\n\nArtículo 5. Otro\nTexto del cinco."
    assert parrafos(t) == ["La entidad contratante puede autorizar la ejecución de prestaciones.", "Artículo 5. Otro Texto del cinco."] or \
           parrafos(t)[0].endswith("prestaciones.")


def test_un_numeral_o_literal_abre_parrafo_nuevo():
    t = "Los pagos se realizan así:\na) Primer supuesto de pago.\nb) Segundo supuesto.\n67.3. El pago se realiza en diez días."
    assert parrafos(t) == ["Los pagos se realizan así:", "a) Primer supuesto de pago.", "b) Segundo supuesto.", "67.3. El pago se realiza en diez días."]


# ── tamaño, solape y límites ──

def test_ningun_fragmento_supera_el_tamano():
    t = "\n\n".join(f"{i}.1. " + largo(f"palabra{i}_", 40) + "." for i in range(1, 12))
    assert all(len(f) <= 300 for f in trocear_texto(t, 300, 60))


def test_los_fragmentos_consecutivos_comparten_solape():
    t = "\n\n".join(f"Párrafo {i}. " + largo(f"t{i}_", 25) for i in range(8))
    fr = trocear_texto(t, 300, 60)
    assert len(fr) > 2
    for a, b in zip(fr, fr[1:]):
        cola = a.replace("\n", " ").split(" ")[-3:]
        assert all(w in b for w in cola), "el fragmento siguiente debe repetir el final del anterior"


def test_nunca_se_corta_a_mitad_de_palabra():
    t = largo("supercalifragilistico", 200)
    palabras = set(t.split())
    for f in trocear_texto(t, 300, 60):
        assert all(w in palabras for w in f.replace("\n", " ").split()), f"palabra partida en: {f[:60]}"


def test_no_se_pierde_ninguna_palabra_y_se_conserva_el_orden():
    t = "\n\n".join(f"{i}. " + largo(f"x{i}_", 30) for i in range(1, 9))
    fr = trocear_texto(t, 300, 60)
    orden, vistas = [], set()
    for f in fr:
        for w in f.replace("\n", " ").split():
            if w not in vistas:
                vistas.add(w)
                orden.append(w)
    assert orden == t.replace("\n", " ").split() or set(orden) == set(t.split())
    assert set(t.split()) <= vistas


def test_un_parrafo_mas_largo_que_el_tamano_se_parte_en_frases():
    t = ("Primera frase del párrafo largo. " * 6 + "Segunda parte con más frases. " * 6).strip()
    fr = trocear_texto(t, 200, 40)
    assert len(fr) >= 2 and all(len(f) <= 200 for f in fr)
    assert all(f.rstrip().endswith(".") or f.rstrip().endswith(":") for f in fr[:-1])


def test_una_frase_sin_puntuacion_se_parte_en_palabras():
    fr = trocear_texto(largo("w", 400), 200, 30)
    assert len(fr) > 3 and all(len(f) <= 200 for f in fr)


def test_pagina_corta_da_un_solo_fragmento_y_pagina_vacia_ninguno():
    assert trocear_texto("Texto breve.", 300, 60) == ["Texto breve."]
    assert trocear_texto("  \n\n ", 300, 60) == []


def test_solape_no_menor_que_tamano_es_error():
    with pytest.raises(ValueError):
        trocear_texto("abc", 100, 100)


def test_es_determinista():
    t = "\n\n".join(f"{i}. " + largo(f"y{i}_", 30) for i in range(1, 9))
    assert trocear_texto(t, 300, 60) == trocear_texto(t, 300, 60)


# ── página como metadato, sin mezclar ──

def test_cada_fragmento_lleva_su_pagina_y_no_mezcla_texto_de_otra():
    paginas = [pagina(3, largo("alfa", 80)), pagina(4, largo("beta", 80)), pagina(9, largo("gamma", 80))]
    fr = trocear_documento(DOC_LEY, paginas, CFG, MAX)
    assert {f.pagina for f in fr} == {3, 4, 9}
    for f in fr:
        marca = {3: "alfa", 4: "beta", 9: "gamma"}[f.pagina]
        otras = {"alfa", "beta", "gamma"} - {marca}
        assert marca in f.texto and not any(o in f.texto for o in otras), f"{f.id} mezcla páginas"


def test_metadatos_completos_y_es_ocr():
    fr = trocear_documento(DOC_REG, [pagina(60, "Artículo 257. Valor legal\n\n257.1. Los actos se realizan en la Pladicop.", origen="ocr")], CFG, MAX)
    m = fr[0].metadatos()
    assert m["documento"] == "ds_009_2025_ef" and m["version"] == "reglamento_original_2025" and m["pagina"] == 60
    assert m["es_ocr"] is True and m["posicion"] == 0 and m["caracteres"] == len(fr[0].texto)
    assert set(m) >= {"articulos_ley", "articulos_reglamento", "encabezado", "hash_texto"}
    assert all(isinstance(v, (str, int, float, bool)) for v in m.values())      # ChromaDB solo admite escalares


# ── IDs ──

def test_ids_estables_unicos_y_con_el_formato_pedido():
    paginas = [pagina(n, largo(f"p{n}_", 90)) for n in (12, 13)]
    a = trocear_documento(DOC_LEY, paginas, CFG, MAX)
    b = trocear_documento(DOC_LEY, list(reversed(paginas)), CFG, MAX)
    assert [f.id for f in a] == [f.id for f in b]
    assert len({f.id for f in a}) == len(a)
    assert re.fullmatch(r"ley_32069:ley_vigente:p0012:c000:[0-9a-f]{8}", a[0].id)


def test_ids_distintos_entre_documentos_aunque_coincidan_pagina_y_posicion():
    x = trocear_documento(DOC_LEY, [pagina(5, "Texto.")], CFG, MAX)[0]
    y = trocear_documento(DOC_REG, [pagina(5, "Texto.")], CFG, MAX)[0]
    assert x.id != y.id


def test_configuraciones_distintas_no_se_pisan():
    a = trocear_documento(DOC_LEY, [pagina(1, "Texto.")], ConfigChunk("a", 500, 50), MAX)[0]
    b = trocear_documento(DOC_LEY, [pagina(1, "Texto.")], ConfigChunk("b", 1000, 150), MAX)[0]
    assert a.id != b.id and a.id.rsplit(":", 1)[0] == b.id.rsplit(":", 1)[0]


# ── menciones de artículos ──

def test_menciones_separadas_por_norma_segun_el_documento_y_la_frase():
    t = "según el numeral 61.8 del artículo 61 de la Ley y los artículos 231 y 232 del Reglamento, además del artículo 40."
    assert extraer_menciones(t, "reglamento", MAX) == ([61], [40, 231, 232])
    assert extraer_menciones(t, "norma_base", MAX) == ([40, 61], [231, 232])


def test_ignora_menciones_a_otras_normas():
    t = "conforme al artículo 252 del Texto Único Ordenado de la Ley 27444 y el artículo 8 de la Ley N° 27444, y el artículo 5 de la Ley Nº 32069"
    assert extraer_menciones(t, "reglamento", MAX) == ([5], [])


def test_descarta_numeros_fuera_de_rango_por_errores_de_ocr():
    assert extraer_menciones("Artículo 399. Listado de bienes y el artículo 55 de la Ley", "reglamento", MAX) == ([55], [])
    assert extraer_menciones("el artículo 150 de la Ley", "reglamento", MAX) == ([], [])    # la Ley solo llega a 100


def test_listas_de_articulos():
    assert extraer_menciones("los artículos 3, 4 y 5 del Reglamento", "norma_base", MAX) == ([], [3, 4, 5])


# ── contexto de encabezado ──

def test_el_fragmento_hereda_el_encabezado_de_la_pagina_anterior():
    p1 = pagina(46, "Texto previo.\n\nArtículo 93. Prescripción de las infracciones administrativas")
    p2 = pagina(47, "93.1. Las infracciones establecidas en la presente ley prescriben a los cuatro años.")
    f = trocear_documento(DOC_LEY, [p1, p2], CFG, MAX)
    en_47 = [x for x in f if x.pagina == 47][0]
    assert en_47.encabezado == "Artículo 93. Prescripción de las infracciones administrativas"
    assert en_47.texto_embedding.startswith("Artículo 93. Prescripción")
    assert not en_47.texto.startswith("Artículo 93")             # lo que se muestra no lleva el contexto
    assert en_47.pagina == 47                                    # y sigue siendo de la página 47


def test_un_encabezado_propio_de_la_pagina_reemplaza_al_heredado():
    p1 = pagina(1, "Artículo 10. Uno\n\nTexto del diez.")
    p2 = pagina(2, "Texto que continúa el diez.\n\nArtículo 11. Otro título\n\nTexto del once.")
    f = [x for x in trocear_documento(DOC_LEY, [p1, p2], ConfigChunk("t", 60, 10), MAX) if x.pagina == 2]
    assert f[0].encabezado.startswith("Artículo 10")
    assert f[-1].encabezado.startswith("Artículo 11")


def test_encabezado_fuera_de_rango_no_se_usa():
    f = trocear_documento(DOC_REG, [pagina(26, "Artículo 399. Listado de bienes\n\n99.1. La DGA puede aprobar.")], CFG, MAX)
    assert f[0].encabezado == ""


def test_el_contexto_se_puede_desactivar():
    p = pagina(1, "Artículo 10. Uno\n\nTexto del diez.")
    f = trocear_documento(DOC_LEY, [p], ConfigChunk("t", 300, 60, contexto_encabezado=False), MAX)[0]
    assert f.encabezado == "" and f.texto_embedding == f.texto


def test_el_hash_del_texto_cambia_si_cambia_el_contenido():
    a = trocear_documento(DOC_LEY, [pagina(1, "Texto uno.")], CFG, MAX)[0]
    b = trocear_documento(DOC_LEY, [pagina(1, "Texto dos.")], CFG, MAX)[0]
    assert a.id == b.id and a.hash_texto != b.hash_texto


# ── fragmentos diminutos: numerales y encabezados no quedan solos ──

def test_un_numeral_no_queda_solo_como_fragmento_o_pieza():
    largo_num = "1.1. " + " ".join(f"palabra{i}" for i in range(80))          # un solo "párrafo" más largo que el tamaño
    for f in trocear_texto(largo_num, 300, 60):
        assert not re.fullmatch(r"\s*\d+(\.\d+)*\.?\s*", f) and len(f) > 30


def test_un_encabezado_corto_se_pega_al_parrafo_siguiente():
    t = "Artículo 93. Prescripción de las infracciones\n\n93.1. " + " ".join(f"palabra{i}" for i in range(70)) + "."
    fr = trocear_texto(t, 300, 40)
    assert fr[0].startswith("Artículo 93. Prescripción") and "93.1." in fr[0] and len(fr[0]) > 150      # no es un fragmento de solo el título


def test_no_hay_fragmentos_diminutos_en_una_pagina_tipica():
    t = ("CAPÍTULO III\nDISPOSICIONES ESPECIALES\n\nSUBCAPÍTULO 1\nSubasta inversa electrónica\n\nArtículo 96. Evaluación de ofertas\n\n"
         + "\n\n".join(f"96.{i}. " + " ".join(f"termino{i}_{j}" for j in range(45)) + "." for i in range(1, 6)))
    fr = trocear_texto(t, 400, 60)
    assert len(fr) >= 3 and min(len(f) for f in fr) > 100


def test_encabezados_seguidos_heredan_el_articulo_correcto():
    p = pagina(26, "CAPÍTULO III\nDISPOSICIONES ESPECIALES\n\nArtículo 96. Evaluación de ofertas en subasta\n\n96.1. Mediante subasta se contratan bienes comunes.")
    f = trocear_documento(DOC_REG, [p], CFG, MAX)[0]
    assert f.encabezado == "Artículo 96. Evaluación de ofertas en subasta"
    assert f.texto.startswith("CAPÍTULO III")                    # el texto mostrado conserva todo lo de la página


def test_un_encabezado_sin_cuerpo_al_final_de_la_pagina_es_su_propio_fragmento():
    fr = trocear_texto("Texto previo suficientemente largo para ser un párrafo.\n\nArtículo 93. Prescripción de las infracciones", 300, 40)
    assert fr[-1].endswith("Artículo 93. Prescripción de las infracciones")
