"""Paso 4 — OCR de los CVs con PaddleOCR 3.x (PP-OCRv5), un JSON por CV en data/ocr/{id}.json.

Cada JSON:
    {"id", "lines": [{"text", "confidence", "box": [x1, y1, x2, y2], "row"}],
     "full_text", "mean_confidence", "ocr_time_seconds", "image_size": [ancho, alto]}

``lines`` ya viene en orden de lectura (arriba→abajo; a la misma altura, izquierda→derecha). ``row`` es el
índice de la fila visual a la que pertenece cada caja; ``full_text`` une con espacio las cajas de una misma fila
y con salto de línea las filas.

El proceso es REANUDABLE (omite los CV que ya tienen JSON) y admite repartir el trabajo en procesos paralelos
con ``--shard k/n``.

Uso (desde Tarea 3/):
    python -m src.ocr_extraction                 # todos los CV de data/raw/metadata.csv
    python -m src.ocr_extraction --limit 5       # prueba rápida
    python -m src.ocr_extraction --shard 0/2     # primera mitad (lanzar también 1/2 en otra terminal)
    python -m src.ocr_extraction --report-only   # solo recalcula el reporte
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

import pandas as pd
from PIL import Image

from src import utils as U

# Evita la comprobación de conectividad de PaddleX en cada arranque (los modelos se cachean tras la 1ª descarga).
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

ROW_Y_THRESHOLD = 15  # px: dos cajas con |Δ y_centro| menor que esto se consideran de la misma fila


def build_ocr():
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def _field(result, key):
    """Lee un campo del resultado de predict() (objeto dict-like en 3.x)."""
    try:
        return result[key]
    except (KeyError, TypeError):
        return result.json["res"][key]


def reading_order(texts, scores, boxes, y_threshold: float = ROW_Y_THRESHOLD) -> list[dict]:
    """Ordena cajas de arriba a abajo; las que están a la misma altura (|Δy| < umbral) de izquierda a derecha.

    Se agrupa por el CENTRO vertical de cada caja: primero se ordena por ese centro y se abre una fila nueva cuando
    el centro dista del promedio de la fila actual más que ``y_threshold``. Dentro de cada fila se ordena por x.
    Esto recorre los layouts de dos columnas fila por fila (la regla pedida en el enunciado).
    """
    items = []
    for text, score, box in zip(texts, scores, boxes):
        x1, y1, x2, y2 = (int(v) for v in box)
        items.append({"text": text, "confidence": float(score), "box": [x1, y1, x2, y2],
                      "_yc": (y1 + y2) / 2})
    items.sort(key=lambda it: it["_yc"])

    rows: list[list[dict]] = []
    row_mean = 0.0
    for it in items:
        if rows and abs(it["_yc"] - row_mean) < y_threshold:
            rows[-1].append(it)
            row_mean = sum(x["_yc"] for x in rows[-1]) / len(rows[-1])
        else:
            rows.append([it])
            row_mean = it["_yc"]

    ordered = []
    for r_idx, row in enumerate(rows):
        for it in sorted(row, key=lambda x: x["box"][0]):
            ordered.append({"text": it["text"], "confidence": it["confidence"], "box": it["box"], "row": r_idx})
    return ordered


def lines_to_text(lines: list[dict]) -> str:
    """Une cajas de una misma fila con espacio y filas con salto de línea."""
    out: list[str] = []
    current, buf = None, []
    for ln in lines:
        if ln["row"] != current and buf:
            out.append(" ".join(buf))
            buf = []
        current = ln["row"]
        buf.append(ln["text"])
    if buf:
        out.append(" ".join(buf))
    return "\n".join(out)


def ocr_one(ocr, image_path: Path, y_threshold: float = ROW_Y_THRESHOLD) -> dict:
    with Image.open(image_path) as im:
        size = list(im.size)
    t0 = time.perf_counter()
    result = ocr.predict(str(image_path))[0]
    elapsed = time.perf_counter() - t0

    texts = list(_field(result, "rec_texts"))
    scores = list(_field(result, "rec_scores"))
    try:
        boxes = [list(b) for b in _field(result, "rec_boxes")]
    except Exception:  # sin detecciones: array vacío
        boxes = []
    n = min(len(texts), len(scores), len(boxes))
    lines = reading_order(texts[:n], scores[:n], boxes[:n], y_threshold)
    confs = [ln["confidence"] for ln in lines]
    return {
        "id": image_path.stem,
        "lines": lines,
        "full_text": lines_to_text(lines),
        "mean_confidence": float(sum(confs) / len(confs)) if confs else 0.0,
        "ocr_time_seconds": round(elapsed, 3),
        "image_size": size,
    }


def hardware_description() -> dict:
    info = {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version()}
    try:
        info["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
                                     timeout=5).stdout.strip() or platform.processor()
        mem = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout.strip()
        if mem:
            info["ram_gb"] = round(int(mem) / 1024 ** 3, 1)
    except Exception:
        info["cpu"] = platform.processor()
    info["cpu_count"] = os.cpu_count()
    try:
        import paddle
        info["paddle_version"] = paddle.__version__
        info["paddle_device"] = paddle.device.get_device()
        info["paddle_compiled_with_cuda"] = paddle.device.is_compiled_with_cuda()
    except Exception:
        pass
    try:
        import paddleocr
        info["paddleocr_version"] = paddleocr.__version__
    except Exception:
        pass
    return info


def build_report(expected_ids: list[str], ocr_dir: Path, failed: list[dict], wall_seconds: float | None) -> dict:
    times, confs, n_lines = [], [], []
    done_ids = set()
    for cv_id in expected_ids:
        p = ocr_dir / f"{cv_id}.json"
        if not p.exists():
            continue
        try:
            d = U.read_json(p)
        except json.JSONDecodeError:
            continue
        done_ids.add(cv_id)
        times.append(d["ocr_time_seconds"])
        confs.append(d["mean_confidence"])
        n_lines.append(len(d["lines"]))
    missing = [i for i in expected_ids if i not in done_ids]
    report = {
        "cvs_expected": len(expected_ids),
        "cvs_processed": len(done_ids),
        "cvs_failed_or_pending": len(missing),
        "failed_this_run": failed,
        "total_ocr_seconds": round(sum(times), 1),
        "mean_seconds_per_cv": round(statistics.fmean(times), 3) if times else None,
        "median_seconds_per_cv": round(statistics.median(times), 3) if times else None,
        "mean_confidence": round(statistics.fmean(confs), 4) if confs else None,
        "mean_lines_per_cv": round(statistics.fmean(n_lines), 1) if n_lines else None,
        "wall_seconds_this_run": round(wall_seconds, 1) if wall_seconds is not None else None,
        "hardware": hardware_description(),
        "row_y_threshold_px": ROW_Y_THRESHOLD,
    }
    return report


def print_report(r: dict) -> None:
    print("\n══ REPORTE OCR ══")
    print(f"CVs procesados: {r['cvs_processed']}/{r['cvs_expected']}  (fallidos/pendientes: {r['cvs_failed_or_pending']})")
    print(f"Tiempo total de OCR (suma de JSON): {r['total_ocr_seconds']} s  |  medio por CV: {r['mean_seconds_per_cv']} s  "
          f"|  mediana: {r['median_seconds_per_cv']} s")
    print(f"Confianza media: {r['mean_confidence']}  |  líneas medias por CV: {r['mean_lines_per_cv']}")
    print(f"Hardware: {r['hardware']}")
    if r["failed_this_run"]:
        print(f"Imágenes fallidas en esta corrida: {[f['id'] for f in r['failed_this_run']]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="procesar solo N CV (pruebas)")
    ap.add_argument("--shard", default=None, help="k/n: procesa solo los ids con índice %% n == k")
    ap.add_argument("--force", action="store_true", help="rehacer aunque ya exista el JSON")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--y-threshold", type=float, default=ROW_Y_THRESHOLD)
    args = ap.parse_args(argv)

    U.ensure_dirs()
    if U.METADATA_CSV.exists():
        ids = pd.read_csv(U.METADATA_CSV, dtype={"id": str})["id"].tolist()
    else:
        ids = sorted(p.stem for p in U.RAW_IMAGES_DIR.glob("*.png"))
    if not ids:
        print("ERROR: no hay CVs. Corre primero python -m src.download_data", file=sys.stderr)
        return 2

    my_ids = ids
    if args.shard:
        k, n = (int(x) for x in args.shard.split("/"))
        my_ids = [i for idx, i in enumerate(ids) if idx % n == k]
    todo = [i for i in my_ids if args.force or not (U.OCR_DIR / f"{i}.json").exists()]
    if args.limit:
        todo = todo[: args.limit]

    failed: list[dict] = []
    wall = None
    if todo and not args.report_only:
        print(f"OCR de {len(todo)} CV (de {len(my_ids)} asignados); cargando modelos...", flush=True)
        ocr = build_ocr()
        t_start = time.perf_counter()
        for n_done, cv_id in enumerate(todo, 1):
            img = U.RAW_IMAGES_DIR / f"{cv_id}.png"
            try:
                U.write_json_atomic(U.OCR_DIR / f"{cv_id}.json", ocr_one(ocr, img, args.y_threshold))
            except Exception as exc:  # una imagen mala no debe tumbar las 4000
                failed.append({"id": cv_id, "error": f"{type(exc).__name__}: {exc}"})
                traceback.print_exc()
            if n_done % 10 == 0 or n_done == len(todo):
                el = time.perf_counter() - t_start
                eta = el / n_done * (len(todo) - n_done)
                print(f"  {n_done}/{len(todo)}  {el / n_done:.1f} s/CV  ETA {eta / 60:.0f} min", flush=True)
        wall = time.perf_counter() - t_start

    report = build_report(ids, U.OCR_DIR, failed, wall)
    suffix = f"_shard{args.shard.replace('/', 'of')}" if args.shard and not args.report_only else ""
    with open(U.METRICS_DIR / f"ocr_report{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    if failed:
        pd.DataFrame(failed).to_csv(U.METRICS_DIR / f"ocr_failed{suffix}.csv", index=False)
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
