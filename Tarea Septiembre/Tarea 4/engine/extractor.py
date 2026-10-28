"""Extracción de campos estructurados a partir de la transcripción.

Dos caminos con la misma interfaz `extract(transcript, schema) -> dict`:
  - RuleExtractor: regex en español + léxicos del config (glosario y carta). Sin red, determinista.
  - LLMExtractor: API de Anthropic; el prompt vive en config.yaml (`llm.prompts`) y devuelve JSON.

`schema` es "interview" o "sales" (claves de `schemas` en config.yaml). Siempre se devuelven todas las claves del
schema: lo que no se encuentra queda en None (o [] en listas). Para ventas se captura la orden FINAL, es decir,
después de las correcciones del cliente.
"""
import json
import os
import re

from .validator import normalize_spoken_numbers, sin_acentos, verify_record

FLAGS = re.IGNORECASE


# ── Utilidades comunes ────────────────────────────────────────────────────────

def _preparar(texto):
    """Expande abreviaturas con punto (para no cortar oraciones) y pasa los números hablados a dígitos."""
    t = re.sub(r"\bAv\.", "Avenida", texto)
    t = re.sub(r"\bJr\.", "Jirón", t)
    t = re.sub(r"\b[Dd]e?pto\.?", "departamento", t)
    return normalize_spoken_numbers(t)


def _oraciones(texto):
    """[(inicio, fin, texto)] cortando en . ? ! (las abreviaturas ya vienen expandidas)."""
    return [(m.start(), m.end(), m.group(0).strip()) for m in re.finditer(r"[^.?!]+[.?!]*", texto) if m.group(0).strip()]


def _indice_oracion(oraciones, pos):
    for i, (a, b, _) in enumerate(oraciones):
        if a <= pos < b:
            return i
    return len(oraciones) - 1


def _contexto(oraciones, pos):
    """(oración, oración previa + oración) en minúsculas y sin tildes."""
    i = _indice_oracion(oraciones, pos)
    actual = sin_acentos(oraciones[i][2].lower())
    previa = sin_acentos(oraciones[i - 1][2].lower()) if i > 0 else ""
    return actual, previa + " " + actual


def _num_salida(x):
    x = round(float(x), 2)
    return int(x) if x == int(x) else x


def _a_numero(tok):
    tok = tok.lower()
    if tok in ("un", "una", "uno"):
        return 1.0
    return float(tok.replace(",", "."))


# ── Entrevistas ───────────────────────────────────────────────────────────────

_NUM = r"(\d+(?:[.,]\d+)?|un|una)"
_POS_ANIOS = ("experiencia", "total", "llevo", "llevas", "trabajando", "rubro", "tiempo", "serian", "ya van",
              "empece", "practicas", "sector", "area")
_NEG_ANIOS = ("equipos", "estados unidos", "ingles", "contrato", "aviso", "ganaba", "anterior", "ciclo")


def _anios_experiencia(t):
    cands = []  # (inicio, fin, valor, preciso)
    for m in re.finditer(rf"\b{_NUM}\s+años?\s+(?:y\s+)?{_NUM}\s+mes(?:es)?\b", t, FLAGS):
        cands.append((m.start(), m.end(), _a_numero(m.group(1)) + _a_numero(m.group(2)) / 12, True))
    for m in re.finditer(rf"\b{_NUM}\s+años?\s+y\s+medio\b", t, FLAGS):
        cands.append((m.start(), m.end(), _a_numero(m.group(1)) + 0.5, False))
    for m in re.finditer(r"\baños?\s+y\s+medio\b", t, FLAGS):
        cands.append((m.start(), m.end(), 1.5, False))
    for m in re.finditer(rf"\b{_NUM}\s+años?\b", t, FLAGS):
        cands.append((m.start(), m.end(), _a_numero(m.group(1)), False))
    for m in re.finditer(r"\b(\d+)\s+meses\b", t, FLAGS):
        cands.append((m.start(), m.end(), int(m.group(1)) / 12, False))
    # Si dos candidatos se pisan se queda el más largo (p. ej. "1 año 8 meses" gana a "1 año" y a "8 meses").
    cands.sort(key=lambda c: (c[0], -(c[1] - c[0])))
    kept = []
    for c in cands:
        if all(c[0] >= k[1] or c[1] <= k[0] for k in kept):
            kept.append(c)
    mejor, mejor_puntaje = None, None
    for ini, fin, valor, preciso in kept:
        ctx = sin_acentos(t[max(0, ini - 70): fin + 50].lower())
        puntaje = 2 * sum(w in ctx for w in _POS_ANIOS) - 3 * sum(w in ctx for w in _NEG_ANIOS) + (1 if preciso else 0)
        if mejor_puntaje is None or puntaje > mejor_puntaje:
            mejor, mejor_puntaje = valor, puntaje
    return None if mejor is None else _num_salida(mejor)


