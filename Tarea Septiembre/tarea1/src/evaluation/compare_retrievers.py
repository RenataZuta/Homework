"""compare_retrievers.py — BM25 frente a embeddings frente a un híbrido (Reciprocal Rank Fusion) sobre los MISMOS fragmentos, sin llamar al LLM.

Para cada variante calcula Recall@1/3/5 y MRR sobre el set completo, DESGLOSADO por estilo de la pregunta (coloquial / jurídico), por preguntas sobre artículos
modificados por el DS 001-2026-EF y por si la pregunta contiene cifras (números de artículo, montos, plazos). Además lista, pregunta por pregunta, dónde gana
cada método, para el análisis del README.
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.compare_retrievers [--aplicar VARIANTE]
Escribe eval/results/retrievers_comparacion.{csv,json,md} y retrievers_por_pregunta.csv (la app Streamlit lee la tabla).
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from evaluation.eval_set import cargar_preguntas
from evaluation.informes import aviso_set, escribir_atomico, escribir_csv, tabla_markdown
from evaluation.metrics import evaluar_recuperacion
from rag_engine.config import cargar_config
from rag_engine.embeddings.factory import crear_embedder
from rag_engine.retrieval.bm25 import buscar_bm25
from rag_engine.retrieval.hybrid import buscar_hibrido
from rag_engine.retrieval.indice import abrir_para_lectura
from rag_engine.retrieval.semantic import buscar as buscar_semantico

# (nombre, modo de config.yaml, parámetros léxicos). El orden es el de la tabla.
VARIANTES = [
    ("semantico", "semantico", {}),
    ("bm25", "bm25", {"stemming": False, "usar_encabezado": True}),
    ("bm25_stem", "bm25", {"stemming": True, "usar_encabezado": True}),
    ("bm25_sin_encabezado", "bm25", {"stemming": False, "usar_encabezado": False}),
    ("hibrido_rrf", "hibrido", {"stemming": False, "usar_encabezado": True}),
    ("hibrido_rrf_stem", "hibrido", {"stemming": True, "usar_encabezado": True}),
]
RE_CIFRAS = re.compile(r"\d")
RE_ARTICULO = re.compile(r"^Art[ií]culo (\d+)\.")


def articulos_de_la_ley(col) -> dict[int, set[tuple[str, int]]]:
    """{número de artículo: {(documento, página)} de los fragmentos cuyo encabezado es ese artículo}. Sale del propio índice (no de un etiquetado manual)."""
    d = col.get(where={"documento": "ley_32069"}, include=["metadatas"])
    salida: dict[int, set[tuple[str, int]]] = {}
    for m in d["metadatas"]:
        n = RE_ARTICULO.match(m.get("encabezado", ""))
        if n:
            salida.setdefault(int(n.group(1)), set()).add((m["documento"], int(m["pagina"])))
    return salida


def sonda_articulos(recuperadores: dict, articulos: dict[int, set], ks=(1, 3, 5)) -> list[dict]:
    """SONDA SINTÉTICA (no es parte del set de evaluación): la consulta «artículo N de la Ley» debería traer una página de ese artículo. Mide la búsqueda por
    número de artículo, donde se espera que BM25 (los números son términos exactos) supere a los embeddings."""
    filas = []
    for nombre, rec in recuperadores.items():
        aciertos = {k: 0 for k in ks}
        for n, paginas in articulos.items():
            r = rec(f"artículo {n} de la Ley", max(ks))
            pos = next((i for i, x in enumerate(r, start=1) if (x.documento, x.pagina) in paginas), None)
            for k in ks:
                aciertos[k] += pos is not None and pos <= k
        filas.append({"variante": nombre, "consultas": len(articulos), **{f"recall@{k}": round(aciertos[k] / len(articulos), 3) for k in ks}})
    return filas


def recuperador(cfg, col, emb, modo: str, lexico: dict):
    k1, b = cfg.get("retrieval.bm25.k1"), cfg.get("retrieval.bm25.b")
    if modo == "semantico":
        return lambda t, k: buscar_semantico(col, emb, t, k)
    if modo == "bm25":
        return lambda t, k: buscar_bm25(col, emb, t, k, k1=k1, b=b, **lexico)
    return lambda t, k: buscar_hibrido(col, emb, t, k, rrf_k=cfg.get("retrieval.hibrido.rrf_k"), candidatos=cfg.get("retrieval.hibrido.candidatos"), k1=k1, b=b, **lexico)


def fila_resumen(nombre: str, modo: str, ev, ks) -> dict:
    r = ev.resumen()
    return {"variante": nombre, "modo": modo, **{k: (round(v, 3) if v is not None else None) for k, v in r.items()}, "fallos@3": len(ev.fallos(3)), "preguntas_in_domain": len(ev._en_dominio())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", metavar="VARIANTE", help="escribe el modo (y el stemming) de esa variante en config.yaml: retrieval.modo y retrieval.bm25.stemming")
    args = ap.parse_args(argv)
    cfg = cargar_config(cargar_env=False)
    preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
    emb, col = crear_embedder(cfg), abrir_para_lectura(cfg)
    ks = tuple(cfg.get("eval.ks"))
    evals = {}
    for nombre, modo, lexico in VARIANTES:
        evals[nombre] = (modo, lexico, evaluar_recuperacion(preguntas, recuperador(cfg, col, emb, modo, lexico), ks))
    filas = [fila_resumen(n, m, ev, ks) for n, (m, _, ev) in evals.items()]

    # por cifras en la pregunta (números de artículo, montos, plazos)
    con_cifras = {q.id for q in preguntas if q.tipo == "in_domain" and RE_CIFRAS.search(q.pregunta)}
    for f, (n, (_, _, ev)) in zip(filas, evals.items()):
        f["n_con_cifras"] = len(con_cifras)
        f["recall@3_con_cifras"] = round(ev.recall(3, lambda x: x.id in con_cifras), 3) if con_cifras else None
        f["recall@3_sin_cifras"] = round(ev.recall(3, lambda x: x.id not in con_cifras), 3)

    # por pregunta: posición del acierto en cada variante
    por_pregunta = []
    q_por_id = {q.id: q for q in preguntas}
    for i, q in enumerate(x for x in preguntas if x.tipo == "in_domain"):
        fila = {"id": q.id, "estilo": q.estilo, "modificada_2026": q.modificada_2026, "con_cifras": q.id in con_cifras, "pregunta": q.pregunta}
        for n, (_, _, ev) in evals.items():
            r = next(x for x in ev.por_pregunta if x.id == q.id)
            fila[n] = r.rango_acierto
        por_pregunta.append(fila)
    sem, bm, hib = "semantico", "bm25", "hibrido_rrf_stem"

    def gana(a: str, b: str, k: int = 3):
        """Preguntas donde `a` acierta en el top-k y `b` no."""
        ok = lambda v: v is not None and v <= k
        return [f for f in por_pregunta if ok(f[a]) and not ok(f[b])]

    articulos = articulos_de_la_ley(col)
    sonda = sonda_articulos({n: recuperador(cfg, col, emb, m, l) for n, (m, l, _) in evals.items()}, articulos, ks)

    salida = cfg.ruta("eval_results")
    escribir_csv(salida / "retrievers_sonda_articulos.csv", sonda)
    escribir_csv(salida / "retrievers_comparacion.csv", filas)
    escribir_csv(salida / "retrievers_por_pregunta.csv", por_pregunta)
    escribir_atomico(salida / "retrievers_comparacion.json", json.dumps({"filas": filas, "por_pregunta": por_pregunta, "sonda_articulos": sonda}, ensure_ascii=False, indent=1) + "\n")

    cols = [("variante", "Variante", ""), ("recall@1", "R@1", ".3f"), ("recall@3", "R@3", ".3f"), ("recall@5", "R@5", ".3f"), ("mrr", "MRR", ".3f"),
            ("recall@3_coloquial", "R@3 coloquial", ".3f"), ("recall@3_juridico", "R@3 jurídico", ".3f"), ("recall@3_modificatoria", "R@3 modificatoria", ".3f"),
            ("recall@3_con_cifras", "R@3 con cifras", ".3f"), ("recall@3_sin_cifras", "R@3 sin cifras", ".3f"), ("fallos@3", "Fallos@3", "")]
    def lista(items):
        return "\n".join(f"- **{f['id']}** ({f['estilo']}{', modificada' if f['modificada_2026'] else ''}): {f['pregunta']} — rangos: semántico {f[sem]}, BM25 {f[bm]}, híbrido {f[hib]}" for f in items) or "- (ninguna)"
    md = ["# BM25 frente a búsqueda semántica", "", aviso_set(cfg) +
          f"Los MISMOS {len(col.get()['ids'])} fragmentos (`{cfg.get('chunking.activa')}`), modelo de embeddings `{emb.name}`, búsqueda exacta, {sum(q.tipo == 'in_domain' for q in preguntas)} preguntas del dominio. "
          f"BM25: k1={cfg.get('retrieval.bm25.k1')}, b={cfg.get('retrieval.bm25.b')}; híbrido: RRF con k={cfg.get('retrieval.hibrido.rrf_k')} sobre los {cfg.get('retrieval.hibrido.candidatos')} mejores de cada lista. "
          "Sin llamar al LLM.", "",
          tabla_markdown(filas, cols), "",
          "«Con cifras» = la pregunta contiene algún dígito (número de artículo, monto o plazo).", "",
          "## Preguntas que acierta el semántico en el top-3 y BM25 no", "", lista(gana(sem, bm)), "",
          "## Preguntas que acierta BM25 en el top-3 y el semántico no", "", lista(gana(bm, sem)), "",
          "## Preguntas que acierta el híbrido en el top-3 y el semántico no", "", lista(gana(hib, sem)), "",
          "## Preguntas que acierta el semántico en el top-3 y el híbrido no", "", lista(gana(sem, hib)), "",
          f"## Sonda sintética: búsqueda por número de artículo ({len(articulos)} consultas «artículo N de la Ley»)", "",
          "No forma parte del set de evaluación (que no tiene ninguna pregunta con cifras): se genera a partir del propio índice. Una consulta acierta si alguna de las k páginas "
          "recuperadas es una donde el encabezado del fragmento es ese artículo.", "",
          tabla_markdown(sonda, [("variante", "Variante", ""), ("consultas", "Consultas", ""), ("recall@1", "R@1", ".3f"), ("recall@3", "R@3", ".3f"), ("recall@5", "R@5", ".3f")]), "",
          "**Limitación:** con 21 preguntas, una pregunta pesa 4,8 puntos de Recall: las diferencias de un solo caso no son concluyentes.", ""]
    escribir_atomico(salida / "retrievers_comparacion.md", "\n".join(md))
    print(tabla_markdown(filas, cols))
    if args.aplicar:
        import os
        elegido = next((v for v in VARIANTES if v[0] == args.aplicar), None)
        if not elegido:
            print(f"Variante desconocida: {args.aplicar}", file=sys.stderr)
            return 2
        p = cfg.archivo
        s = p.read_text(encoding="utf-8")
        s, n1 = re.subn(r"(?m)^(  modo: )\w+(.*)$", rf"\g<1>{elegido[1]}\g<2>", s, count=1)
        s, n2 = re.subn(r"(?m)^(    stemming: )\w+(.*)$", rf"\g<1>{'true' if elegido[2].get('stemming') else 'false'}\g<2>", s, count=1)
        s, n3 = re.subn(r"(?m)^(    usar_encabezado: )\w+(.*)$", rf"\g<1>{'true' if elegido[2].get('usar_encabezado', True) else 'false'}\g<2>", s, count=1)
        assert n1 == n2 == n3 == 1 and len(s) > 1000
        tmp = p.with_suffix(".yaml.tmp"); tmp.write_text(s, encoding="utf-8"); os.replace(tmp, p)
        print(f"config.yaml: retrieval.modo = {elegido[1]}; retrieval.bm25.stemming = {elegido[2].get('stemming', False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
