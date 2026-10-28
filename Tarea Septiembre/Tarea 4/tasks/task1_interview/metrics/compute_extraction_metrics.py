"""Métricas de extracción de las entrevistas en dos capas: transcripción (WER, CER) y registro (campos).

Compara los campos extraídos por cada camino (reglas y, opcionalmente, LLM) contra el ground truth y calcula:
  - por campo: accuracy; para los numéricos (anios_experiencia, pretension_salarial) además el error absoluto medio (MAE)
    sobre los clips con valor; para los categóricos (ultimo_puesto, tecnologias, disponibilidad, nivel_ingles) la
    accuracy es de coincidencia exacta (tecnologias: mismo conjunto de herramientas);
  - macro F1 de nivel_ingles (Básico / Intermedio / Avanzado; un campo sin valor cuenta como error del nivel verdadero);
  - la tabla de dos capas por clip y global: capa transcripción (WER, WER con números normalizados, CER, tomados de
    benchmark_detail.csv) y capa registro (campos correctos y accuracy por campo);
  - los contrastes para el video (sobre todas las transcripciones cacheadas, con el extractor por reglas):
      A) el clip con WER más alto entre los de registro perfecto (WER alto, registro perfecto);
      B) el clip con peor registro entre los de WER bajo, es decir, por debajo de la mediana (WER bajo, registro roto).

Qué transcripciones se usan: la tabla de dos capas usa UNA configuración de ASR (por defecto la de menor WER del
benchmark; se puede fijar con --model/--compute-type/--device/--glossary), porque así cada clip aparece una vez. Los
contrastes recorren todas las configuraciones cacheadas (clip × modelo × precisión × glosario), que dan más casos.

Camino LLM (--llm): none (por defecto) | answers (respuestas simuladas de un JSON; NO miden a ningún modelo) | api (API de
Anthropic, de pago: ANTHROPIC_API_KEY y --confirm-api; una llamada por clip).

Uso (desde cualquier carpeta):
  python tasks/task1_interview/metrics/compute_extraction_metrics.py
  python tasks/task1_interview/metrics/compute_extraction_metrics.py --llm answers
Salida (junto a este script): extraction_metrics_by_field.csv, extraction_metrics_two_layer_by_clip.csv,
extraction_metrics_two_layer_summary.csv y extraction_metrics_contrasts.csv.
"""
import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]  # carpeta de la Tarea 4
sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402

from engine import load_config, task_dir  # noqa: E402
from engine.benchmark import field_accuracy, load_ground_truth  # noqa: E402
from engine.compare_extractors import ClienteSimulado  # noqa: E402
from engine.core import process_audio  # noqa: E402

TASK, SCHEMA = "task1_interview", "interview"
CAMPOS = ["anios_experiencia", "ultimo_puesto", "tecnologias", "pretension_salarial", "disponibilidad", "nivel_ingles"]
NUMERICOS = ["anios_experiencia", "pretension_salarial"]
NIVELES_INGLES = ["Básico", "Intermedio", "Avanzado"]
SALIDA = Path(__file__).resolve().parent


def cargar_transcripciones(config):
    """Todas las transcripciones cacheadas de las entrevistas, con su configuración de ASR."""
    filas = []
    for ruta in sorted(task_dir(config, TASK, "transcriptions_cache").glob("*.json")):
        d = json.loads(ruta.read_text(encoding="utf-8"))
        filas.append({"clip": d["clip"], "model": d["model"], "compute_type": d["compute_type"],
                      "device": d["device_requested"], "glossary": "on" if d["glossary"] else "off",
                      "transcript": d["transcript"]})
    return pd.DataFrame(filas).drop_duplicates(["clip", "model", "compute_type", "device", "glossary"])


def cargar_capa_transcripcion(config):
    """WER/CER por clip y configuración (benchmark_detail.csv)."""
    d = pd.read_csv(task_dir(config, TASK, "metrics") / "benchmark_detail.csv")
    d = d.rename(columns={"glossary": "glossary"})
    return d[["clip", "model", "compute_type", "device", "glossary", "wer", "wer_numnorm", "cer", "w_err", "w_n"]]


