"""Genera docs/pipeline_diagram.png: diagrama de flujo del pipeline completo de la Tarea 4.

Dos carriles:
  - Carril 1 (azul): se ejecuta UNA VEZ (armar y transcribir el corpus).
  - Carril 2 (verde): se ejecuta POR CADA AUDIO NUEVO (audio -> registro verificado).

Uso:  python docs/pipeline_diagram.py
"""
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).with_name("pipeline_diagram.png")

# Decisiones de ASR que se marcan en el diagrama (ver config.yaml: asr.models / asr.precisions).
CORPUS_MODEL, CORPUS_PRECISION = "large-v3", "float16"  # corpus completo, una vez, en GPU
LIVE_MODEL, LIVE_PRECISION = "medium", "int8"  # audio nuevo, uno por uno (asr.default_*)

BLUE = {"fc": "#dbeafe", "ec": "#1d4ed8", "dark": "#1e3a8a"}
GREEN = {"fc": "#dcfce7", "ec": "#15803d", "dark": "#14532d"}
RED = "#b91c1c"
GREY = "#374151"

LH = 1.25  # alto de línea en unidades de datos (fuente ~9.5 pt)


def card(ax, x, y_top, w, h, c, dashed=False):
    ax.add_patch(
        FancyBboxPatch(
            (x, y_top - h), w, h,
            boxstyle="round,pad=0,rounding_size=0.9",
            fc=c["fc"], ec=c["ec"], lw=1.8, ls="--" if dashed else "-", zorder=2,
        )
    )


def badge(ax, x, y, n, c):
    ax.text(
        x, y, str(n), ha="center", va="center", color="white", fontsize=11, fontweight="bold",
        bbox=dict(boxstyle="circle,pad=0.3", fc=c["ec"], ec="none"), zorder=4,
    )


def stack(ax, x, y, items, width):
    """Escribe líneas apiladas hacia abajo; items = [(texto, estilo)]. Devuelve la y final."""
    for text, style in items:
        wrapped = textwrap.fill(text, width)
        n = wrapped.count("\n") + 1
        kw = dict(fontsize=9.5, color=GREY, fontstyle="normal", fontweight="normal")
        step = LH
        if style == "title":
            kw.update(fontsize=11.5, fontweight="bold", color="black")
            step = 1.8
        elif style == "decision":
            kw.update(color="#7c2d12", fontstyle="italic")
        elif style == "discard":
            kw.update(color=RED, fontweight="bold")
        ax.text(x, y, wrapped, ha="left", va="top", zorder=4, linespacing=1.25, **kw)
        y -= n * step if style != "title" else step
        y -= 0.3
    return y


def arrow(ax, p0, p1, c, style="-|>"):
    ax.add_patch(
        FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=18, lw=2, color=c["ec"], zorder=3)
    )


