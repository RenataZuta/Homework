"""Validación de los registros extraídos contra la transcripción.

Tres piezas:
  - normalize_spoken_numbers: "seis mil quinientos" -> 6500 (regla de normalización del pipeline).
  - verify_literal: ¿el valor extraído existe en el texto transcrito? Primero forma literal, luego normalizada; si no, "sin_verificar".
  - validate_order_arithmetic: ¿cantidad × precio − promo = total dicho? Con diagnóstico ASR vs hablante.
"""
import difflib
import math
import re
import unicodedata

from text_to_num import alpha2digit

VERIFICADO = "verificado"
SIN_VERIFICAR = "sin_verificar"
SIN_VALOR = "sin_valor"

_PEQUENOS = {"dos": "2", "tres": "3"}  # text2num deja estas palabras sueltas cuando son < su umbral
_UNIDADES_TIEMPO = r"(?:a[ñn]os?|mes(?:es)?|semanas?|d[ií]as?|horas?)"
_ABREVIATURAS = {"av": "avenida", "jr": "jiron", "dpto": "departamento", "depto": "departamento",
                 "psje": "pasaje", "int": "interior"}
_BEBIDAS = ("chicha", "limonada", "inca kola", "coca", "gaseosa", "jugo", "cerveza", "agua", "bebida", "refresco")
_STOP_PROMO = {"promo", "promocion", "familiar", "la", "el", "los", "las", "de", "con", "y", "mas", "en", "vez",
               "por", "un", "una", "grande", "happy", "hour"}


# ── Normalización de texto y números ──────────────────────────────────────────

def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize_spoken_numbers(text):
    """Convierte números hablados en español a dígitos: "seis mil quinientos" -> 6500, "tres mil" -> 3000, "veinte" -> 20.

    Reglas de normalización (las usa verify_literal: primero compara literal y luego con esta forma):
      1. Cardinales compuestos -> un solo número: "ciento diez" -> 110, "mil doscientos cincuenta" -> 1250
         (librería text2num, `alpha2digit(texto, "es")`).
      2. "dos" y "tres" sueltos -> 2 y 3 (text2num los deja como palabra cuando están solos).
      3. "un/una" + unidad de tiempo -> 1: "un año ocho meses" -> "1 año 8 meses". Fuera de ese contexto "un" no se toca.
      4. Separador de miles: "4,500" y "4.500" -> "4500". Los decimales ("1.5") se conservan.
      5. Palabras que text2num confunde con números y se protegen: "unas/unos" (no son 1) y "cuartos de pollo"
         (ordinal 4º, no cantidad).
      6. Mayúsculas y acentos NO se alteran aquí; eso lo hace normalize_text (minúsculas, sin acentos ni puntuación,
         "Av." -> "avenida", "Jr." -> "jiron", "depto" -> "departamento").
    Límite conocido: variantes poco habituales como "veintiún" no las resuelve text2num y quedan como palabra.
    """
    if not text:
        return text
    # text2num convierte "unas" en 1 y "cuartos" en 4ᵒˢ: se protegen con un prefijo que no parece número y se restauran.
    protegido = re.sub(r"\b(cuartos?|unas|unos)\b", lambda m: "xq" + m.group(1), text, flags=re.IGNORECASE)
    out = re.sub(r"\bxq(?=(?:cuartos?|unas|unos)\b)", "", alpha2digit(protegido, "es"), flags=re.IGNORECASE)
    out = re.sub(r"\b(dos|tres)\b", lambda m: _PEQUENOS[m.group(1).lower()], out, flags=re.IGNORECASE)
    out = re.sub(rf"\b(un|una)\b(?=\s+{_UNIDADES_TIEMPO}\b)", "1", out, flags=re.IGNORECASE)
    out = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", out)  # separador de miles: 4,500 -> 4500
    return out


