"""Pruebas de scripts/download_pdfs.py contra un servidor HTTP local (sin tocar la red real)."""
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pymupdf
import pytest
import yaml

from rag_engine.config import RUTA_CONFIG_POR_DEFECTO

RUTA_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_pdfs.py"
spec = importlib.util.spec_from_file_location("download_pdfs", RUTA_SCRIPT)
dp = importlib.util.module_from_spec(spec)
sys.modules["download_pdfs"] = dp
spec.loader.exec_module(dp)


def hacer_pdf(texto: str, paginas: int = 2) -> bytes:
    doc = pymupdf.open()
    for i in range(paginas):
        doc.new_page().insert_text((72, 72), f"{texto} pagina {i + 1}")
    contenido = doc.tobytes()
    doc.close()
    return contenido


class Servidor:
    """Sirve rutas -> (status, content_type, bytes) y cuenta las peticiones recibidas."""

    def __init__(self):
        self.rutas: dict[str, tuple[int, str, bytes]] = {}
        self.peticiones: list[str] = []
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            def do_GET(self):
                servidor.peticiones.append(self.path)
                estado, tipo, cuerpo = servidor.rutas.get(self.path, (404, "text/plain", b"no existe"))
                self.send_response(estado)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def cerrar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def servidor():
    s = Servidor()
    yield s
    s.cerrar()


@pytest.fixture
def entorno(tmp_path, servidor):
    """Config temporal con dos documentos apuntando al servidor local. Devuelve (ruta_config, raw, manifiesto)."""
    datos = yaml.safe_load(RUTA_CONFIG_POR_DEFECTO.read_text(encoding="utf-8"))
    datos["documentos"] = [
        {"id": "doc_a", "nombre": "Doc A", "archivo": "doc_a.pdf", "url": "https://pagina/a",
         "url_pdf": f"{servidor.url}/a.pdf", "version": "v1", "rol": "norma_base", "nota": "nota  con\n espacios"},
        {"id": "doc_b", "nombre": "Doc B", "archivo": "doc_b.pdf", "url": "https://pagina/b",
         "url_pdf": f"{servidor.url}/b.pdf", "version": "v2", "rol": "modificatoria", "modifica": "doc_a"},
    ]
    datos["extraccion"]["rangos_paginas"] = {"doc_a": None, "doc_b": None}
    datos["descarga"].update({"reintentos": 2, "espera_reintento_segundos": 0, "timeout_segundos": 5})
    ruta = tmp_path / "config.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    servidor.rutas["/a.pdf"] = (200, "application/pdf", hacer_pdf("A", 2))
    servidor.rutas["/b.pdf"] = (200, "application/pdf", hacer_pdf("B", 3))
    return ruta, tmp_path / "data" / "raw", tmp_path / "data" / "raw" / "MANIFEST.json"


def ejecutar(ruta_config, *extra) -> int:
    return dp.main(["--config", str(ruta_config), *extra])


def leer(manifiesto: Path) -> dict:
    return json.loads(manifiesto.read_text(encoding="utf-8"))


# ── primera descarga ──

def test_primera_corrida_descarga_todo_y_escribe_el_manifiesto(entorno, servidor):
    ruta, raw, manifiesto = entorno
    assert ejecutar(ruta) == 0
    assert (raw / "doc_a.pdf").is_file() and (raw / "doc_b.pdf").is_file()
    m = leer(manifiesto)["documentos"]
    assert list(m) == ["doc_a", "doc_b"]
    a = m["doc_a"]
    assert a["paginas"] == 2 and m["doc_b"]["paginas"] == 3
    assert a["sha256"] == dp.sha256_archivo(raw / "doc_a.pdf")
    assert a["bytes"] == (raw / "doc_a.pdf").stat().st_size
    assert a["url_origen"].endswith("/a.pdf") and a["origen"] == "descarga"
    assert a["fecha_descarga"][:4].isdigit() and "T" in a["fecha_descarga"]  # ISO 8601
    assert a["nota"] == "nota con espacios"