def main():
    fig, ax = plt.subplots(figsize=(22, 15))
    ax.set_xlim(0, 110)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(55, 97.5, "Tarea 4 — From Voice to Record: pipeline completo", ha="center", va="center",
            fontsize=20, fontweight="bold")

    # ── Carril 1 ──────────────────────────────────────────────────────────
    x1, w1, h1, gap1 = 2, 32, 12, 4.5
    ax.add_patch(FancyBboxPatch((x1, 89.5), w1, 4, boxstyle="round,pad=0,rounding_size=0.9",
                                fc=BLUE["ec"], ec="none", zorder=2))
    ax.text(x1 + w1 / 2, 91.5, "CARRIL 1 — se ejecuta UNA VEZ", ha="center", va="center",
            color="white", fontsize=13, fontweight="bold", zorder=4)

    lane1 = [
        ("Escribir guiones de entrevista y ventas",
         "5 entrevistas laborales + 5 llamadas de ventas (restaurante).",
         "Se plantan trampas a propósito: correcciones, total incorrecto, dirección con dígitos.",
         None),
        ("Grabar audios con compañero",
         "Una persona hace de entrevistador/operador y la otra de candidato/cliente.",
         "Voz real grabada, no audio generado.",
         "✗ Descartado: corpus sintético (demasiado limpio)"),
        ("Escribir ground truth",
         "Gratis: sale de los guiones, que se escriben antes de grabar.",
         "El ground truth viene del guion, no de un ASR.",
         "✗ Descartado: YouTube captions como ground truth (circular)"),
        ("Transcribir corpus completo en GPU",
         "faster-whisper, idioma español, los 10 audios de una sola vez.",
         f"Modelo {CORPUS_MODEL} · precisión {CORPUS_PRECISION}",
         None),
        ("Cachear transcripciones en JSON",
         "Se guardan en transcriptions_cache/ y se commitean.",
         "Las métricas se reproducen sin volver a transcribir.",
         None),
    ]
    y = 87
    for i, (title, body, decision, discard) in enumerate(lane1, 1):
        card(ax, x1, y, w1, h1, BLUE)
        badge(ax, x1 + 2, y - 2.1, i, BLUE)
        items = [(title, "title"), (body, "body"), ("▸ " + decision, "decision")]
        if discard:
            items.append((discard, "discard"))
        stack(ax, x1 + 4.2, y - 1.2, items, 52)
        if i < len(lane1):
            arrow(ax, (x1 + w1 / 2, y - h1 - 0.1), (x1 + w1 / 2, y - h1 - gap1 + 0.1), BLUE)
        y -= h1 + gap1

    # ── Carril 2 ──────────────────────────────────────────────────────────
    x2, w2, split = 40, 69, 36  # split: ancho de la zona izquierda (texto) dentro de cada fila
    ax.add_patch(FancyBboxPatch((x2, 89.5), w2, 4, boxstyle="round,pad=0,rounding_size=0.9",
                                fc=GREEN["ec"], ec="none", zorder=2))
    ax.text(x2 + w2 / 2, 91.5, "CARRIL 2 — se ejecuta POR CADA AUDIO NUEVO", ha="center",
            va="center", color="white", fontsize=13, fontweight="bold", zorder=4)

    h, h_ext, gap2 = 8.3, 12.2, 2.9
    lane2 = [
        dict(h=h, title="Transcribir audio",
             body="faster-whisper, idioma español.",
             decision=f"Modelo {LIVE_MODEL} · precisión {LIVE_PRECISION}"),
        dict(h=h_ext, title="Extraer campos", body=None,
             decision="Dos caminos independientes para contrastar el resultado: regex y LLM."),
        dict(h=h, title="Normalizar números hablados",
             body="“seis mil quinientos” → 6500",
             decision="Regla: palabras → dígitos (text2num, español) antes de verificar."),
        dict(h=h, title="Verificar literalmente",
             body="¿El valor existe en la transcripción?",
             decision="Regla: valor sin respaldo literal → queda marcado con flag."),
        dict(h=h, title="Validar aritmética  [solo ventas]",
             body="¿cantidad × precio − promo = total?",
             decision="Se compara el total dicho contra el total recalculado.", optional=True),
        dict(h=h, title="Diagnosticar errores",
             body="¿El error es del ASR o del hablante?",
             decision="ASR: la transcripción no refleja lo dicho. Hablante: lo dicho ya estaba mal."),
        dict(h=h, title="Retornar registro",
             body="Campos extraídos + flags de verificación.",
             decision="Cada campo sale con su estado de verificación."),
    ]
    y = 87
    mids, boxes = [], []
    for i, r in enumerate(lane2, 1):
        hh = r["h"]
        card(ax, x2, y, w2, hh, GREEN, dashed=r.get("optional", False))
        ax.plot([x2 + split, x2 + split], [y - 0.8, y - hh + 0.8], color=GREEN["ec"], lw=1,
                ls=":", zorder=3)
        badge(ax, x2 + 2, y - 2.1, i, GREEN)
        items = [(r["title"], "title")]
        if r["body"]:
            items.append((r["body"], "body"))
        stack(ax, x2 + 4.2, y - 1.2, items, 58)
        stack(ax, x2 + split + 1.5, y - 1.2, [("▸ " + r["decision"], "decision")], 50)
        if i == 2:  # dos caminos: regex y LLM
            for k, label in enumerate(["Regex (reglas)", "LLM (Claude)"]):
                bx = x2 + 4.2 + k * 17.5
                ax.add_patch(FancyBboxPatch((bx, y - hh + 1.5), 14.5, 3.6,
                                            boxstyle="round,pad=0,rounding_size=0.6",
                                            fc="white", ec=GREEN["ec"], lw=1.5, zorder=3))
                ax.text(bx + 7.25, y - hh + 3.3, label, ha="center", va="center", fontsize=10,
                        fontweight="bold", color=GREEN["dark"], zorder=4)
            ax.text(x2 + 4.2 + 15.75, y - hh + 3.3, "Y", ha="center", va="center", fontsize=10,
                    fontweight="bold", color=GREEN["dark"], zorder=4)
        boxes.append((y, hh))
        mids.append(y - hh / 2)
        if i < len(lane2):
            arrow(ax, (x2 + w2 / 2, y - hh - 0.1), (x2 + w2 / 2, y - hh - gap2 + 0.1), GREEN)
        y -= hh + gap2

    # Rodeo del paso 5: las entrevistas se lo saltan (paso 4 → paso 6)
    bx = x2 - 2.6
    ax.plot([x2, bx, bx], [mids[3], mids[3], mids[5] + 0.0], color=GREEN["ec"], lw=2, ls="--", zorder=3)
    arrow(ax, (bx, mids[5]), (x2 - 0.1, mids[5]), GREEN)
    ax.text(bx - 0.9, (mids[3] + mids[5]) / 2, "entrevistas: se omite el paso 5", rotation=90,
            ha="center", va="center", fontsize=9, color=GREEN["dark"], fontstyle="italic")

    # ── Leyenda ───────────────────────────────────────────────────────────
    ly = 3.2
    for lx, c, label in [(2, BLUE, "Carril 1: una vez"), (26, GREEN, "Carril 2: por audio nuevo")]:
        ax.add_patch(FancyBboxPatch((lx, ly - 1), 3.2, 2, boxstyle="round,pad=0,rounding_size=0.4",
                                    fc=c["fc"], ec=c["ec"], lw=1.8))
        ax.text(lx + 4.2, ly, label, va="center", fontsize=10.5)
    ax.text(56, ly, "▸ decisión clave", va="center", fontsize=10.5, color="#7c2d12",
            fontstyle="italic")
    ax.text(72, ly, "✗ descartado", va="center", fontsize=10.5, color=RED, fontweight="bold")
    ax.text(88, ly, "recuadro punteado = condicional", va="center", fontsize=10.5, color=GREY)

    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"Guardado: {OUT}")


if __name__ == "__main__":
    main()
