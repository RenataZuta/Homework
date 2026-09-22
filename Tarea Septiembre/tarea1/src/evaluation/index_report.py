"""index_report.py — reporte del índice: fragmentos por documento, distribución de longitudes e histograma, y truncamiento.

Escribe en eval/results/: indice_reporte.md/.csv/.json, indice_histograma.png y indice_histograma_oscuro.png.
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.index_report
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from evaluation.informes import escribir_atomico, escribir_csv, tabla_markdown  # noqa: E402
from indexing.carga import chunk_desde_config, docs_paginas  # noqa: E402
from indexing.chunking import trocear_documento  # noqa: E402
from rag_engine.config import cargar_config  # noqa: E402
from rag_engine.embeddings.factory import crear_embedder  # noqa: E402

# Tokens de diseño (paleta de referencia de la guía de visualización): una sola serie -> color categórico 1.
TEMAS = {
    "claro": {"superficie": "#fcfcfb", "serie": "#2a78d6", "tinta": "#0b0b0b", "tinta_2": "#52514e"},
    "oscuro": {"superficie": "#1a1a19", "serie": "#3987e5", "tinta": "#ffffff", "tinta_2": "#c3c2b7"},
}


def percentil(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def histograma(largos: list[int], ruta: Path, tema: str, titulo: str, bins: int) -> list[tuple[int, int, int]]:
    """Dibuja el histograma y devuelve las clases (desde, hasta, n) para la tabla equivalente."""
    t = TEMAS[tema]
    lo, hi = min(largos), max(largos)
    ancho = max(1, -(-(hi - lo + 1) // bins))
    clases = [(lo + i * ancho, lo + (i + 1) * ancho - 1, 0) for i in range(bins)]
    conteo = [0] * bins
    for x in largos:
        conteo[min((x - lo) // ancho, bins - 1)] += 1
    clases = [(a, b, n) for (a, b, _), n in zip(clases, conteo)]

    fig, ax = plt.subplots(figsize=(8.4, 4.4), dpi=160)
    fig.patch.set_facecolor(t["superficie"])
    ax.set_facecolor(t["superficie"])
    centros = [(a + b) / 2 for a, b, _ in clases]
    ax.bar(centros, conteo, width=ancho, color=t["serie"], edgecolor=t["superficie"], linewidth=1.6, zorder=3)   # separación de 2 px entre barras
    ax.yaxis.grid(True, color=t["tinta_2"], alpha=0.18, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(t["tinta_2"])
        ax.spines[lado].set_alpha(0.4)
    ax.tick_params(colors=t["tinta_2"], labelsize=9, length=0)
    ax.set_xlabel("Longitud del fragmento (caracteres)", color=t["tinta_2"], fontsize=10, labelpad=8)
    ax.set_ylabel("Fragmentos", color=t["tinta_2"], fontsize=10, labelpad=8)
    tope = max(conteo) * 1.18
    ax.set_ylim(0, tope)
    ax.set_xlim(0, max(largos) * 1.12)
    med, p95 = statistics.median(largos), percentil(largos, 95)
    for valor, etiqueta, alinear in ((med, f"mediana {int(med)} ", "right"), (p95, f" p95 {int(p95)}", "left")):
        ax.axvline(valor, color=t["tinta"], linewidth=1.2, linestyle=(0, (4, 3)), zorder=4)         # etiquetas directas: solo estas dos
        ax.text(valor, tope * 0.985, etiqueta, color=t["tinta"], fontsize=9, va="top", ha=alinear)
    fig.text(0.075, 0.955, titulo, color=t["tinta"], fontsize=13, fontweight="bold", ha="left", va="top")
    fig.text(0.075, 0.905, f"{len(largos)} fragmentos", color=t["tinta_2"], fontsize=10, ha="left", va="top")
    fig.subplots_adjust(left=0.09, right=0.97, top=0.82, bottom=0.15)
    fig.savefig(ruta, facecolor=fig.get_facecolor())
    plt.close(fig)
    return clases


def main() -> int:
    cfg = cargar_config()
    chunk, docs = chunk_desde_config(cfg), docs_paginas(cfg)
    maximo = dict(cfg.get("chunking.articulo_maximo"))
    emb = crear_embedder(cfg)
    por_doc, todos = [], []
    for doc_id, (d, ps) in docs.items():
        frag = trocear_documento(d, ps, chunk, maximo)
        L = [len(f.texto) for f in frag]
        tok = emb.contar_tokens([f.texto_embedding for f in frag])
        todos += frag
        por_doc.append({"documento": doc_id, "version": d["version"], "paginas": len(ps), "fragmentos": len(frag), "con_ocr": sum(f.es_ocr for f in frag),
                        "min_car": min(L), "mediana_car": int(statistics.median(L)), "p95_car": int(percentil(L, 95)), "max_car": max(L),
                        "tokens_max": max(tok), "truncados": sum(t > emb.max_tokens for t in tok)})
    largos = [len(f.texto) for f in todos]
    tok_todos = emb.contar_tokens([f.texto_embedding for f in todos])
    total = {"documento": "TOTAL", "version": "", "paginas": sum(x["paginas"] for x in por_doc), "fragmentos": len(todos), "con_ocr": sum(f.es_ocr for f in todos),
             "min_car": min(largos), "mediana_car": int(statistics.median(largos)), "p95_car": int(percentil(largos, 95)), "max_car": max(largos),
             "tokens_max": max(tok_todos), "truncados": sum(t > emb.max_tokens for t in tok_todos)}
    salida = cfg.ruta("eval_results")
    titulo = f"Longitud de los fragmentos ({chunk.nombre}, {chunk.tamano} car., solape {chunk.solapamiento})"
    clases = histograma(largos, salida / "indice_histograma.png", "claro", titulo, cfg.get("indexacion.bins_histograma"))
    histograma(largos, salida / "indice_histograma_oscuro.png", "oscuro", titulo, cfg.get("indexacion.bins_histograma"))

    escribir_csv(salida / "indice_reporte.csv", por_doc + [total])
    escribir_atomico(salida / "indice_reporte.json", json.dumps({"troceado": chunk.nombre, "modelo": emb.name, "max_tokens": emb.max_tokens, "por_documento": por_doc,
                                                                 "total": total, "histograma": [{"desde": a, "hasta": b, "n": n} for a, b, n in clases]}, ensure_ascii=False, indent=1))
    cols = [("documento", "Documento", ""), ("paginas", "Págs.", ""), ("fragmentos", "Fragmentos", ""), ("con_ocr", "De OCR", ""), ("min_car", "Mín.", ""),
            ("mediana_car", "Mediana", ""), ("p95_car", "p95", ""), ("max_car", "Máx.", ""), ("tokens_max", "Tokens máx.", ""), ("truncados", "Truncados", "")]
    md = ["# Reporte del índice", "",
          f"Troceado `{chunk.nombre}` ({chunk.tamano} caracteres, solape {chunk.solapamiento}, contexto de encabezado: {'sí' if chunk.contexto_encabezado else 'no'}) · "
          f"modelo `{emb.name}` (longitud máxima de entrada: {emb.max_tokens} tokens).", "",
          "## Fragmentos por documento y longitud (caracteres)", "", tabla_markdown(por_doc + [total], cols), "",
          f"## Truncamiento: {total['truncados']} de {total['fragmentos']} fragmentos superan {emb.max_tokens} tokens", "",
          f"El fragmento más largo mide {total['tokens_max']} tokens (con el prefijo y el encabezado de contexto)."
          + (" Ninguno se trunca en silencio." if total["truncados"] == 0 else " Los que exceden pierden su cola al calcular el vector."), "",
          "## Distribución de longitudes", "", "![Histograma de longitudes](indice_histograma.png)", "",
          "Tabla equivalente del histograma:", "", "| Longitud (caracteres) | Fragmentos |", "|---|---:|"]
    md += [f"| {a}–{b} | {n} |" for a, b, n in clases]
    escribir_atomico(salida / "indice_reporte.md", "\n".join(md) + "\n")
    print(f"Escrito {salida / 'indice_reporte.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
