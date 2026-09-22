"""sweep_threshold.py — calibra el umbral de similitud con un barrido sobre el set de evaluación, SIN llamar al LLM.

Para cada umbral t del barrido, cada pregunta se "responde" si su mejor similitud es >= t y "se abstiene" si es menor. Se cuentan:
  * respuestas CORRECTAS:      in_domain, respondida y con la página esperada entre los `top_k` recuperados;
  * respuestas ERRÓNEAS:       in_domain, respondida pero SIN la página esperada (contexto equivocado);
  * abstenciones INCORRECTAS:  in_domain que se abstuvo (se perdió una respuesta posible);
  * abstenciones CORRECTAS:    out_of_domain que se abstuvo;
  * respuestas INDEBIDAS:      out_of_domain que se respondió.
Criterio de elección (explícito): se maximiza F-beta con beta < 1 (config: eval.barrido_umbral.beta = 0,5), donde
  precisión = correctas / (correctas + erróneas + indebidas)   y   cobertura = correctas / (preguntas in_domain).
Con beta = 0,5 la precisión pesa el doble que la cobertura: responder mal es peor que no responder. Si varios umbrales empatan en el
máximo, se toma el CENTRO de esa meseta (el más robusto a pequeños cambios).
LIMITACIÓN: se calibra con el MISMO set de preguntas con que se evalúa; el umbral no se ha probado con preguntas nuevas.
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.sweep_threshold [--aplicar]
"""
from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from evaluation.eval_set import cargar_preguntas  # noqa: E402
from evaluation.informes import aviso_set, escribir_atomico, escribir_csv, tabla_markdown  # noqa: E402
from evaluation.metrics import evaluar_recuperacion  # noqa: E402
from rag_engine.config import cargar_config  # noqa: E402

