"""Filtros estructurados (departamento, categoría, monto, fecha) para el RAG híbrido.

Por qué existen: una pregunta como *"obras de agua y saneamiento en Cusco por encima de un millón de soles"*
mezcla DOS tipos de condición. "Cusco" y "por encima de un millón" son condiciones EXACTAS (territorio,
número); un embedding no las representa de forma confiable — dos textos pueden ser "parecidos" en coseno y
uno costar 900 000 y el otro 1 900 000, o uno ser de Cusco y el otro de Puno con una redacción parecida. "agua
y saneamiento" sí es una condición semántica razonable para similitud de texto. Por eso las primeras se
aplican como filtro de metadatos ANTES del coseno (``store.py``) y solo la segunda llega a los embeddings.

``extraer_filtros_pregunta`` hace esa separación con reglas explícitas (listas y regex de config.yaml), no
con el LLM: así es gratis, determinista y se puede probar con pytest sin red. Es un complemento, no un
reemplazo: la interfaz (``app.py``) siempre puede pasar los mismos filtros de forma explícita (sidebar), y
esos valores explícitos GANAN sobre lo que se extraiga de la pregunta (ver ``combinar``).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from radar_engine.config import Config

# el orden de la alternancia importa: "millon" antes que "mil" (si no, "mil" ya matchea como prefijo de
# "millon" y el \b nunca se evalúa dentro de la propia alternancia); el \b final es la protección real.
_RE_NUM = re.compile(r"(\d+(?:[.,]\d+)?)\s*(millon(?:es)?|mil(?:es)?)?\b")


def _normalizar(texto: str) -> str:
    """minúsculas, sin tildes, espacios colapsados (para comparar palabras clave sin depender de acentos).
    "un millón" / "una unidad de mil" se escriben con la PALABRA "un/una", no con el dígito 1: se normaliza
    aquí (antes de _RE_NUM, que exige un dígito) para que "por encima de un millón" también se reconozca."""
    s = unicodedata.normalize("NFKD", texto.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\buna?\s+(mil(?:es)?|millon(?:es)?)\b", r"1 \1", s)


@dataclass
class Filtros:
    departamento: str | None = None
    categoria: str | None = None            # goods | services | works (mainProcurementCategory de OCDS)
    monto_min: float | None = None
    monto_max: float | None = None
    fecha_desde: str | None = None          # YYYY-MM-DD
    fecha_hasta: str | None = None

    def esta_vacio(self) -> bool:
        return not any((self.departamento, self.categoria, self.monto_min is not None, self.monto_max is not None,
                        self.fecha_desde, self.fecha_hasta))

    def como_texto(self) -> str:
        """Descripción legible para el prompt del LLM y para mostrar en la interfaz."""
        partes = []
        if self.departamento:
            partes.append(f"departamento = {self.departamento}")
        if self.categoria:
            partes.append(f"categoría = {self.categoria}")
        if self.monto_min is not None:
            partes.append(f"monto ≥ S/ {self.monto_min:,.0f}")
        if self.monto_max is not None:
            partes.append(f"monto ≤ S/ {self.monto_max:,.0f}")
        if self.fecha_desde:
            partes.append(f"convocado desde {self.fecha_desde}")
        if self.fecha_hasta:
            partes.append(f"convocado hasta {self.fecha_hasta}")
        return "; ".join(partes) if partes else "(ninguno)"


def combinar(explicitos: Filtros, extraidos: Filtros) -> Filtros:
    """Los valores EXPLÍCITOS (sidebar) ganan; donde el usuario no fijó nada, se usa lo extraído de la pregunta."""
    return Filtros(
        departamento=explicitos.departamento or extraidos.departamento,
        categoria=explicitos.categoria or extraidos.categoria,
        monto_min=explicitos.monto_min if explicitos.monto_min is not None else extraidos.monto_min,
        monto_max=explicitos.monto_max if explicitos.monto_max is not None else extraidos.monto_max,
        fecha_desde=explicitos.fecha_desde or extraidos.fecha_desde,
        fecha_hasta=explicitos.fecha_hasta or extraidos.fecha_hasta,
    )


def _departamentos_conocidos() -> dict[str, str]:
    from territory_mapping import load_rules   # import tardío: requiere 'src' en sys.path (lo pone pytest.ini / app.py)
    r = load_rules()
    return {**r["departments"], **r["aliases"]}


def _extraer_departamento(pregunta: str) -> str | None:
    from territory_mapping import clean_text   # misma normalización que usan las claves de departamentos.yaml (conserva la Ñ)
    texto = clean_text(pregunta) or ""
    candidatos = _departamentos_conocidos()
    for clave in sorted(candidatos, key=len, reverse=True):     # más largo primero: "LIMA METROPOLITANA" antes que "LIMA"
        if re.search(rf"\b{re.escape(clave)}\b", texto):
            return candidatos[clave]
    return None


def _extraer_categoria(limpio: str, cfg: Config) -> str | None:
    for categoria, palabras in cfg.get("filtros_nl.categorias").items():
        for palabra in palabras:
            if re.search(rf"\b{re.escape(_normalizar(palabra))}\b", limpio):
                return categoria
    return None


def _es_probable_anio(texto_num: str, unidad: str | None) -> bool:
    """"hasta 2026" es una fecha, no un monto: un entero de 4 cifras 1900-2100 SIN unidad (mil/millón) ni
    decimales/separadores se descarta como monto (evita falsos positivos con años)."""
    return unidad is None and re.fullmatch(r"(19|20)\d{2}", texto_num) is not None


def _valor_monto(texto_num: str, unidad: str | None, unidades: dict[str, int]) -> float:
    numero = float(texto_num.replace(",", ""))
    return numero * unidades.get(unidad or "", 1)


def _buscar_monto(limpio: str, frases: list[str]) -> tuple[float | None, str | None] | tuple[None, None]:
    for frase in frases:
        m = re.search(rf"{re.escape(_normalizar(frase))}\s+(?:s/\.?\s*)?" + _RE_NUM.pattern, limpio)
        if m and not _es_probable_anio(m.group(1), m.group(2)):
            return m.group(1), m.group(2)
    return None, None


def _extraer_monto(limpio: str, cfg: Config) -> tuple[float | None, float | None]:
    unidades = cfg.get("filtros_nl.unidades_monto")
    num, unidad = _buscar_monto(limpio, cfg.get("filtros_nl.monto_mayor"))
    mayor_min = _valor_monto(num, unidad, unidades) if num else None
    num, unidad = _buscar_monto(limpio, cfg.get("filtros_nl.monto_menor"))
    menor_max = _valor_monto(num, unidad, unidades) if num else None
    return mayor_min, menor_max


def extraer_filtros_pregunta(pregunta: str, cfg: Config) -> Filtros:
    """Filtros deducidos por reglas explícitas (sin LLM, sin red): ver docstring del módulo."""
    limpio = _normalizar(pregunta)
    monto_min, monto_max = _extraer_monto(limpio, cfg)
    return Filtros(departamento=_extraer_departamento(pregunta), categoria=_extraer_categoria(limpio, cfg),
                   monto_min=monto_min, monto_max=monto_max)
