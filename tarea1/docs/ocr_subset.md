# Subconjunto del DS 009-2025-EF procesado con OCR

_Generado por `scripts/plan_ocr.py` el 2026-09-21. Es un PLAN reproducible: si cambia el mapa o los pesos de `config.yaml`, se regenera._

## Resumen

- El PDF tiene **196 páginas**, todas escaneadas (0 caracteres de capa de texto).
- **75 páginas procesadas con OCR** (mínimo exigido: 60): `3-7, 9-11, 13-21, 26-34, 36-48, 50-60, 62-65, 67-68, 70-71, 73-74, 76-82, 91-94, 96-98, 100`.
- Páginas con texto normativo legible: 98 (págs. 3–104); se procesa el 77 % de ellas.
- **Cobertura del manejo de versiones (verificada sobre el texto OCR):** el texto original de **98 de 105** artículos modificados o incorporados por el DS 001-2026-EF está en el corpus (estimación previa al OCR, por interpolación de páginas: 104).

## Convención de número de página

`pagina` es el índice del PDF empezando en 1 (la primera página del archivo es la 1). En este PDF coincide con el número impreso en la cabecera de El Peruano (p. ej. la página 60 dice «60 NORMAS LEGALES»), pero el sistema usa siempre el índice del PDF, igual que en una corrida completa del OCR; así las citas son las mismas con o sin subconjunto.

## Cómo se eligió

1. **Mapeo de estructura** (`scripts/map_structure.py`): un OCR rápido de las 196 páginas que guarda solo estructura (tipo de página, encabezados, números de artículo, conteos de palabras clave), **no el texto**. Ese OCR de exploración no forma parte del corpus.
2. **Solo páginas de texto**: al menos 4500 caracteres leídos **y** confianza del motor ≥ 80. Las portadas, formularios y tablas (`escasa_lectura`) quedan fuera. Ninguna de las dos condiciones basta sola: los formularios del anexo dan miles de caracteres de ruido con confianza ≈ 55, y algunas páginas de formulario dan confianza alta con casi nada de texto.
3. **Cobertura obligatoria:** la página donde empieza cada título, capítulo, subcapítulo, disposición y anexo detectados.
4. **Versiones:** se prioriza el texto ORIGINAL de los artículos que el DS 001-2026-EF modifica o incorpora (`data/processed/articulos_modificados.json`, 105 artículos). Sin él no se puede mostrar cuándo el reglamento original quedó desactualizado.
5. **Relevancia para una MYPE:** el resto del presupuesto (75 páginas) se llena por puntaje (`10` × artículos modificados que empiezan en la página + densidad de palabras clave sobre contratación menor, registro de proveedores, procedimientos de selección, garantías y penalidades, controversias y Pladicop).

## Estructura detectada y página de inicio

