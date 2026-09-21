# Embeddings local frente a API

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Los MISMOS 1674 fragmentos (troceado `c750_o100`; se verificó que ambos índices tienen los mismos IDs y hashes de contenido) y las 21 preguntas in_domain. Sin llamar al LLM.

| Tipo | Modelo | Estado | Dim | Indexación (s) | Costo USD | Consulta (ms) | Vectores (MB) | R@1 | R@3 | R@5 | R@3 modif. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| local | intfloat/multilingual-e5-small | medido | 384 | 52.6 | 0.000000 | 17.2 | 2.45 | 0.762 | 0.905 | 0.905 | 0.800 |
| API | text-embedding-3-small | pendiente: falta OPENAI_API_KEY en .env | — | — | — | — | — | — | — | — | — |

> **Fila pendiente:** `text-embedding-3-small` — pendiente: falta OPENAI_API_KEY en .env. No se estiman recall, tiempos ni costo reales sin la llamada real.

## Costo

Precio de `text-embedding-3-small`: **USD 0.02 por millón de tokens de entrada**, verificado el 2026-09-21 en https://platform.openai.com/docs/pricing. Estimación previa con el tokenizador de OpenAI: 282,884 tokens para el corpus completo = **USD 0.0057**. Los tokens y el costo reales salen de la respuesta de la API y quedan en la tabla al ejecutar con clave.