_ROLES = (r"analista|desarrolladora?|asistente|coordinador[a]?|practicante|gerente|jefe|jefa|ingeniero|ingeniera|"
          r"dise[ñn]ador[a]?|administrador[a]?|contador[a]?|vendedor[a]?|ejecutiv[oa]|supervisor[a]?|especialista|"
          r"consultor[a]?|auxiliar|t[eé]cnic[oa]|programador[a]?|community manager|l[ií]der|director[a]?|encargad[oa]|"
          r"reclutador[a]?|secretari[oa]|cajer[oa]")
_FIN_PUESTO = r"(?=\s+en\s+(?:una?|la|el|mi|las|los)\b|\s+(?:pero|donde|durante|desde|hasta|por\s+\d|hace)\b|[.,;:?!]|$)"


def _ultimo_puesto(t):
    patrones = [
        rf"(?:mi\s+)?[uú]ltimo\s+(?:puesto|cargo)\s+(?:fue|era)\s+(?:como\s+)?(?P<v>[^.,;?!]+?){_FIN_PUESTO}",
        rf"\b(?:mi\s+)?(?:cargo|puesto)\s+(?:era|fue)\s+(?:como\s+)?(?P<v>[^.,;?!]+?){_FIN_PUESTO}",
        rf"\b(?:fui|era|trabajé\s+como|trabaje\s+como|me\s+desempeñé\s+como|estuve\s+como)\s+(?:el\s+|la\s+|un\s+|una\s+)?"
        rf"(?P<v>(?:{_ROLES})[^.,;?!]*?){_FIN_PUESTO}",
    ]
    for p in patrones:
        m = re.search(p, t, FLAGS)
        if m:
            return m.group("v").strip()
    m = re.search(r"\bcoordin(?:ar|é|e|aba|ando)\s+(?:todo\s+)?(?:el\s+)?equipo\s+de\s+(?P<a>[^.,;?!]+?)"
                  r"(?=\s+en\s+(?:una?|la|el)\b|[.,;?!]|$)", t, FLAGS)
    if m:  # "coordiné el equipo de marketing digital" -> "coordinador de marketing digital"
        return f"coordinador de {m.group('a').strip()}"
    return None


_ALIAS_TECNOLOGIAS = {
    "Node.js": ["node.js", "node js", "nodejs"], "Power BI": ["power bi", "powerbi"],
    "PostgreSQL": ["postgresql", "postgres"], "JavaScript": ["javascript", "java script"],
    "AWS": ["aws", "amazon web services"], "GitHub": ["github", "git hub"], "Meta Ads": ["meta ads", "facebook ads"],
}


def _tecnologias(t, glosario):
    encontrados = []  # (posición, canónico)
    for termino in glosario:
        variantes = _ALIAS_TECNOLOGIAS.get(termino, [termino.lower()])
        pos = [m.start() for v in variantes for m in re.finditer(rf"(?<![\w.]){re.escape(v)}(?![\w])", t, FLAGS)]
        if pos:
            encontrados.append((min(pos), termino))
    for pos, termino in _tecnologias_en_listas(t):
        if not any(termino.lower() == c.lower() for _, c in encontrados):
            encontrados.append((pos, termino))
    return [c for _, c in sorted(encontrados)]


_DISPARA_TECNOLOGIAS = (r"(?:manejo|manejaba|conozco|domino|dominio|utilizo|uso|trabajo\s+con|trabajaba\s+con|"
                        r"trabajé\s+con|experiencia\s+(?:en|con))")
_CORTA_LISTA = r"\b(?:pero|aunque|adem[aá]s|durante|desde|hace|para|porque|y\s+tambi[eé]n)\b"