def test_segunda_corrida_no_descarga_nada_ni_toca_el_manifiesto(entorno, servidor, capsys):
    ruta, raw, manifiesto = entorno
    assert ejecutar(ruta) == 0
    peticiones_1ra = len(servidor.peticiones)
    contenido_manifiesto = manifiesto.read_bytes()
    capsys.readouterr()
    assert ejecutar(ruta) == 0
    assert len(servidor.peticiones) == peticiones_1ra, "la segunda corrida hizo peticiones de red"
    assert manifiesto.read_bytes() == contenido_manifiesto, "la segunda corrida modificó el manifiesto"
    assert "sin_cambios=2" in capsys.readouterr().out


def test_solo_baja_el_documento_pedido(entorno, servidor):
    ruta, raw, _ = entorno
    assert ejecutar(ruta, "--solo", "doc_b") == 0
    assert (raw / "doc_b.pdf").is_file() and not (raw / "doc_a.pdf").exists()
    assert servidor.peticiones == ["/b.pdf"]


# ── archivos existentes ──

def test_archivo_colocado_a_mano_se_registra_sin_descargar(entorno, servidor):
    ruta, raw, manifiesto = entorno
    raw.mkdir(parents=True)
    (raw / "doc_a.pdf").write_bytes(hacer_pdf("manual", 4))
    assert ejecutar(ruta, "--solo", "doc_a") == 0
    assert servidor.peticiones == []
    e = leer(manifiesto)["documentos"]["doc_a"]
    assert e["origen"] == "manual" and e["paginas"] == 4 and e["url_origen"] is None


def test_pdf_modificado_en_disco_no_se_sobrescribe(entorno, servidor, capsys):
    ruta, raw, manifiesto = entorno
    assert ejecutar(ruta) == 0
    original = leer(manifiesto)["documentos"]["doc_a"]["sha256"]
    (raw / "doc_a.pdf").write_bytes(hacer_pdf("alterado", 1))
    alterado = (raw / "doc_a.pdf").read_bytes()
    peticiones = len(servidor.peticiones)
    assert ejecutar(ruta) == 1
    assert "no coincide con el manifiesto" in capsys.readouterr().err
    assert (raw / "doc_a.pdf").read_bytes() == alterado, "el script sobrescribió un PDF de data/raw"
    assert len(servidor.peticiones) == peticiones
    assert leer(manifiesto)["documentos"]["doc_a"]["sha256"] == original


def test_archivo_borrado_se_vuelve_a_descargar(entorno, servidor):
    ruta, raw, manifiesto = entorno
    assert ejecutar(ruta) == 0
    hash_original = leer(manifiesto)["documentos"]["doc_a"]["sha256"]
    (raw / "doc_a.pdf").unlink()
    assert ejecutar(ruta) == 0
    assert dp.sha256_archivo(raw / "doc_a.pdf") == hash_original


# ── la fuente cambia ──

def test_si_la_fuente_cambio_no_se_sobrescribe_sin_permiso(entorno, servidor, capsys):
    ruta, raw, manifiesto = entorno
    assert ejecutar(ruta) == 0
    viejo = leer(manifiesto)["documentos"]["doc_a"]["sha256"]
    servidor.rutas["/a.pdf"] = (200, "application/pdf", hacer_pdf("VERSION NUEVA", 5))
    assert ejecutar(ruta, "--forzar") == 1
    assert "la fuente cambió" in capsys.readouterr().err
    assert leer(manifiesto)["documentos"]["doc_a"]["sha256"] == viejo
    assert dp.sha256_archivo(raw / "doc_a.pdf") == viejo
    assert not list(raw.glob("*.part")), "quedó un .part huérfano"


