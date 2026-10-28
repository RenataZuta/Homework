"""Extracción por reglas y validación aritmética sobre las transcripciones de la escalera de degradación, por nivel.

Lee `tasks/task2_sales/transcriptions_cache/{clip}@{nivel}__{modelo}_{precisión}_{dispositivo}_{gloss}.json` (sin ASR),
corre `process_audio(..., transcript=...)` con el extractor por reglas y puntúa contra el ground truth. Para cada
transcripción guarda la exactitud por campo, la aritmética del pedido (total esperado vs. dicho) y su diagnóstico:
  - `diagnostico`: por transcripción (¿las cifras usadas aparecen en el texto?), ver validator.validate_order_arithmetic;
  - `diagnostico_gt`: contra el ground truth (¿el registro difiere de lo realmente dicho?).

Salidas en --out-dir (con el prefijo --prefix): {prefix}_detail.csv (campo por campo), {prefix}_summary.csv (exactitud
media por modelo × nivel) y {prefix}_validation.csv (aritmética por transcripción).

Uso:  python -m engine.evaluate_ladder --levels L0 L1 L2 L3 --prefix l0_l3
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from . import load_config, task_dir
from .benchmark import field_accuracy, load_ground_truth
from .core import process_audio
from .validator import validate_order_arithmetic


def evaluar(config, levels, cache_dir=None, task="task2_sales"):
    """Devuelve (detalle, validacion): DataFrames con una fila por campo y por transcripción respectivamente."""
    cache_dir = Path(cache_dir) if cache_dir else task_dir(config, task, "transcriptions_cache")
    gt = load_ground_truth(config, task)
    detalle, validacion = [], []
    for ruta in sorted(cache_dir.glob("*@*.json")):
        d = json.loads(ruta.read_text(encoding="utf-8"))
        nivel = ruta.name.split("@")[1].split("__")[0]
        if nivel not in levels or d["clip"] not in gt:
            continue
        clip, base = d["clip"], {"clip": d["clip"], "level": nivel, "model": d["model"], "compute_type": d["compute_type"]}
        r = process_audio(None, "sales", config_path=config["_path"], extractor="rules", transcript=d["transcript"])
        if r["error"]:
            raise RuntimeError(f"{ruta.name}: {r['error']}")
        acc = field_accuracy(config, task, clip, r["fields"], gt)
        for campo, valor in r["fields"].items():
            detalle.append({**base, "campo": campo, "correcto": acc.get(campo), "valor": json.dumps(valor, ensure_ascii=False),
                            "verificacion": r["verified_fields"][campo]})
        a = r["diagnostics"]["arithmetic"]
        fila_gt = gt[clip]
        con_gt = validate_order_arithmetic(r["fields"], ground_truth={"items": json.loads(fila_gt["items_json"]),
                                                                      "total_dicho": fila_gt["total_dicho"]})
        incorrecto = fila_gt["total_es_incorrecto"] == "Sí"
        validacion.append({**base, "total_dicho": a["total_dicho"], "total_esperado": a["expected_total"],
                           "aritmetica": a["status"], "diagnostico": a["diagnosis"], "diagnostico_gt": con_gt["diagnosis"],
                           "gt_total_incorrecto": incorrecto,
                           "detecta_bien": (a["status"] == "discrepancia") == incorrecto if a["status"] != "incompleto" else None})
    return pd.DataFrame(detalle), pd.DataFrame(validacion)


def resumen(detalle, validacion):
    """Exactitud media por campo y aritmética por modelo × nivel."""
    exactitud = detalle.pivot_table(index=["model", "level"], columns="campo", values="correcto", aggfunc="mean")
    exactitud["todos_los_campos"] = detalle.groupby(["model", "level"])["correcto"].mean()
    aritmetica = validacion.groupby(["model", "level"]).agg(
        total_ok=("aritmetica", lambda s: int((s == "ok").sum())), discrepancias=("aritmetica", lambda s: int((s == "discrepancia").sum())),
        incompletos=("aritmetica", lambda s: int((s == "incompleto").sum())), detecta_bien=("detecta_bien", "sum"),
        n=("clip", "count"))
    return exactitud.join(aritmetica).reset_index()


def main(argv=None):
    p = argparse.ArgumentParser(description="Extracción y validación aritmética por nivel de la escalera de degradación")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--levels", nargs="+", required=True, help="niveles de la escalera, p. ej. L0 L1 L2 L3")
    p.add_argument("--cache-dir", help="carpeta con las transcripciones (por defecto, la caché de ventas)")
    p.add_argument("--out-dir", help="carpeta de salida (por defecto tasks/task2_sales/metrics)")
    p.add_argument("--prefix", default="ladder_levels", help="prefijo de los CSV de salida")
    a = p.parse_args(argv)
    config = load_config(a.config)
    config["_path"] = a.config
    detalle, validacion = evaluar(config, a.levels, a.cache_dir)
    if detalle.empty:
        raise SystemExit(f"No hay transcripciones de los niveles {a.levels} en la caché")
    out = Path(a.out_dir) if a.out_dir else task_dir(config, "task2_sales", "metrics")
    out.mkdir(parents=True, exist_ok=True)
    resumen_df = resumen(detalle, validacion)
    for nombre, df in (("detail", detalle), ("summary", resumen_df.round(3)), ("validation", validacion)):
        df.to_csv(out / f"{a.prefix}_{nombre}.csv", index=False, encoding="utf-8")
    pd.set_option("display.width", 220)
    print(resumen_df.round(2).to_string(index=False))
    print(f"\nCSV en {out}: {a.prefix}_detail / _summary / _validation")


if __name__ == "__main__":
    main()