def _tecnologias_en_listas(t):
    """Herramientas fuera del glosario: lista tras 'manejo/conozco/trabajo con…' ("Python, SQL y Power BI").

    Solo acepta ítems de hasta 3 palabras que empiecen en mayúscula o lleven dígito/punto (nombres propios de
    herramienta), para no tomar frases comunes. Devuelve (posición, nombre).
    """
    out = []
    for m in re.finditer(rf"\b{_DISPARA_TECNOLOGIAS}\s+(?P<l>[^.;?!]+)", t, FLAGS):
        lista = re.split(_CORTA_LISTA, m.group("l"), maxsplit=1, flags=FLAGS)[0]
        base = m.start("l")
        for it in re.finditer(r"[^,]+", re.sub(r"\s+(?:y|e)\s+(?=[A-ZÁÉÍÓÚ\d])", ", ", lista)):
            nombre = it.group().strip()
            nombre = re.sub(r"^(?:tambi[eé]n\s+|el\s+|la\s+|los\s+|las\s+|de\s+)", "", nombre, flags=FLAGS).strip()
            if nombre and len(nombre.split()) <= 3 and re.match(r"[A-ZÁÉÍÓÚ]|.*[\d.]", nombre):
                out.append((base + it.start(), nombre))
    return out


_POS_SUELDO = ("pretensi", "buscand", "busco", "esper", "expectativa", "sueldo", "salario", "ganar", "alrededor",
               "mensual", "remuner")
_NEG_SUELDO = ("ganaba", "anterior", "antes")


def _pretension_salarial(t):
    oraciones = _oraciones(t)
    cands = []
    for m in re.finditer(r"(?:s/\.?\s*(\d+(?:\.\d+)?))|(?<![\d.])(\d+(?:\.\d+)?)\s*(?:soles|sol)\b", t, FLAGS):
        valor = float(m.group(1) or m.group(2))
        if valor < 300:  # descarta precios chicos y cantidades
            continue
        actual, ctx = _contexto(oraciones, m.start())
        puntaje = 2 * sum(w in ctx for w in _POS_SUELDO) - 3 * sum(w in actual for w in _NEG_SUELDO)
        cands.append((puntaje, -m.start(), valor))
    # También cifras sueltas sin "soles" (respuesta a "¿cuánto esperas ganar?"): penalizadas para preferir las que lo dicen.
    for m in re.finditer(r"(?<![\d.,])(\d{3,6})(?![\d]|\s*(?:años?|meses|mes|semanas?|d[ií]as?))", t):
        if any(-c[1] == m.start() for c in cands) or any(abs(-c[1] - m.start()) < 3 for c in cands):
            continue
        actual, ctx = _contexto(oraciones, m.start())
        if not any(w in ctx for w in _POS_SUELDO):
            continue
        cands.append((2 * sum(w in ctx for w in _POS_SUELDO) - 3 * sum(w in actual for w in _NEG_SUELDO) - 1,
                      -m.start(), float(m.group(1))))
    return _num_salida(max(cands)[2]) if cands else None


_MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"
_CLAVES_DISPONIBILIDAD = ("disponib", "empezar", "comenzar", "libre", "aviso", "incorpor", "iniciar", "a partir")


def _disponibilidad(t):
    oraciones = _oraciones(t)
    for _, _, oracion in oraciones:
        actual, ctx = _contexto(oraciones, t.find(oracion))
        if not any(c in ctx for c in _CLAVES_DISPONIBILIDAD):
            continue
        if re.search(r"\binmediat[ao]\b", oracion, FLAGS):
            return "Inmediata"
        m = re.search(rf"\b(\d{{1,2}})\s+de\s+({_MESES})\b", oracion, FLAGS)
        if m:
            return f"{m.group(1)} de {m.group(2).lower()}"
        if re.search(r"\bpr[oó]xima\s+semana\b", oracion, FLAGS):
            return "Próxima semana"
        m = re.search(r"\b(\d+)\s+(semanas?|meses|mes|d[ií]as?)\b", oracion, FLAGS)
        if m:
            return f"{m.group(1)} {m.group(2).lower()}"
    return None


_NIVELES = [("Básico", r"b[aá]sico|elemental|principiante"), ("Intermedio", r"intermedio"),
            ("Avanzado", r"avanzado|fluido|nativo|biling[uü]e")]


