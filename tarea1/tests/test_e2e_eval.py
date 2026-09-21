"""Agregación de la evaluación de punta a punta con el motor real y un LLM falso (sin red)."""
from fakes import EmbedderFalso, LLMFalso, cfg_con, escribir_modificaciones, paginas_sinteticas
from evaluation.eval_end_to_end import clasificar, con_umbral, ejecutar, resumir
from evaluation.eval_set import Pregunta
from indexing.build_index import construir_indice
from indexing.chunking import ConfigChunk
from rag_engine.config import cargar_config
from rag_engine.engine import MotorRAG
from rag_engine.llm.pricing import cargar_tabla
from rag_engine.retrieval.indice import abrir_cliente, nombre_coleccion
from rag_engine.retrieval.versions import Modificaciones

BASE = cargar_config(cargar_env=False)


def q(id_, texto, tipo="in_domain", esperados=None):
    return Pregunta(id=id_, pregunta=texto, tipo=tipo, estilo="coloquial", modificada_2026=False, esperados=esperados or {}, notas="x")


def motor(tmp_path, llm):
    e = EmbedderFalso()
    docs = {i: ({d["id"]: d for d in BASE.documentos}[i], ps) for i, ps in paginas_sinteticas().items()}
    construir_indice(e, ConfigChunk("t500", 500, 50), docs, tmp_path / "index", "normas", {"ley": 100, "reglamento": 389}, mostrar=lambda *_: None)
    col = abrir_cliente(tmp_path / "index").get_collection(nombre_coleccion("normas", "t500", e.name))
    ruta = tmp_path / "m.json"
    escribir_modificaciones(ruta)
    return MotorRAG(cfg_con(BASE, **{"retrieval.umbral_similitud": 0.3, "retrieval.top_k": 3}), e, col, Modificaciones.cargar(ruta), cargar_tabla(BASE.ruta("pricing"), BASE.get("llm.provider")),
                    cliente_llm=llm, ruta_log=tmp_path / "l.jsonl")


def test_resumen_de_desenlaces_citas_y_costos(tmp_path):
    preguntas = [q("q1", "plazo máximo para el pago tras la conformidad diez días hábiles intereses legales", esperados={"ley_32069": [32]}),
                 q("q2", "plazo máximo para el pago tras la conformidad diez días hábiles", esperados={"ley_32069": [99]}),        # cita otra página
                 q("o1", "cocinar ceviche pescado limón cebolla", tipo="out_of_domain")]
    filas = ejecutar(motor(tmp_path, LLMFalso(citas=[{"documento": "Ley 32069", "pagina": 32}])), preguntas)
    assert [f.desenlace for f in filas] == ["respondida", "respondida", "abstuvo_umbral"]
    assert [f.cita_correcta for f in filas] == [True, False, None]
    s = resumir(filas)
    assert (s["in_domain_respondidas"], s["in_domain_con_cita_correcta"], s["fuera_abstenciones_por_umbral"], s["fuera_respuestas_indebidas"]) == (2, 1, 1, 0)
    assert s["llamadas_al_llm"] == 2 and s["llamadas_reales"] == 2 and s["respuestas_de_cache"] == 0 and s["no_ejecutadas"] == 0
    assert s["costo_real_total_usd"] == 0.0 and s["costo_referencia_total_usd"] > 0          # capa gratuita: real 0, referencia > 0
    assert s["costo_referencia_medio_por_llamada_usd"] == round(s["costo_referencia_total_usd"] / 2, 6)


def test_el_llm_que_se_abstiene_en_una_pregunta_ajena_que_paso_la_compuerta(tmp_path):
    filas = ejecutar(motor(tmp_path, LLMFalso(suficiente=False)), [q("o1", "plazo máximo para el pago tras la conformidad", tipo="out_of_domain")])
    assert filas[0].desenlace == "abstuvo_llm" and resumir(filas)["fuera_abstenciones_por_llm"] == 1


def test_con_umbral_no_modifica_la_config_original():
    nueva = con_umbral(BASE, 0.5)
    assert nueva.get("retrieval.umbral_similitud") == 0.5 and BASE.get("retrieval.umbral_similitud") != 0.5


# ── caché y corte por cuota ──

def _preguntas_in(n=3):
    return [q(f"q{i}", "plazo máximo para el pago tras la conformidad diez días hábiles intereses legales", esperados={"ley_32069": [32]}) for i in range(n)]


def test_repetir_la_evaluacion_con_cache_no_repite_llamadas_ni_ensucia_el_log(tmp_path):
    from rag_engine.llm.cache import ClienteConCache
    from rag_engine.llm.cost_log import leer_registros
    llm = LLMFalso()
    cliente = ClienteConCache(lambda: llm, tmp_path / "cache", "gemini", "gemini-2.5-flash-lite", 0.0, 1024)
    m = motor(tmp_path, cliente)
    primera = ejecutar(m, _preguntas_in(1))
    assert len(llm.llamadas) == 1 and primera[0].desde_cache is False and len(leer_registros(tmp_path / "l.jsonl")) == 1
    segunda = ejecutar(m, _preguntas_in(1))
    assert len(llm.llamadas) == 1                                                    # NO hubo otra llamada
    assert segunda[0].desde_cache is True and segunda[0].desenlace == "respondida" and segunda[0].respuesta == primera[0].respuesta
    assert len(leer_registros(tmp_path / "l.jsonl")) == 1                            # la caché no cuenta como llamada
    s = resumir(primera + segunda)
    assert (s["llamadas_al_llm"], s["llamadas_reales"], s["respuestas_de_cache"]) == (2, 1, 1)


def test_si_se_agota_la_cuota_se_corta_y_las_restantes_quedan_no_ejecutadas(tmp_path):
    from rag_engine.llm.base import ErrorLLM
    filas = ejecutar(motor(tmp_path, LLMFalso(error=ErrorLLM("cuota_agotada", "sin cuota"))), _preguntas_in(3))
    assert [f.desenlace for f in filas] == ["error", "no_ejecutada", "no_ejecutada"]
    assert filas[0].error_tipo == "cuota_agotada" and all(f.error_tipo == "cuota_agotada" for f in filas[1:])
    s = resumir(filas)
    assert s["no_ejecutadas"] == 2 and s["in_domain_errores"] == 1 and s["llamadas_al_llm"] == 0


def test_un_error_que_no_es_de_cuota_no_corta_la_evaluacion(tmp_path):
    from rag_engine.llm.base import ErrorLLM
    filas = ejecutar(motor(tmp_path, LLMFalso(error=ErrorLLM("servidor", "caído"))), _preguntas_in(2))
    assert [f.desenlace for f in filas] == ["error", "error"]
