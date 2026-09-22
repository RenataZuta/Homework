"""Interfaz de embeddings: contrato común, prefijos, contabilidad y errores."""
from types import SimpleNamespace

import numpy as np
import pytest

from fakes import EmbedderFalso
from rag_engine.embeddings.base import ErrorEmbeddings
from rag_engine.embeddings.factory import crear_embedder
from rag_engine.embeddings.local_st import LocalSentenceTransformers
from rag_engine.embeddings.openai_api import OpenAIEmbeddings
from rag_engine.config import ConfigError, cargar_config


class ModeloFalso:
    """Imita a SentenceTransformer: registra lo que recibe para verificar los prefijos."""
    max_seq_length = 512

    def __init__(self, dim=4):
        self.dim = dim
        self.recibido = []
        self.tokenizer = lambda textos, **kw: {"input_ids": [list(range(len(t.split()) + 2)) for t in textos]}

    def get_sentence_embedding_dimension(self):
        return self.dim

    def encode(self, textos, **kw):
        self.recibido.append(list(textos))
        return np.array([[len(t), 1.0, 2.0, 3.0] for t in textos], dtype=np.float32)


# ── contrato común ──

def test_los_vectores_salen_normalizados():
    e = EmbedderFalso()
    m = e.embed_passages(["pago de contratistas al Estado", "penalidad por mora en la ejecución"])
    assert m.shape == (2, e.dim) and np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-5)
    assert np.isclose(np.linalg.norm(e.embed_query("multa a la microempresa")), 1.0, atol=1e-5)


def test_procesa_por_lotes_y_conserva_el_orden():
    e = EmbedderFalso(batch=3)
    textos = [f"texto numero{i} distinto" for i in range(10)]
    m = e.embed_passages(textos)
    assert m.shape == (10, e.dim) and e.contabilidad.llamadas == 4          # 3+3+3+1
    assert np.allclose(m[7], e.embed_passages([textos[7]])[0])


def test_lista_vacia_no_llama_al_modelo():
    e = EmbedderFalso()
    assert e.embed_passages([]).shape == (0, e.dim) and e.contabilidad.llamadas == 0


def test_contabilidad_acumula_textos_tokens_y_costo():
    e = EmbedderFalso(batch=2)
    e.embed_passages(["uno dos tres", "cuatro cinco", "seis"])
    c = e.contabilidad
    assert (c.llamadas, c.textos) == (2, 3) and c.tokens == 6 and c.segundos >= 0 and c.costo_usd == 0.0


# ── local: prefijos y longitud real ──

def test_local_aplica_prefijos_distintos_a_consulta_y_a_pasaje():
    m = ModeloFalso()
    e = LocalSentenceTransformers("intfloat/multilingual-e5-small", "query: ", "passage: ", modelo_cargado=m)
    e.embed_query("¿cuánto es la multa?")
    e.embed_passages(["La multa no puede ser mayor al 8 %."])
    assert m.recibido[0] == ["query: ¿cuánto es la multa?"] and m.recibido[1] == ["passage: La multa no puede ser mayor al 8 %."]


def test_local_sin_prefijos_no_agrega_nada():
    m = ModeloFalso()
    LocalSentenceTransformers("otro/modelo", modelo_cargado=m).embed_passages(["texto"])
    assert m.recibido[0] == ["texto"]


def test_local_reporta_la_longitud_maxima_real_del_modelo_no_la_de_la_config():
    m = ModeloFalso()
    m.max_seq_length = 128
    e = LocalSentenceTransformers("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", modelo_cargado=m)
    assert e.max_tokens == 128 and e.dim == 4


def test_local_cuenta_tokens_con_el_prefijo_incluido():
    m = ModeloFalso()
    e = LocalSentenceTransformers("x", "query: ", "passage: ", modelo_cargado=m)
    sin, con = e.contar_tokens(["a b c"], es_consulta=False), LocalSentenceTransformers("x", modelo_cargado=m).contar_tokens(["a b c"])
    assert sin[0] == con[0] + 1                       # "passage:" agrega una palabra en el doble de prueba


def test_local_con_modelo_inexistente_da_un_error_claro():
    with pytest.raises(ErrorEmbeddings, match="No se pudo cargar el modelo local"):
        LocalSentenceTransformers("no-existe/este-modelo-12345", dispositivo="cpu")


# ── OpenAI (cliente simulado) ──

class ClienteOpenAIFalso:
    def __init__(self, falla=False):
        self.llamadas, self.falla = [], falla
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        if self.falla:
            raise RuntimeError("rate limit")
        self.llamadas.append(kw)
        datos = [SimpleNamespace(index=i, embedding=[float(i + 1), 0.0, 0.0]) for i in reversed(range(len(kw["input"])))]   # desordenados
        return SimpleNamespace(data=datos, usage=SimpleNamespace(total_tokens=10 * len(kw["input"])))