def _nivel_ingles(t):
    oraciones = _oraciones(t)
    cands = []
    for nivel, patron in _NIVELES:
        for m in re.finditer(rf"\b(?:{patron})\b", t, FLAGS):
            _, ctx = _contexto(oraciones, m.start())
            if "ingles" in ctx:  # el nivel se dice en la oración del inglés o en la respuesta a la pregunta
                cands.append((m.start(), nivel))
    if not cands:
        return None
    # Cuando hay varios (p. ej. "intermedio alto ... cursos en inglés") se toma el primero que se dijo tras mencionar inglés.
    return sorted(cands)[0][1]


def _extraer_entrevista(t, config):
    glosario = config.get("domain_glossary", {}).get("tecnologias", [])
    return {
        "anios_experiencia": _anios_experiencia(t),
        "ultimo_puesto": _ultimo_puesto(t),
        "tecnologias": _tecnologias(t, glosario),
        "pretension_salarial": _pretension_salarial(t),
        "disponibilidad": _disponibilidad(t),
        "nivel_ingles": _nivel_ingles(t),
    }


# ── Ventas ────────────────────────────────────────────────────────────────────

_ARTICULOS = {"el", "la", "los", "las", "otro", "otra", "otros", "otras"}
_UNIDADES = {"porciones": "porción", "porcion": "porción", "jarras": "jarra", "jarra": "jarra", "vasos": None,
             "vaso": None, "botellas": None, "botella": None, "platos": None, "plato": None, "ordenes": None,
             "orden": None}
_PALABRAS_PRECIO = r"(?:\b(?:a|son|es|cuesta|cuestan|vale|valen)\s+(\d+(?:\.\d+)?))|(?::\s*(\d+(?:\.\d+)?))"
_PRECIO_SOLES = r"(?<![\d.])(\d+(?:\.\d+)?)\s+soles?\b"
_TAMANIOS = [(r"grandes?", "grande"), (r"personal(?:es)?", "personal"), (r"para compartir", "para compartir"),
             (r"medio litro", "medio litro"), (r"litro y medio", "1.5L")]
_METODOS_PAGO = [("Yape", r"yape"), ("Plin", r"plin"), ("Tarjeta", r"tarjeta"), ("Efectivo", r"efectivo"),
                 ("Transferencia", r"transferencia")]
_PROMOCIONES = r"promoci[oó]n|promo\b|happy hour|oferta|descuento|2x1|2 por uno|2 por 1|combo"
_UNIDADES_DIRECCION = {"departamento": "depto", "depto": "depto", "dpto": "depto", "piso": "piso",
                       "interior": "interior", "int": "interior", "oficina": "oficina", "lote": "lote", "mz": "mz",
                       "manzana": "mz"}


def _indice_menu(menu):
    entradas = [(sin_acentos(a.lower()), item) for item in menu for a in item["aliases"]]
    return sorted(entradas, key=lambda e: -len(e[0]))


def _menciones(s, entradas):
    menciones, ocupado = [], []
    for alias, item in entradas:
        for m in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", s):
            if any(m.start() < b and a < m.end() for a, b in ocupado):
                continue
            menciones.append((m.start(), m.end(), alias, item))
            ocupado.append((m.start(), m.end()))
    return sorted(menciones, key=lambda x: x[0])


def _cantidad_antes(s, inicio):
    """(cantidad|None, unidad|None) justo antes de una mención: '2 jarras de', 'una porción de', 'las 2'."""
    previo = re.split(r"[.?!;]", s[max(0, inicio - 60):inicio])[-1]
    toks = re.findall(r"[^\s,:¿¡]+", previo)
    i, unidad, cantidad = len(toks) - 1, None, None
    while i >= 0 and toks[i] in _ARTICULOS:
        i -= 1
    if i >= 1 and toks[i] == "de" and toks[i - 1] in _UNIDADES:
        unidad, i = toks[i - 1], i - 2
    elif i >= 0 and toks[i] in _UNIDADES:
        unidad, i = toks[i], i - 1
    while i >= 0 and toks[i] in _ARTICULOS:
        i -= 1
    if i >= 0 and (toks[i].isdigit() or toks[i] in ("un", "una", "uno")):
        cantidad = 1 if toks[i] in ("un", "una", "uno") else int(toks[i])
    return cantidad, unidad


