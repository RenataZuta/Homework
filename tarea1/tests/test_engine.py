"""Motor RAG: contrato, compuerta del umbral SIN llamar al LLM, versiones, errores como errores y log de costos."""
from pathlib import Path

import pytest

from fakes import EmbedderFalso, LLMFalso, cfg_con, escribir_modificaciones, paginas_sinteticas
from indexing.build_index import construir_indice
from indexing.chunking import ConfigChunk
from rag_engine import engine as motor_mod
from rag_engine.config import cargar_config
from rag_engine.engine import MOTIVO_LLM, MOTIVO_UMBRAL, Fuente, MotorRAG, ResultadoRAG, responder
from rag_engine.llm.base import ErrorLLM
from rag_engine.llm.cost_log import leer_registros
from rag_engine.llm.pricing import cargar_tabla
from rag_engine.retrieval.indice import abrir_cliente, nombre_coleccion
from rag_engine.retrieval.versions import Modificaciones

BASE = cargar_config(cargar_env=False)
DOCS = {d["id"]: d for d in BASE.documentos}
MAX = {"ley": 100, "reglamento": 389}
P_RETENCION = "retención de pago garantía micro pequeña empresa independencia del monto"
P_PAGO = "plazo máximo para el pago tras la conformidad diez días hábiles intereses legales"
P_AJENA = "cocinar ceviche pescado limón cebolla"


@pytest.fixture
def entorno(tmp_path):
    e = EmbedderFalso()
    docs = {i: (DOCS[i], ps) for i, ps in paginas_sinteticas().items()}
    construir_indice(e, ConfigChunk("t500", 500, 50), docs, tmp_path / "index", "normas", MAX, mostrar=lambda *_: None)
    col = abrir_cliente(tmp_path / "index").get_collection(nombre_coleccion("normas", "t500", e.name))
    ruta_mod = tmp_path / "articulos_modificados.json"
    escribir_modificaciones(ruta_mod)
    return {"embedder": e, "col": col, "mods": Modificaciones.cargar(ruta_mod), "log": tmp_path / "logs" / "llm_calls.jsonl", "tmp": tmp_path}


def motor(env, llm=None, **cfg_cambios):
    cfg = cfg_con(BASE, **{"retrieval.umbral_similitud": 0.3, "retrieval.top_k": 3, **cfg_cambios})
    return MotorRAG(cfg, env["embedder"], env["col"], env["mods"], cargar_tabla(BASE.ruta("pricing"), BASE.get("llm.provider")), cliente_llm=llm, ruta_log=env["log"])


# ── contrato ──

def test_el_resultado_tiene_todos_los_campos_del_contrato(entorno):
    r = motor(entorno, LLMFalso()).responder(P_PAGO)
    campos = {"respuesta", "fuentes", "abstuvo", "motivo_abstencion", "mejor_similitud", "tokens_entrada", "tokens_salida", "costo_usd_real", "costo_usd_referencia",
              "latencia_ms", "modelo", "proveedor", "advertencias_version", "error", "error_tipo", "desde_cache", "timestamp"}
    assert set(r.como_dict()) == campos and isinstance(r, ResultadoRAG)
    assert isinstance(r.fuentes[0], Fuente) and set(r.fuentes[0].__dict__) >= {"documento", "version", "pagina", "similitud", "fragmento_id", "texto"}
    assert isinstance(r.abstuvo, bool) and r.timestamp.endswith("-05:00") or "T" in r.timestamp


# ── camino normal ──

