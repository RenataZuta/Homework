"""Pruebas de rag_engine.config: la config real carga, y los errores son claros."""
from pathlib import Path

import pytest
import yaml

from rag_engine.config import ConfigError, RUTA_CONFIG_POR_DEFECTO, cargar_config


def _escribir_variante(tmp_path: Path, mutar) -> Path:
    """Copia el config.yaml real a tmp_path aplicando `mutar(datos)`; devuelve la ruta."""
    datos = yaml.safe_load(RUTA_CONFIG_POR_DEFECTO.read_text(encoding="utf-8"))
    mutar(datos)
    destino = tmp_path / "config.yaml"
    destino.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    return destino


def _borrar(datos: dict, ruta: str) -> None:
    *padres, hoja = ruta.split(".")
    for p in padres:
        datos = datos[p]
    del datos[hoja]


def _asignar(datos: dict, ruta: str, valor) -> None:
    *padres, hoja = ruta.split(".")
    for p in padres:
        datos = datos[p]
    datos[hoja] = valor


# ── la configuración real ──

def test_config_real_carga_sin_env():
    cfg = cargar_config(cargar_env=False)
    assert [d["id"] for d in cfg.documentos] == ["ley_32069", "ds_009_2025_ef", "ds_001_2026_ef"]
    assert cfg.get("retrieval.top_k") >= 1
    assert cfg["llm.modelo"].startswith("claude-")


def test_rutas_se_resuelven_absolutas_dentro_de_tarea1():
    cfg = cargar_config(cargar_env=False)
    raw = cfg.ruta("raw")
    assert raw.is_absolute()
    assert raw == (cfg.base / "data" / "raw").resolve()
    assert cfg.ruta("llm_calls_log").name == "llm_calls.jsonl"


def test_cada_documento_tiene_version_y_rol():
    cfg = cargar_config(cargar_env=False)
    versiones = {d["id"]: d["version"] for d in cfg.documentos}
    assert versiones == {
        "ley_32069": "ley_vigente",
        "ds_009_2025_ef": "reglamento_original_2025",
        "ds_001_2026_ef": "modificatoria_2026-01",
    }
    assert cfg.documento("ds_001_2026_ef")["modifica"] == "ds_009_2025_ef"


def test_documento_inexistente_lista_los_disponibles():
    cfg = cargar_config(cargar_env=False)
    with pytest.raises(ConfigError, match="ley_32069"):
        cfg.documento("no_existe")


def test_chunking_activo_es_una_de_las_configuraciones():
    cfg = cargar_config(cargar_env=False)
    assert cfg.chunking_activo["nombre"] == cfg["chunking.activa"]
    assert cfg.chunking_activo["solapamiento"] < cfg.chunking_activo["tamano"]


# ── errores claros ──

@pytest.mark.parametrize("ruta", [
    "retrieval.top_k", "llm.modelo", "mensajes.abstencion",
    "eval.min_recall_at_3", "deploy.topes.consultas_por_sesion", "paths.llm_calls_log",
])
def test_falta_una_clave_y_el_mensaje_la_nombra(tmp_path, ruta):
    archivo = _escribir_variante(tmp_path, lambda d: _borrar(d, ruta))
    with pytest.raises(ConfigError) as exc:
        cargar_config(archivo, cargar_env=False)
    assert f"'{ruta}'" in str(exc.value)


def test_reporta_todos_los_problemas_juntos(tmp_path):
    def mutar(d):
        _borrar(d, "llm.modelo")
        _borrar(d, "retrieval.top_k")
    archivo = _escribir_variante(tmp_path, mutar)
    with pytest.raises(ConfigError) as exc:
        cargar_config(archivo, cargar_env=False)
    assert "llm.modelo" in str(exc.value) and "retrieval.top_k" in str(exc.value)