def test_openai_ordena_por_indice_y_calcula_el_costo_con_el_precio_dado():
    c = ClienteOpenAIFalso()
    e = OpenAIEmbeddings("text-embedding-3-small", precio_usd_por_millon=0.5, cliente=c, batch=10)
    m = e.embed_passages(["a", "b", "c"])
    assert np.allclose(m[:, 0], 1.0) and c.llamadas[0]["model"] == "text-embedding-3-small"
    assert e.contabilidad.tokens == 30 and e.contabilidad.costo_usd == pytest.approx(30 * 0.5 / 1e6)


def test_openai_sin_precio_verificado_deja_el_costo_en_none_en_vez_de_inventarlo():
    e = OpenAIEmbeddings("text-embedding-3-small", precio_usd_por_millon=None, cliente=ClienteOpenAIFalso())
    e.embed_passages(["a"])
    assert e.contabilidad.costo_usd is None


def test_openai_un_fallo_de_la_api_es_un_error_no_un_vector():
    e = OpenAIEmbeddings("text-embedding-3-small", cliente=ClienteOpenAIFalso(falla=True))
    with pytest.raises(ErrorEmbeddings, match="rate limit"):
        e.embed_query("hola")


@pytest.mark.parametrize("nombre, extra, tipo", [
    ("RateLimitError", {"code": "insufficient_quota"}, "cuota_insuficiente"),          # sin crédito: NO se reintenta ni se le pide pagar al usuario
    ("RateLimitError", {"status_code": 429}, "limite_de_tasa"), ("AuthenticationError", {}, "autenticacion"),
    ("APIConnectionError", {}, "red"), ("Extraño", {}, "otro"),
])
def test_openai_clasifica_sus_errores_y_detecta_insufficient_quota(nombre, extra, tipo):
    exc = type(nombre, (Exception,), {})("You exceeded your current quota" if extra.get("code") else "fallo")
    for k, v in extra.items():
        setattr(exc, k, v)

    class Falla:
        embeddings = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(exc))
    with pytest.raises(ErrorEmbeddings) as e:
        OpenAIEmbeddings("text-embedding-3-small", cliente=Falla()).embed_query("hola")
    assert e.value.tipo == tipo


def test_openai_reconoce_insufficient_quota_aunque_solo_venga_en_el_texto():
    exc = RuntimeError("Error code: 429 - {'error': {'code': 'insufficient_quota'}}")

    class Falla:
        embeddings = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(exc))
    with pytest.raises(ErrorEmbeddings) as e:
        OpenAIEmbeddings("text-embedding-3-small", cliente=Falla()).embed_query("hola")
    assert e.value.tipo == "cuota_insuficiente"


def test_openai_sin_clave_falla_con_mensaje_claro():
    with pytest.raises(ErrorEmbeddings, match="OPENAI_API_KEY"):
        OpenAIEmbeddings("text-embedding-3-small", api_key=None)


# ── fábrica ──

def test_la_fabrica_lee_proveedor_y_modelo_de_la_config(monkeypatch):
    cfg = cargar_config(cargar_env=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):          # clave ausente = problema de configuración
        crear_embedder(cfg, proveedor="openai")
    with pytest.raises(ErrorEmbeddings, match="desconocido"):
        crear_embedder(cfg, proveedor="magia")


# ── carga: primero desde el disco, sin depender de internet ──

def test_la_carga_intenta_primero_solo_desde_el_disco(monkeypatch):
    import sys, types
    llamadas = []

    class Falso:
        max_seq_length = 512
        def __init__(self, nombre, **kw):
            llamadas.append(kw)
        def get_sentence_embedding_dimension(self):
            return 4

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=Falso))
    LocalSentenceTransformers("cualquiera/modelo")
    assert llamadas == [{"device": "cpu", "local_files_only": True}]            # una sola carga, sin red


def test_si_no_esta_en_cache_reintenta_permitiendo_la_descarga(monkeypatch):
    import sys, types
    llamadas = []

    class Falso:
        max_seq_length = 512
        def __init__(self, nombre, **kw):
            llamadas.append(kw)
            if kw.get("local_files_only"):
                raise OSError("no está en la caché")
        def get_sentence_embedding_dimension(self):
            return 4

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=Falso))
    LocalSentenceTransformers("cualquiera/modelo")
    assert [bool(k.get("local_files_only")) for k in llamadas] == [True, False]
