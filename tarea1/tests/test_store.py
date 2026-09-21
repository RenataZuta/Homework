"""Almacenamiento por página: escritura atómica y tolerancia a interrupciones."""
import json

import pytest

from extraction import store


def entrada(n, **extra):
    base = {"documento": "doc", "version": "v1", "pagina": n, "texto": f"texto {n}", "texto_crudo": f"crudo {n}",
            "caracteres": 7, "origen": "texto", "ocr_segundos": None, "calidad": {"pct_alfabeticos": 0.9}}
    base.update(extra)
    return base


def test_guardar_y_leer_una_pagina(tmp_path):
    ruta = store.guardar_pagina(tmp_path, entrada(3))
    assert ruta.name == "p0003.json"
    e = store.leer_pagina(tmp_path, 3)
    assert e["pagina"] == 3 and e["texto"] == "texto 3" and e["esquema"] == store.VERSION_ESQUEMA


def test_no_queda_archivo_temporal_tras_guardar(tmp_path):
    store.guardar_pagina(tmp_path, entrada(1))
    assert list(tmp_path.glob("*.tmp")) == []


def test_listar_ordena_por_pagina_y_ignora_lo_ajeno(tmp_path):
    for n in (10, 2, 33):
        store.guardar_pagina(tmp_path, entrada(n))
    (tmp_path / "_mapa_estructura.json").write_text("{}")
    (tmp_path / "notas.txt").write_text("x")
    assert [e["pagina"] for e in store.listar_paginas(tmp_path)] == [2, 10, 33]


def test_una_pagina_a_medias_se_trata_como_pendiente(tmp_path):
    """Simula un corte durante la escritura: JSON truncado y un .tmp huérfano."""
    store.guardar_pagina(tmp_path, entrada(1))
    (tmp_path / "p0002.json").write_text('{"documento": "doc", "pagina": 2, "tex', encoding="utf-8")   # truncado
    (tmp_path / "p0003.json.tmp").write_text("{}", encoding="utf-8")                                    # huérfano
    assert store.leer_pagina(tmp_path, 2) is None
    assert [e["pagina"] for e in store.listar_paginas(tmp_path)] == [1]
    assert store.borrar_temporales(tmp_path) == 1
    assert not (tmp_path / "p0003.json.tmp").exists()


def test_entrada_incompleta_se_rechaza(tmp_path):
    e = entrada(1)
    del e["calidad"]
    with pytest.raises(ValueError, match="calidad"):
        store.guardar_pagina(tmp_path, e)


def test_origen_invalido_se_rechaza(tmp_path):
    with pytest.raises(ValueError, match="origen"):
        store.guardar_pagina(tmp_path, entrada(1, origen="magia"))


def test_sobrescribir_reemplaza_sin_dejar_basura(tmp_path):
    store.guardar_pagina(tmp_path, entrada(1, texto="viejo"))
    store.guardar_pagina(tmp_path, entrada(1, texto="nuevo"))
    assert store.leer_pagina(tmp_path, 1)["texto"] == "nuevo"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p0001.json"]


def test_borrar_temporales_en_carpeta_inexistente(tmp_path):
    assert store.borrar_temporales(tmp_path / "no_existe") == 0


def test_json_es_utf8_legible(tmp_path):
    store.guardar_pagina(tmp_path, entrada(1, texto="Artículo 3. Ñandú"))
    assert "Artículo 3. Ñandú" in (tmp_path / "p0001.json").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "p0001.json").read_text(encoding="utf-8"))["pagina"] == 1