def configuracion_principal(config, args):
    """(model, compute_type, device, glossary) de la tabla de dos capas: la indicada o la de menor WER normalizado."""
    if args.model:
        return args.model, args.compute_type or "float16", args.device or "cuda", args.glossary or "off"
    s = pd.read_csv(task_dir(config, TASK, "metrics") / "benchmark_summary.csv")
    m = s[s["task"] == TASK].sort_values("wer_numnorm").iloc[0]
    return m["model"], m["compute_type"], m["device"], m["glossary"]


def extraer(config, extractor, transcript, cliente=None):
    r = process_audio(None, SCHEMA, config_path=str(RAIZ / "config.yaml"), extractor=extractor, transcript=transcript,
                      llm_client=cliente)
    if r["error"]:
        raise SystemExit(f"error ({extractor}): {r['error']}")
    return r["fields"]


# ── Métricas ──────────────────────────────────────────────────────────────────

def _valor_num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def macro_f1(verdad, prediccion, clases=NIVELES_INGLES):
    """Macro F1 sobre las clases con soporte en `verdad`. Una predicción vacía no es de ninguna clase (falso negativo)."""
    f1s = {}
    for c in clases:
        soporte = sum(v == c for v in verdad)
        if soporte == 0:
            continue
        tp = sum(v == c and p == c for v, p in zip(verdad, prediccion))
        fp = sum(v != c and p == c for v, p in zip(verdad, prediccion))
        fn = soporte - tp
        f1s[c] = 0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn)
    return (sum(f1s.values()) / len(f1s) if f1s else float("nan")), f1s


def metricas_por_campo(filas, gt):
    """DataFrame por extractor y campo: accuracy, MAE (numéricos), n_sin_valor y, en nivel_ingles, el macro F1."""
    res = []
    for extractor, g in filas.groupby("extractor"):
        for campo in CAMPOS:
            ok = g[f"ok_{campo}"].astype(bool)
            fila = {"extractor": extractor, "campo": campo, "tipo": "numérico" if campo in NUMERICOS else "categórico",
                    "n": len(g), "accuracy": ok.mean(), "mae": None, "f1_macro": None, "n_sin_valor": int(g[f"val_{campo}"].isna().sum())}
            if campo in NUMERICOS:
                errores = [abs(_valor_num(v) - float(gt[c][campo])) for v, c in zip(g[f"val_{campo}"], g["clip"])
                           if _valor_num(v) is not None]
                fila["mae"] = sum(errores) / len(errores) if errores else None
            if campo == "nivel_ingles":
                verdad = [gt[c]["nivel_ingles"] for c in g["clip"]]
                fila["f1_macro"], _ = macro_f1(verdad, [v if isinstance(v, str) else None for v in g["val_nivel_ingles"]])
            res.append(fila)
    return pd.DataFrame(res)


def filas_de_registro(config, transcripciones, extractor, gt, cliente=None):
    """Una fila por transcripción: campos extraídos, aciertos por campo y total."""
    filas = []
    for t in transcripciones.to_dict("records"):
        if cliente is not None:
            cliente.clip = t["clip"]
        campos = extraer(config, extractor, t["transcript"], cliente)
        acc = field_accuracy(config, TASK, t["clip"], campos, gt)
        fila = {k: t[k] for k in ("clip", "model", "compute_type", "device", "glossary")}
        fila["extractor"] = extractor
        for c in CAMPOS:
            fila[f"val_{c}"] = campos.get(c)
            fila[f"ok_{c}"] = bool(acc[c])
        fila["campos_correctos"] = sum(bool(acc[c]) for c in CAMPOS)
        fila["registro_accuracy"] = fila["campos_correctos"] / len(CAMPOS)
        filas.append(fila)
    return pd.DataFrame(filas)


# ── Contrastes para el video ──────────────────────────────────────────────────