# Tokens de diseño (paleta de referencia de la guía de visualización): colores categóricos 1-4 en ORDEN FIJO.
TEMAS = {
    "claro": {"superficie": "#fcfcfb", "tinta": "#0b0b0b", "tinta_2": "#52514e", "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]},
    "oscuro": {"superficie": "#1a1a19", "tinta": "#ffffff", "tinta_2": "#c3c2b7", "series": ["#3987e5", "#d95926", "#199e70", "#c98500"]},
}
ETIQUETAS_CORTAS = [("correctas", "Correctas"), ("abstenciones_incorrectas", "Abst. incorrectas"), ("abstenciones_correctas", "Abst. correctas"), ("indebidas", "Indebidas")]
SERIES = [("correctas", "Respuestas correctas (in_domain)"), ("abstenciones_incorrectas", "Abstenciones incorrectas (in_domain)"),
          ("abstenciones_correctas", "Abstenciones correctas (fuera de dominio)"), ("indebidas", "Respuestas indebidas (fuera de dominio)")]


@dataclass
class Punto:
    tipo: str            # in_domain | out_of_domain
    similitud: float     # mejor similitud recuperada
    acierto: bool        # in_domain: la página esperada está entre los top_k


def umbrales(desde: float, hasta: float, paso: float) -> list[float]:
    n = int(round((hasta - desde) / paso))
    return [round(desde + i * paso, 6) for i in range(n + 1)]


def fbeta(precision: float | None, cobertura: float, beta: float) -> float:
    if not precision or (precision == 0 and cobertura == 0):
        return 0.0
    b2 = beta * beta
    return (1 + b2) * precision * cobertura / (b2 * precision + cobertura) if (b2 * precision + cobertura) > 0 else 0.0


def barrido(puntos: list[Punto], desde: float, hasta: float, paso: float, beta: float) -> list[dict]:
    n_dom = sum(p.tipo == "in_domain" for p in puntos)
    filas = []
    for t in umbrales(desde, hasta, paso):
        resp = [p for p in puntos if p.similitud >= t]
        correctas = sum(p.tipo == "in_domain" and p.acierto for p in resp)
        erroneas = sum(p.tipo == "in_domain" and not p.acierto for p in resp)
        indebidas = sum(p.tipo == "out_of_domain" for p in resp)
        abst = [p for p in puntos if p.similitud < t]
        contestadas = correctas + erroneas + indebidas
        precision = correctas / contestadas if contestadas else None
        cobertura = correctas / n_dom if n_dom else 0.0
        filas.append({"umbral": t, "correctas": correctas, "erroneas": erroneas, "abstenciones_incorrectas": sum(p.tipo == "in_domain" for p in abst),
                      "abstenciones_correctas": sum(p.tipo == "out_of_domain" for p in abst), "indebidas": indebidas,
                      "precision": round(precision, 4) if precision is not None else None, "cobertura": round(cobertura, 4),
                      "fbeta": round(fbeta(precision, cobertura, beta), 4)})
    return filas


def elegir(filas: list[dict]) -> tuple[float, list[float]]:
    """Umbral elegido (centro de la meseta de máximo F-beta) y la meseta completa."""
    maximo = max(f["fbeta"] for f in filas)
    meseta = [f["umbral"] for f in filas if abs(f["fbeta"] - maximo) < 1e-9]
    return meseta[len(meseta) // 2], meseta


def grafico(filas: list[dict], elegido: float, ruta: Path, tema: str, x_min: float, x_max: float) -> None:
    t = TEMAS[tema]
    fig, ax = plt.subplots(figsize=(8.8, 4.8), dpi=160)
    fig.patch.set_facecolor(t["superficie"])
    ax.set_facecolor(t["superficie"])
    xs = [f["umbral"] for f in filas]
    for (clave, nombre), color in zip(SERIES, t["series"]):
        ax.plot(xs, [f[clave] for f in filas], color=color, linewidth=2.0, drawstyle="steps-post", label=nombre, zorder=3)
    for (clave, _), (_, corto), color in zip(SERIES, ETIQUETAS_CORTAS, t["series"]):
        valores = [f[clave] for f in filas if x_min <= f["umbral"] <= x_max]
        if not valores or max(valores) == 0:
            continue
        pico = max(valores)
        a_la_izquierda = valores.index(pico) < len(valores) / 2                   # etiqueta sobre la meseta más alta, hacia el lado donde ocurre
        ax.text(x_min + 0.004 if a_la_izquierda else x_max - 0.004, pico + 0.45, corto, color=t["tinta"], fontsize=9, fontweight="bold",
                ha="left" if a_la_izquierda else "right", va="bottom", zorder=5)
    ax.axvline(elegido, color=t["tinta"], linewidth=1.2, linestyle=(0, (4, 3)), zorder=4)
    ax.yaxis.grid(True, color=t["tinta_2"], alpha=0.18, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(t["tinta_2"])
        ax.spines[lado].set_alpha(0.4)
    ax.tick_params(colors=t["tinta_2"], labelsize=9, length=0)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Umbral de similitud (coseno)", color=t["tinta_2"], fontsize=10, labelpad=8)
    ax.set_ylabel("Preguntas", color=t["tinta_2"], fontsize=10, labelpad=8)
    ax.text(elegido, ax.get_ylim()[1] * 0.985, f" elegido {elegido:.3f}", color=t["tinta"], fontsize=9, va="top", ha="left")
    leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False, fontsize=9)
    for texto in leg.get_texts():
        texto.set_color(t["tinta"])                      # la leyenda va en tinta de texto; el color lo lleva la línea
    fig.text(0.075, 0.955, "Barrido del umbral de similitud", color=t["tinta"], fontsize=13, fontweight="bold", ha="left", va="top")
    fig.text(0.075, 0.905, "Cuántas preguntas caen en cada caso según el umbral (sin llamar al LLM)", color=t["tinta_2"], fontsize=10, ha="left", va="top")
    fig.subplots_adjust(left=0.085, right=0.97, top=0.82, bottom=0.27)
    fig.savefig(ruta, facecolor=fig.get_facecolor())
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true", help="escribe el umbral elegido en config.yaml y marca umbral_calibrado: true")
    args = ap.parse_args(argv)
    from rag_engine.embeddings.factory import crear_embedder
    from rag_engine.retrieval.indice import abrir_para_lectura
    from rag_engine.retrieval.modos import buscar_por_modo

    cfg = cargar_config()
    preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
    emb, col = crear_embedder(cfg), abrir_para_lectura(cfg)
    k = cfg.get("retrieval.top_k")
    ev = evaluar_recuperacion(preguntas, lambda q, kk: buscar_por_modo(col, emb, q, cfg, kk), (k,))
    puntos = [Punto(r.tipo, r.mejor_similitud, r.rango_acierto is not None and r.rango_acierto <= k) for r in ev.por_pregunta]
    b = cfg.get("eval.barrido_umbral")
    filas = barrido(puntos, b["desde"], b["hasta"], b["paso"], b["beta"])
    elegido, meseta = elegir(filas)
    fila = next(f for f in filas if f["umbral"] == elegido)

    salida = cfg.ruta("eval_results")
    escribir_csv(salida / "umbral_barrido.csv", filas)
    q = {p.id: p for p in preguntas}
    por_pregunta = sorted(({"id": r.id, "tipo": r.tipo, "estilo": r.estilo, "mejor_similitud": round(r.mejor_similitud, 4),
                            "acierto_top_k": (r.rango_acierto is not None and r.rango_acierto <= k) if r.tipo == "in_domain" else "",
                            "pregunta": q[r.id].pregunta} for r in ev.por_pregunta), key=lambda x: x["mejor_similitud"])
    escribir_csv(salida / "umbral_por_pregunta.csv", por_pregunta)
    sims = [p.similitud for p in puntos]
    x_min, x_max = max(0.0, min(sims) - 0.03), min(1.0, max(sims) + 0.03)
    grafico(filas, elegido, salida / "umbral_barrido.png", "claro", x_min, x_max)
    grafico(filas, elegido, salida / "umbral_barrido_oscuro.png", "oscuro", x_min, x_max)

    cerca = [f for f in filas if abs(f["umbral"] - elegido) <= 0.02 and round((f["umbral"] - filas[0]["umbral"]) / b["paso"]) % 2 == 0]
    cols = [("umbral", "Umbral", ".3f"), ("correctas", "Correctas", ""), ("erroneas", "Erróneas", ""), ("abstenciones_incorrectas", "Abst. incorrectas", ""),
            ("abstenciones_correctas", "Abst. correctas", ""), ("indebidas", "Indebidas", ""), ("precision", "Precisión", ".3f"), ("cobertura", "Cobertura", ".3f"), ("fbeta", "F-β", ".3f")]
    dentro = [p.similitud for p in puntos if p.tipo == "in_domain"]
    fuera = [p.similitud for p in puntos if p.tipo == "out_of_domain"]
    md = ["# Calibración del umbral de similitud", "", aviso_set(cfg) +
          f"Barrido de {b['desde']} a {b['hasta']} en pasos de {b['paso']} sobre las {len(dentro)} preguntas in_domain y las {len(fuera)} out_of_domain del set de evaluación "
          f"(recuperación `{cfg.get('retrieval.modo')}`, {k} fragmentos, modelo `{emb.name}`). Sin llamar al LLM.", "",
          f"## Umbral elegido: **{elegido:.3f}**", "",
          f"Criterio: máximo **F-β con β = {b['beta']}** (la precisión pesa {1 / (b['beta'] ** 2):.0f} veces lo que la cobertura: responder mal es peor que no responder). "
          f"Empatan {len(meseta)} umbrales entre {meseta[0]:.3f} y {meseta[-1]:.3f}; se toma el centro de esa meseta. En {elegido:.3f}: "
          f"{fila['correctas']} respuestas correctas, {fila['erroneas']} erróneas, {fila['abstenciones_incorrectas']} abstenciones incorrectas, "
          f"{fila['abstenciones_correctas']} abstenciones correctas y {fila['indebidas']} respuestas indebidas (precisión {fila['precision']}, cobertura {fila['cobertura']}).", "",
          "## Por qué el margen es estrecho", "",
          f"Los modelos multilingües dan similitudes comprimidas. Aquí las preguntas in_domain tienen mejor similitud entre {min(dentro):.3f} y {max(dentro):.3f} "
          f"(mediana {statistics.median(dentro):.3f}) y las out_of_domain entre {min(fuera):.3f} y {max(fuera):.3f} (mediana {statistics.median(fuera):.3f}). "
          "Un umbral «a ojo» (0,78 en el ejemplo del enunciado) no separa nada.", "",
          "## Gráfico", "", "![Barrido del umbral](umbral_barrido.png)", "",
          "Solo se dibuja el tramo donde hay preguntas; la tabla completa (0 a 1) está en `umbral_barrido.csv`. Tabla equivalente alrededor del umbral elegido:", "",
          tabla_markdown(cerca, cols), "",
          "## Mejor similitud de cada pregunta (de menor a mayor)", "",
          tabla_markdown(por_pregunta, [("id", "Id", ""), ("tipo", "Tipo", ""), ("estilo", "Estilo", ""), ("mejor_similitud", "Mejor similitud", ".4f"), ("acierto_top_k", f"Acierto en top-{k}", "")]), "",
          "**Limitación:** el umbral se calibra con el mismo set de preguntas con que se evalúa; no se ha probado con preguntas nuevas.", ""]
    escribir_atomico(salida / "umbral_resumen.md", "\n".join(md))
    print(f"Umbral elegido: {elegido:.3f} (meseta {meseta[0]:.3f}-{meseta[-1]:.3f}); correctas={fila['correctas']} indebidas={fila['indebidas']} "
          f"abst_incorrectas={fila['abstenciones_incorrectas']} F-β={fila['fbeta']}")
    print(f"in_domain sim: {min(dentro):.3f}-{max(dentro):.3f} | out_of_domain sim: {min(fuera):.3f}-{max(fuera):.3f}")
    if args.aplicar:
        import os, re
        p = cfg.archivo
        s = p.read_text(encoding="utf-8")
        s, n1 = re.subn(r"(?m)^(  umbral_similitud: )[0-9.]+(.*)$", rf"\g<1>{elegido:.3f}   # CALIBRADO (Fase 5, provisional hasta validar el set): ver eval/results/umbral_resumen.md", s, count=1)
        s, n2 = re.subn(r"(?m)^(  umbral_calibrado: )\w+(.*)$", r"\g<1>true\g<2>", s, count=1)
        assert n1 == 1 and n2 == 1 and len(s) > 1000
        tmp = p.with_suffix(".yaml.tmp"); tmp.write_text(s, encoding="utf-8"); os.replace(tmp, p)
        print("config.yaml actualizado (retrieval.umbral_similitud y umbral_calibrado).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
