#!/usr/bin/env python3
"""download_pdfs.py — descarga los PDFs oficiales a data/raw/ y escribe data/raw/MANIFEST.json.

Uso (desde tarea1/):
    python scripts/download_pdfs.py                    # los 3 documentos de config.yaml
    python scripts/download_pdfs.py --solo ley_32069   # uno solo
    python scripts/download_pdfs.py --forzar           # vuelve a bajar y compara con lo registrado

Reglas:
  * Idempotente: si el archivo existe y su sha256 coincide con el del manifiesto, NO hace ninguna
    petición de red.
  * Los PDFs de data/raw/ nunca se modifican: si uno en disco no coincide con el manifiesto, se avisa
    y se sale con error; nunca se sobrescribe.
  * Si la fuente cambió desde la descarga registrada (hash distinto), no se sobrescribe salvo con
    --aceptar-cambio: los datos procesados dependen de ese hash.
  * Descarga a un archivo .part y lo renombra al final; valida la firma %PDF y que el archivo abra.
  * Un 401/403 (portal que bloquea) NO se reintenta ni se esquiva: se indica cómo hacerlo a mano.

Códigos de salida: 0 = todo bien, 1 = algún documento falló.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rag_engine.config import ConfigError, RUTA_CONFIG_POR_DEFECTO, cargar_config  # noqa: E402

VERSION_MANIFIESTO = 1


class ErrorDescarga(Exception):
    """Fallo al obtener o validar un documento (el mensaje se muestra al usuario)."""


class Bloqueado(ErrorDescarga):
    """El portal rechazó la petición (401/403): no se insiste."""


# ── utilidades ──

def ahora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def validar_pdf(ruta: Path) -> int:
    """Comprueba firma y que el PDF abra; devuelve el número de páginas."""
    with ruta.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise ErrorDescarga("el archivo descargado no es un PDF (falta la firma %PDF-); ¿el portal devolvió una página HTML?")
    import pymupdf
    try:
        with pymupdf.open(ruta) as doc:
            paginas = doc.page_count
    except Exception as exc:  # PyMuPDF lanza varios tipos según el daño
        raise ErrorDescarga(f"el PDF está dañado o no se puede abrir: {exc}") from exc
    if paginas < 1:
        raise ErrorDescarga("el PDF no tiene páginas")
    return paginas


def escribir_json_atomico(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, ruta)


def cargar_manifiesto(ruta: Path) -> dict:
    if ruta.is_file():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"version_manifiesto": VERSION_MANIFIESTO, "documentos": {}}


# ── red ──

def bajar(url: str, destino_part: Path, ajustes: dict) -> tuple[str, int, str]:
    """Descarga `url` a `destino_part` calculando el sha256 al vuelo. Devuelve (sha256, bytes, content_type)."""
    req = urllib.request.Request(url, headers={"User-Agent": ajustes["user_agent"], "Accept": "application/pdf,*/*;q=0.8"})
    ultimo_error = "sin detalle"
    for intento in range(1, ajustes["reintentos"] + 1):
        try:
            with urllib.request.urlopen(req, timeout=ajustes["timeout_segundos"]) as resp:
                tipo = resp.headers.get("Content-Type", "")
                h, total = hashlib.sha256(), 0
                with destino_part.open("wb") as f:
                    while bloque := resp.read(1 << 20):
                        f.write(bloque)
                        h.update(bloque)
                        total += len(bloque)
                return h.hexdigest(), total, tipo
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise Bloqueado(f"el portal respondió HTTP {exc.code} (bloquea la descarga automática)") from exc
            if exc.code != 429 and exc.code < 500:
                raise ErrorDescarga(f"HTTP {exc.code} al pedir {url}") from exc
            ultimo_error = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            ultimo_error = str(getattr(exc, "reason", exc))
        if intento < ajustes["reintentos"]:
            time.sleep(ajustes["espera_reintento_segundos"] * intento)
    raise ErrorDescarga(f"no se pudo descargar tras {ajustes['reintentos']} intentos ({ultimo_error})")


def _instrucciones_manuales(doc: dict, raw: Path) -> str:
    return (f"[MANUAL] Descarga el PDF desde {doc['url']} y guárdalo como {raw / doc['archivo']}; "
            f"luego vuelve a ejecutar este script para registrarlo en el manifiesto.")


# ── lógica por documento ──

def _entrada_manifiesto(doc: dict, url_origen: str | None, fecha: str, sha: str, tamano: int,
                        paginas: int, tipo: str, origen: str) -> dict:
    return {
        "documento": doc["id"], "nombre": doc["nombre"], "version": doc["version"], "archivo": doc["archivo"],
        "url_pagina": doc["url"], "url_origen": url_origen, "fecha_descarga": fecha, "sha256": sha,
        "bytes": tamano, "paginas": paginas, "content_type": tipo, "origen": origen,
        **({"nota": " ".join(str(doc["nota"]).split())} if doc.get("nota") else {}),
    }


def procesar_documento(doc: dict, raw: Path, manifiesto: dict, ajustes: dict, forzar: bool, aceptar_cambio: bool) -> str:
    """Devuelve el estado: descargado | sin_cambios | registrado_manual | identico. Lanza ErrorDescarga si falla."""
    destino = raw / doc["archivo"]
    entrada = manifiesto["documentos"].get(doc["id"])

    if destino.is_file():
        sha_disco = sha256_archivo(destino)
        if entrada is None:
            paginas = validar_pdf(destino)
            fecha = datetime.fromtimestamp(destino.stat().st_mtime).astimezone().isoformat(timespec="seconds")
            manifiesto["documentos"][doc["id"]] = _entrada_manifiesto(
                doc, None, fecha, sha_disco, destino.stat().st_size, paginas, "application/pdf", "manual")
            return "registrado_manual"
        if entrada["sha256"] != sha_disco:
            raise ErrorDescarga(
                f"{destino.name} en disco (sha256 {sha_disco[:12]}…) no coincide con el manifiesto "
                f"({entrada['sha256'][:12]}…). Los PDFs de data/raw/ no se modifican: restaura el original con git "
                f"(git checkout -- {destino}) o borra el archivo y el manifiesto si el cambio es intencional.")
        if not forzar:
            return "sin_cambios"

    url = doc.get("url_pdf")
    if not url:
        raise ErrorDescarga(f"el documento '{doc['id']}' no tiene 'url_pdf' en config.yaml. {_instrucciones_manuales(doc, raw)}")

    raw.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".part")
    try:
        try:
            sha, tamano, tipo = bajar(url, parcial, ajustes)
        except Bloqueado as exc:
            raise ErrorDescarga(f"{exc}. No se insiste ni se esquiva el bloqueo. {_instrucciones_manuales(doc, raw)}") from exc
        paginas = validar_pdf(parcial)
        if entrada and entrada["sha256"] != sha and not aceptar_cambio:
            raise ErrorDescarga(
                f"la fuente cambió desde la descarga registrada (sha256 {entrada['sha256'][:12]}… → {sha[:12]}…). "
                f"No se sobrescribe porque los datos procesados dependen de ese hash; usa --aceptar-cambio si es intencional.")
        if destino.is_file() and entrada and entrada["sha256"] == sha:
            return "identico"  # --forzar y la fuente sigue igual: el archivo en disco ya es ese
        os.replace(parcial, destino)
        manifiesto["documentos"][doc["id"]] = _entrada_manifiesto(doc, url, ahora_iso(), sha, tamano, paginas, tipo, "descarga")
        if tamano > ajustes["aviso_tamano_mb"] * 1024 * 1024:
            print(f"  AVISO: {destino.name} pesa {tamano / 1048576:.1f} MB (> {ajustes['aviso_tamano_mb']} MB). GitHub rechaza "
                  f"archivos de más de 100 MB: usa Git LFS (git lfs track \"*.pdf\") o excluye el archivo y documenta cómo obtenerlo.")
        return "descargado"
    finally:
        parcial.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Descarga los PDFs oficiales y escribe MANIFEST.json.")
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG_POR_DEFECTO)
    ap.add_argument("--solo", metavar="ID", action="append", help="limitar a estos documentos (repetible)")
    ap.add_argument("--forzar", action="store_true", help="volver a bajar aunque el archivo ya exista")
    ap.add_argument("--aceptar-cambio", action="store_true", help="permitir que la fuente haya cambiado desde la descarga registrada")
    args = ap.parse_args(argv)

    try:
        cfg = cargar_config(args.config, cargar_env=False)
        docs = cfg.documentos
        if args.solo:
            docs = [cfg.documento(i) for i in args.solo]
    except ConfigError as exc:
        print(f"ERROR de configuración: {exc}", file=sys.stderr)
        return 1

    raw, ruta_manifiesto = cfg.ruta("raw"), cfg.ruta("manifest")
    ajustes = cfg.get("descarga")
    manifiesto = cargar_manifiesto(ruta_manifiesto)
    foto_inicial = json.dumps(manifiesto, sort_keys=True)
    conteo: dict[str, int] = {}
    errores = 0
    t0 = time.time()

    for doc in docs:
        try:
            estado = procesar_documento(doc, raw, manifiesto, ajustes, args.forzar, args.aceptar_cambio)
        except ErrorDescarga as exc:
            errores += 1
            print(f"  ERROR  {doc['id']}: {exc}", file=sys.stderr)
            continue
        e = manifiesto["documentos"][doc["id"]]
        conteo[estado] = conteo.get(estado, 0) + 1
        print(f"  {estado:18s} {doc['id']:16s} {e['paginas']:>4d} págs  {e['bytes'] / 1048576:7.2f} MB  sha256={e['sha256'][:12]}…")

    orden = [d["id"] for d in cfg.documentos]
    manifiesto["documentos"] = {k: manifiesto["documentos"][k] for k in orden if k in manifiesto["documentos"]}
    if not ruta_manifiesto.is_file() or json.dumps(manifiesto, sort_keys=True) != foto_inicial:
        manifiesto["actualizado"] = ahora_iso()  # solo si algo cambió: una corrida sin novedades no toca el archivo
        escribir_json_atomico(ruta_manifiesto, manifiesto)

    resumen = ", ".join(f"{k}={v}" for k, v in sorted(conteo.items())) or "nada que hacer"
    print(f"Resumen: {resumen}, errores={errores} ({time.time() - t0:.1f} s). Manifiesto: {ruta_manifiesto}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
