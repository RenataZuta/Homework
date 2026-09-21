# PROGRESO — Tarea 1: RAG normativo de contrataciones públicas

> Archivo de retoma: si se pierde el contexto, continuar desde la primera fase sin marcar.
> Issue: https://github.com/d2cml-ai/Data-Science-Python/issues/187 · Fecha límite: **miércoles 23-sep-2026**.
> Rama de trabajo: `tarea1-rag` · Repo: `RenataZuta/Homework` (público) · Carpeta: `tarea1/`.

## Fases

- [x] **Fase 0** — Preparación: estructura, `.gitignore`, `.env.example`, `config.yaml`, `config.py`, `check_secrets.py`
- [ ] **Fase 1** — Descarga de PDFs oficiales + `MANIFEST.json`
- [ ] **Fase 2** — Extracción por página, OCR (≥ 60 págs del DS 009-2025-EF), limpieza, reporte de calidad `[MANUAL]`
- [ ] **Fase 3** — Set de evaluación (`eval/preguntas.csv`) `[MANUAL: validar páginas contra el PDF]`
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

## Decisiones registradas

| Fase | Decisión | Evidencia / fuente | Fecha |
|---|---|---|---|
| 0 | LLM de generación: `claude-haiku-4-5-20251001` (alias `claude-haiku-4-5`), USD 1 / 5 por millón de tokens (entrada / salida) | https://platform.claude.com/docs/en/about-claude/pricing y `/models/overview` (Haiku 4.5 es el más barato vigente; Sonnet 5 cuesta USD 2 / 10) | 2026-09-21 |
| 0 | La documentación oficial de Anthropic **no publica precios distintos por hora**: un solo precio por modelo | Misma página de precios, sin mención de tarifas horarias | 2026-09-21 |
| 0 | README completo en `tarea1/README.md`; el README de la raíz solo recibe una sección con enlace | El repo aloja varias tareas; no se sobrescribe lo existente | 2026-09-21 |
| 0 | Los módulos se crean en la fase que los necesita (sin archivos vacíos de relleno) | Historial de commits refleja el trabajo real | 2026-09-21 |

## Hallazgos del issue que afectan el plan

1. **El Reglamento no es parte del índice obligatorio.** El issue pide Ley 32069 + DS 001-2026-EF, y el documento opcional debe ser *una norma que modifica la ley o su reglamento*. El DS 009-2025-EF es el Reglamento mismo y además es un escaneo. Se incluye por decisión propia (subconjunto con OCR); hay que documentarlo y conservar en la evaluación al menos una pregunta `out_of_domain` que solo responda una página **no** procesada del Reglamento (requisito 3.4 del issue).
2. **Plazo:** el issue fija el 23-sep; el trabajo real empezó el 21-sep. El historial de esta rama será necesariamente reciente; no se altera ninguna fecha de commit.
