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
    return MotorRAG(cfg_con(BASE, **{"retrieval.umbral_similitud": 0.3, "retrieval.top_k": 3}), e, col, Modificaciones.cargar(ruta), cargar_tabla(BASE.ruta("pricing")),
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
    assert s["llamadas_al_llm"] == 2 and s["costo_total_usd"] > 0 and s["costo_medio_por_llamada_usd"] == round(s["costo_total_usd"] / 2, 6)


def test_el_llm_que_se_abstiene_en_una_pregunta_ajena_que_paso_la_compuerta(tmp_path):
    filas = ejecutar(motor(tmp_path, LLMFalso(suficiente=False)), [q("o1", "plazo máximo para el pago tras la conformidad", tipo="out_of_domain")])
    assert filas[0].desenlace == "abstuvo_llm" and resumir(filas)["fuera_abstenciones_por_llm"] == 1


def test_con_umbral_no_modifica_la_config_original():
    nueva = con_umbral(BASE, 0.5)
    assert nueva.get("retrieval.umbral_similitud") == 0.5 and BASE.get("retrieval.umbral_similitud") != 0.5
