"""Log de costos: una línea por llamada, éxito o fallo, sin claves."""
import json

from rag_engine.llm.cost_log import CAMPOS, leer_registros, registrar_llamada, resumen, sanear


def reg(ruta, **kw):
    base = dict(timestamp="2026-09-21T10:00:00-05:00", proveedor="gemini", modelo="gemini-2.5-flash-lite", nivel="gratuito", tokens_in=2000, tokens_out=300,
                latencia_ms=850.4, costo_usd_real=0.0, costo_usd_referencia=0.0035, exito=True)
    return registrar_llamada(ruta, **{**base, **kw})


def test_una_linea_por_llamada_con_todos_los_campos(tmp_path):
    ruta = tmp_path / "logs" / "llm_calls.jsonl"
    reg(ruta)
    reg(ruta, exito=False, error="rate limit", tokens_in=0, tokens_out=0, costo_usd_referencia=0.0, intentos=3)
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 2 and all(set(json.loads(l)) == set(CAMPOS) for l in lineas)
    assert json.loads(lineas[1])["exito"] is False and json.loads(lineas[1])["error"] == "rate limit"
    assert json.loads(lineas[0])["intentos"] == 1 and json.loads(lineas[1])["intentos"] == 3       # 1 = a la primera; 3 = dos reintentos


def test_el_log_es_de_solo_agregar(tmp_path):
    ruta = tmp_path / "l.jsonl"
    reg(ruta, tokens_in=1)
    reg(ruta, tokens_in=2)
    assert [r["tokens_in"] for r in leer_registros(ruta)] == [1, 2]


def test_nunca_se_escribe_una_clave(tmp_path):
    clave_a = "sk-" + "ant-" + "abcdefgh12345678"
    clave_t = "123456789" + ":" + "A" * 35
    clave_g = "AI" + "za" + "SyD-abcdefghijklmnopqrstuvwxyz012345"
    ruta = tmp_path / "l.jsonl"
    reg(ruta, exito=False, error=f"401 con la clave {clave_a} y el token {clave_t}, la de Google {clave_g}, Bearer abc123def456, x-goog-api-key: cabecera123456")
    contenido = ruta.read_text(encoding="utf-8")
    assert clave_a not in contenido and clave_t not in contenido and clave_g not in contenido
    assert "abc123def456" not in contenido and "cabecera123456" not in contenido and "[CLAVE-OCULTA]" in contenido


def test_sanear_trunca_y_acepta_none():
    assert sanear(None) is None and len(sanear("x" * 1000)) == 300


def test_una_linea_danada_no_rompe_la_lectura(tmp_path):
    ruta = tmp_path / "l.jsonl"
    reg(ruta)
    with ruta.open("a", encoding="utf-8") as f:
        f.write('{"timestamp": "roto\n')
        f.write('{"otro": 1}\n')
    assert len(leer_registros(ruta)) == 1


def test_archivo_inexistente_da_lista_vacia(tmp_path):
    assert leer_registros(tmp_path / "no.jsonl") == []


def test_resumen_de_costos(tmp_path):
    ruta = tmp_path / "l.jsonl"
    reg(ruta, costo_usd_referencia=0.002, latencia_ms=800)
    reg(ruta, costo_usd_referencia=0.004, latencia_ms=1200, intentos=3)
    reg(ruta, exito=False, error="x", tokens_in=0, tokens_out=0, costo_usd_referencia=0.0, latencia_ms=50)
    r = resumen(leer_registros(ruta))
    assert (r["llamadas"], r["exitosas"], r["fallidas"]) == (3, 2, 1)
    assert r["costo_referencia_total_usd"] == 0.006 and r["costo_referencia_medio_por_consulta_usd"] == 0.003 and r["latencia_mediana_ms"] == 1000.0
    assert r["costo_real_total_usd"] == 0.0 and r["reintentos"] == 2            # en la capa gratuita se cobra 0 aunque la referencia sea > 0
    assert resumen([])["costo_referencia_medio_por_consulta_usd"] is None