def _tamanio_despues(s, fin):
    post = s[fin:fin + 30]
    for patron, nombre in _TAMANIOS:
        if re.match(rf"\s*(?:de\s+)?{patron}\b", post):
            return nombre
    return None


def _precio_en(segmento):
    """Precio de un segmento: primero un número suelto pegado al plato ('la chicha 8, en total 58 soles' -> 8) y luego
    'a 35 soles' / 'son 45 soles', ignorando precios de paquete ('por 70 soles')."""
    m = re.match(r"\s*(?:(?:grandes?|personal|para compartir|especial)\s+)*(\d+(?:\.\d+)?)\s*(?:,|\.|\by\b|$)", segmento)
    if m:
        return float(m.group(1))
    for m in re.finditer(rf"{_PALABRAS_PRECIO}|{_PRECIO_SOLES}", segmento):
        antes = segmento[:m.start()].rstrip()
        if antes.endswith(("por", "vez de")):
            continue
        return float(next(g for g in m.groups() if g))
    return None


def _items_venta(s, menu):
    entradas = _indice_menu(menu)
    menciones = _menciones(s, entradas)
    eventos = [(m[0], "m", m) for m in menciones]
    # Correcciones que sacan un plato del pedido: "cámbiame el tallarín por ...", "quítame la ensalada".
    for m in re.finditer(r"\bcambia(?:me|lo|r)?\s+(?:el|la|los|las)\s+(?P<old>[a-z ]+?)\s+por\b|"
                         r"\bquita(?:me|lo)?\s+(?:el|la|los|las)\s+(?P<old2>[a-z ]+?)(?=[,.;?!]|\s+y\b|$)|"
                         r"\bya no (?:quiero|va)\s+(?:el|la|los|las)?\s*(?P<old3>[a-z ]+?)(?=[,.;?!]|\s+y\b|$)", s):
        g = next(k for k in ("old", "old2", "old3") if m.group(k))
        eventos.append((m.end(g), "r", (m.start(g), m.end(g))))
    estado = {}  # clave del ítem -> datos
    for _, tipo, dato in sorted(eventos, key=lambda e: (e[0], e[1] == "m")):
        if tipo == "r":
            a, b = dato
            for ini, fin, alias, item in menciones:
                if a <= ini and fin <= b:
                    estado.pop(item["name"], None)
            continue
        ini, fin, alias, item = dato
        cantidad, unidad = _cantidad_antes(s, ini)
        reg = estado.setdefault(item["name"], {"item": item, "orden": ini, "cantidad": None, "precio": None,
                                               "tamanio": None})
        if cantidad is not None:
            reg["cantidad"] = cantidad
        tam = (_UNIDADES.get(unidad) if unidad else None) or _tamanio_despues(s, fin) or \
            ("1.5L" if "litro y medio" in alias else None)
        if tam:
            reg["tamanio"] = tam
        # Precio: texto entre esta mención y la siguiente (o el fin de la oración), solo si la oración habla de soles/cada.
        siguiente = next((x[0] for x in menciones if x[0] >= fin), None)
        corte = re.search(r"[?!]|\.(?!\d)", s[fin:])
        limite = min(x for x in (siguiente, fin + corte.start() if corte else None, fin + 90) if x is not None)
        precio = _precio_en(s[fin:limite])
        if precio is not None:
            reg["precio"] = precio
    items = []
    for nombre, reg in sorted(estado.items(), key=lambda kv: kv[1]["orden"]):
        item = reg["item"]
        variantes = item.get("variants")
        if variantes:  # "cuartos de pollo": "2 de pecho y 2 de pierna" se separa en dos ítems
            partes = {}
            for m in re.finditer(rf"(\d+|un|una|uno)\s+de\s+({'|'.join(variantes)})\b", s):
                partes[m.group(2)] = 1 if m.group(1) in ("un", "una", "uno") else int(m.group(1))
            if partes:
                for v, q in partes.items():
                    items.append({"plato": f"{nombre} {v}", "cantidad": q, "precio_unitario": reg["precio"]})
                continue
        plato = f"{nombre} {reg['tamanio']}" if item.get("size_in_name") and reg["tamanio"] else nombre
        fila = {"plato": plato, "cantidad": reg["cantidad"] or 1, "precio_unitario": reg["precio"]}
        if reg["tamanio"] and not item.get("size_in_name"):
            fila["tamaño"] = reg["tamanio"]
        items.append(fila)
    for it in items:
        if it["precio_unitario"] is not None:
            it["precio_unitario"] = _num_salida(it["precio_unitario"])
    return items


