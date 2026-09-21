"""Troceado de páginas en fragmentos.

Reglas de diseño (cada una previene un error concreto):
  * Se trocea DENTRO de cada página. Nunca se une un documento en un solo texto para trocearlo después: se perderían las
    citas. Cada fragmento nace con su ``pagina`` (y ``documento``/``version``) y no contiene texto de otra página.
  * El PDF corta las líneas a mitad de frase; se reagrupan en párrafos (una línea en blanco o el inicio de un numeral,
    literal o encabezado abre un párrafo nuevo). Los fragmentos se cortan en límites de párrafo o de frase y, solo si
    hace falta, en límites de palabra; nunca a mitad de palabra.
  * El ID es estable entre corridas y único entre documentos: ``documento:version:p0012:c003:<hash de la config>``.
    No hay UUID ni contadores globales. El hash de la config hace que dos índices con troceados distintos no se pisen.
  * Las menciones de artículos se guardan SEPARADAS por norma: la Ley 32069 y su Reglamento numeran sus artículos por
    separado (el art. 98 de la Ley y el 98 del Reglamento son cosas distintas). Los números fuera de rango son errores
    de OCR y se descartan; las menciones a otras normas (p. ej. el TUO de la Ley 27444) no cuentan.
  * Contexto de encabezado: el último encabezado de artículo visto (incluso el de la página anterior) se antepone al texto
    que se EMBEBE, no al que se muestra. Así «93.1 … prescriben a los cuatro años» hereda «Artículo 93. Prescripción…».
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

VERSION_ALGORITMO = 1

RE_INICIO_PARRAFO = re.compile(
    r"^(?:[“\"]?Art[ií]culo\b|CAP[IÍ]TULO\b|T[IÍ]TULO\b|SUBCAP|SECCI[OÓ]N\b|DISPOSICI|ANEXO\b|"
    r"\(?\d{1,3}(?:\.\d+)+\.?\s|\d{1,3}\.\s|\(?[a-z]{1,2}\)\s|[ivxIVX]{1,4}\)\s|\(…\)|\(\.\.\.\))")
RE_ENCABEZADO = re.compile(r"^[“\"]?Art[ií]culo\s+(\d{1,3})\s*[.,\-–:]\s*([^.]{3,90})")
RE_ENCABEZADO_LINEA = re.compile(r"^(?:[“\"]?Art[ií]culo\s+\d{1,3}\s*[.,\-–:]\s*[^.]{3,90}|(?:CAP[IÍ]TULO|T[IÍ]TULO|SUBCAP[IÍ]TULO|SECCI[OÓ]N)\b[^.]{0,140}|[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 ,\-–]{3,119})$")
RE_NUMERAL_FINAL = re.compile(r"\(?\d{1,3}(?:\.\d+)*\.")   # "1." "67.3." "Artículo 93." terminan en punto pero NO cierran una frase
RE_MENCION = re.compile(
    r"\bart[ií]culos?\s+(?P<lista>\d{1,3}(?:\.\d+)?(?:\s*(?:,|y|e|al|a)\s*\d{1,3}(?:\.\d+)?)*)(?=(?P<cola>.{0,60}))", re.I | re.S)     # la cola es una mirada hacia delante: NO consume la siguiente mención
RE_NORMA_LEY = re.compile(r"^\W{0,3}(?:de\s+la\s+|de\s+esta\s+)(?:presente\s+)?ley\b(?P<num>\s*N[º°o.]*\s*(?P<n>\d[\d.]*))?", re.I)
RE_NORMA_REGLAMENTO = re.compile(r"^\W{0,3}(?:del?\s+(?:presente\s+)?)reglamento\b", re.I)
RE_OTRA_NORMA = re.compile(r"^\W{0,3}(?:del|de\s+la|de\s+los)\s+(?:texto\s+[uú]nico|decreto|c[oó]digo|constituci[oó]n|resoluci[oó]n|ley\s+n)", re.I)
LEY_PRINCIPAL = "32069"


@dataclass(frozen=True)
class ConfigChunk:
    nombre: str
    tamano: int
    solapamiento: int
    contexto_encabezado: bool = True
    unidad: str = "caracteres"

    @property
    def hash(self) -> str:
        base = f"{self.unidad}|{self.tamano}|{self.solapamiento}|{int(self.contexto_encabezado)}|v{VERSION_ALGORITMO}"
        return hashlib.sha1(base.encode()).hexdigest()[:8]


@dataclass
class Fragmento:
    id: str
    documento: str
    version: str
    pagina: int
    es_ocr: bool
    posicion: int
    texto: str                         # lo que se muestra y se cita
    texto_embedding: str               # lo que se convierte en vector (con el contexto de encabezado, si lo hay)
    articulos_ley: list[int] = field(default_factory=list)
    articulos_reglamento: list[int] = field(default_factory=list)
    encabezado: str = ""
    hash_texto: str = ""

    def metadatos(self) -> dict:
        """Metadatos escalares (ChromaDB solo admite str/int/float/bool). Las listas van como ",64,71," para poder filtrar."""
        lista = lambda xs: "," + ",".join(map(str, xs)) + "," if xs else ""
        return {"documento": self.documento, "version": self.version, "pagina": self.pagina, "es_ocr": self.es_ocr,
                "posicion": self.posicion, "articulos_ley": lista(self.articulos_ley),
                "articulos_reglamento": lista(self.articulos_reglamento), "encabezado": self.encabezado,
                "hash_texto": self.hash_texto, "caracteres": len(self.texto)}


# ───────────────────────── párrafos y unidades ─────────────────────────

def parrafos(texto: str) -> list[str]:
    """Reagrupa las líneas cortadas del PDF en párrafos."""
    salida: list[str] = []
    actual: list[str] = []
    for linea in texto.split("\n"):
        l = linea.strip()
        if not l:
            if actual:
                salida.append(" ".join(actual))
                actual = []
            continue
        if actual and RE_INICIO_PARRAFO.match(l):
            salida.append(" ".join(actual))
            actual = []
        actual.append(l)
    if actual:
        salida.append(" ".join(actual))
    return [re.sub(r"\s+", " ", p).strip() for p in salida if p.strip()]


def _dividir_frases(p: str) -> list[str]:
    """Divide en frases (fin en . ; :) sin cortar tras el punto de un numeral («67.3.», «Artículo 93.»)."""
    partes, ini = [], 0
    for m in re.finditer(r"[.;:]\s+", p):
        token = re.search(r"(\S+)$", p[:m.start() + 1]).group(1)
        if RE_NUMERAL_FINAL.fullmatch(token):
            continue
        partes.append(p[ini:m.end()].strip())
        ini = m.end()
    partes.append(p[ini:].strip())
    return [x for x in partes if x]


def _partir_largo(p: str, tamano: int) -> list[str]:
    """Parte un párrafo más largo que `tamano` en frases y, si una sola frase no cabe, en límites de palabra."""
    piezas: list[str] = []
    for f in _dividir_frases(p):
        while len(f) > tamano:
            corte = f.rfind(" ", 0, tamano)
            corte = corte if corte > 0 else tamano
            piezas.append(f[:corte].strip())
            f = f[corte:].strip()
        if f:
            piezas.append(f)
    return piezas


def _cola_de_solape(texto: str, solapamiento: int) -> str:
    """Últimos ~`solapamiento` caracteres, empezando en un límite de palabra."""
    if solapamiento <= 0 or len(texto) <= solapamiento:
        return "" if solapamiento <= 0 else texto
    cola = texto[-solapamiento:]
    i = cola.find(" ")
    return cola[i + 1:].strip() if i != -1 else ""


def _trocear_con_indices(pars: list[str], tamano: int, solapamiento: int) -> list[tuple[str, int]]:
    """Fragmentos de UNA página como (texto, índice del párrafo donde empieza su contenido NUEVO, sin contar el solape)."""
    if solapamiento >= tamano:
        raise ValueError("el solapamiento debe ser menor que el tamaño")
    unidades: list[tuple[str, int]] = []
    pegados: list[str] = []                                   # encabezados cortos que esperan a su párrafo
    for k, p in enumerate(pars):
        if RE_ENCABEZADO_LINEA.match(p) and k < len(pars) - 1:
            pegados.append(p)
            continue
        cuerpo = "\n".join(pegados + [p]) if pegados else p
        pegados = []
        # el índice es el del párrafo de cuerpo: los encabezados pegados quedan antes, así que ya están "vigentes"
        unidades += [(x, k) for x in (_partir_largo(cuerpo, tamano) if len(cuerpo) > tamano else [cuerpo])]
    fragmentos: list[tuple[str, int]] = []
    actual, par_inicio = "", 0
    for u, k in unidades:
        candidato = f"{actual}\n{u}" if actual else u
        if actual and len(candidato) > tamano:
            fragmentos.append((actual, par_inicio))
            cola = _cola_de_solape(actual.replace("\n", " "), solapamiento)
            actual = f"{cola} {u}" if cola and len(cola) + 1 + len(u) <= tamano else u
            par_inicio = k
        else:
            if not actual:
                par_inicio = k
            actual = candidato
    if actual:
        fragmentos.append((actual, par_inicio))
    return fragmentos


def trocear_texto(texto: str, tamano: int, solapamiento: int) -> list[str]:
    """Trocea el texto de UNA página. Cada fragmento mide como máximo `tamano` caracteres."""
    return [t for t, _ in _trocear_con_indices(parrafos(texto), tamano, solapamiento)]


# ───────────────────────── menciones de artículos ─────────────────────────

def extraer_menciones(texto: str, rol_documento: str, maximo: dict[str, int]) -> tuple[list[int], list[int]]:
    """(artículos de la Ley, artículos del Reglamento) mencionados. `rol_documento`: norma_base | reglamento | modificatoria."""
    por_defecto = "ley" if rol_documento == "norma_base" else "reglamento"
    ley: set[int] = set()
    reglamento: set[int] = set()
    plano = re.sub(r"\s+", " ", texto)
    for m in RE_MENCION.finditer(plano):
        cola = m.group("cola")
        if RE_OTRA_NORMA.match(cola) and not RE_NORMA_LEY.match(cola):
            continue
        norma = por_defecto
        ml = RE_NORMA_LEY.match(cola)
        if ml:
            if ml.group("n") and ml.group("n").replace(".", "") != LEY_PRINCIPAL:
                continue                                  # otra ley (p. ej. la 27444)
            norma = "ley"
        elif RE_NORMA_REGLAMENTO.match(cola):
            norma = "reglamento"
        for n in re.findall(r"\d{1,3}(?:\.\d+)?", m.group("lista")):
            num = int(n.split(".")[0])
            if 1 <= num <= maximo[norma]:
                (ley if norma == "ley" else reglamento).add(num)
    return sorted(ley), sorted(reglamento)


def _encabezado_de(parrafo: str, rol: str, maximo: dict[str, int]) -> str | None:
    m = RE_ENCABEZADO.match(parrafo)
    if not m:
        return None
    n = int(m.group(1))
    tope = maximo["ley"] if rol == "norma_base" else maximo["reglamento"]
    return f"Artículo {n}. {m.group(2).strip()}" if 1 <= n <= tope else None


# ───────────────────────── documento completo ─────────────────────────

def trocear_documento(doc: dict, paginas: list[dict], cfg: ConfigChunk, maximo: dict[str, int]) -> list[Fragmento]:
    """Fragmentos de un documento, página por página. `paginas`: entradas de data/processed/<doc>/ (cualquier orden)."""
    resultado: list[Fragmento] = []
    encabezado_actual = ""                      # el último encabezado visto, incluso el de la página anterior
    for entrada in sorted(paginas, key=lambda e: e["pagina"]):
        pars = parrafos(entrada["texto"])
        encabezados = {k: h for k, p in enumerate(pars) if (h := _encabezado_de(p, doc["rol"], maximo))}
        for pos, (t, par_inicio) in enumerate(_trocear_con_indices(pars, cfg.tamano, cfg.solapamiento)):
            vigente = encabezado_actual
            for k in sorted(encabezados):
                if k <= par_inicio:
                    vigente = encabezados[k]
            contexto = vigente if cfg.contexto_encabezado else ""
            emb = f"{contexto}\n{t}" if contexto else t
            ley, reg = extraer_menciones(t, doc["rol"], maximo)
            resultado.append(Fragmento(
                id=f"{doc['id']}:{doc['version']}:p{entrada['pagina']:04d}:c{pos:03d}:{cfg.hash}",
                documento=doc["id"], version=doc["version"], pagina=entrada["pagina"], es_ocr=entrada["origen"] == "ocr",
                posicion=pos, texto=t, texto_embedding=emb, articulos_ley=ley, articulos_reglamento=reg,
                encabezado=contexto, hash_texto=hashlib.sha1(emb.encode()).hexdigest()[:12]))
        if encabezados:
            encabezado_actual = encabezados[max(encabezados)]
    return resultado
