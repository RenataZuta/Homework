# PROGRESO — Tarea 1: RAG normativo de contrataciones públicas

> Archivo de retoma: si se pierde el contexto, continuar desde la primera fase sin `[x]`. Leyenda: `[x]` hecha y verificada · `[~]` trabajo técnico hecho, **falta confirmación `[MANUAL]`** de la persona.
> Issue: https://github.com/d2cml-ai/Data-Science-Python/issues/187 · Fecha límite: **miércoles 23-sep-2026**.
> Rama de trabajo: `tarea1-rag` · Repo: `RenataZuta/Homework` (público) · Carpeta: `tarea1/`.

## Fases

- [x] **Fase 0** — Preparación: estructura, `.gitignore`, `.env.example`, `config.yaml`, `config.py`, `check_secrets.py`
- [x] **Fase 1** — Descarga de PDFs oficiales + `MANIFEST.json`
- [x] **Fase 2** — Extracción por página, OCR (75 págs del DS 009-2025-EF), limpieza, reporte de calidad (revisión manual confirmada por la persona el 2026-09-21)
- [~] **Fase 3** — Set de evaluación (`eval/preguntas.csv`) `[MANUAL pendiente: validar CADA paginas_esperadas con docs/eval_revision_manual.md; no empezar la Fase 4 hasta confirmarlo]`
- [ ] **Fase 4** — Chunking, embeddings, índice idempotente y reanudable
- [ ] **Fase 5** — Motor RAG: umbral, versiones, costo `[MANUAL: ANTHROPIC_API_KEY]`
- [ ] **Fase 6** — Evaluación y comparación de embeddings local vs API `[MANUAL: OPENAI_API_KEY]`
- [ ] **Fase 7** — Interfaz Streamlit
- [ ] **Fase 8** — Innovación A: BM25 vs semántica
- [ ] **Fase 9** — Innovación B: GitHub Actions con umbral de Recall@3
- [ ] **Fase 10** — Innovación C: bot de Telegram `[MANUAL: @BotFather]`
- [ ] **Fase 11** — Innovación D: bot 24/7 con Cloudflare Worker `[MANUAL: cuentas y deploy]`
- [ ] **Fase 12** — Innovación E: despliegue público de la app `[MANUAL: deploy]`
- [ ] **Fase 13** — Cierre: README, notas de video, auditoría final, costo real

Tarea 2 (`tarea2/`): pendiente, se hará después; importará `rag_engine`.

## Entorno de desarrollo (medido el 2026-09-21)

| Ítem | Valor |
|---|---|
| Máquina | macOS (Darwin 23.4, arm64), 8 GB RAM, ~16 GB de disco libres |
| Python del sistema | 3.14 (anaconda) y 3.9 (Apple) → **no se usan** (las ruedas de PyTorch/ChromaDB tardan en llegar a versiones nuevas) |
| Entorno del proyecto | `conda` env `tarea1` con **Python 3.12** |
| No instalado | Tesseract, Homebrew, `gh`, Node/wrangler, Docker |
| Sistema objetivo del README | Windows (PowerShell). Los pasos de Windows se documentan pero **no se ejecutan aquí**. |

## Revisión de fuentes (preliminar, medida el 2026-09-21; el reporte formal por página es de la Fase 2)

| Documento | Páginas | Con texto | Sin texto | Car./pág. (media) | ¿Usable tal cual? |
|---|---:|---:|---:|---:|---|
| `ley_32069` (compendio OECE, al 19.07.2026) | 63 | 63 | 0 | ~3 490 | Sí |
| `ds_001_2026_ef` (El Peruano, 08/01/2026) | 16 | 16 | 0 | ~7 036 | Sí |
| `ds_009_2025_ef` (Reglamento) | 196 | 0 | **196** | 0 | **No: escaneo completo, exige OCR** |

## Resultados de la Fase 2 (medidos el 2026-09-21)

| Ítem | Resultado |
|---|---|
| Ley 32069 | 63 págs con texto, 215 269 car., 0 páginas a OCR |
| DS 001-2026-EF | 16 págs con texto, 103 454 car.; la p. 16 traía 141 líneas de OTRAS normas (recortadas por la regla R3) |
| DS 009-2025-EF | 196 págs escaneadas a 96 DPI nativos → **75 procesadas con OCR** (529 118 car.); 121 excluidas (98 formularios/tablas + 23 de menor prioridad) |
| OCR | Tesseract 5.5.2 `spa`, 200 DPI: 4,5 s/pág (mediana 4,5; máx 5,0), confianza media 88,9, 88,2 % de palabras en el vocabulario de referencia |
| Reanudación | Ctrl+C real tras 6 páginas → exit 130; relanzado procesó 69 y reutilizó 6; 3.ª corrida: **0 OCR, 75 desde caché en 0,3 s** |
| Orden de lectura | 3 páginas de 2 columnas revisadas: 1 salto de columna cada una (ideal); 1 desorden local en un título justificado |
| Versiones | DS 001 modifica 96 y incorpora 15 (105 artículos distintos); **98 de 105** tienen su texto original en el corpus (verificado sobre el OCR) |
| Tests | 175 pasan |

