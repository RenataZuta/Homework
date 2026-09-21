"""Embeddings de Gemini con transporte simulado: un vector por texto, prefijos, normalización, contabilidad sin tokens y errores."""
import numpy as np
import pytest

from rag_engine.embeddings.base import ErrorEmbeddings
from rag_engine.embeddings.gemini_api import GeminiEmbeddings
from rag_engine.limites import ErrorProveedor, PoliticaReintentos

CLAVE = "AI" + "za" + "SyDsecretosecretosecretosecreto12345"
DIM = 8


class Transporte:
    def __init__(self, dim=DIM, respuestas=None, valores=None):
        self.llamadas, self.dim, self.respuestas, self.valores = [], dim, list(respuestas or []), valores

    def __call__(self, url, cabeceras, cuerpo, timeout):
        self.llamadas.append({"url": url, "cabeceras": cabeceras, "cuerpo": cuerpo, "timeout": timeout})
        if self.respuestas:
            r = self.respuestas.pop(0)
            if isinstance(r, Exception):
                raise r
            if r is not None:
                return r
        n = len(cuerpo["requests"])
        vals = self.valores or [[float(i + 1)] + [0.5] * (self.dim - 1) for i in range(n)]      # sin normalizar a propósito
        return 200, {"embeddings": [{"values": v} for v in vals]}, {}


def emb(t, **kw):
    args = dict(modelo="gemini-embedding-2", api_key=CLAVE, dimensiones=DIM, prefijo_consulta="task: search result | query: ",
                prefijo_pasaje="title: none | text: ", batch=2, transporte=t)
    return GeminiEmbeddings(**{**args, **kw})


def test_cada_texto_va_en_su_propia_peticion_con_modelo_dimension_y_prefijo_de_pasaje():
    t = Transporte()
    emb(t).embed_passages(["uno", "dos"])
    c = t.llamadas[0]
    assert c["url"].endswith("/models/gemini-embedding-2:batchEmbedContents") and c["cabeceras"] == {"x-goog-api-key": CLAVE}
    assert c["cuerpo"]["requests"] == [
        {"model": "models/gemini-embedding-2", "content": {"parts": [{"text": "title: none | text: uno"}]}, "outputDimensionality": DIM},
        {"model": "models/gemini-embedding-2", "content": {"parts": [{"text": "title: none | text: dos"}]}, "outputDimensionality": DIM}]
    assert CLAVE not in c["url"]                                                         # la clave solo viaja en la cabecera


def test_la_consulta_lleva_el_prefijo_de_consulta_y_no_el_de_pasaje():
    t = Transporte()
    emb(t).embed_query("¿plazo de pago?")
    assert t.llamadas[0]["cuerpo"]["requests"][0]["content"]["parts"][0]["text"] == "task: search result | query: ¿plazo de pago?"


def test_los_vectores_salen_normalizados_y_en_orden_aunque_la_api_no_los_normalice():
    t = Transporte()
    m = emb(t).embed_passages(["a", "b"])
    assert m.shape == (2, DIM) and np.allclose(np.linalg.norm(m, axis=1), 1.0) and m[1, 0] > m[0, 0]          # el 2.º tenía valor 2, el 1.º valor 1


def test_los_textos_se_parten_en_lotes_del_tamano_configurado():
    t = Transporte()
    assert emb(t, batch=2).embed_passages(list("abcde")).shape == (5, DIM)
    assert [len(c["cuerpo"]["requests"]) for c in t.llamadas] == [2, 2, 1]


def test_la_contabilidad_declara_que_no_hay_tokens_y_el_costo_real_es_cero_en_la_capa_gratuita():
    e = emb(Transporte())
    e.embed_passages(["a", "b", "c"])
    assert e.tokens_reportados is False and e.contabilidad.tokens == 0 and e.contabilidad.costo_usd == 0.0
    assert (e.contabilidad.llamadas, e.contabilidad.textos) == (2, 3)


def test_con_nivel_de_pago_no_se_inventa_un_costo_sin_tokens():
    e = emb(Transporte(), nivel="pago")
    e.embed_passages(["a"])
    assert e.contabilidad.costo_usd is None


