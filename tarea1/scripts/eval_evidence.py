#!/usr/bin/env python3
"""eval_evidence.py — recorta del PDF la zona de cada página esperada y arma la hoja de revisión manual.

Para cada (documento, página) de eval/evidencia.yaml localiza la frase-ancla en la página y guarda un recorte de la
IMAGEN del PDF (con la línea resaltada) en docs/eval_evidencia/. Así se valida contra lo que se ve en el PDF, no solo contra
el texto extraído (evita el razonamiento circular). Escribe también docs/eval_revision_manual.md.

Cómo se localiza el ancla: en páginas con capa de texto, con las líneas del PDF; en páginas escaneadas, con las líneas
del OCR (fuzzy: el OCR tiene errores). Si no se encuentra, el script falla: el ancla o la página están mal.
"""
from __future__ import annotations

import difflib
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pymupdf  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from evaluation.eval_set import cargar_evidencia, cargar_preguntas  # noqa: E402
from extraction import store  # noqa: E402
from extraction.ocr import crear_motor, ocr_pagina, rasterizar  # noqa: E402
from rag_engine.config import ConfigError, cargar_config  # noqa: E402

UMBRAL = 0.80
DOCS_DOS_COLUMNAS = {"ds_001_2026_ef", "ds_009_2025_ef"}


