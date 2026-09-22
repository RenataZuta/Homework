"""Búsqueda exacta: coincide con la fuerza bruta, es determinista (desempate por ID), filtra por metadatos y no usa datos viejos."""
import numpy as np
import pytest

from rag_engine.retrieval import semantic
from rag_engine.retrieval.indice import abrir_cliente, crear_o_abrir
from rag_engine.retrieval.semantic import buscar, olvidar_matrices

DIM = 16


class EmbedderVector:
    """Devuelve el vector que se le indique (sin modelo): la consulta ES el vector."""
    def __init__(self, v):
        self.v = np.asarray(v, dtype=np.float32)

    def embed_query(self, _texto):
        return self.v


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def col(tmp_path):
    olvidar_matrices()
    rng = np.random.default_rng(7)
    m = rng.normal(size=(300, DIM)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    c = crear_o_abrir(abrir_cliente(tmp_path / "i"), "coleccion_prueba", {})
    ids = [f"d:v:p{i:04d}:c000" for i in range(300)]
    c.upsert(ids=ids, embeddings=m.tolist(), documents=[f"texto {i}" for i in range(300)],
             metadatas=[{"documento": "ley" if i % 2 else "reg", "version": "v", "pagina": i} for i in range(300)])
    c._m, c._ids = m, ids
    return c


def test_coincide_con_la_fuerza_bruta_para_muchas_consultas(col):
    rng = np.random.default_rng(1)
    for _ in range(25):
        q = unit(rng.normal(size=DIM))
        esperado = [col._ids[i] for i in np.argsort(-(col._m @ q))[:5]]
        r = buscar(col, EmbedderVector(q), "x", 5)
        assert [x.id for x in r] == esperado
        assert [x.similitud for x in r] == sorted((x.similitud for x in r), reverse=True)


def test_la_similitud_es_el_coseno_real(col):
    q = unit(np.ones(DIM))
    r = buscar(col, EmbedderVector(q), "x", 1)[0]
    assert r.similitud == pytest.approx(float(col._m[col._ids.index(r.id)] @ q), abs=1e-6)
    assert r.pagina == int(r.id.split(":p")[1][:4]) and r.texto.startswith("texto")


def test_es_determinista_y_desempata_por_id(tmp_path):
    olvidar_matrices()
    c = crear_o_abrir(abrir_cliente(tmp_path / "i"), "coleccion_prueba", {})
    v = unit(np.ones(DIM)).tolist()
    ids = ["z:v:p0001:c000", "a:v:p0002:c000", "m:v:p0003:c000"]                       # tres vectores IDÉNTICOS
    c.upsert(ids=ids, embeddings=[v] * 3, documents=["1", "2", "3"], metadatas=[{"documento": "d", "version": "v", "pagina": p} for p in (1, 2, 3)])
    for _ in range(5):
        assert [x.id for x in buscar(c, EmbedderVector(v), "x", 3)] == ["a:v:p0002:c000", "m:v:p0003:c000", "z:v:p0001:c000"]


def test_el_filtro_por_metadatos_solo_devuelve_ese_documento(col):
    r = buscar(col, EmbedderVector(unit(np.ones(DIM))), "x", 10, donde={"documento": "ley"})
    assert len(r) == 10 and {x.documento for x in r} == {"ley"}


def test_k_mayor_que_el_indice_devuelve_todo(col):
    assert len(buscar(col, EmbedderVector(unit(np.ones(DIM))), "x", 1000)) == 300


def test_la_consulta_no_necesita_venir_normalizada(col):
    q = unit(np.arange(1, DIM + 1))
    a = buscar(col, EmbedderVector(q), "x", 5)
    b = buscar(col, EmbedderVector(q * 37.0), "x", 5)
    assert [x.id for x in a] == [x.id for x in b] and a[0].similitud == pytest.approx(b[0].similitud, abs=1e-6)


def test_la_matriz_se_reconstruye_si_cambia_el_indice(col):
    q = unit(np.ones(DIM))
    antes = buscar(col, EmbedderVector(q), "x", 1)[0].id
    col.upsert(ids=["nuevo:v:p9999:c000"], embeddings=[q.tolist()], documents=["idéntico a la consulta"], metadatas=[{"documento": "d", "version": "v", "pagina": 9999}])
    despues = buscar(col, EmbedderVector(q), "x", 1)[0]
    assert despues.id == "nuevo:v:p9999:c000" and despues.similitud == pytest.approx(1.0, abs=1e-5) and antes != despues.id


def test_olvidar_matrices_evita_datos_viejos_con_el_mismo_numero_de_fragmentos(col):
    q = unit(np.ones(DIM))
    buscar(col, EmbedderVector(q), "x", 1)
    col.upsert(ids=[col._ids[0]], embeddings=[q.tolist()], documents=["reemplazado"], metadatas=[{"documento": "d", "version": "v", "pagina": 0}])   # mismo conteo
    olvidar_matrices()
    r = buscar(col, EmbedderVector(q), "x", 1)[0]
    assert r.id == col._ids[0] and r.texto == "reemplazado"


def test_la_busqueda_aproximada_sigue_disponible_por_configuracion(col):
    q = unit(np.ones(DIM))
    r = buscar(col, EmbedderVector(q), "x", 3, exacta=False)
    assert len(r) == 3 and semantic._buscar_aproximada is not None


def test_un_filtro_complejo_cae_a_la_consulta_de_chroma(col):
    r = buscar(col, EmbedderVector(unit(np.ones(DIM))), "x", 3, donde={"$and": [{"documento": "ley"}, {"pagina": {"$gte": 100}}]})
    assert r and all(x.documento == "ley" and x.pagina >= 100 for x in r)