## Resultados de la Fase 3 (borrador; 2026-09-21)

| Ítem | Resultado |
|---|---|
| Preguntas | **27**: 21 in_domain (11 coloquiales, 10 jurídicas, 5 sobre artículos modificados por el DS 001) y 6 out_of_domain |
| Páginas esperadas | 34 evidencias en 29 páginas distintas, **todas dentro del subconjunto procesado** (lo comprueba `validate_eval_set.py`) |
| Verificación contra el PDF | Los 34 recortes de imagen se revisaron uno a uno (`docs/eval_evidencia/`); el ancla no se tomó del texto extraído sino que se comparó con la imagen |
| Fuera de dominio | tributación (o01), contratación privada (o02), Colombia (o03), ceviche (o04), **fórmula de la capacidad máxima de contratación (o05, art. 28, p. 8 del DS 009, excluida del índice)**, valor de la UIT (o06) |
| Tests | 192 pasan (17 nuevos del set de evaluación) |

## Decisiones registradas

| Fase | Decisión | Evidencia / fuente | Fecha |
|---|---|---|---|
| 0 | LLM de generación: `claude-haiku-4-5-20251001` (alias `claude-haiku-4-5`), USD 1 / 5 por millón de tokens (entrada / salida) | https://platform.claude.com/docs/en/about-claude/pricing y `/models/overview` (Haiku 4.5 es el más barato vigente; Sonnet 5 cuesta USD 2 / 10) | 2026-09-21 |
| 0 | La documentación oficial de Anthropic **no publica precios distintos por hora**: un solo precio por modelo | Misma página de precios, sin mención de tarifas horarias | 2026-09-21 |
| 1 | El PDF de la Ley es el **compendio "versión actualizada" del OECE (fuente base SPIJ) al 19.07.2026**: es lo único que ofrece la colección oficial del OECE. No es el texto original de El Peruano. Se etiqueta `ley_vigente` y se declara en el README | Nota de la propia página del OECE | 2026-09-21 |
| 1 | Enlace directo al PDF del DS 001-2026-EF: aparece en el HTML de la ficha de El Peruano (`/api/archivo/file/…/2474920-3.PDF`); no hubo bloqueo, así que no se necesitó descarga manual | Descarga real, 3,56 MB, 16 págs | 2026-09-21 |
| 1 | Tamaños: 0,52 / 18,68 / 3,56 MB; ninguno se acerca a los 90 MB de aviso → no se necesita Git LFS | `data/raw/MANIFEST.json` | 2026-09-21 |
| 2 | Motor de OCR: **Tesseract `spa` a 200 DPI** (no EasyOCR, no 96/150/300 DPI) | `eval/results/ocr_benchmark.md`: 620 palabras correctas/pág frente a 276 (EasyOCR), 6,7× más rápido; 150 DPI da mejor porcentaje pero omite ~20 % del texto | 2026-09-21 |
| 2 | Umbral de OCR = 100 caracteres útiles **y** imagen a página completa | Páginas con texto: mín 946; escaneadas: 0 | 2026-09-21 |
| 2 | Cabecera de páginas escaneadas: regla por **posición** (banda superior 10 %), no por texto | El OCR lee la cabecera de forma impredecible (`Miércoses 22 48 enero…`) | 2026-09-21 |
| 2 | Página pública = índice del PDF (base 1), que coincide con el nº impreso del DS 009 | Verificado en las págs. 10 y 60 | 2026-09-21 |
| 2 | Subconjunto de OCR: 75 págs = 33 por cobertura de estructura + resto por artículos modificados y relevancia MYPE; criterio de página de texto = ≥ 4 500 car. **y** confianza ≥ 80 | `docs/ocr_subset.md`; separa exactamente las 98 págs normativas de los formularios del anexo | 2026-09-21 |
| 3 | Formato del CSV: varios documentos con `\|` y varias páginas de un documento con `;` (`ds_001_2026_ef\|ds_009_2025_ef` / `8;9\|47`); en las preguntas de versiones el primer documento es siempre el DS 001 | Permite medir aparte si el recuperador trae el texto vigente y no solo el original | 2026-09-21 |
| 3 | Las evidencias (ancla + dato de cada página) van en `eval/evidencia.yaml`, no en el CSV, para no romper las columnas pedidas | `scripts/eval_evidence.py` recorta la imagen del PDF | 2026-09-21 |
| 3 | 27 preguntas en lugar de 20: más out_of_domain cercanas (o02, o03, o05, o06) para que el barrido de umbral no se calibre solo con casos fáciles | Limitación: se calibra con el mismo set | 2026-09-21 |
| 0 | README completo en `tarea1/README.md`; el README de la raíz solo recibe una sección con enlace | El repo aloja varias tareas; no se sobrescribe lo existente | 2026-09-21 |
| 0 | Los módulos se crean en la fase que los necesita (sin archivos vacíos de relleno) | Historial de commits refleja el trabajo real | 2026-09-21 |

