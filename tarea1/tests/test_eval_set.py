"""Set de evaluación: el CSV real es válido y el validador detecta cada tipo de error."""
import copy
import json
from pathlib import Path

import pytest

from evaluation.eval_set import Pregunta, cargar_evidencia, cargar_preguntas, validar
from rag_engine.config import cargar_config

RAIZ = Path(__file__).resolve().parents[1]
CFG = cargar_config(cargar_env=False)
DOCS = {d["id"]: d for d in CFG.documentos}
REQ = CFG.get("eval.requisitos_set")
PROCESSED = CFG.ruta("processed")


@pytest.fixture(scope="module")
def real():
    if not (RAIZ / "eval" / "preguntas.csv").is_file() or not (PROCESSED / "ds_009_2025_ef").is_dir():
        pytest.skip("falta eval/preguntas.csv o data/processed/")
    preguntas = cargar_preguntas(CFG.ruta("eval_preguntas"))
    evidencia = cargar_evidencia(CFG.ruta("eval_preguntas").with_name("evidencia.yaml"))
    paginas = {k: v["paginas"] for k, v in json.loads(CFG.ruta("manifest").read_text(encoding="utf-8"))["documentos"].items()}
    return preguntas, evidencia, paginas


def _validar(preguntas, evidencia, paginas):
    return validar(preguntas, evidencia, DOCS, PROCESSED, paginas, REQ)


def test_el_set_real_es_valido_y_cumple_los_minimos_del_issue(real):
    errores, stats = _validar(*real)
    assert errores == []
    assert stats["in_domain"] >= 15 and stats["out_of_domain"] >= 5
    assert stats["modificadas_2026"] >= 3 and stats["coloquiales_in_domain"] >= 5


def test_toda_pagina_esperada_esta_en_el_subconjunto_procesado(real):
    preguntas, _, _ = real
    for q in preguntas:
        for doc, pag in q.pares:
            assert (PROCESSED / doc / f"p{pag:04d}.json").is_file(), f"{q.id}: {doc} p.{pag} no está procesada"


def test_la_pagina_del_ejemplo_fuera_de_dominio_esta_realmente_fuera_del_indice(real):
    _, evidencia, _ = real
    for item in evidencia["o05"]["fuera_del_indice"]:
        assert not (PROCESSED / item["documento"] / f"p{item['pagina']:04d}.json").exists()


def test_en_las_preguntas_de_versiones_el_primer_documento_es_el_ds_001(real):
    preguntas, _, _ = real
    modificadas = [q for q in preguntas if q.modificada_2026]
    assert len(modificadas) >= 3
    assert all(q.documento_modificatoria == "ds_001_2026_ef" for q in modificadas)


def test_hay_preguntas_fuera_de_dominio_de_los_tres_tipos_del_plan(real):
    preguntas, _, _ = real
    fuera = " ".join(q.pregunta.lower() for q in preguntas if q.tipo == "out_of_domain")
    for palabra in ("sunat", "privado", "colombia", "ceviche", "capacidad máxima", "uit"):
        assert palabra in fuera


# ── el validador detecta errores (sobre una copia modificada del set real) ──

def _copia(real):
    p, e, pg = real
    return copy.deepcopy(p), copy.deepcopy(e), pg


def _q(preguntas, qid):
    return next(q for q in preguntas if q.id == qid)


def test_detecta_pagina_fuera_del_subconjunto(real):
    p, e, pg = _copia(real)
    _q(p, "q10").esperados = {"ds_009_2025_ef": [8]}          # la p. 8 está excluida del OCR
    assert any("NO está en el subconjunto" in x for x in _validar(p, e, pg)[0])


def test_detecta_pagina_inexistente(real):
    p, e, pg = _copia(real)
    _q(p, "q02").esperados = {"ley_32069": [999]}
    assert any("no existe en ley_32069" in x for x in _validar(p, e, pg)[0])


def test_detecta_version_sin_la_modificatoria_primero(real):
    p, e, pg = _copia(real)
    _q(p, "q11").esperados = {"ds_009_2025_ef": [18], "ds_001_2026_ef": [4]}
    assert any("primer documento debe ser la modificatoria" in x for x in _validar(p, e, pg)[0])


def test_detecta_modificatoria_en_pregunta_no_marcada(real):
    p, e, pg = _copia(real)
    _q(p, "q11").modificada_2026 = False
    assert any("no está marcada modificada_2026" in x for x in _validar(p, e, pg)[0])


def test_detecta_fuera_de_dominio_con_paginas(real):
    p, e, pg = _copia(real)
    _q(p, "o04").esperados = {"ley_32069": [1]}
    assert any("no lleva documento ni páginas" in x for x in _validar(p, e, pg)[0])


def test_detecta_evidencia_que_no_coincide_con_el_csv(real):
    p, e, pg = _copia(real)
    e["q02"][0]["pagina"] = 33
    assert any("no coinciden con las de evidencia.yaml" in x for x in _validar(p, e, pg)[0])


def test_detecta_pregunta_sin_evidencia(real):
    p, e, pg = _copia(real)
    del e["q03"]
    assert any("q03: no tiene evidencia" in x for x in _validar(p, e, pg)[0])


def test_detecta_pagina_que_deberia_estar_fuera_del_indice_pero_esta(real):
    p, e, pg = _copia(real)
    e["o05"]["fuera_del_indice"][0]["pagina"] = 60
    assert any("debe estar FUERA del índice" in x for x in _validar(p, e, pg)[0])


def test_detecta_faltan_preguntas(real):
    p, e, pg = _copia(real)
    sobran = [q.id for q in p if q.tipo == "in_domain" and q.estilo == "coloquial"]
    p = [q for q in p if q.id not in sobran[:8]]
    errores = _validar(p, e, pg)[0]
    assert any("'coloquiales' tiene" in x for x in errores)


def test_detecta_id_y_pregunta_repetidos(real):
    p, e, pg = _copia(real)
    p.append(copy.deepcopy(_q(p, "q01")))
    errores = _validar(p, e, pg)[0]
    assert any("id repetido: q01" in x for x in errores) and any("pregunta repetida" in x for x in errores)


def test_detecta_pregunta_mal_escrita_o_sin_notas(real):
    p, e, pg = _copia(real)
    _q(p, "q04").pregunta = "Hasta qué monto me pueden comprar"
    _q(p, "q04").notas = ""
    errores = _validar(p, e, pg)[0]
    assert any("terminar en '?'" in x for x in errores) and any("falta explicar" in x for x in errores)


def test_parseo_de_columnas_con_varios_documentos_y_paginas():
    from evaluation.eval_set import _parsear_esperados
    assert _parsear_esperados("ds_001_2026_ef|ds_009_2025_ef", "8;9|47") == {"ds_001_2026_ef": [8, 9], "ds_009_2025_ef": [47]}
    assert _parsear_esperados("", "") == {}
    with pytest.raises(ValueError, match="deben coincidir"):
        _parsear_esperados("a|b", "1")