def test_aceptar_cambio_actualiza_archivo_y_manifiesto(entorno, servidor):
    ruta, raw, manifiesto = entorno
    assert ejecutar(ruta) == 0
    servidor.rutas["/a.pdf"] = (200, "application/pdf", hacer_pdf("VERSION NUEVA", 5))
    assert ejecutar(ruta, "--forzar", "--aceptar-cambio") == 0
    e = leer(manifiesto)["documentos"]["doc_a"]
    assert e["paginas"] == 5 and e["sha256"] == dp.sha256_archivo(raw / "doc_a.pdf")


def test_forzar_con_fuente_identica_no_cambia_nada(entorno, servidor, capsys):
    ruta, raw, manifiesto = entorno
    assert ejecutar(ruta) == 0
    antes = manifiesto.read_bytes()
    capsys.readouterr()
    assert ejecutar(ruta, "--forzar") == 0
    assert "identico=2" in capsys.readouterr().out and manifiesto.read_bytes() == antes


# ── fallos de red y de contenido ──

def test_una_pagina_html_no_se_acepta_como_pdf(entorno, servidor, capsys):
    ruta, raw, manifiesto = entorno
    servidor.rutas["/a.pdf"] = (200, "text/html", b"<html>Acceso denegado</html>")
    assert ejecutar(ruta, "--solo", "doc_a") == 1
    assert "no es un PDF" in capsys.readouterr().err
    assert not (raw / "doc_a.pdf").exists() and not list(raw.glob("*.part"))
    assert "doc_a" not in leer(manifiesto)["documentos"]


def test_pdf_truncado_o_danado_se_rechaza(entorno, servidor, capsys):
    ruta, raw, _ = entorno
    servidor.rutas["/a.pdf"] = (200, "application/pdf", b"%PDF-1.4\nesto no es un pdf valido")
    assert ejecutar(ruta, "--solo", "doc_a") == 1
    assert not (raw / "doc_a.pdf").exists()


def test_403_no_se_reintenta_y_da_instrucciones_manuales(entorno, servidor, capsys):
    ruta, raw, _ = entorno
    servidor.rutas["/a.pdf"] = (403, "text/plain", b"prohibido")
    assert ejecutar(ruta, "--solo", "doc_a") == 1
    err = capsys.readouterr().err
    assert "[MANUAL]" in err and "https://pagina/a" in err and "No se insiste" in err
    assert servidor.peticiones.count("/a.pdf") == 1, "un 403 no debe reintentarse"


def test_500_se_reintenta_y_luego_falla(entorno, servidor, capsys):
    ruta, raw, _ = entorno
    servidor.rutas["/a.pdf"] = (503, "text/plain", b"caido")
    assert ejecutar(ruta, "--solo", "doc_a") == 1
    assert servidor.peticiones.count("/a.pdf") == 2  # reintentos=2 en la config de prueba
    assert "no se pudo descargar tras 2 intentos" in capsys.readouterr().err


def test_un_documento_que_falla_no_impide_bajar_los_demas(entorno, servidor):
    ruta, raw, manifiesto = entorno
    servidor.rutas["/a.pdf"] = (404, "text/plain", b"no")
    assert ejecutar(ruta) == 1
    assert (raw / "doc_b.pdf").is_file()
    assert list(leer(manifiesto)["documentos"]) == ["doc_b"]


def test_sin_url_pdf_y_sin_archivo_pide_descarga_manual(entorno, capsys):
    ruta, raw, _ = entorno
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    datos["documentos"][0]["url_pdf"] = None
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    assert ejecutar(ruta, "--solo", "doc_a") == 1
    err = capsys.readouterr().err
    assert "[MANUAL]" in err and "doc_a.pdf" in err


def test_aviso_de_tamano_cuando_supera_el_limite(entorno, servidor, capsys):
    ruta, raw, _ = entorno
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    datos["descarga"]["aviso_tamano_mb"] = 0.0001  # ~100 bytes: cualquier PDF lo supera
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    assert ejecutar(ruta, "--solo", "doc_a") == 0
    assert "Git LFS" in capsys.readouterr().out