def test_pregunta_del_dominio_se_responde_con_fuentes_costo_y_log(entorno):
    llm = LLMFalso(tokens=(2000, 300))
    r = motor(entorno, llm).responder(P_PAGO)
    assert r.error is None and r.abstuvo is False and r.motivo_abstencion is None and r.respuesta.startswith("Respuesta")
    assert (r.documento if False else r.fuentes[0].documento, r.fuentes[0].pagina) == ("ley_32069", 32)
    assert r.tokens_entrada == 2000 and r.tokens_salida == 300 and r.modelo == "gemini-2.5-flash-lite" and r.proveedor == "gemini"
    assert r.mejor_similitud >= 0.3 and len(llm.llamadas) == 1
    # capa gratuita: costo REAL 0; costo de REFERENCIA con el precio de pago de pricing.yaml (0,10 / 0,40 USD por millón)
    assert r.costo_usd_real == 0.0 and r.costo_usd_referencia == pytest.approx((2000 * 0.10 + 300 * 0.40) / 1e6)
    regs = leer_registros(entorno["log"])
    assert len(regs) == 1 and regs[0]["exito"] is True and regs[0]["tokens_in"] == 2000 and regs[0]["nivel"] == "gratuito" and regs[0]["proveedor"] == "gemini"
    assert regs[0]["costo_usd_real"] == 0.0 and regs[0]["costo_usd_referencia"] == pytest.approx(r.costo_usd_referencia) and regs[0]["intentos"] == 1


def test_con_nivel_de_pago_el_costo_real_es_el_de_referencia(entorno):
    r = motor(entorno, LLMFalso(tokens=(2000, 300)), **{"llm.nivel": "pago"}).responder(P_PAGO)
    assert r.costo_usd_real == pytest.approx(r.costo_usd_referencia) and r.costo_usd_real > 0
    assert leer_registros(entorno["log"])[0]["costo_usd_real"] == pytest.approx(r.costo_usd_real)


def test_una_respuesta_de_la_cache_no_es_una_llamada_no_se_registra_ni_se_cobra(entorno):
    r = motor(entorno, LLMFalso(desde_cache=True)).responder(P_PAGO)
    assert r.desde_cache is True and r.error is None and r.respuesta and r.costo_usd_referencia > 0 and r.costo_usd_real == 0.0
    assert not entorno["log"].exists()


def test_los_reintentos_quedan_en_el_log(entorno):
    motor(entorno, LLMFalso(intentos=3)).responder(P_PAGO)
    assert leer_registros(entorno["log"])[0]["intentos"] == 3


def test_al_proveedor_solo_llegan_la_pregunta_y_fragmentos_de_normas(entorno, monkeypatch):
    """Privacidad: el prompt es la plantilla de config + fragmentos indexados + la pregunta; ningún secreto ni variable de entorno viaja."""
    secreto = "AI" + "za" + "SyD-clave-que-jamas-debe-salir-0123456789"
    monkeypatch.setenv("GEMINI_API_KEY", secreto)
    llm = LLMFalso()
    motor(entorno, llm).responder(P_PAGO)
    enviado = llm.llamadas[0]["sistema"] + llm.llamadas[0]["usuario"]
    assert secreto not in enviado and "GEMINI_API_KEY" not in enviado and str(entorno["tmp"]) not in enviado
    assert P_PAGO in llm.llamadas[0]["usuario"] and "diez días hábiles" in llm.llamadas[0]["usuario"]      # sí: pregunta y norma


def test_las_fuentes_citadas_se_marcan_por_nombre_o_id_de_documento(entorno):
    r = motor(entorno, LLMFalso(citas=[{"documento": "Ley 32069", "pagina": 32}])).responder(P_PAGO)
    assert [f.citada for f in r.fuentes if f.documento == "ley_32069" and f.pagina == 32] == [True]
    r2 = motor(entorno, LLMFalso(citas=[{"documento": "ley_32069", "pagina": "32"}, {"documento": "inventado", "pagina": 1}, {"basura": 1}])).responder(P_PAGO)
    assert any(f.citada for f in r2.fuentes)


def test_el_prompt_lleva_cada_fragmento_etiquetado_con_su_version(entorno):
    llm = LLMFalso()
    motor(entorno, llm).responder(P_PAGO)
    u = llm.llamadas[0]["usuario"]
    assert "[Ley 32069 | versión: ley_vigente | p. 32]" in u and P_PAGO in u and "CONTEXTO" in u and "PREGUNTA" in u
    assert "PREVALECE el DS 001-2026-EF" in llm.llamadas[0]["sistema"]


# ── compuerta del umbral: sin llamar al LLM ──