def buscar_contrastes(registro, wer_col="wer_numnorm"):
    """(A) WER más alto con registro perfecto y (B) peor registro con WER bajo (≤ mediana). Devuelve lista de dicts."""
    mediana = registro[wer_col].median()
    salida = []
    perfectos = registro[registro["campos_correctos"] == len(CAMPOS)]
    if len(perfectos):
        a = perfectos.sort_values(wer_col, ascending=False).iloc[0]
        salida.append(("A: WER alto, registro perfecto", a, a[wer_col] > mediana))
    bajos = registro[registro[wer_col] <= mediana]
    b = bajos.sort_values(["campos_correctos", wer_col]).iloc[0]
    salida.append(("B: WER bajo, registro roto", b, b["campos_correctos"] < len(CAMPOS)))
    return salida, mediana


def describir(etiqueta, fila, genuino, gt, wer_col):
    clip = fila["clip"]
    malos = [c for c in CAMPOS if not fila[f"ok_{c}"]]
    detalle = [{"campo": c, "extraido": fila[f"val_{c}"], "esperado": gt[clip][c]} for c in malos]
    return {"contraste": etiqueta, "clip": clip, "model": fila["model"], "compute_type": fila["compute_type"],
            "glossary": fila["glossary"], wer_col: round(fila[wer_col], 3), "wer": round(fila["wer"], 3),
            "cer": round(fila["cer"], 3), "palabras_erradas": f"{int(fila['w_err'])}/{int(fila['w_n'])}",
            "campos_correctos": f"{fila['campos_correctos']}/{len(CAMPOS)}", "campos_fallidos": json.dumps(detalle, ensure_ascii=False),
            "contraste_genuino": bool(genuino)}