def _puntaje_promocion(oracion):
    bajo = sin_acentos(oracion.lower())
    return (3 * bool(re.search(r"happy hour|promocion|2x1|2 por (?:uno|1)|oferta|combo", bajo))
            + 2 * ("tenemos" in bajo) + 1 * ("promo" in bajo))


def _promocion(t):
    candidatas = [o for _, _, o in _oraciones(t) if re.search(_PROMOCIONES, sin_acentos(o.lower()))]
    if not candidatas:
        return None
    # La oferta la dice el operador ("Tenemos ..."); las menciones sueltas ("aplícame esa promo") puntúan menos.
    oracion = max(candidatas, key=lambda o: (_puntaje_promocion(o), len(o)))
    bajo = sin_acentos(oracion.lower())
    if re.search(r"2x1|2 por (?:uno|1)", bajo):
        return "2x1 en bebidas" if "bebida" in bajo else "2x1"
    m = re.search(r"(\w+)\s+(?:estan\s+)?a mitad de precio", bajo)
    if m:  # "Tenemos happy hour: las limonadas están a mitad de precio" -> "Happy hour: limonadas a mitad de precio"
        return f"{'Happy hour' if 'happy hour' in bajo else 'Promoción'}: {m.group(1)} a mitad de precio"
    m = re.search(r"promo(?:cion)?\s+(\w+)\s*:?\s*(.+?)\s+por\s+(\d+(?:\.\d+)?)", bajo)
    if m:  # paquete: "promo familiar: 4 cuartos más la gaseosa grande por 70" -> "Promo familiar: 4 cuartos + gaseosa por 70"
        cuerpo = re.sub(r"\b(?:el|la|los|las|grandes?)\s*", "", m.group(2)).replace(" mas ", " + ").strip(" ,:;")
        return f"Promo {m.group(1)}: {cuerpo} por {m.group(3)}"
    limpia = re.sub(r"^(?:\W*(?:ah|ok|listo|perfecto|entonces)\W+)*", "", oracion, flags=FLAGS)
    limpia = re.sub(r"^tenemos\s+(?:la|una|el)\s+", "", limpia, flags=FLAGS).strip(" .¿?!")
    limpia = re.sub(r"\s+soles\b", "", limpia)
    return limpia[:1].upper() + limpia[1:] if limpia else None


def _direccion(t):
    ancla = re.search(r"direcci[oó]n", t, FLAGS)
    desde = ancla.end() if ancla else 0
    m = re.search(r"\b(?P<tipo>Avenida|Calle|Jir[oó]n|Pasaje|Psje|Prolongaci[oó]n|Malec[oó]n|Alameda)\s+"
                  r"(?P<resto>[^.?!]+)", t[desde:], FLAGS)
    if not m:
        return None
    tipo = {"avenida": "Av.", "jiron": "Jr."}.get(sin_acentos(m.group("tipo").lower()), m.group("tipo").capitalize())
    toks = m.group("resto").replace(",", " ").split()
    idx = next((i for i, x in enumerate(toks) if x.isdigit()), None)
    if idx is None:
        return f"{tipo} {' '.join(toks)}"
    partes = [f"{tipo} {' '.join(toks[:idx + 1])}"]
    j = idx + 1
    while j + 1 < len(toks) and sin_acentos(toks[j].lower()) in _UNIDADES_DIRECCION:
        partes.append(f"{_UNIDADES_DIRECCION[sin_acentos(toks[j].lower())]} {toks[j + 1]}")
        j += 2
    if j < len(toks) and sin_acentos(toks[j].lower()) == "por":  # "... 3100, por Jesús María"
        j += 1
    if j < len(toks):
        partes.append(" ".join(toks[j:]))
    return ", ".join(partes)


def _metodo_pago(s):
    cands = []
    for nombre, patron in _METODOS_PAGO:
        for m in re.finditer(rf"\b{patron}\b", s):
            previo = s[max(0, m.start() - 100):m.start()]
            cands.append((bool(re.search(r"\bpag(?:o|a|ar|as)\b|metodo|forma de", previo)), m.start(), nombre))
    if not cands:
        return None
    con_contexto = [c for c in cands if c[0]]
    return (con_contexto or cands)[-1][2]


