"""Compara el extractor por reglas con el extractor LLM sobre las transcripciones cacheadas, contra el ground truth.

No hace ASR: usa tasks/{task}/transcriptions_cache/ (la mejor configuración del benchmark, o la que se indique).
Para cada clip corre `process_audio(..., transcript=...)` con cada extractor y puntúa con `benchmark.field_accuracy`.

Origen de las respuestas del LLM (`--llm`):
  none     solo reglas (por defecto; sin API ni clave).
  api      API real de Anthropic: de PAGO, necesita ANTHROPIC_API_KEY (en .env) y el flag --confirm-api. Hace una llamada
           por transcripción; el número se muestra antes de empezar y `--max-calls` lo limita (por defecto 10).
  answers  respuestas LLM SIMULADAS leídas de un JSON {clip: {campo: valor}} (`--answers`). Pasan por el mismo
           LLMExtractor (prompt, parseo, verificación) pero NO miden a ningún modelo; sirve para probar el flujo sin clave.
           `tasks/comparison/llm_answers_simulado.json` es un ejemplo escrito a mano viendo el ground truth: sus
           aciertos son optimistas y no deben citarse como resultado del LLM.

Uso:  python -m engine.compare_extractors
      python -m engine.compare_extractors --llm answers --answers tasks/comparison/llm_answers_simulado.json
      python -m engine.compare_extractors --llm api --confirm-api [--max-calls 10]
Salida: tabla por campo y lista de fallos; `--out CSV` guarda el detalle por campo y clip.
"""
import argparse
import json
import types
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import load_config, task_dir
from .benchmark import field_accuracy, load_ground_truth
from .core import process_audio

ESQUEMAS = {"task1_interview": "interview", "task2_sales": "sales"}


def mejor_configuracion(config, task):
    """Fila de benchmark_summary.csv con menor wer_numnorm (la misma que usa el notebook full_pipeline)."""
    s = pd.read_csv(task_dir(config, task, "metrics") / "benchmark_summary.csv")
    return s[s["task"] == task].sort_values("wer_numnorm").iloc[0]


def cargar_transcripciones(config, task, model=None, compute_type=None, device=None, glossary=None):
    """{clip: transcripción} de la caché para una configuración ASR (por defecto la mejor del benchmark)."""
    if model is None:
        m = mejor_configuracion(config, task)
        model, compute_type, device, glossary = m["model"], m["compute_type"], m["device"], m["glossary"]
    sufijo = "gloss" if glossary == "on" else "nogloss"
    patron = f"*__{model}_{compute_type}_{device}_{sufijo}.json"
    # los archivos con "@" son de la escalera de degradación; aquí solo se usa el audio original
    archivos = [p for p in sorted(task_dir(config, task, "transcriptions_cache").glob(patron)) if "@" not in p.name]
    datos = [json.loads(p.read_text(encoding="utf-8")) for p in archivos]
    return {d["clip"]: d["transcript"] for d in datos}, f"{model} {compute_type} {device} glosario={glossary}"


class ClienteSimulado:
    """Imita client.beta.messages.create / client.messages.create devolviendo respuestas JSON ya escritas."""

    def __init__(self, respuestas):
        self.respuestas, self.clip, self.llamadas = respuestas, None, []
        self.messages = self.beta = types.SimpleNamespace(create=self.create)
        self.beta.messages = self

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        texto = "```json\n" + json.dumps(self.respuestas[self.clip], ensure_ascii=False) + "\n```"
        return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=texto)])


def comparar(config, extractores, cliente_llm=None, tasks=None, config_path="config.yaml", **asr):
    """Devuelve (detalle, fallos). detalle: filas {task, clip, extractor, campo, correcto, valor, verificacion}."""
    detalle, fallos, configs = [], [], {}
    for task in tasks or ESQUEMAS:
        schema = ESQUEMAS[task]
        textos, configs[task] = cargar_transcripciones(config, task, **asr)
        gt = load_ground_truth(config, task)
        for clip, texto in textos.items():
            if cliente_llm is not None:
                cliente_llm.clip = clip
            for ext in extractores:
                r = process_audio(None, schema, config_path=config_path, extractor=ext, transcript=texto,
                                  llm_client=cliente_llm if ext == "llm" else None)
                if r["error"]:
                    raise RuntimeError(f"{clip} [{ext}]: {r['error']}")
                acc = field_accuracy(config, task, clip, r["fields"], gt)
                for campo, valor in r["fields"].items():
                    ok = acc.get(campo)
                    detalle.append({"task": task, "clip": clip, "extractor": ext, "campo": campo, "correcto": ok,
                                    "valor": json.dumps(valor, ensure_ascii=False),
                                    "verificacion": r["verified_fields"][campo]})
                    if ok is False:
                        fallos.append((ext, clip, campo, valor, r["verified_fields"][campo]))
    return pd.DataFrame(detalle), fallos, configs


