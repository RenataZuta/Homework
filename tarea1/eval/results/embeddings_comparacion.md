# Embeddings local frente a API

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Los MISMOS 1674 fragmentos (troceado `c750_o100`; se verificó que los índices medidos tienen los mismos IDs y hashes de contenido) y las 21 preguntas in_domain. Sin llamar al LLM de generación. No se cargó crédito en ningún proveedor.

| Tipo | Modelo | Estado | Nivel | Dim | Indexación (s) | Costo real USD | Consulta (ms) | Vectores (MB) | R@1 | R@3 | R@5 | R@3 modif. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| local | intfloat/multilingual-e5-small | medido | local | 384 | 51.5 | 0.000000 | 21.5 | 2.45 | 0.762 | 0.905 | 0.905 | 0.800 |
| API (OpenAI) | text-embedding-3-small | pendiente: falta OPENAI_API_KEY en .env | — | — | — | — | — | — | — | — | — | — |
| API (Gemini) | gemini-embedding-2 | no completada: cuota agotada del proveedor (Se agotó la cuota DIARIA de la capa gratuita de Google. Vuelve a intentarlo mañana o cambia de modelo. (You ex); 960/1674 fragmentos indexados; repetir más tarde para reanudar | — | — | — | — | — | — | — | — | — | — |

> **Filas no medidas:** `text-embedding-3-small` — pendiente: falta OPENAI_API_KEY en .env; `gemini-embedding-2` — no completada: cuota agotada del proveedor (Se agotó la cuota DIARIA de la capa gratuita de Google. Vuelve a intentarlo mañana o cambia de modelo. (You ex); 960/1674 fragmentos indexados; repetir más tarde para reanudar. No se estiman recall, tiempos ni costo reales sin la llamada real.

## Costo

- **API (OpenAI), `text-embedding-3-small`:** precio de pago USD 0.02 por millón de tokens de entrada, verificado el 2026-09-21 en https://platform.openai.com/docs/pricing. Estimación previa con el tokenizador de OpenAI: 282,884 tokens = **USD 0.0057** para indexar el corpus (estimación, no medición).
- **API (Gemini), `gemini-embedding-2`:** precio de pago USD 0.2 por millón de tokens de entrada, verificado el 2026-09-21 en https://ai.google.dev/gemini-api/docs/pricing. Tiene capa gratuita («Free of charge»): el costo real es 0 y en ella Google puede usar el contenido para mejorar sus productos (solo se envían fragmentos de normas públicas). La API no informa tokens, así que no se calcula un costo de referencia.
