# Evaluación sin LLM: recuperación y compuerta del umbral

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Modelo `intfloat/multilingual-e5-small` · troceado `c750_o100` · 1674 fragmentos · umbral 0.865.

## Recuperación (Recall@k)

| k | Todas | Coloquiales | Jurídicas | Versiones: trae el DS 001 |
|---|---|---|---|---|
| 1 | 0.762 | 0.727 | 0.800 | 0.200 |
| 3 | 0.905 | 0.818 | 1.000 | 0.800 |
| 5 | 0.905 | 0.818 | 1.000 | 0.800 |

MRR = 0.825. «Versiones: trae el DS 001» exige el fragmento de la modificatoria entre los k primeros; traer solo el texto original desactualizado no cuenta.

## Compuerta del umbral

- **Dentro del dominio (21):** 16 pasan la compuerta; **5 abstenciones incorrectas** (tasa 0.238).
- **Fuera de dominio (6):** **5 abstenciones correctas** (tasa 0.833); 1 pasan la compuerta y dependerían del LLM.

**Veredicto:** FALLA: Recall@3 = 0.905 es menor que el mínimo exigido 0.99