def norm(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def cobertura(ancla: str, candidato: str) -> float:
    """Fracción de los caracteres del ancla que aparecen (en orden) en el candidato."""
    bloques = difflib.SequenceMatcher(None, ancla, candidato, autojunk=False).get_matching_blocks()
    return sum(b.size for b in bloques) / max(len(ancla), 1)


def mejor_linea(ancla: str, textos: list[str]) -> tuple[int, float]:
    """Índice de la línea donde EMPIEZA el ancla. Primero busca el ancla completa en UNA sola línea; solo si ninguna
    la contiene casi entera prueba con pares de líneas consecutivas (ancla partida por un salto de línea)."""
    a = norm(ancla)
    simples = [cobertura(a, norm(t)) for t in textos]
    if simples and max(simples) >= 0.95:
        return simples.index(max(simples)), max(simples)
    mejor = (max(range(len(simples)), key=simples.__getitem__), max(simples, default=0.0)) if simples else (-1, 0.0)
    for i in range(len(textos) - 1):
        s2 = cobertura(a, norm(f"{textos[i]} {textos[i + 1]}"))
        if s2 > mejor[1] + 0.02:
            mejor = (i, s2)
    return mejor


def _resaltar(img: Image.Image, caja: tuple[int, int, int, int]) -> Image.Image:
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(capa).rectangle(caja, fill=(255, 235, 0, 90), outline=(255, 140, 0, 255), width=2)
    return Image.alpha_composite(img.convert("RGBA"), capa).convert("RGB")


def recorte_capa_texto(pdf: pymupdf.Document, pagina: int, ancla: str, doc_id: str):
    pg = pdf[pagina - 1]
    lineas = [(l["bbox"], "".join(s["text"] for s in l["spans"])) for b in pg.get_text("dict")["blocks"] if b["type"] == 0 for l in b["lines"]]
    i, score = mejor_linea(ancla, [t for _, t in lineas])
    if i < 0 or score < UMBRAL:
        return None, score
    x0, y0, x1, y1 = lineas[i][0]
    dpi = 150
    img = pg.get_pixmap(dpi=dpi).tobytes("png")
    from io import BytesIO
    img = Image.open(BytesIO(img)).convert("RGB")
    k = dpi / 72
    img = _resaltar(img, (int(x0 * k) - 3, int(y0 * k) - 2, int(x1 * k) + 3, int(y1 * k) + 2))
    ancho = img.width
    if doc_id in DOCS_DOS_COLUMNAS:
        cx = (x0 + x1) / 2
        izq = cx < pg.rect.width / 2
        cx0, cx1 = (0, ancho // 2 + 20) if izq else (ancho // 2 - 20, ancho)
    else:
        cx0, cx1 = 0, ancho
    return img.crop((cx0, max(int((y0 - 30) * k), 0), cx1, min(int((y1 + 170) * k), img.height))), score


def recorte_ocr(pdf: pymupdf.Document, pagina: int, ancla: str, lineas_ocr: list[list], dpi: int = 200):
    i, score = mejor_linea(ancla, [l[2] for l in lineas_ocr])
    if i < 0 or score < UMBRAL:
        return None, score
    y, _, _, x = lineas_ocr[i]
    img = rasterizar(pdf[pagina - 1], dpi).convert("RGB")
    an, al = img.size
    izq = x < 0.5
    cx0, cx1 = (int(0.03 * an), int(0.53 * an)) if izq else (int(0.47 * an), int(0.97 * an))
    img = _resaltar(img, (cx0, int((y - 0.002) * al), cx1, int((y + 0.016) * al)))
    return img.crop((cx0, max(int((y - 0.035) * al), 0), cx1, min(int((y + 0.17) * al), al))), score


def main() -> int:
    try:
        cfg = cargar_config()
        preguntas = {q.id: q for q in cargar_preguntas(cfg.ruta("eval_preguntas"))}
        evidencia = cargar_evidencia(cfg.ruta("eval_preguntas").with_name("evidencia.yaml"))
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    dir_img = cfg.ruta("docs") / "eval_evidencia"
    dir_img.mkdir(parents=True, exist_ok=True)
    pdfs, motor = {}, None
    fallos, resultados = [], {}

    def pdf_de(doc):
        if doc not in pdfs:
            pdfs[doc] = pymupdf.open(cfg.ruta("raw") / cfg.documento(doc)["archivo"])
        return pdfs[doc]

    for qid, ev in evidencia.items():
        items = ev["fuera_del_indice"] if isinstance(ev, dict) else ev
        for it in items:
            doc, pag = it["documento"], it["pagina"]
            e = store.leer_pagina(cfg.ruta("processed") / doc, pag)
            if e is not None and e["origen"] == "texto":
                img, score = recorte_capa_texto(pdf_de(doc), pag, it["ancla"], doc)
            else:
                if e is None:                       # página fuera del índice: OCR temporal, no se guarda
                    motor = motor or crear_motor(cfg.get("extraccion.motor_ocr"), cfg.get("extraccion.idioma_ocr"))
                    lineas = ocr_pagina(pdf_de(doc)[pag - 1], motor, cfg.get("extraccion.dpi")).lineas
                else:
                    lineas = e["ocr_lineas"]
                img, score = recorte_ocr(pdf_de(doc), pag, it["ancla"], lineas)
            nombre = f"{qid}_{doc}_p{pag:03d}.png"
            if img is None:
                fallos.append(f"{qid} {doc} p.{pag}: ancla no encontrada (mejor cobertura {score:.2f}): «{it['ancla']}»")
                continue
            img.save(dir_img / nombre, optimize=True)
            resultados[(qid, doc, pag)] = (nombre, score)
            print(f"  {qid} {doc:15s} p{pag:>3}  cobertura {score:.2f}  -> {nombre}")

    # ── hoja de revisión manual ──
    L = ["# Hoja de revisión manual del set de evaluación", "",
         "Antes de usar las métricas hay que validar **cada página esperada contra el PDF original** (sin esto, Recall@k no significa nada). "
         "Para cada pregunta se muestra el recorte de la IMAGEN del PDF, con la línea del pasaje resaltada, y el dato que debe verse en él. "
         "Marca la casilla si la página es correcta o anota qué está mal.", "",
         "**Cómo leerla**", "",
         "- `documento_esperado` / `paginas_esperadas` del CSV: varios documentos se separan con `|`; varias páginas del mismo documento con `;`.",
         "- En las preguntas de **versiones** el primer documento es siempre el DS 001-2026-EF (la modificatoria).",
         "- Las páginas son el índice del PDF (la primera página del archivo es la 1). En la Ley y el DS 001 el número puede no coincidir con el impreso.",
         "- Los recortes del DS 009 son de un escaneo de 96 DPI: se ven borrosos pero legibles. Sus **cifras** conviene leerlas en el recorte, no en el texto OCR "
         "(p. ej. el OCR leyó `430 000` donde el texto en letras dice *cuatrocientos ochenta mil*).", ""]
    L += ["## Preguntas dentro del dominio", ""]
    for qid, q in preguntas.items():
        if q.tipo != "in_domain":
            continue
        etiqueta = f"{q.estilo}" + (" · **versiones (DS 001-2026-EF)**" if q.modificada_2026 else "")
        L += [f"### {qid} · {etiqueta}", "", f"**{q.pregunta}**", "",
              "Esperado: " + " · ".join(f"`{d}` p. {', '.join(map(str, ps))}" for d, ps in q.esperados.items()), "", f"_{q.notas}_", ""]
        for it in evidencia[qid]:
            nombre, score = resultados.get((qid, it["documento"], it["pagina"]), (None, 0))
            L += [f"**`{it['documento']}` — página {it['pagina']}** · debe verse: {it['dato']}", ""]
            if nombre:
                L += [f"![{qid} {it['documento']} p.{it['pagina']}](eval_evidencia/{nombre})", ""]
            L += ["- [ ] La página es correcta   ·   Comentario: ", ""]
    L += ["## Preguntas fuera del dominio", "",
          "Para cada una hay que confirmar que **el corpus indexado no la responde**. Las cercanas al dominio (o02, o03, o05, o06) son las que ponen a prueba el umbral.", ""]
    for qid, q in preguntas.items():
        if q.tipo != "out_of_domain":
            continue
        L += [f"### {qid} · {q.estilo}", "", f"**{q.pregunta}**", "", f"_{q.notas}_", ""]
        for it in (evidencia.get(qid) or {}).get("fuera_del_indice", []):
            nombre, _ = resultados.get((qid, it["documento"], it["pagina"]), (None, 0))
            L += [f"La respuesta está en `{it['documento']}` p. {it['pagina']}, **excluida del índice**: {it['dato']}", ""]
            if nombre:
                L += [f"![{qid} p.{it['pagina']}](eval_evidencia/{nombre})", ""]
        L += ["- [ ] Confirmo que el corpus indexado no la responde   ·   Comentario: ", ""]
    ruta = cfg.ruta("docs") / "eval_revision_manual.md"
    tmp = ruta.with_suffix(".md.tmp")
    tmp.write_text("\n".join(L), encoding="utf-8")
    os.replace(tmp, ruta)
    print(f"\nEscrito {ruta}")
    for f in fallos:
        print("  FALLO", f, file=sys.stderr)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
