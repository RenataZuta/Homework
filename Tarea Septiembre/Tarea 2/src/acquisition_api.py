"""Fase 1b — Cliente de la API OCDS de OECE (/api/v1/records y /api/v1/record/{ocid}).

Uso:
    python src/acquisition_api.py --pages               # recorre api.max_pages páginas de /records
    python src/acquisition_api.py --ocid ocds-dgv273-seacev3-1234567 [--ocid ...]
    python src/acquisition_api.py --pages --no-cache    # ignora la caché (vuelve a pedir todo)

Tres protecciones, todas configurables en config.yaml → api:
1. Rate limiting: nunca más de 1 petición cada `min_seconds_between_requests` (no saturar un servidor público).
2. Reintentos: si hay error de red o el servidor responde 429/5xx, espera 2, 4, 8, 16... s y reintenta
   (espera exponencial). Si el servidor manda "Retry-After", se respeta ese tiempo.
   Un 404 u otro 4xx NO se reintenta: repetir no lo va a arreglar.
3. Caché en disco: cada respuesta exitosa se guarda en data/raw/api_cache/<clave>.json ANTES de seguir.
   Si el proceso se cae en la página 47, al relanzarlo las 46 primeras salen de la caché al instante
   y se continúa desde la 47: no se pierde trabajo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

from common import get_logger, load_config, log_event, path

log = get_logger("acquisition_api")

# Nombre de los archivos de caché: parte legible (recortada) + hash corto del URL completo.
# Son detalles internos de nombrado (no cambian ningún resultado), por eso son constantes y no config.
CACHE_NAME_MAX_CHARS = 80
CACHE_HASH_CHARS = 10


class OCDSApiClient:
    def __init__(self, cfg: dict, use_cache: bool = True):
        self.cfg = cfg
        self.api = cfg["api"]
        self.use_cache = use_cache
        self.cache_dir = path(f"{cfg['paths']['api_cache']}/x").parent
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.api["user_agent"]
        self._last_request = 0.0
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0, "errors": 0}

    # ── caché ────────────────────────────────────────────────────────────────
    def _cache_file(self, url: str, params: dict | None) -> Path:
        key = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())) if params else "")
        # nombre legible + hash corto (evita caracteres inválidos en Windows y colisiones)
        readable = re.sub(r"[^A-Za-z0-9]+", "_", key.split("/api/v1/")[-1])[:CACHE_NAME_MAX_CHARS]
        return self.cache_dir / f"{readable}_{hashlib.sha1(key.encode()).hexdigest()[:CACHE_HASH_CHARS]}.json"

    # ── rate limiting ────────────────────────────────────────────────────────
    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.api["min_seconds_between_requests"] - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    # ── petición con reintentos ──────────────────────────────────────────────
    def get_json(self, url: str, params: dict | None = None) -> dict:
        cache = self._cache_file(url, params)
        if self.use_cache and cache.exists():
            self.stats["cache_hits"] += 1
            return json.loads(cache.read_text(encoding="utf-8"))

        last_error = None
        for attempt in range(self.api["max_retries"] + 1):
            self._wait_turn()
            t0 = time.perf_counter()
            status = None
            try:
                self.stats["requests"] += 1
                r = self.session.get(url, params=params, timeout=self.api["timeout_seconds"])
                status = r.status_code
                seconds = round(time.perf_counter() - t0, 2)
                log_event(self.api["request_log"], url=r.url, status=status, attempt=attempt + 1,
                          size_bytes=len(r.content), seconds=seconds)
                if status == 200:
                    data = r.json()
                    tmp = cache.with_suffix(".tmp")  # escritura atómica: .tmp y luego renombrar
                    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(cache)
                    return data
                if status not in self.api["retry_on_status"]:
                    self.stats["errors"] += 1
                    raise requests.HTTPError(f"HTTP {status} (no reintentable) en {r.url}", response=r)
                last_error = f"HTTP {status}"
                retry_after = r.headers.get("Retry-After")
            except (requests.ConnectionError, requests.Timeout, ValueError) as e:
                # ValueError = el servidor respondió 200 pero con JSON roto/cortado
                last_error = f"{type(e).__name__}: {e}"
                retry_after = None
                log_event(self.api["request_log"], url=url, params=params, status=status,
                          attempt=attempt + 1, error=last_error)

            if attempt == self.api["max_retries"]:
                break
            wait = float(retry_after) if retry_after and retry_after.isdigit() else \
                self.api["backoff_base_seconds"] * 2 ** attempt
            self.stats["retries"] += 1
            log.warning("Intento %d falló (%s). Reintento en %.1f s…", attempt + 1, last_error, wait)
            time.sleep(wait)

        self.stats["errors"] += 1
        raise RuntimeError(f"Se agotaron {self.api['max_retries']} reintentos para {url}: {last_error}")

    # ── endpoints ────────────────────────────────────────────────────────────
    def iter_record_pages(self, max_pages: int):
        """Recorre /records siguiendo `links.next` (paginación OCDS). Devuelve (n_página, lista de records)."""
        src = self.cfg["source"]
        url = src["records_url"].format(base_url=src["base_url"])
        params = {"page": 1, "paginateBy": self.api["page_size"]}
        for page in range(1, max_pages + 1):
            params["page"] = page
            data = self.get_json(url, dict(params))
            yield page, data.get("records", [])
            if not (data.get("links") or {}).get("next"):
                break

    def get_record(self, ocid: str) -> dict:
        src = self.cfg["source"]
        return self.get_json(src["record_by_ocid_url"].format(base_url=src["base_url"], ocid=ocid))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages", action="store_true", help="recorrer /records (hasta api.max_pages)")
    parser.add_argument("--ocid", action="append", default=[], help="descargar un record por su ocid")
    parser.add_argument("--no-cache", action="store_true", help="ignorar la caché y volver a pedir")
    args = parser.parse_args()
    if not args.pages and not args.ocid:
        parser.error("indica --pages y/o --ocid")

    cfg = load_config()
    client = OCDSApiClient(cfg, use_cache=not args.no_cache)
    t0 = time.perf_counter()
    page_records, ocid_records, failed = [], [], []

    try:
        if args.pages:
            for page, recs in client.iter_record_pages(cfg["api"]["max_pages"]):
                log.info("Página %d: %d records", page, len(recs))
                page_records.extend(recs)
        for ocid in args.ocid:
            try:
                data = client.get_record(ocid)
            except requests.HTTPError as e:  # p. ej. 404: ese ocid no existe; seguimos con los demás
                log.error("ocid %s omitido: %s", ocid, e)
                failed.append(ocid)
                continue
            recs = data.get("records", [data])
            log.info("ocid %s: %d record(s), %d releases", ocid, len(recs),
                     sum(len(r.get("releases", [])) for r in recs))
            ocid_records.extend(recs)
    except RuntimeError as e:
        log.error("%s", e)
        log.error("Lo ya descargado quedó en la caché: relanza el mismo comando para continuar.")
        return 1

    # --pages y --ocid se guardan por separado: la validación usa la muestra de páginas, y un --ocid suelto
    # no debe sobrescribirla.
    for recs, out in ((page_records, cfg["api"]["pages_output"]), (ocid_records, cfg["api"]["ocid_output"])):
        if recs:
            with open(path(out), "w", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            log.info("Guardados %d records en %s", len(recs), out)
    log.info("Resumen | peticiones=%d, desde caché=%d, reintentos=%d, errores=%d | %.1f s", client.stats["requests"], client.stats["cache_hits"],
             client.stats["retries"], client.stats["errors"], time.perf_counter() - t0)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