## Hallazgos del issue que afectan el plan

1. **El Reglamento no es parte del índice obligatorio.** El issue pide Ley 32069 + DS 001-2026-EF, y el documento opcional debe ser *una norma que modifica la ley o su reglamento*. El DS 009-2025-EF es el Reglamento mismo y además es un escaneo. Se incluye por decisión propia (subconjunto con OCR); hay que documentarlo y conservar en la evaluación al menos una pregunta `out_of_domain` que solo responda una página **no** procesada del Reglamento (requisito 3.4 del issue).
2. **Plazo:** el issue fija el 23-sep; el trabajo real empezó el 21-sep. El historial de esta rama será necesariamente reciente; no se altera ninguna fecha de commit.
3. **La "Ley" ya incorpora modificatorias posteriores.** El compendio integra, entre otras, el DL 1715 (04/02/2026) y la Ley 32515. Además, la modificación de la Ley 32732 (19/07/2026) entra en vigencia recién al día siguiente de la publicación de la modificación del Reglamento (aviso de OECE en la misma página). Consecuencia: `ley_vigente` significa "texto consolidado por OECE a esa fecha", no "texto original".
4. **Documentos oficiales relacionados que NO se incluyen** (se declaran como limitación en el README): la **fe de erratas del DS 009-2025-EF** (gob.pe) y el **Reglamento consolidado del OECE al 09.01.2026**. Este último no se descargó ni se verificó; además fusiona el DS 001-2026-EF con el texto original, lo que borraría la distinción de versiones que el proyecto necesita mostrar. Solo se consideraría como verificación cruzada, nunca como parte del índice.
5. **El anexo del DS 009 son formularios** (págs. 105–196): trámites del RNP, instituciones arbitrales, cuadros de experiencia. Se excluyen del corpus: OCR ilegible a 96 DPI (confianza ≈ 55) y sin normativa consultable. La p. 100 no es el Anexo I sino las Disposiciones Complementarias Transitorias.
6. **Errores de carácter en números del OCR** (`Articulo 399` por 99, `598.2` por 98.2, `CAPITULO 111`): la extracción de `articulos_mencionados` (Fase 4) debe descartar números > 389 y apoyarse en el rango de artículos de la página. El OCR suele leer coma en vez de punto tras el número de artículo.
7. **Siete artículos modificados sin texto original en el corpus**: `46, 88, 94, 113, 198, 218, 318` (página excluida o número mal leído). Para ellos el motor solo tendrá el texto del DS 001.
8. **Trabajo pendiente para la Fase 4:** `easyocr` y `torch` quedaron instalados en el entorno `tarea1` solo por el benchmark; `requirements.txt` los deja comentados.
9. **El compendio de la Ley trae versiones dentro de la propia página.** En la p. 36 el art. 73.2 aparece en cursiva (0,5 %, tope 50 UIT) y una nota `(*)` reproduce el texto vigente desde 2025 (Ley 32187: 3 % en general); el 67.8 está derogado por la Ley 32103. El prompt de la Fase 5 debe tratar «(*) … cuyo texto es el siguiente» como el texto que prevalece.
10. **Ley y Reglamento numeran sus artículos por separado** (el art. 98 de la Ley es «Retiro temporal del registro»; el 98 del Reglamento es sobre la comparación de precios). Al extraer `articulos_mencionados` hay que registrar a qué norma remite cada mención («artículo 61 **de la Ley**»), y el aviso de versión solo aplica a fragmentos del Reglamento.
11. **Encabezados huérfanos:** el título de un artículo puede quedar al final de una página y su contenido en la siguiente (arts. 89 y 93 de la Ley). Las páginas esperadas son siempre las del contenido. Idea para la Fase 4: guardar el último encabezado de la página anterior como metadato del primer fragmento.
12. **El OCR falla en cifras:** el art. 114 original dice «S/ 480 000» y el OCR leyó `430 000` (la imagen y el DS 001, que tiene capa de texto, confirman 480 000). Toda respuesta con cifras del Reglamento original merece cautela. El DS 001 marca en **negrita** lo nuevo de cada numeral, y el art. 25.7 se invierte: el original dice que los ejecutores de obra **no pueden** acreditar experiencia de una reorganización societaria y el DS 001 dice que **pueden** (esa página del original, la 8, está fuera del índice).
