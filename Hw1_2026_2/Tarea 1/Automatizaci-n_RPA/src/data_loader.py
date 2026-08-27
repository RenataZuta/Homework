"""Carga el conjunto de datos de entrada (Google Sheets publicado como CSV,
o un archivo local) y lo normaliza a una lista de diccionarios cuyas claves
coinciden con los id de los campos del formulario PeopleSync."""

import pandas as pd

from . import config

COLUMNAS_ESPERADAS = [
    "apellidos_nombres", "dni", "fecha_nacimiento", "genero", "telefono",
    "correo", "area", "puesto", "contrato", "sede", "fecha_ingreso", "modalidad",
]


def cargar_empleados(fuente=None):
    """fuente puede ser una URL (export CSV de Google Sheets) o una ruta local.
    Si no se indica, se usa config.DATA_SOURCE."""
    fuente = fuente or config.DATA_SOURCE
    df = pd.read_csv(fuente, dtype=str, keep_default_na=False)

    faltantes = set(COLUMNAS_ESPERADAS) - set(df.columns)
    if faltantes:
        raise ValueError(
            f"El origen de datos '{fuente}' no tiene las columnas esperadas: {sorted(faltantes)}"
        )

    registros = []
    for posicion, fila in df.iterrows():
        registro = {col: str(fila[col]).strip() for col in COLUMNAS_ESPERADAS}
        registro["nombres"] = registro.pop("apellidos_nombres")
        registro["_fila"] = posicion + 2  # +2: encabezado ocupa la fila 1, iterrows es base 0
        registros.append(registro)

    return registros
