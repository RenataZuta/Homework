"""scripts/set_env_key.py: edición de .env sin filtrar valores."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("set_env_key", Path(__file__).resolve().parents[1] / "scripts" / "set_env_key.py")
sek = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sek)


def test_reemplaza_la_linea_existente_y_conserva_las_demas():
    antes = "TESSERACT_CMD=/x/tesseract\nANTHROPIC_API_KEY=\nOPENAI_API_KEY=viejo\n"
    despues = sek.actualizar_env(antes, "ANTHROPIC_API_KEY", "sk-ant-nuevo")
    assert despues == "TESSERACT_CMD=/x/tesseract\nANTHROPIC_API_KEY=sk-ant-nuevo\nOPENAI_API_KEY=viejo\n"


def test_no_confunde_un_nombre_que_es_prefijo_de_otro():
    antes = "MI_OPENAI_API_KEY=a\nOPENAI_API_KEY=b\n"
    assert sek.actualizar_env(antes, "OPENAI_API_KEY", "c") == "MI_OPENAI_API_KEY=a\nOPENAI_API_KEY=c\n"


def test_añade_al_final_aunque_falte_el_salto_de_linea():
    assert sek.actualizar_env("A=1", "B", "2") == "A=1\nB=2\n"


def test_valores_con_barras_o_referencias_de_regex_se_guardan_literales():
    assert sek.actualizar_env("K=\n", "K", r"a\1\g<0>b") == "K=a\\1\\g<0>b\n"


def test_rechaza_saltos_de_linea_y_nombres_raros():
    with pytest.raises(ValueError):
        sek.actualizar_env("", "K", "a\nOTRA=1")
    with pytest.raises(ValueError):
        sek.actualizar_env("", "k-minuscula", "x")


def test_estado_no_revela_valores():
    est = sek.variables_definidas("A=secreto\nB=\nC=  \n")
    assert est == {"A": True, "B": False, "C": False}
    assert "secreto" not in repr(est)


def test_solo_acepta_nombres_de_env_example():
    nombres = sek.nombres_permitidos()
    assert "ANTHROPIC_API_KEY" in nombres and "OPENAI_API_KEY" in nombres
    assert "PATH" not in nombres


def test_main_guarda_sin_imprimir_el_valor(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    monkeypatch.setattr(sek, "RUTA_ENV", env)
    monkeypatch.setattr(sek.getpass, "getpass", lambda _p: "sk-ant-SECRETO123")
    assert sek.main(["ANTHROPIC_API_KEY"]) == 0
    salida = capsys.readouterr()
    assert "SECRETO123" not in salida.out + salida.err
    assert env.read_text() == "ANTHROPIC_API_KEY=sk-ant-SECRETO123\n"
    assert oct(env.stat().st_mode)[-3:] == "600"


def test_main_rechaza_nombre_no_permitido_y_valor_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(sek, "RUTA_ENV", tmp_path / ".env")
    assert sek.main(["NO_EXISTE"]) == 2
    monkeypatch.setattr(sek.getpass, "getpass", lambda _p: "   ")
    assert sek.main(["OPENAI_API_KEY"]) == 1
    assert not (tmp_path / ".env").exists()
