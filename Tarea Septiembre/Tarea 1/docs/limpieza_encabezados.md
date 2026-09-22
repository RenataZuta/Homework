# Limpieza de encabezados: reglas, antes/después y verificación

_Generado por `scripts/cleaning_report.py` a partir de `data/processed/` (que guarda el texto **crudo** y el **limpio** de cada página)._

## Reglas (`src/extraction/clean.py`)

| Regla | Qué elimina | Dónde actúa |
|---|---|---|
| R1 | Cabecera de El Peruano: nº de página · `NORMAS LEGALES` · fecha · `El Peruano /` | Solo al INICIO de la página y solo si la firma está completa. El `/` a veces baja de línea. |
| R2 | Sello de firma digital (`Firmado por: …`, `Fecha: dd/mm/aaaa hh:mm`) | Solo al FINAL de la página |
| R3 | Texto de OTRAS normas tras el código de cierre de la norma (`2474920-3`) | El PDF de El Peruano trae páginas de la edición completa |
| R1o | Cabecera de páginas ESCANEADAS | Por POSICIÓN: líneas cuyo borde superior está en la banda superior (`extraccion.ocr.banda_cabecera` = 0.1 de la altura). El texto que el OCR lee ahí es impredecible. |
| R4 | Espacios (NBSP, ancho cero, blancos de fin de línea, líneas en blanco repetidas) | Toda la página. **No** se quitan guiones de fin de línea: rompería `009-2025-\nEF`. |

El texto **crudo** nunca se pierde: queda en `texto_crudo` de cada entrada, de modo que toda regla es auditable y se puede re-aplicar (`run_extraction.py --relimpiar`) sin repetir el OCR.

## Antes / después en tres páginas

### `ds_001_2026_ef` — página 2 (texto) · reglas aplicadas: R1_cabecera_el_peruano

**Antes (texto crudo, primeras líneas; total 168 líneas / 6980 caracteres)**

```text
34
NORMAS LEGALES
Jueves 8 de enero de 2026
 El Peruano 
/
332.2 del artículo 332; el numeral 338.2 del artículo 338; 
el numeral 346.3 del artículo 346; los numerales 353.1, 
353.5 y 353.10 del artículo 353; los numerales 363.1 y 
363.2 del artículo 363; el literal b) del numeral 366.2 del 
```

**Después (texto limpio, primeras líneas; total 162 líneas / 6803 caracteres)**

```text
332.2 del artículo 332; el numeral 338.2 del artículo 338;
el numeral 346.3 del artículo 346; los numerales 353.1,
353.5 y 353.10 del artículo 353; los numerales 363.1 y
363.2 del artículo 363; el literal b) del numeral 366.2 del
artículo 366; el numeral 376.2 del artículo 376; el numeral
381.6 del artículo 381; el numeral 4 del artículo 382; el
```

### `ds_001_2026_ef` — página 16 (texto) · reglas aplicadas: R1_cabecera_el_peruano, R3_fin_de_norma

**Antes (texto crudo, primeras líneas; total 153 líneas / 6556 caracteres)**

```text
48
NORMAS LEGALES
Jueves 8 de enero de 2026
 El Peruano 
/
Dado en la Casa de Gobierno, en Lima, a los siete 
días del mes de enero del año dos mil veintiséis.
JOSÉ ENRIQUE JERÍ ORÉ
Presidente de la República
```

**Después (texto limpio, primeras líneas; total 6 líneas / 214 caracteres)**

```text
Dado en la Casa de Gobierno, en Lima, a los siete
días del mes de enero del año dos mil veintiséis.
JOSÉ ENRIQUE JERÍ ORÉ
Presidente de la República
DENISSE AZUCENA MIRALLES MIRALLES
Ministra de Economía y Finanzas
```

En esta página R3 descartó **141 líneas** de otras normas; el texto limpio termina así:

**Final del texto limpio**

```text
JOSÉ ENRIQUE JERÍ ORÉ
Presidente de la República
DENISSE AZUCENA MIRALLES MIRALLES
Ministra de Economía y Finanzas
```

### `ds_009_2025_ef` — página 60 (ocr) · reglas aplicadas: R1o_banda_cabecera

**Antes (texto crudo, primeras líneas; total 167 líneas / 7365 caracteres)**

```text
NORMAS LEGALES

Miércoses 22 48 enero e 2005 / 85 ElPerano

años, aplicando estándares internacionales de seguridad
de la información, ciberseguridad y privacidad.

Articulo 257. Obligatoriedad y valor legal del uso
la Pladicop
```

**Después (texto limpio, primeras líneas; total 163 líneas / 7305 caracteres)**

```text
años, aplicando estándares internacionales de seguridad
de la información, ciberseguridad y privacidad.

Articulo 257. Obligatoriedad y valor legal del uso
la Pladicop

```

## Verificación: la regla no borra contenido legítimo

| Documento | Páginas | Con cabecera eliminada | Líneas eliminadas | Empiezan con «Artículo» | Resultado |
|---|---:|---:|---:|---:|---|
| `ley_32069` | 63 | 0 | 0 | 4 | ✅ sin problemas |
| `ds_009_2025_ef` | 75 | 75 | 161 | 0 | ✅ sin problemas |
| `ds_001_2026_ef` | 16 | 16 | 72 | 6 | ✅ sin problemas |