| Página | Nivel | Encabezado (leído por OCR) | ¿En el subconjunto? |
|---:|---|---|---|
| 3 | titulo | TÍTULO 1 DISPOSICIONES GENERALES | sí |
| 4 | titulo | TÍTULO 1 | sí |
| 5 | capitulo | CAPÍTULO II ENTIDADES CONTRATANTES | sí |
| 6 | subcapitulo | SUBCAPÍTULO 1 | sí |
| 11 | titulo | TÍTULO Ii | sí |
| 11 | capitulo | CAPÍTULO 1 ACTUACIONES PREPARATORIAS | sí |
| 11 | subcapitulo | SUBCAPÍTULO 1 | sí |
| 15 | subcapitulo | SUBCAPÍTULO 1 | sí |
| 26 | capitulo | CAPITULO 111 DISPOSICIONES ESPECIALES PARA LAS | sí |
| 26 | subcapitulo | SUBCAPÍTULO 1 | sí |
| 26 | capitulo | CAPÍTULO Iv A | sí |
| 28 | subcapitulo | SUBCAPÍTULO 1 | sí |
| 32 | titulo | TÍTULO IV | sí |
| 33 | capitulo | CAPÍTULO 1 DISPOSICIONES ESPECIALES DE LA FASE DE | sí |
| 34 | capitulo | CAPITULO 11 DISPOSICIONES ESPECÍFICAS DE LA FASE DE | sí |
| 34 | subcapitulo | SUBCAPÍTULO 1 | sí |
| 37 | capitulo | CAPITULO 1 DISPOSICIONES ESPECIALES PARA LA FASE DE | sí |
| 39 | capitulo | CAPÍTULO 11 DISPOSICIONES ESPECIALES DE FASE DE | sí |
| 40 | capitulo | CAPÍTULO Il zi | sí |
| 40 | subcapitulo | SUBCAPÍTULO 1 | sí |
| 53 | capitulo | CAPÍTULO IV CONTRATOS ESTANDARIZADO 5 | sí |
| 54 | titulo | TÍTULO VI | sí |
| 55 | capitulo | CAPÍTULO 1 COMPRA CENTRALIZADA | sí |
| 56 | capitulo | CAPÍTULO Il COMPRAS POR ENCARGO | sí |
| 57 | capitulo | CAPÍTULO IV COMPRA CORPORATIVA | sí |
| 58 | capitulo | CAPÍTULO VI o | sí |
| 59 | titulo | TÍTULO vil | sí |
| 59 | capitulo | CAPÍTULO 1 PLADICOP | sí |
| 60 | capitulo | CAPÍTULO 1 ESTANDARIZACIÓN DE REQUERIMIENTOS | sí |
| 65 | titulo | TÍTULO IX | sí |
| 67 | titulo | TÍTULO X | sí |
| 70 | titulo | TÍTULO XI | sí |
| 70 | capitulo | CAPITULO 1 REGISTRO DE INSTITUCIONES ARBITRALES Y | sí |
| 73 | capitulo | CAPÍTULO ll IMPEDIMENTOS Y REQUISITOS PARA LOS | sí |
| 78 | titulo | TÍTULO XII RÉGIMEN DE INFRACCIONES Y SANCIONES | sí |
| 78 | capitulo | CAPITULO 1 PROCEDIMIENTO SANCIONADOR A | sí |
| 81 | capitulo | CAPÍTULO 1 PROCEDIMIENTO SANCIONADOR A INSTITUCIONES | sí |
| 82 | capitulo | CAPÍTULO 1 CONDICIONES Y REQUISITOS DE LOS | sí |
| 94 | capitulo | CAPÍTULO 11 REQUISITOS DE LOS SERVICIOS PRESTADOS EN | sí |
| 96 | disposicion | DISPOSICIÓN COMPLEMENTARIA FINAL | sí |
| 97 | disposicion | DISPOSICIÓN COMPLEMENTARIA TRANSITORIA | sí |
| 97 | disposicion | DISPOSICIÓN COMPLEMENTARIA TRANSITORIA | sí |
| 100 | anexo | ANEXO | sí |

Los encabezados se leen con OCR a baja resolución y pueden tener errores de numeración (p. ej. `TÍTULO 1x` por IX). La revisión visual está pendiente `[MANUAL]`.

## Páginas excluidas y motivo

- **`escasa_lectura` — 98 páginas** (`1-2, 22-25, 105-196`): portadas, formularios y tablas de anexos. El OCR lee casi nada (la p. 150 es un formulario de estados financieros: 7 palabras reconocidas) y no contienen normativa consultable.
- **`menor prioridad` — 23 páginas de texto** (`8, 12, 35, 49, 61, 66, 69, 72, 75, 83-90, 95, 99, 101-104`): sin encabezado, con pocos o ningún artículo modificado que empiece en ellas y bajo puntaje MYPE. Su contenido queda **fuera del índice a propósito**: una pregunta cuya respuesta solo esté ahí debe producir una abstención (requisito de «conocer los límites del corpus»).

## Artículos modificados cuyo texto original NO está en el subconjunto

`94`. Para estos, el motor solo tendrá el texto del DS 001-2026-EF (la modificatoria).

## Verificación posterior al OCR: artículos modificados presentes en el corpus

Se buscó, en el texto ya extraído de las 75 páginas, una línea que empiece con «Artículo N.» para cada uno de los 105 artículos que el DS 001-2026-EF modifica o incorpora: **98 encontrados**, 7 no encontrados (`46, 88, 94, 113, 198, 218, 318`). Un «no encontrado» puede ser un artículo cuyo número el OCR leyó mal o cuya página quedó fuera del subconjunto; para ninguno de ellos hay garantía de que el texto original esté indexado.

Números de artículo que el OCR leyó pero que no existen en el Reglamento (> 389; errores de lectura): `399`. La extracción de `articulos_mencionados` (Fase 4) debe descartarlos.

## Limitaciones

- La página de inicio de cada artículo se **detecta** por OCR (cobertura de detección medida en el mapa) o se **interpola** entre artículos vecinos (error típico de ±1 página). Un artículo puede empezar en una página incluida y terminar en una excluida.
- El escaneo es de **96 DPI nativos**; el OCR tiene errores de carácter (ver `eval/results/ocr_benchmark.md`).

## Detalle por página

El detalle completo (puntaje y motivo de cada una de las páginas) está en `data/processed/ds_009_2025_ef/_plan_ocr.json`.
