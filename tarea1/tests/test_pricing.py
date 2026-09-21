"""Precios por hora: el cálculo respeta la hora de CADA llamada (tabla ficticia con horas pico y valle) y nunca inventa un precio."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rag_engine.llm.pricing import ErrorPrecio, TablaPrecios, cargar_tabla

LIMA = timezone(timedelta(hours=-5))
UTC = timezone.utc

TABLA_FICTICIA = {
    "fuente": "TABLA FICTICIA SOLO PARA PRUEBAS", "fecha_verificacion": "2026-01-01",
    "modelos": {"modelo-x": {"ventanas": [
        {"zona_horaria": "America/Lima", "hora_inicio": "08:00", "hora_fin": "20:00", "usd_por_millon_entrada": 2.0, "usd_por_millon_salida": 10.0},   # pico
        {"zona_horaria": "America/Lima", "hora_inicio": "20:00", "hora_fin": "08:00", "usd_por_millon_entrada": 1.0, "usd_por_millon_salida": 5.0},    # valle (cruza la medianoche)
    ]}},
}


@pytest.fixture
def tabla():
    return TablaPrecios.desde_dict(TABLA_FICTICIA)


def lima(h, m=0):
    return datetime(2026, 9, 21, h, m, tzinfo=LIMA)


# ── la tabla ficticia: pico y valle ──

def test_el_mismo_uso_cuesta_distinto_segun_la_hora_de_la_llamada(tabla):
    de_dia = tabla.costo("modelo-x", 1_000_000, 100_000, lima(12))
    de_noche = tabla.costo("modelo-x", 1_000_000, 100_000, lima(3))
    assert de_dia == pytest.approx(2.0 + 1.0)            # 1M x 2 + 0,1M x 10
    assert de_noche == pytest.approx(1.0 + 0.5)          # 1M x 1 + 0,1M x 5
    assert de_dia == pytest.approx(2 * de_noche)


@pytest.mark.parametrize("h, m, esperado", [
    (7, 59, (1.0, 5.0)), (8, 0, (2.0, 10.0)), (19, 59, (2.0, 10.0)), (20, 0, (1.0, 5.0)),      # los cuatro límites
    (0, 0, (1.0, 5.0)), (23, 59, (1.0, 5.0)), (12, 30, (2.0, 10.0)),                          # medianoche y mediodía
])
def test_limites_de_las_ventanas_incluida_la_que_cruza_la_medianoche(tabla, h, m, esperado):
    assert tabla.precio_en(lima(h, m), "modelo-x") == esperado


def test_la_hora_se_convierte_a_la_zona_de_la_tabla(tabla):
    assert tabla.precio_en(datetime(2026, 9, 21, 17, 0, tzinfo=UTC), "modelo-x") == (2.0, 10.0)     # 17:00 UTC = 12:00 Lima
    assert tabla.precio_en(datetime(2026, 9, 22, 1, 0, tzinfo=UTC), "modelo-x") == (1.0, 5.0)       # 01:00 UTC = 20:00 Lima
    # casos donde la hora "cruda" y la hora de Lima caen en ventanas DISTINTAS (si se ignorara la zona, fallarían):
    assert tabla.precio_en(datetime(2026, 9, 21, 12, 0, tzinfo=UTC), "modelo-x") == (1.0, 5.0)      # 12:00 UTC = 07:00 Lima -> valle
    assert tabla.precio_en(datetime(2026, 9, 21, 20, 30, tzinfo=UTC), "modelo-x") == (2.0, 10.0)    # 20:30 UTC = 15:30 Lima -> pico


def test_varias_llamadas_del_mismo_dia_se_facturan_cada_una_a_su_hora(tabla):
    llamadas = [(lima(2), 1000, 200), (lima(9), 1000, 200), (lima(21), 1000, 200)]
    costos = [tabla.costo("modelo-x", i, o, t) for t, i, o in llamadas]
    assert costos[0] == costos[2] and costos[1] == pytest.approx(2 * costos[0])


# ── nunca se inventa un precio ──

def test_momento_sin_zona_horaria_es_error(tabla):
    with pytest.raises(ErrorPrecio, match="zona horaria"):
        tabla.precio_en(datetime(2026, 9, 21, 12, 0), "modelo-x")


def test_modelo_sin_precios_es_error(tabla):
    with pytest.raises(ErrorPrecio, match="No hay precios verificados"):
        tabla.costo("otro-modelo", 1, 1, lima(12))


def test_precio_null_es_error_al_cargar():
    d = {"modelos": {"m": {"ventanas": [{"zona_horaria": "America/Lima", "hora_inicio": "00:00", "hora_fin": "24:00",
                                          "usd_por_millon_entrada": None, "usd_por_millon_salida": 5.0}]}}}
    with pytest.raises(ErrorPrecio, match="null"):
        TablaPrecios.desde_dict(d)


def _con(ventanas):
    return {"modelos": {"m": {"ventanas": [{"zona_horaria": "America/Lima", "usd_por_millon_entrada": 1.0, "usd_por_millon_salida": 2.0, **v} for v in ventanas]}}}


def test_huecos_entre_ventanas_son_error_y_se_indica_la_hora():
    with pytest.raises(ErrorPrecio, match="dejan sin precio.*08:00"):
        TablaPrecios.desde_dict(_con([{"hora_inicio": "00:00", "hora_fin": "08:00"}, {"hora_inicio": "09:00", "hora_fin": "24:00"}]))


def test_ventanas_que_se_solapan_son_error():
    with pytest.raises(ErrorPrecio, match="se solapan"):
        TablaPrecios.desde_dict(_con([{"hora_inicio": "00:00", "hora_fin": "12:00"}, {"hora_inicio": "10:00", "hora_fin": "24:00"}]))


def test_ventana_vacia_hora_invalida_y_zonas_mezcladas():
    with pytest.raises(ErrorPrecio, match="vacía"):
        TablaPrecios.desde_dict(_con([{"hora_inicio": "08:00", "hora_fin": "08:00"}]))
    with pytest.raises(ErrorPrecio, match="fuera de rango|inválida"):
        TablaPrecios.desde_dict(_con([{"hora_inicio": "00:00", "hora_fin": "25:00"}]))
    d = _con([{"hora_inicio": "00:00", "hora_fin": "12:00"}, {"hora_inicio": "12:00", "hora_fin": "24:00", "zona_horaria": "UTC"}])
    with pytest.raises(ErrorPrecio, match="mezcla zonas"):
        TablaPrecios.desde_dict(d)


# ── la tabla real (Anthropic) ──

def test_la_tabla_real_de_anthropic_carga_y_tiene_precio_unico_verificado():
    t = cargar_tabla(Path(__file__).resolve().parents[1] / "pricing.yaml")
    assert t.fecha_verificacion == "2026-09-21" and "platform.claude.com" in t.fuente
    precios = {t.precio_en(lima(h), "claude-haiku-4-5-20251001") for h in (0, 6, 12, 18, 23)}
    assert precios == {(1.0, 5.0)}                                  # sin tarifas por hora: el mismo precio a todas horas
    assert t.costo("claude-haiku-4-5-20251001", 2000, 300, lima(15)) == pytest.approx((2000 * 1 + 300 * 5) / 1e6)


def test_la_tabla_real_de_gemini_tiene_precio_de_referencia_con_fuente_y_fecha():
    import yaml
    ruta = Path(__file__).resolve().parents[1] / "pricing.yaml"
    t = cargar_tabla(ruta, "gemini")
    assert t.fecha_verificacion == "2026-09-21" and "ai.google.dev" in t.fuente
    precios = {t.precio_en(lima(h), "gemini-3.5-flash-lite") for h in (0, 6, 12, 18, 23)}
    assert precios == {(0.30, 2.50)}                                # precio de PAGO (referencia); la capa gratuita cobra 0 (llm.nivel)
    assert t.costo("gemini-3.5-flash-lite", 2000, 300, lima(15)) == pytest.approx((2000 * 0.30 + 300 * 2.50) / 1e6)
    assert t.precio_en(lima(12), "gemini-2.5-flash-lite") == (0.10, 0.40)       # el modelo anterior sigue tabulado (ya no lo admite la API en cuentas nuevas)
    b = yaml.safe_load(ruta.read_text(encoding="utf-8"))["gemini"]
    assert "Free of charge" in b["nota_nivel_gratuito"] and "Used to improve" in b["nota_nivel_gratuito"]


def test_gemini_tambien_cumple_la_estructura_de_ventanas_horarias():
    """La estructura por hora se conserva para Gemini: una tabla ficticia pico/valle da costos distintos según la hora de la llamada."""
    d = {"modelos": {"gemini-2.5-flash-lite": {"ventanas": [
        {"zona_horaria": "America/Lima", "hora_inicio": "08:00", "hora_fin": "20:00", "usd_por_millon_entrada": 0.20, "usd_por_millon_salida": 0.80},
        {"zona_horaria": "America/Lima", "hora_inicio": "20:00", "hora_fin": "08:00", "usd_por_millon_entrada": 0.10, "usd_por_millon_salida": 0.40}]}}}
    t = TablaPrecios.desde_dict(d)
    pico, valle = t.costo("gemini-2.5-flash-lite", 1_000_000, 0, lima(12)), t.costo("gemini-2.5-flash-lite", 1_000_000, 0, lima(23))
    assert (pico, valle) == (pytest.approx(0.20), pytest.approx(0.10))


def test_el_precio_de_embeddings_de_gemini_esta_verificado_con_fuente_y_fecha():
    import yaml
    from rag_engine.llm.pricing import cargar_precio_embedding
    ruta = Path(__file__).resolve().parents[1] / "pricing.yaml"
    assert cargar_precio_embedding(ruta, "gemini-embedding-2", "gemini_embeddings") == 0.20
    b = yaml.safe_load(ruta.read_text(encoding="utf-8"))["gemini_embeddings"]
    assert str(b["fecha_verificacion"]) == "2026-09-21" and "ai.google.dev" in b["fuente"] and b["modelos"]["gemini-embedding-2"]["max_tokens_entrada"] == 8192
    with pytest.raises(ErrorPrecio):
        cargar_precio_embedding(ruta, "gemini-embedding-2")          # el bloque por defecto es el de OpenAI: no lo confunde


def test_el_precio_de_embeddings_por_api_esta_verificado_con_fuente_y_fecha():
    from rag_engine.llm.pricing import cargar_precio_embedding
    ruta = Path(__file__).resolve().parents[1] / "pricing.yaml"
    assert cargar_precio_embedding(ruta, "text-embedding-3-small") == 0.02
    import yaml
    b = yaml.safe_load(ruta.read_text(encoding="utf-8"))["openai_embeddings"]
    assert str(b["fecha_verificacion"]) == "2026-09-21" and "platform.openai.com" in b["fuente"] and b["modelos"]["text-embedding-3-small"]["dimensiones"] == 1536


def test_un_modelo_de_embeddings_sin_precio_es_error(tmp_path):
    from rag_engine.llm.pricing import cargar_precio_embedding
    ruta = tmp_path / "p.yaml"
    ruta.write_text("openai_embeddings:\n  modelos:\n    m:\n      usd_por_millon_tokens: null\n", encoding="utf-8")
    with pytest.raises(ErrorPrecio, match="No hay un precio verificado"):
        cargar_precio_embedding(ruta, "m")
    with pytest.raises(ErrorPrecio):
        cargar_precio_embedding(ruta, "otro")
