"""Fase 1a — Descarga masiva de los archivos mensuales CSV de SEACE V3.0 (OCDS).

Uso:
    python src/acquisition_bulk.py            # descarga los meses de config.yaml → bulk.months
    python src/acquisition_bulk.py --force    # vuelve a descargar aunque ya existan

Qué hace, por cada mes:
1. Si el ZIP ya existe en data/raw/ y está íntegro, NO lo vuelve a descargar.
2. Si no existe, lo descarga en streaming a un archivo temporal ".part" y solo al terminar lo renombra
   (así una descarga cortada nunca deja un ZIP "a medias" que parezca válido).
3. Verifica la integridad: bytes recibidos = Content-Length y CRC de cada CSV del ZIP.
   (El SHA-256 que publica OECE es el del JSON descomprimido, no el del ZIP CSV; guardamos
   nuestro propio SHA-256 en el log para que el equipo pueda comprobar que usa el mismo archivo.)
4. Descomprime los CSV en data/raw/extracted/YYYY-MM/.
5. Registra en logs/descargas.jsonl: fecha, mes, URL, tamaño, tiempo, velocidad, SHA-256, estado.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
import zipfile
from pathlib import Path

import requests

from common import get_logger, load_config, log_event, path

log = get_logger("acquisition_bulk")


def build_url(cfg: dict, fmt: str, year: str, month: str) -> str:
    src = cfg["source"]
    return src["file_url_template"].format(
        base_url=src["base_url"], system=src["system"], fmt=fmt, year=year, month=month
    )


def sha256_of(file: Path) -> str:
    h = hashlib.sha256()
    with open(file, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def zip_is_valid(file: Path) -> bool:
    """True si el ZIP se abre y el CRC de cada archivo interno es correcto (detecta descargas cortadas o corruptas)."""
    try:
        with zipfile.ZipFile(file) as z:
            return z.testzip() is None
    except zipfile.BadZipFile:
        return False


def download_month(cfg: dict, ym: str, force: bool) -> dict:
    year, month = ym.split("-")
    bulk = cfg["bulk"]
    fmt = bulk["format"]
    url = build_url(cfg, fmt, year, month)
    target = path(f"{cfg['paths']['raw']}/{ym}_{cfg['source']['system']}_{fmt}.zip")

    # 1) ¿Ya lo tenemos? Si existe y es un ZIP íntegro, no se vuelve a descargar.
    if target.exists() and not force:
        if not bulk["verify_zip"] or zip_is_valid(target):
            info = dict(month=ym, url=url, file=target.name, status="skipped_exists",
                        size_bytes=target.stat().st_size, seconds=0.0)
            log.info("%s ya existe (%.1f MB): no se re-descarga", target.name, target.stat().st_size / 1e6)
            log_event(bulk["download_log"], **info)
            return info
        log.warning("%s existe pero está corrupto: se re-descarga", target.name)

    # 2) Descarga en streaming a .part
    part = target.with_suffix(target.suffix + ".part")
    t0 = time.perf_counter()
    try:
        with requests.get(url, stream=True, timeout=bulk["timeout_seconds"]) as r:
            r.raise_for_status()
            announced = int(r.headers.get("Content-Length", 0)) or None
            server_last_modified = r.headers.get("Last-Modified")
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=bulk["chunk_bytes"]):
                    f.write(chunk)
    except requests.RequestException as e:
        part.unlink(missing_ok=True)
        info = dict(month=ym, url=url, file=target.name, status="error", error=str(e),
                    seconds=round(time.perf_counter() - t0, 2))
        log.error("Falló la descarga de %s: %s", ym, e)
        log_event(bulk["download_log"], **info)
        return info
    seconds = time.perf_counter() - t0
    size = part.stat().st_size

    # 3) Verificación de integridad: tamaño anunciado por el servidor + CRC del ZIP
    if bulk["verify_zip"]:
        problems = []
        if announced is not None and size != announced:
            problems.append(f"tamaño {size} != Content-Length {announced}")
        if not zip_is_valid(part):
            problems.append("ZIP corrupto (CRC)")
        if problems:
            part.unlink()
            info = dict(month=ym, url=url, file=target.name, status="error_integrity",
                        error="; ".join(problems), seconds=round(seconds, 2))
            log.error("Descarga de %s descartada: %s", ym, "; ".join(problems))
            log_event(bulk["download_log"], **info)
            return info
    part.replace(target)

    info = dict(month=ym, url=url, file=target.name, status="downloaded", size_bytes=size,
                seconds=round(seconds, 2), mb_per_s=round(size / 1e6 / max(seconds, 1e-9), 2),
                sha256=sha256_of(target), server_last_modified=server_last_modified,
                integrity_verified=bulk["verify_zip"])
    log.info("Descargado %s: %.1f MB en %.1f s (%.2f MB/s)", target.name, size / 1e6, seconds, info["mb_per_s"])
    log_event(bulk["download_log"], **info)
    return info


def extract_month(cfg: dict, ym: str) -> list[str]:
    zip_path = path(f"{cfg['paths']['raw']}/{ym}_{cfg['source']['system']}_{cfg['bulk']['format']}.zip")
    out_dir = path(f"{cfg['paths']['raw_extracted']}/{ym}/x").parent
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        missing = [n for n in names if not (out_dir / n).exists()]
        if missing:
            z.extractall(out_dir, members=missing)
    log.info("%s: %d archivos en %s", ym, len(names), out_dir.relative_to(path(".").parent))
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-descargar aunque el archivo exista")
    args = parser.parse_args()

    cfg = load_config()
    results = []
    for ym in cfg["bulk"]["months"]:
        info = download_month(cfg, ym, args.force)
        if info["status"] in ("downloaded", "skipped_exists"):
            info["files_in_zip"] = extract_month(cfg, ym)
        results.append(info)

    ok = [r for r in results if r["status"] in ("downloaded", "skipped_exists")]
    log.info("Resumen: %d/%d meses disponibles en data/raw/", len(ok), len(results))
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