def normalize_text(text, numbers=True):
    """Minúsculas, sin acentos ni puntuación, abreviaturas expandidas y espacios simples."""
    t = normalize_spoken_numbers(text) if numbers else text
    t = sin_acentos(t.lower())
    t = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", t)
    t = re.sub(r"[^\w\s.]", " ", t)  # el punto se conserva un instante para decimales y abreviaturas
    t = re.sub(r"\b(av|jr|dpto|depto|psje|int)\.", lambda m: _ABREVIATURAS[m.group(1)], t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    t = re.sub(r"\b(" + "|".join(_ABREVIATURAS) + r")\b", lambda m: _ABREVIATURAS[m.group(1)], t)
    return re.sub(r"\s+", " ", t).strip()


def _stem(tok):
    """Singulariza de forma tosca para que 'lomos saltados' case con 'lomo saltado'."""
    if tok.isdigit() or len(tok) <= 3:
        return tok
    if tok.endswith("ces"):
        return tok[:-3] + "z"
    if tok.endswith("es") and len(tok) > 4:
        return tok[:-2]
    if tok.endswith("s"):
        return tok[:-1]
    return tok


def _tokens(text, numbers=True):
    return [_stem(t) for t in normalize_text(text, numbers).split()]


# ── Verificación literal ──────────────────────────────────────────────────────

def _numeros_en(texto_norm):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", texto_norm)]


def _numero_presente(valor, texto_norm):
    """¿Aparece `valor` como número en el texto? Acepta duraciones derivadas ("1 año 8 meses" -> 1.67)."""
    objetivo = float(valor)
    nums = _numeros_en(texto_norm)
    if any(abs(n - objetivo) < 0.01 for n in nums):
        return f"{objetivo:g}"
    if objetivo == 1 and re.search(r"\b(un|una|uno)\b", texto_norm):
        return "un/una"
    # Duraciones expresadas en años: "1 año 8 meses", "año y medio", "N años y medio", "6 meses".
    for m in re.finditer(r"(\d+(?:\.\d+)?|un|una)\s+anos?\s+(?:y\s+)?(\d+)\s+mes(?:es)?", texto_norm):
        anios = 1.0 if m.group(1) in ("un", "una") else float(m.group(1))
        if abs(anios + int(m.group(2)) / 12 - objetivo) < 0.01:
            return m.group(0)
    for m in re.finditer(r"(?:(\d+(?:\.\d+)?|un|una)\s+)?anos?\s+y\s+medio", texto_norm):
        anios = 1.0 if m.group(1) in (None, "un", "una") else float(m.group(1))
        if abs(anios + 0.5 - objetivo) < 0.01:
            return m.group(0)
    for m in re.finditer(r"(\d+)\s+mes(?:es)?", texto_norm):
        if abs(int(m.group(1)) / 12 - objetivo) < 0.01:
            return m.group(0)
    return None


def _cadena_presente(valor, transcript, numbers=True):
    """Devuelve (encontrado_como, coincidencia_cercana). Compara tokens normalizados y singularizados.

    `numbers=False` deja los números tal como se dijeron (paso literal); `True` los pasa a dígitos (paso normalizado).
    """
    v = _tokens(str(valor), numbers)
    t_norm = normalize_text(transcript, numbers).split()
    t = [_stem(x) for x in t_norm]
    if not v:
        return None, None
    n = len(v)
    for i in range(len(t) - n + 1):
        if t[i:i + n] == v:
            return " ".join(t_norm[i:i + n]), None
    # Sin coincidencia exacta: ¿hay algo casi igual? (típico de un error del ASR: "Payton" por "Python")
    mejor, mejor_ratio = None, 0.0
    objetivo = " ".join(v)
    for tam in {max(1, n - 1), n, n + 1}:
        for i in range(len(t) - tam + 1):
            ratio = difflib.SequenceMatcher(None, objetivo, " ".join(t[i:i + tam])).ratio()
            if ratio > mejor_ratio:
                mejor, mejor_ratio = " ".join(t_norm[i:i + tam]), ratio
    return None, (mejor if mejor_ratio >= 0.7 else None)


def _es_numero(valor):
    if isinstance(valor, bool):
        return False
    if isinstance(valor, (int, float)):
        return True
    return isinstance(valor, str) and re.fullmatch(r"\d+(?:\.\d+)?", valor.strip()) is not None


def verify_literal(value, transcript):
    """¿El valor extraído existe literalmente en la transcripción? Si no, queda `sin_verificar`.

    Se intenta en dos pasos, siempre en este orden:
      1. Forma literal: el valor tal cual aparece en lo dicho. Se compara sin mayúsculas, tildes ni puntuación, con
         abreviaturas expandidas ("Av." ~ "Avenida") y singularizando ("lomos" ~ "lomo"), pero SIN convertir números
         hablados: "seis mil quinientos" solo coincide con "seis mil quinientos", y 6500 solo con "6500"/"6.500".
      2. Forma normalizada (solo si el paso 1 falla): se pasan a dígitos los números hablados de ambos lados con
         `normalize_spoken_numbers`, así 6500 ~ "seis mil quinientos" y "2 semanas" ~ "dos semanas". Para números también
         se aceptan duraciones derivadas ("1 año ocho meses" -> 1.67).

    Devuelve {"status": "verificado" | "sin_verificar" | "sin_valor", "mode": "literal" | "normalizada" | None,
    "found_as": str|None, "near_match": str|None, "items": [...]}. `mode` dice con qué paso se verificó. Una lista queda
    verificada solo si todos sus elementos lo están. `near_match` señala un texto casi igual (probable error del ASR).
    """
    if value is None or value == "" or value == []:
        return {"status": SIN_VALOR, "mode": None, "found_as": None, "near_match": None, "items": []}
    if isinstance(value, (list, tuple)):
        items = [dict(verify_literal(v, transcript), value=v) for v in value]
        ok = all(i["status"] == VERIFICADO for i in items)
        return {"status": VERIFICADO if ok else SIN_VERIFICAR, "mode": None, "found_as": None,
                "near_match": next((i["near_match"] for i in items if i["near_match"]), None), "items": items}
    if _es_numero(value):
        for modo, numbers in (("literal", False), ("normalizada", True)):
            hallado = _numero_presente(float(value), normalize_text(transcript, numbers))
            if hallado:
                return {"status": VERIFICADO, "mode": modo, "found_as": hallado, "near_match": None, "items": []}
        return {"status": SIN_VERIFICAR, "mode": None, "found_as": None, "near_match": None, "items": []}
    for modo, numbers in (("literal", False), ("normalizada", True)):
        hallado, cercano = _cadena_presente(value, transcript, numbers)
        if hallado:
            return {"status": VERIFICADO, "mode": modo, "found_as": hallado, "near_match": None, "items": []}
    return {"status": SIN_VERIFICAR, "mode": None, "found_as": None, "near_match": cercano, "items": []}


# ── Aritmética de pedidos ─────────────────────────────────────────────────────

def _nombre_item(item):
    return " ".join(str(item.get(k, "")) for k in ("plato", "tamaño")).strip()


def _es_bebida(item, menu):
    nombre = sin_acentos(_nombre_item(item).lower())
    for m in menu or []:
        if sin_acentos(m["name"].lower()) in nombre or nombre in sin_acentos(m["name"].lower()):
            return m.get("category") == "bebida"
    return any(b in nombre for b in _BEBIDAS)


def _precio(item):
    p = item.get("precio_unitario")
    return float(p) if isinstance(p, (int, float)) and not isinstance(p, bool) else None


def _ajuste_promocion(items, promocion, menu):
    """(descuento, total_paquete_o_None, ids_en_paquete, nota). El total de un paquete reemplaza a sus ítems."""
    if not promocion:
        return 0.0, None, set(), None
    p = normalize_text(str(promocion))
    if re.search(r"\b(2x1|2 por 1|2 por uno|dos por uno)\b", p) or re.search(r"segunda .*gratis", p):
        desc = 0.0
        for it in items:
            precio = _precio(it)
            if precio is not None and _es_bebida(it, menu):
                desc += precio * (int(it.get("cantidad", 1)) // 2)
        return desc, None, set(), "2x1: la segunda unidad de cada bebida es gratis"
    m = re.search(r"\bpor\s+(\d+(?:\.\d+)?)", p)
    if m:  # paquete: "4 cuartos + gaseosa por 70"
        antes = re.sub(r"\d+(?:\.\d+)?", " ", p[:m.start()])
        claves = [_stem(w) for w in antes.split() if w not in _STOP_PROMO and len(w) > 2]
        ids = set()
        for idx, it in enumerate(items):
            nombre = [_stem(w) for w in normalize_text(_nombre_item(it)).split()]
            gaseosa = "gaseosa" in claves and _es_bebida(it, menu)
            if gaseosa or any(c in nombre for c in claves):
                ids.add(idx)
        if ids:
            return 0.0, float(m.group(1)), ids, f"paquete por {m.group(1)}: reemplaza a sus ítems"
    if "mitad de precio" in p:
        return 0.0, None, set(), "mitad de precio: los precios dichos ya incluyen el descuento"
    return 0.0, None, set(), "promoción no interpretada: no se ajustó el total"


def _diferencias_con_ground_truth(items, total_dicho, ground_truth):
    """Lista de diferencias entre el registro extraído y el ground truth (vacía si coinciden).

    Los ítems se emparejan por cantidad y precio (los nombres varían: "cuarto de pollo" vs "cuarto de pollo brasa
    pecho"); un precio extraído en None solo se compara por cantidad (ítems dentro de un paquete promocional).
    """
    gt_items = ground_truth.get("items") or []
    if isinstance(gt_items, str):
        import json
        gt_items = json.loads(gt_items)
    difs = []
    gt_total = ground_truth.get("total_dicho")
    if gt_total not in (None, "") and not math.isclose(float(gt_total), total_dicho, abs_tol=0.5):
        difs.append(f"total dicho {total_dicho:g} vs {float(gt_total):g}")
    libres = list(gt_items)
    for it in items:
        cant, precio = int(it.get("cantidad", 1)), _precio(it)
        for g in libres:
            if int(g.get("cantidad", 1)) == cant and (precio is None or _precio(g) is None
                                                       or math.isclose(_precio(g), precio, abs_tol=0.5)):
                libres.remove(g)
                break
        else:
            difs.append(f"{_nombre_item(it)}: {cant} × {precio if precio is not None else '?'} no está en el ground truth")
    difs += [f"falta en el registro: {_nombre_item(g)} ({g.get('cantidad')} × {g.get('precio_unitario')})" for g in libres]
    return difs


def validate_order_arithmetic(record, transcript=None, menu=None, tolerance=0.5, ground_truth=None):
    """Calcula el total esperado de un pedido y lo compara con `total_dicho`.

    `record`: {"items": [{"plato", "cantidad", "precio_unitario", ...}], "promocion": str|None, "total_dicho": número}.
    Total esperado = Σ cantidad × precio − descuento de la promo (2x1, paquete por N; "mitad de precio" no ajusta).
    Diagnóstico cuando no coinciden. Con `ground_truth` hay dos reglas, según lo que traiga:
      a) Si trae `total_correcto` (la regla por total correcto), con el total calculado desde los ítems extraídos:
           1. si `total_dicho` del ground truth también viene y el total dicho extraído no lo coincide -> "asr": el ASR
              (o la extracción) leyó mal el total que se dijo;
           2. si el total calculado coincide con `total_correcto` (pero no con el total dicho) -> "hablante": los
              ítems están bien y el hablante dijo un total que no corresponde;
           3. si el total calculado no coincide ni con el total dicho ni con `total_correcto` -> "asr": se malinterpretó
              una cifra de los ítems (precio o cantidad).
         (El paso 1 evita atribuir al hablante un error de lectura del total: si el ASR cambió 86 por 80, el calculado
         coincidiría con el correcto y sin él se diría "hablante".)
      b) Si solo trae {"items", "total_dicho"} (lo que realmente se dijo), se compara el registro extraído contra él:
           - "asr": el registro difiere del ground truth (total, cantidades o precios distintos);
           - "hablante": el registro coincide con el ground truth y aun así no cuadra.
    Sin `ground_truth`, se usa `transcript` (requerido):
      - "asr": algún número usado (total, precios, cantidades) NO aparece en la transcripción -> el ASR o la
        extracción se equivocaron al leer una cifra;
      - "hablante": todos los números aparecen tal cual en la transcripción y aun así no cuadran -> el hablante
        dijo un total que no corresponde a lo pedido;
      - "indeterminado": faltan precios o no hay transcripción.
    Devuelve dict con expected_total, total_dicho, difference, status ("ok" | "discrepancia" | "incompleto"),
    diagnosis, explanation y breakdown.
    """
    items = record.get("items") or []
    if isinstance(items, str):
        import json
        items = json.loads(items)
    total_dicho = record.get("total_dicho")
    res = {"expected_total": None, "total_dicho": total_dicho, "difference": None, "status": "incompleto",
           "diagnosis": "indeterminado", "explanation": "", "breakdown": {}}
    if not items or total_dicho in (None, ""):
        res["explanation"] = "faltan ítems o total_dicho"
        return res
    total_dicho = float(total_dicho)

    sin_precio = [_nombre_item(i) for i in items if _precio(i) is None]
    descuento, paquete, ids_paquete, nota = _ajuste_promocion(items, record.get("promocion"), menu)
    subtotal = sum(_precio(i) * int(i.get("cantidad", 1)) for k, i in enumerate(items)
                   if _precio(i) is not None and (paquete is None or k not in ids_paquete))
    faltan_fuera_del_paquete = [_nombre_item(i) for k, i in enumerate(items)
                                if _precio(i) is None and (paquete is None or k not in ids_paquete)]
    res["breakdown"] = {"subtotal": subtotal, "descuento": descuento, "paquete": paquete,
                        "sin_precio": sin_precio, "promocion": nota}
    if faltan_fuera_del_paquete:
        res["explanation"] = f"faltan precios de: {', '.join(faltan_fuera_del_paquete)}"
        return res

    esperado = subtotal - descuento + (paquete or 0.0)
    res["expected_total"] = esperado
    res["difference"] = round(total_dicho - esperado, 2)
    if math.isclose(esperado, total_dicho, abs_tol=tolerance):
        res.update(status="ok", diagnosis="ok", explanation="el total dicho coincide con el total esperado")
        return res

    res["status"] = "discrepancia"
    if ground_truth is not None and ground_truth.get("total_correcto") not in (None, ""):
        correcto, dicho_gt = float(ground_truth["total_correcto"]), ground_truth.get("total_dicho")
        if dicho_gt not in (None, "") and not math.isclose(float(dicho_gt), total_dicho, abs_tol=tolerance):
            res["diagnosis"] = "asr"
            res["explanation"] = (f"el total dicho extraído ({total_dicho:g}) difiere del realmente dicho ({float(dicho_gt):g}): "
                                  "el ASR o la extracción leyó mal el total")
        elif math.isclose(esperado, correcto, abs_tol=tolerance):
            res["diagnosis"] = "hablante"
            res["explanation"] = (f"el total calculado desde los ítems ({esperado:g}) coincide con el total correcto "
                                  f"({correcto:g}) y no con el dicho ({total_dicho:g}): error del hablante")
        else:
            res["diagnosis"] = "asr"
            res["explanation"] = (f"el total calculado ({esperado:g}) no coincide ni con el dicho ({total_dicho:g}) ni con "
                                  f"el correcto ({correcto:g}): se malinterpretó una cifra de los ítems")
        res["diagnosis_source"] = "ground_truth (total_correcto)"
        return res
    if ground_truth is not None:
        difs = _diferencias_con_ground_truth(items, total_dicho, ground_truth)
        res["diagnosis"] = "asr" if difs else "hablante"
        res["explanation"] = (f"difiere del ground truth: {'; '.join(difs)} (error del ASR o de la extracción)" if difs else
                              f"el registro coincide con el ground truth pero el total dicho ({total_dicho:g}) no "
                              f"coincide con el esperado ({esperado:g}): error del hablante")
        res["diagnosis_source"] = "ground_truth"
        return res
    if not transcript:
        res["explanation"] = "no coincide y no hay transcripción para diagnosticar"
        return res
    numeros = [("total_dicho", total_dicho)]
    for k, it in enumerate(items):
        if paquete is not None and k in ids_paquete:
            continue  # el precio del paquete reemplaza a sus ítems: sus cifras no entran en el total esperado
        if _precio(it) is not None:
            numeros.append((f"precio de {it.get('plato')}", _precio(it)))
        numeros.append((f"cantidad de {it.get('plato')}", it.get("cantidad", 1)))
    if paquete is not None:
        numeros.append(("precio del paquete", paquete))
    res["diagnosis_source"] = "transcripcion"
    ausentes = [n for n, v in numeros if verify_literal(v, transcript)["status"] != VERIFICADO]
    if ausentes:
        res["diagnosis"] = "asr"
        res["explanation"] = f"no aparece en la transcripción: {', '.join(ausentes)} (error del ASR o de la extracción)"
    else:
        res["diagnosis"] = "hablante"
        res["explanation"] = (f"todas las cifras aparecen en la transcripción pero el total dicho ({total_dicho:g}) "
                              f"no coincide con el esperado ({esperado:g}): error del hablante")
    return res


# ── Verificación de un registro completo ──────────────────────────────────────

def _verificar_etiqueta(valor, transcript):
    """Para etiquetas normalizadas (promoción): verificadas si sus palabras de contenido aparecen en el texto."""
    palabras = [w for w in normalize_text(str(valor), numbers=False).split() if len(w) > 3 and w.isalpha()]
    texto = {_stem(w) for w in normalize_text(transcript).split()}
    faltan = [w for w in palabras if _stem(w) not in texto]
    return {"status": VERIFICADO if palabras and not faltan else SIN_VERIFICAR, "found_as": None,
            "near_match": None, "items": [], "missing": faltan}


def verify_record(fields, transcript):
    """Aplica verify_literal a cada campo de un registro extraído.

    Devuelve (verified_fields, details): `verified_fields` = {campo: "verificado" | "sin_verificar" | "sin_valor"};
    `details` = el resultado completo de cada verificación. En `items` (ventas) se verifica el nombre del plato, la
    cantidad y el precio de cada ítem; en `promocion` (etiqueta normalizada) las palabras de contenido.
    """
    estados, detalles = {}, {}
    for campo, valor in fields.items():
        if campo == "items" and valor:
            filas = []
            for it in valor:
                fila = {k: verify_literal(it.get(k), transcript)
                        for k in ("plato", "cantidad", "precio_unitario") if it.get(k) is not None}
                fila["_plato"] = it.get("plato")
                filas.append(fila)
            ok = all(r["status"] == VERIFICADO for f in filas for k, r in f.items() if k != "_plato")
            estados[campo], detalles[campo] = (VERIFICADO if ok else SIN_VERIFICAR), filas
        elif campo == "promocion" and valor:
            detalles[campo] = _verificar_etiqueta(valor, transcript)
            estados[campo] = detalles[campo]["status"]
        else:
            detalles[campo] = verify_literal(valor, transcript)
            estados[campo] = detalles[campo]["status"]
    return estados, detalles
