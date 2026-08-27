"""Reglas de validación que replican, en Python, la función validate() del
formulario PeopleSync (ver <script> de Homework1/index.html). Validar antes
de tocar el navegador permite descartar registros inválidos sin desperdiciar
tiempo de automatización y sin arriesgar que Selenium falle a mitad de un
select con una opción que no existe.

Los catálogos (AREAS_VALIDAS, PUESTOS_VALIDOS, etc.) son una copia exacta de
las <option> del formulario al 2026-08-25."""

import re
from datetime import datetime

GENEROS_VALIDOS = {"Masculino", "Femenino"}

AREAS_VALIDAS = {
    "Recursos Humanos", "Finanzas y Contabilidad", "Tecnología e Innovación",
    "Operaciones", "Comercial y Ventas", "Marketing", "Legal y Cumplimiento",
    "Logística y Supply Chain", "Servicio al Cliente", "Gerencia General",
}

PUESTOS_VALIDOS = {
    "Analista Jr.", "Analista", "Analista Sr.", "Analista de Datos",
    "Analista de RRHH", "Analista Financiero",
    "Especialista en TI", "Especialista Legal", "Especialista en Marketing",
    "Especialista en Logística",
    "Coordinador de Área", "Coordinador Comercial", "Coordinador de Proyectos",
    "Jefe de Área", "Gerente de Área", "Sub Gerente",
    "Asistente Administrativo", "Practicante Profesional", "Practicante Preprofesional",
}

CONTRATOS_VALIDOS = {
    "Planilla Fija", "Contrato por Servicios", "Practicante Profesional",
    "Practicante Preprofesional", "Contrato a Plazo Fijo", "Part-time",
}

SEDES_VALIDAS = {
    "Lima - San Isidro (Sede Central)", "Lima - Miraflores", "Lima - La Molina", "Lima - Callao",
    "Arequipa", "Trujillo", "Cusco", "Piura", "Chiclayo",
}

MODALIDADES_VALIDAS = {"Presencial", "Remoto", "Híbrido"}

DNI_RE = re.compile(r"^\d{8}$")
TELEFONO_RE = re.compile(r"^9\d{8}$")
CORREO_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

FORMATOS_FECHA_ACEPTADOS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y")


def parse_fecha(valor):
    """Convierte una fecha (DD/MM/AAAA u otros formatos comunes) al formato
    AAAA-MM-DD que exige el <input type="date">. Devuelve None si no se pudo
    interpretar."""
    valor = (valor or "").strip()
    for fmt in FORMATOS_FECHA_ACEPTADOS:
        try:
            return datetime.strptime(valor, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def validar_registro(registro):
    """Devuelve la lista de errores encontrados en un registro (lista vacía
    == el registro cumple todas las reglas del formulario y puede cargarse)."""
    errores = []

    if not registro.get("nombres", "").strip():
        errores.append("nombres vacío")

    dni = registro.get("dni", "").strip()
    if not DNI_RE.match(dni):
        errores.append(f"DNI inválido: '{dni}' (se requieren exactamente 8 dígitos numéricos)")

    if parse_fecha(registro.get("fecha_nacimiento", "")) is None:
        errores.append(f"fecha_nacimiento inválida o no reconocida: '{registro.get('fecha_nacimiento')}'")

    genero = registro.get("genero", "").strip()
    if genero not in GENEROS_VALIDOS:
        errores.append(
            f"género no soportado por el formulario: '{genero}' "
            f"(opciones válidas: {', '.join(sorted(GENEROS_VALIDOS))})"
        )

    telefono = registro.get("telefono", "").strip()
    if not TELEFONO_RE.match(telefono):
        errores.append(f"teléfono inválido: '{telefono}' (se requiere que empiece en 9 y tenga 9 dígitos)")

    correo = registro.get("correo", "").strip()
    if not CORREO_RE.match(correo):
        errores.append(f"correo inválido: '{correo}'")

    area = registro.get("area", "").strip()
    if area not in AREAS_VALIDAS:
        errores.append(f"área/departamento no reconocido por el formulario: '{area}'")

    puesto = registro.get("puesto", "").strip()
    if puesto not in PUESTOS_VALIDOS:
        errores.append(f"puesto/cargo no reconocido por el formulario: '{puesto}'")

    contrato = registro.get("contrato", "").strip()
    if contrato not in CONTRATOS_VALIDOS:
        errores.append(f"tipo de contrato no reconocido por el formulario: '{contrato}'")

    sede = registro.get("sede", "").strip()
    if sede not in SEDES_VALIDAS:
        errores.append(f"sede/oficina no reconocida por el formulario: '{sede}'")

    if parse_fecha(registro.get("fecha_ingreso", "")) is None:
        errores.append(f"fecha_ingreso inválida o no reconocida: '{registro.get('fecha_ingreso')}'")

    modalidad = registro.get("modalidad", "").strip()
    if modalidad not in MODALIDADES_VALIDAS:
        errores.append(f"modalidad de trabajo no reconocida por el formulario: '{modalidad}'")

    return errores