def test_un_numero_de_vectores_distinto_al_de_textos_es_un_error_no_vectores_falsos():
    t = Transporte(respuestas=[(200, {"embeddings": [{"values": [1.0] * DIM}]}, {})])
    with pytest.raises(ErrorEmbeddings) as e:
        emb(t).embed_passages(["a", "b"])
    assert e.value.tipo == "respuesta_malformada"


def test_una_dimension_inesperada_es_un_error():
    with pytest.raises(ErrorEmbeddings, match="dimensiones"):
        emb(Transporte(dim=5)).embed_query("hola")


# ── errores, throttle y reintentos ──

def politica(dormidos):
    return PoliticaReintentos(3, 4, 2, 60, 0.0, dormir=dormidos.append, azar=lambda: 0.0)


def error_http(estado, mensaje="x", status="X", detalles=None):
    return estado, {"error": {"code": estado, "message": mensaje, "status": status, "details": detalles or []}}, {}


def test_un_429_por_minuto_se_reintenta_y_luego_funciona():
    dormidos = []
    t = Transporte(respuestas=[error_http(429, "cuota", "RESOURCE_EXHAUSTED", [{"retryDelay": "9s"}]), None])
    m = emb(t, politica=politica(dormidos)).embed_query("hola")
    assert m.shape == (DIM,) and len(t.llamadas) == 2 and dormidos == [9.0]


def test_si_el_limite_persiste_el_error_final_es_cuota_agotada():
    t = Transporte(respuestas=[error_http(429, "cuota", "RESOURCE_EXHAUSTED")] * 10)
    with pytest.raises(ErrorEmbeddings) as e:
        emb(t, politica=politica([])).embed_passages(["a"])
    assert e.value.tipo == "cuota_agotada" and e.value.intentos == 4 and len(t.llamadas) == 4


def test_la_cuota_diaria_no_se_reintenta():
    t = Transporte(respuestas=[error_http(429, "Quota exceeded", "RESOURCE_EXHAUSTED",
                                          [{"violations": [{"quotaId": "EmbedContentRequestsPerDayPerProjectPerModel-FreeTier"}]}])])
    with pytest.raises(ErrorEmbeddings) as e:
        emb(t, politica=politica([])).embed_query("hola")
    assert e.value.tipo == "cuota_agotada" and len(t.llamadas) == 1


def test_una_clave_invalida_es_un_error_de_autenticacion_sin_reintentos():
    t = Transporte(respuestas=[error_http(400, "API key not valid", "INVALID_ARGUMENT")])
    with pytest.raises(ErrorEmbeddings) as e:
        emb(t, politica=politica([])).embed_query("hola")
    assert e.value.tipo == "autenticacion" and len(t.llamadas) == 1 and "GEMINI_API_KEY" in e.value.mensaje


def test_un_fallo_de_red_se_reintenta():
    dormidos = []
    t = Transporte(respuestas=[ErrorProveedor("red", "sin conexión"), None])
    assert emb(t, politica=politica(dormidos)).embed_query("hola").shape == (DIM,) and dormidos == [4]


def test_sin_clave_falla_con_mensaje_claro_y_sin_enviar():
    with pytest.raises(ErrorEmbeddings, match="GEMINI_API_KEY") as e:
        emb(Transporte(), api_key=None)
    assert e.value.solicitud_enviada is False and e.value.tipo == "autenticacion"


def test_la_fabrica_crea_el_embedder_de_gemini_desde_la_config(monkeypatch):
    from rag_engine.config import ConfigError, cargar_config
    from rag_engine.embeddings.factory import crear_embedder
    cfg = cargar_config(cargar_env=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        crear_embedder(cfg, "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", CLAVE)
    e = crear_embedder(cfg, "gemini")
    assert isinstance(e, GeminiEmbeddings) and e.name == "gemini-embedding-2" and e.dim == 768 and e.nivel == "gratuito"
    assert e.prefijo_consulta == "task: search result | query: " and e.prefijo_pasaje == "title: none | text: "
    assert e.limitador.rpm == cfg.get("embeddings.limites.rpm")