# ── Programa principal ────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description="Métricas de extracción de entrevistas en dos capas (transcripción y registro)")
    p.add_argument("--llm", choices=["none", "answers", "api"], default="none")
    p.add_argument("--answers", default=str(RAIZ / "tasks/comparison/llm_answers_simulado.json"), help="JSON para --llm answers")
    p.add_argument("--confirm-api", action="store_true", help="confirma el uso de la API de pago (--llm api)")
    p.add_argument("--model")
    p.add_argument("--compute-type")
    p.add_argument("--device")
    p.add_argument("--glossary", choices=["on", "off"])
    p.add_argument("--wer-col", choices=["wer", "wer_numnorm"], default="wer_numnorm", help="WER usado para los contrastes")
    p.add_argument("--out-dir", type=Path, default=SALIDA)
    a = p.parse_args(argv)

    config = load_config(str(RAIZ / "config.yaml"))
    gt = load_ground_truth(config, TASK)
    todas = cargar_transcripciones(config)
    capa_t = cargar_capa_transcripcion(config)
    clave = ["clip", "model", "compute_type", "device", "glossary"]

    model, ct, dev, gl = configuracion_principal(config, a)
    principal = todas[(todas["model"] == model) & (todas["compute_type"] == ct) & (todas["device"] == dev) & (todas["glossary"] == gl)]
    if principal.empty:
        raise SystemExit(f"No hay transcripciones cacheadas para {model} {ct} {dev} glosario={gl}")
    print(f"Configuración de ASR de la tabla de dos capas: {model} {ct} {dev} glosario={gl} ({len(principal)} clips)\n")

    # (1) campos extraídos por cada camino
    filas = [filas_de_registro(config, principal, "rules", gt)]
    etiquetas = {"rules": "reglas"}
    if a.llm == "answers":
        cliente = ClienteSimulado(json.loads(Path(a.answers).read_text(encoding="utf-8")))
        filas.append(filas_de_registro(config, principal, "llm", gt, cliente))
        filas[-1]["extractor"] = "llm (SIMULADO)"
        print("⚠️  Respuestas LLM SIMULADAS: no miden a ningún modelo (escritas a mano viendo el ground truth).\n")
    elif a.llm == "api":
        if not a.confirm_api:
            p.error(f"--llm api usa la API de pago de Anthropic ({len(principal)} llamadas, {config['llm']['model']}); añade --confirm-api")
        filas.append(filas_de_registro(config, principal, "llm", gt))
        filas[-1]["extractor"] = "llm (API)"
    registro = pd.concat(filas, ignore_index=True)

    # (2) métricas por campo
    por_campo = metricas_por_campo(registro, gt)

    # (3) tabla de dos capas
    por_clip = registro.merge(capa_t, on=clave, how="left")
    columnas = ["extractor", "clip", "wer", "wer_numnorm", "cer", "campos_correctos", "registro_accuracy"] + [f"ok_{c}" for c in CAMPOS]
    por_clip = por_clip[columnas]
    resumen = []
    for ext, g in por_clip.groupby("extractor"):
        fila = {"extractor": ext, "n_clips": len(g), "wer": g["wer"].mean(), "wer_numnorm": g["wer_numnorm"].mean(), "cer": g["cer"].mean(),
                "registro_accuracy": g["registro_accuracy"].mean(), "clips_registro_perfecto": int((g["campos_correctos"] == len(CAMPOS)).sum())}
        for c in CAMPOS:
            fila[f"acc_{c}"] = g[f"ok_{c}"].mean()
        pc = por_campo[(por_campo["extractor"] == ext)]
        fila["f1_macro_nivel_ingles"] = pc[pc["campo"] == "nivel_ingles"]["f1_macro"].iloc[0]
        for c in NUMERICOS:
            fila[f"mae_{c}"] = pc[pc["campo"] == c]["mae"].iloc[0]
        resumen.append(fila)
    resumen = pd.DataFrame(resumen)

    # (4) contrastes sobre todas las configuraciones (reglas)
    todos_reg = filas_de_registro(config, todas, "rules", gt).merge(capa_t, on=clave, how="inner")
    contrastes, mediana = buscar_contrastes(todos_reg, a.wer_col)
    filas_c = [describir(e, f, g, gt, a.wer_col) for e, f, g in contrastes]

    a.out_dir.mkdir(parents=True, exist_ok=True)
    por_campo.round(4).to_csv(a.out_dir / "extraction_metrics_by_field.csv", index=False, encoding="utf-8")
    por_clip.round(4).to_csv(a.out_dir / "extraction_metrics_two_layer_by_clip.csv", index=False, encoding="utf-8")
    resumen.round(4).to_csv(a.out_dir / "extraction_metrics_two_layer_summary.csv", index=False, encoding="utf-8")
    pd.DataFrame(filas_c).to_csv(a.out_dir / "extraction_metrics_contrasts.csv", index=False, encoding="utf-8")

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    print("MÉTRICAS POR CAMPO (accuracy; MAE solo en los numéricos; f1_macro solo en nivel_ingles)")
    print(por_campo.round(3).to_string(index=False))
    print("\nTABLA DE DOS CAPAS, por clip  [capa transcripción: WER, WER con números normalizados, CER | capa registro: campos]")
    print(por_clip.round(3).to_string(index=False))
    print("\nTABLA DE DOS CAPAS, global")
    print(resumen.round(3).T.to_string(header=False))
    print(f"\nCONTRASTES PARA EL VIDEO  (sobre {len(todos_reg)} transcripciones; mediana de {a.wer_col} = {mediana:.3f}; extractor por reglas)")
    for f in filas_c:
        marca = "" if f["contraste_genuino"] else "   ⚠️ no es un contraste claro"
        print(f"\n  {f['contraste']}{marca}\n    {f['clip']} · {f['model']} {f['compute_type']} glosario={f['glossary']}"
              f"\n    {a.wer_col}={f[a.wer_col]} (WER={f['wer']}, CER={f['cer']}, palabras erradas {f['palabras_erradas']})"
              f" | registro {f['campos_correctos']} campos correctos")
        for d in json.loads(f["campos_fallidos"]):
            print(f"    ✗ {d['campo']}: extraído {d['extraido']!r}, esperado {d['esperado']!r}")
    print(f"\nCSV en {a.out_dir}")


if __name__ == "__main__":
    main()