def test_valor_nulo_en_clave_requerida_falla(tmp_path):
    archivo = _escribir_variante(tmp_path, lambda d: _asignar(d, "llm.modelo", None))
    with pytest.raises(ConfigError, match="llm.modelo.*vacía"):
        cargar_config(archivo, cargar_env=False)


def test_modo_de_recuperacion_invalido(tmp_path):
    archivo = _escribir_variante(tmp_path, lambda d: _asignar(d, "retrieval.modo", "magia"))
    with pytest.raises(ConfigError, match="retrieval.modo"):
        cargar_config(archivo, cargar_env=False)


def test_umbral_fuera_de_rango(tmp_path):
    archivo = _escribir_variante(tmp_path, lambda d: _asignar(d, "retrieval.umbral_similitud", 1.7))
    with pytest.raises(ConfigError, match="umbral_similitud"):
        cargar_config(archivo, cargar_env=False)


def test_chunking_activa_debe_existir(tmp_path):
    archivo = _escribir_variante(tmp_path, lambda d: _asignar(d, "chunking.activa", "c9999"))
    with pytest.raises(ConfigError, match="chunking.activa"):
        cargar_config(archivo, cargar_env=False)


def test_solapamiento_mayor_que_tamano(tmp_path):
    def mutar(d):
        d["chunking"]["configuraciones"][0]["solapamiento"] = 999
    archivo = _escribir_variante(tmp_path, mutar)
    with pytest.raises(ConfigError, match="solapamiento"):
        cargar_config(archivo, cargar_env=False)


def test_rangos_de_paginas_deben_cubrir_cada_documento(tmp_path):
    archivo = _escribir_variante(tmp_path, lambda d: _borrar(d, "extraccion.rangos_paginas.ds_001_2026_ef"))
    with pytest.raises(ConfigError, match="ds_001_2026_ef"):
        cargar_config(archivo, cargar_env=False)


def test_archivo_inexistente_indica_la_ruta(tmp_path):
    with pytest.raises(ConfigError, match="no_esta_aqui.yaml"):
        cargar_config(tmp_path / "no_esta_aqui.yaml", cargar_env=False)


def test_yaml_mal_formado(tmp_path):
    malo = tmp_path / "config.yaml"
    malo.write_text("paths: [sin cerrar", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        cargar_config(malo, cargar_env=False)


# ── variables de entorno (credenciales) ──

def test_requerir_env_falta_da_mensaje_util_sin_valores(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = cargar_config(cargar_env=False)
    with pytest.raises(ConfigError) as exc:
        cfg.requerir_env("ANTHROPIC_API_KEY", para="generar respuestas")
    msg = str(exc.value)
    assert "ANTHROPIC_API_KEY" in msg and ".env.example" in msg and "generar respuestas" in msg


def test_env_vacio_cuenta_como_faltante(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    cfg = cargar_config(cargar_env=False)
    assert cfg.env("ANTHROPIC_API_KEY") is None
    with pytest.raises(ConfigError):
        cfg.requerir_env("ANTHROPIC_API_KEY")


def test_env_presente_se_devuelve(monkeypatch):
    monkeypatch.setenv("TESSERACT_CMD", "C:/ruta/tesseract.exe")
    cfg = cargar_config(cargar_env=False)
    assert cfg.requerir_env("TESSERACT_CMD") == "C:/ruta/tesseract.exe"


def test_dotenv_de_la_carpeta_de_config_se_carga(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKEND_INTERNAL_KEY", raising=False)
    archivo = _escribir_variante(tmp_path, lambda d: None)
    (tmp_path / ".env").write_text("BACKEND_INTERNAL_KEY=valor-de-prueba\n", encoding="utf-8")
    cfg = cargar_config(archivo, cargar_env=True)
    assert cfg.requerir_env("BACKEND_INTERNAL_KEY") == "valor-de-prueba"
    monkeypatch.delenv("BACKEND_INTERNAL_KEY", raising=False)  # no contaminar otros tests