def test_pregunta_fuera_de_dominio_se_abstiene_sin_llamar_al_llm_y_sin_log(entorno):
    llm = LLMFalso()
    r = motor(entorno, llm).responder(P_AJENA)
    assert r.abstuvo is True and r.motivo_abstencion == MOTIVO_UMBRAL and r.error is None
    assert r.costo_usd_real == 0.0 and r.costo_usd_referencia == 0.0 and r.tokens_entrada == 0 and r.tokens_salida == 0 and r.modelo is None
    assert llm.llamadas == [] and leer_registros(entorno["log"]) == [] and not entorno["log"].exists()
    assert r.respuesta == " ".join(BASE.get("mensajes.abstencion").split()) and r.mejor_similitud < 0.3


def test_la_abstencion_por_umbral_no_necesita_clave_de_api(entorno, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = motor(entorno, llm=None).responder(P_AJENA)
    assert r.abstuvo and r.motivo_abstencion == MOTIVO_UMBRAL and r.error is None


def test_el_umbral_es_inclusivo_en_el_limite_exacto(entorno, monkeypatch):
    """Con la similitud FIJADA por un doble, un umbral igual a ella responde y uno apenas mayor se abstiene."""
    from rag_engine.retrieval.semantic import Recuperado
    fijo = [Recuperado(id="x:v:p0001:c000:h", documento="ley_32069", version="ley_vigente", pagina=1, similitud=0.5, texto="texto", metadatos={})]
    monkeypatch.setattr(motor_mod, "buscar", lambda *a, **k: fijo)
    assert motor(entorno, LLMFalso(), **{"retrieval.umbral_similitud": 0.5}).responder("hola").abstuvo is False
    assert motor(entorno, LLMFalso(), **{"retrieval.umbral_similitud": 0.5000001}).responder("hola").abstuvo is True


def test_el_umbral_se_lee_de_la_config(entorno):
    mejor = motor(entorno, LLMFalso()).responder(P_PAGO).mejor_similitud
    assert motor(entorno, LLMFalso(), **{"retrieval.umbral_similitud": mejor - 0.001}).responder(P_PAGO).abstuvo is False
    assert motor(entorno, LLMFalso(), **{"retrieval.umbral_similitud": mejor + 0.05}).responder(P_PAGO).abstuvo is True


# ── abstención decidida por el LLM ──

def test_el_llm_declara_contexto_insuficiente_es_un_campo_no_un_texto(entorno):
    llm = LLMFalso(respuesta="No lo sé", suficiente=False)
    r = motor(entorno, llm).responder(P_PAGO)
    assert r.abstuvo is True and r.motivo_abstencion == MOTIVO_LLM and r.error is None
    assert r.costo_usd_referencia > 0 and len(llm.llamadas) == 1 and len(leer_registros(entorno["log"])) == 1          # SÍ se llamó (y consumió cuota)


def test_una_respuesta_que_dice_no_se_pero_marca_suficiente_no_es_abstencion(entorno):
    r = motor(entorno, LLMFalso(respuesta="No encontré nada, no sé.", suficiente=True)).responder(P_PAGO)
    assert r.abstuvo is False                                                   # la abstención NUNCA se infiere del texto


# ── errores como errores ──

@pytest.mark.parametrize("tipo", ["limite_de_tasa", "red", "autenticacion", "solicitud", "servidor", "respuesta_malformada"])
def test_un_error_del_llm_se_devuelve_como_error_no_como_respuesta(entorno, tipo):
    r = motor(entorno, LLMFalso(error=ErrorLLM(tipo, f"falló por {tipo}"))).responder(P_PAGO)
    assert r.error == f"falló por {tipo}" and r.error_tipo == tipo and r.respuesta is None and r.abstuvo is False and r.motivo_abstencion is None
    assert r.costo_usd_real == 0.0 and r.costo_usd_referencia == 0.0
    regs = leer_registros(entorno["log"])
    assert len(regs) == 1 and regs[0]["exito"] is False and tipo in regs[0]["error"] and regs[0]["costo_usd_real"] == 0.0


def test_la_cuota_agotada_es_un_error_estructurado_y_registra_los_intentos(entorno):
    exc = ErrorLLM("cuota_agotada", "Se agotó la cuota diaria")
    exc.intentos = 5
    r = motor(entorno, LLMFalso(error=exc)).responder(P_PAGO)
    assert r.error == "Se agotó la cuota diaria" and r.error_tipo == "cuota_agotada" and r.respuesta is None and r.abstuvo is False and r.fuentes
    reg = leer_registros(entorno["log"])[0]
    assert reg["exito"] is False and reg["intentos"] == 5 and reg["proveedor"] == "gemini" and "cuota_agotada" in reg["error"]


def test_sin_clave_de_api_el_error_lo_dice_y_no_se_disfraza_de_respuesta(entorno, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = motor(entorno, llm=None).responder(P_PAGO)
    assert r.error and "GEMINI_API_KEY" in r.error and "aistudio.google.com" in r.error and r.respuesta is None and r.abstuvo is False
    assert r.error_tipo == "autenticacion"
    assert not entorno["log"].exists()          # no hubo llamada: el log de costos no se ensucia con un evento que no ocurrió


def test_un_error_que_si_salio_al_proveedor_se_registra_pero_uno_previo_no(entorno):
    salio = motor(entorno, LLMFalso(error=ErrorLLM("red", "sin red"))).responder(P_PAGO)
    assert salio.error and len(leer_registros(entorno["log"])) == 1
    antes = motor(entorno, LLMFalso(error=ErrorLLM("autenticacion", "sin clave", solicitud_enviada=False))).responder(P_PAGO)
    assert antes.error and len(leer_registros(entorno["log"])) == 1           # sigue en 1


def test_pregunta_vacia_es_error(entorno):
    for q in ("", "   ", None):
        r = motor(entorno, LLMFalso()).responder(q)
        assert r.error == "La pregunta está vacía." and r.respuesta is None


def test_un_fallo_del_indice_es_un_error(entorno):
    class ColeccionRota:
        def count(self): raise RuntimeError("índice corrupto")
        def query(self, **kw): raise RuntimeError("índice corrupto")
    m = motor(entorno, LLMFalso())
    m.coleccion = ColeccionRota()
    r = m.responder(P_PAGO)
    assert r.error and "índice" in r.error and r.respuesta is None


def test_indice_inexistente_da_error_con_instrucciones(tmp_path, monkeypatch):
    cfg = cfg_con(BASE, **{"paths.index": str(tmp_path / "no_hay_indice")})
    motor_mod._MOTORES.clear()
    r = responder("¿cuánto es la multa?", cfg)
    assert r.error and "build_index.py" in r.error and r.respuesta is None and r.abstuvo is False


# ── versiones ──

def test_pregunta_sobre_un_articulo_modificado_trae_el_ds_001_y_avisa(entorno):
    llm = LLMFalso()
    r = motor(entorno, llm, **{"retrieval.top_k": 1}).responder(P_RETENCION)      # solo el original entre los recuperados
    assert any("artículo 114" in a and "numeral 114.2 (incorporado)" in a and "prevalece el texto de la modificatoria" in a for a in r.advertencias_version)
    forzadas = [f for f in r.fuentes if f.origen == "version"]
    assert forzadas and all(f.documento == "ds_001_2026_ef" and f.version == "modificatoria_2026-01" and f.pagina == 14 for f in forzadas)
    assert any("114.2" in f.texto for f in forzadas)
    u = llm.llamadas[0]["usuario"]
    assert "[DS 001-2026-EF (modificatoria) | versión: modificatoria_2026-01 | p. 14]" in u and "[Reglamento (DS 009-2025-EF) | versión: reglamento_original_2025 | p. 30]" in u
    assert u.index("modificatoria_2026-01") < u.index("reglamento_original_2025")          # la modificatoria va primero en el contexto


def test_si_solo_se_recupero_la_modificatoria_se_agrega_el_original_y_la_modificatoria_va_primero(entorno):
    llm = LLMFalso()
    r = motor(entorno, llm, **{"retrieval.top_k": 1}).responder("retención de pago primera mitad del número total de pagos prorrateada")
    assert [f.origen for f in r.fuentes] == ["recuperado", "original"] and r.fuentes[0].documento == "ds_001_2026_ef" and r.fuentes[1].documento == "ds_009_2025_ef"
    assert any("artículo 114" in a for a in r.advertencias_version)
    u = llm.llamadas[0]["usuario"]
    assert u.index("modificatoria_2026-01") < u.index("reglamento_original_2025")           # la modificatoria primero aunque el original sea el forzado
    assert "independencia del monto" in u                                                   # y el texto original completo está en el contexto


def test_si_el_ds_001_ya_esta_entre_los_recuperados_no_se_duplica(entorno):
    r = motor(entorno, LLMFalso(), **{"retrieval.top_k": 5}).responder(P_RETENCION)
    ids = [f.fragmento_id for f in r.fuentes]
    assert len(ids) == len(set(ids)) and r.advertencias_version


def test_una_pregunta_sin_articulos_modificados_no_agrega_nada(entorno):
    r = motor(entorno, LLMFalso(), **{"retrieval.top_k": 1}).responder(P_PAGO)          # solo el fragmento de la Ley
    assert r.advertencias_version == [] and all(f.origen == "recuperado" for f in r.fuentes)


def test_un_fragmento_del_reglamento_con_articulo_modificado_entre_los_recuperados_avisa_aunque_sea_de_relleno(entorno):
    r = motor(entorno, LLMFalso(), **{"retrieval.top_k": 3}).responder(P_PAGO)         # el art. 114 entra como tercer fragmento
    assert any("artículo 114" in a for a in r.advertencias_version)


def test_las_versiones_se_pueden_desactivar_por_config(entorno):
    r = motor(entorno, LLMFalso(), **{"retrieval.versiones.activo": False, "retrieval.top_k": 1}).responder(P_RETENCION)
    assert r.advertencias_version == [] and all(f.origen == "recuperado" for f in r.fuentes)


def test_el_maximo_de_fragmentos_forzados_se_respeta(entorno):
    r = motor(entorno, LLMFalso(), **{"retrieval.versiones.max_fragmentos_forzados": 0, "retrieval.top_k": 1}).responder(P_RETENCION)
    assert [f for f in r.fuentes if f.origen == "version"] == [] and r.advertencias_version


def test_la_abstencion_por_umbral_no_hace_trabajo_de_versiones(entorno):
    r = motor(entorno, LLMFalso()).responder(P_AJENA)
    assert r.advertencias_version == [] and all(f.origen == "recuperado" for f in r.fuentes)


# ── costo por hora de la llamada ──

def test_el_costo_usa_la_hora_de_la_llamada(entorno):
    from datetime import datetime
    de_dia = motor(entorno, LLMFalso(momento=datetime(2026, 9, 21, 12, 0, tzinfo=__import__("fakes").LIMA))).responder(P_PAGO)
    de_noche = motor(entorno, LLMFalso(momento=datetime(2026, 9, 21, 3, 0, tzinfo=__import__("fakes").LIMA))).responder(P_PAGO)
    assert de_dia.costo_usd_referencia == de_noche.costo_usd_referencia > 0      # Gemini publica un único precio por modelo: mismo costo a todas horas


# ── arquitectura ──

def test_el_motor_no_abre_pdfs():
    for archivo in (Path(__file__).resolve().parents[1] / "src" / "rag_engine").rglob("*.py"):
        texto = archivo.read_text(encoding="utf-8").lower()
        assert "pymupdf" not in texto and "import fitz" not in texto and ".pdf\"" not in texto, f"{archivo.name} toca PDFs"


def test_el_motor_se_carga_una_sola_vez_por_proceso(monkeypatch, entorno):
    motor_mod._MOTORES.clear()
    llamadas = []
    monkeypatch.setattr(MotorRAG, "desde_config", classmethod(lambda cls, cfg=None: llamadas.append(1) or motor(entorno, LLMFalso())))
    cfg = cfg_con(BASE)
    responder(P_PAGO, cfg)
    responder(P_PAGO, cfg)
    assert llamadas == [1]
    motor_mod._MOTORES.clear()