def _total_dicho(s):
    m = re.findall(r"\btotal(?:\s+(?:seria|serian|son|es|sera|a pagar))?\s*:?\s*(?:de\s+)?(\d+(?:\.\d+)?)", s)
    return _num_salida(m[-1]) if m else None


def _extraer_ventas(t, config):
    s = sin_acentos(t.lower())
    return {
        "items": _items_venta(s, config.get("menu", [])),
        "promocion": _promocion(t),
        "direccion_entrega": _direccion(t),
        "metodo_pago": _metodo_pago(s),
        "total_dicho": _total_dicho(s),
    }


# ── Interfaz pública ──────────────────────────────────────────────────────────

class RuleExtractor:
    """Extractor por reglas (regex en español). Usa el glosario y la carta de config.yaml como léxico."""

    def __init__(self, config):
        self.config = config

    def extract(self, transcript: str, schema: str) -> dict:
        t = _preparar(transcript)
        if schema == "interview":
            return _extraer_entrevista(t, self.config)
        if schema == "sales":
            return _extraer_ventas(t, self.config)
        raise ValueError(f"schema desconocido: {schema!r} (usa 'interview' o 'sales')")

    def extract_verified(self, transcript, schema):
        """Extrae y verifica cada campo contra la transcripción.

        Devuelve {"fields": {campo: valor}, "verificado": {campo: bool}, "estado": {campo: str}, "detalles": {...}}.
        `verificado` es True solo si el valor aparece literalmente en lo dicho (ver validator.verify_literal);
        un campo sin valor o con valor no hallado es False. `estado` conserva el matiz verificado/sin_verificar/sin_valor.
        """
        campos = self.extract(transcript, schema)
        estado, detalles = verify_record(campos, transcript)
        return {"fields": campos, "verificado": {k: v == "verificado" for k, v in estado.items()},
                "estado": estado, "detalles": detalles}


class LLMExtractor:
    """Extractor con la API de Anthropic. El prompt sale de config.yaml; la respuesta se parsea como JSON."""

    def __init__(self, config, client=None):
        self.config = config
        self.cfg = config["llm"]
        self._client = client

    def _get_client(self):
        if self._client is None:
            from dotenv import load_dotenv

            load_dotenv()
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("Falta ANTHROPIC_API_KEY (cópiala en .env; ver .env.example)")
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def build_prompt(self, transcript, schema):
        campos = "\n".join(f'- "{k}": {v}' for k, v in self.config["schemas"][schema].items())
        return self.cfg["prompts"][schema].format(transcript=transcript, fields=campos)

    def extract(self, transcript: str, schema: str) -> dict:
        if schema not in self.config["schemas"]:
            raise ValueError(f"schema desconocido: {schema!r}")
        kwargs = dict(model=self.cfg["model"], max_tokens=self.cfg.get("max_tokens", 2048),
                      system=self.cfg["prompts"]["system"],
                      messages=[{"role": "user", "content": self.build_prompt(transcript, schema)}],
                      output_config={"effort": self.cfg.get("effort", "low")})
        client = self._get_client()
        if self.cfg.get("use_fallbacks", True):
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            categoria = getattr(getattr(resp, "stop_details", None), "category", None)
            raise RuntimeError(f"el modelo rechazó la solicitud (categoría: {categoria})")
        texto = "".join(b.text for b in resp.content if b.type == "text")
        return self.parse_response(texto, schema)

    def parse_response(self, texto, schema):
        """Extrae el JSON de la respuesta (tolera ```json ... ``` y texto alrededor) y fija las claves del schema."""
        texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
        ini, fin = texto.find("{"), texto.rfind("}")
        if ini < 0 or fin < ini:
            raise ValueError(f"la respuesta del LLM no contiene JSON: {texto[:120]!r}")
        datos = json.loads(texto[ini:fin + 1])
        return {campo: datos.get(campo) for campo in self.config["schemas"][schema]}


def get_extractor(nombre, config):
    """'rules' -> RuleExtractor, 'llm' -> LLMExtractor."""
    if nombre == "rules":
        return RuleExtractor(config)
    if nombre == "llm":
        return LLMExtractor(config)
    raise ValueError(f"extractor desconocido: {nombre!r}")
