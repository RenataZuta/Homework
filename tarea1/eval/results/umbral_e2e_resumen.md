# Calibración del umbral con el LLM real (punta a punta)

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Modelo `gemini/gemini-3.5-flash-lite`. Se parte de la evaluación con umbral 0 (las 27 preguntas pasan por el LLM); para cada umbral, una pregunta cuenta como respondida solo si su mejor similitud lo alcanza **y** el LLM la respondió.

## Umbral elegido: **0.835**

F-β (β = 0.5) máximo = 0.928, plano hasta 0.840: mientras el umbral no pase de 0.840 no se pierde ninguna respuesta buena, y el LLM rechaza por sí solo las preguntas ajenas que la compuerta deja pasar. Se toma el tope menos un margen de 0.005 → **0.835**. En ese umbral: 18 respuestas correctas, 0 erróneas, 3 abstenciones incorrectas, 5 abstenciones correctas, 1 respuestas indebidas (precisión 0.9474, cobertura 0.8571).

## Por qué el umbral anterior (0.865) era peor

El barrido solo con recuperación (`umbral_resumen.md`) eligió 0.865 porque solo veía la similitud. Con el LLM real, ese umbral da 16 respuestas correctas (frente a 18 en 0.835), 5 abstenciones incorrectas (frente a 3) y 1 respuestas indebidas (frente a 1): descarta respuestas buenas y no evita ninguna mala, porque el LLM ya rechaza por sí solo 5 de las 6 preguntas ajenas y las que responde superan cualquier umbral razonable. La compuerta se conserva por **costo y latencia** (cada abstención por umbral es una llamada menos) y como defensa si el LLM fallara, no como filtro de calidad.

## Alrededor del umbral elegido

| Umbral | Correctas | Erróneas | Abst. incorrectas | Abst. correctas | Indebidas | Precisión | Cobertura | F-β |
|---|---|---|---|---|---|---|---|---|
| 0.810 | 18 | 0 | 3 | 5 | 1 | 0.947 | 0.857 | 0.928 |
| 0.820 | 18 | 0 | 3 | 5 | 1 | 0.947 | 0.857 | 0.928 |
| 0.830 | 18 | 0 | 3 | 5 | 1 | 0.947 | 0.857 | 0.928 |
| 0.840 | 18 | 0 | 3 | 5 | 1 | 0.947 | 0.857 | 0.928 |
| 0.850 | 17 | 0 | 4 | 5 | 1 | 0.944 | 0.809 | 0.914 |
| 0.860 | 17 | 0 | 4 | 5 | 1 | 0.944 | 0.809 | 0.914 |

Similitudes de las preguntas que el LLM respondió: de 0.843 a 0.931. La tabla completa (0 a 1) está en `umbral_e2e_barrido.csv`.

**Limitación:** calibrado con el mismo set de 27 preguntas y un solo modelo; con preguntas nuevas la similitud más baja de una buena respuesta puede ser menor que la de q01 (0,843). Vuelve a ejecutar este script si cambian el modelo, el troceado o el prompt.