def imprimir(detalle, fallos, configs, etiquetas):
    for task, cfg in configs.items():
        print(f"{task}: ASR {cfg}")
    tabla = detalle.pivot_table(index=["task", "campo"], columns="extractor", values="correcto", aggfunc=["sum", "count"])
    exts = list(detalle["extractor"].unique())
    print(f"\n{'campo':36}" + "".join(f"{etiquetas[e]:>14}" for e in exts))
    for (task, campo), fila in tabla.iterrows():
        print(f"{task.split('_')[1][:9] + ' ' + campo:36}" +
              "".join(f"{int(fila[('sum', e)])}/{int(fila[('count', e)])}".rjust(14) for e in exts))
    print(f"{'TOTAL':36}" + "".join(
        f"{int(detalle[detalle.extractor == e].correcto.sum())}/{(detalle.extractor == e).sum()}".rjust(14) for e in exts))
    print("\nFallos:")
    for ext, clip, campo, valor, ver in fallos:
        print(f"  [{etiquetas[ext]}] {clip} · {campo}: {valor!r} (verificación: {ver})")
    if not fallos:
        print("  ninguno")


def main(argv=None):
    p = argparse.ArgumentParser(description="Compara extractor por reglas vs LLM contra el ground truth")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--tasks", nargs="+", choices=list(ESQUEMAS))
    p.add_argument("--llm", choices=["none", "answers", "api"], default="none")
    p.add_argument("--answers", help="JSON {clip: {campo: valor}} para --llm answers")
    p.add_argument("--confirm-api", action="store_true", help="confirma que la API de pago puede usarse (--llm api)")
    p.add_argument("--max-calls", type=int, default=10, help="tope de llamadas a la API (--llm api)")
    p.add_argument("--model", help="modelo ASR de la caché (por defecto, la mejor configuración del benchmark)")
    p.add_argument("--compute-type")
    p.add_argument("--device")
    p.add_argument("--glossary", choices=["on", "off"])
    p.add_argument("--out", help="CSV de salida con el detalle por campo y clip")
    a = p.parse_args(argv)

    config = load_config(a.config)
    asr = {}
    if a.model:
        asr = dict(model=a.model, compute_type=a.compute_type or "float16", device=a.device or "cuda",
                   glossary=a.glossary or "off")
    tasks = a.tasks or list(ESQUEMAS)
    n_clips = sum(len(cargar_transcripciones(config, t, **asr)[0]) for t in tasks)

    extractores, cliente, etiquetas = ["rules"], None, {"rules": "reglas"}
    if a.llm == "answers":
        if not a.answers:
            p.error("--llm answers requiere --answers RUTA.json")
        cliente = ClienteSimulado(json.loads(Path(a.answers).read_text(encoding="utf-8")))
        extractores, etiquetas["llm"] = ["rules", "llm"], "LLM SIMULADO"
        print("⚠️  Respuestas LLM SIMULADAS: no miden a ningún modelo (ver el docstring del módulo).\n")
    elif a.llm == "api":
        if not a.confirm_api:
            p.error(f"--llm api usa la API de pago de Anthropic ({n_clips} llamadas, modelo {config['llm']['model']}); "
                    "añade --confirm-api para continuar")
        if n_clips > a.max_calls:
            p.error(f"{n_clips} llamadas superan --max-calls {a.max_calls}; súbelo o reduce con --tasks")
        print(f"Se harán {n_clips} llamadas a la API ({config['llm']['model']}, de pago).\n")
        extractores, etiquetas["llm"] = ["rules", "llm"], "LLM (API)"

    try:
        detalle, fallos, configs = comparar(config, extractores, cliente, tasks, config_path=a.config, **asr)
    except RuntimeError as e:
        raise SystemExit(f"error: {e}")
    imprimir(detalle, fallos, configs, etiquetas)
    if a.out:
        detalle.to_csv(a.out, index=False, encoding="utf-8")
        print(f"\nDetalle guardado en {a.out}")


if __name__ == "__main__":
    main()
