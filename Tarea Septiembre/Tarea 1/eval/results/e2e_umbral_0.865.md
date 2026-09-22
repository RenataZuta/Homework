# Evaluación de punta a punta (con LLM), umbral 0.865

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Proveedor `gemini`, modelo `gemini-3.5-flash-lite`, nivel `gratuito`. Cada pregunta pasa por el motor completo. Resumen:

- **In_domain (21):** 16 respondidas, de ellas **16 citando una página esperada**; 5 abstenciones incorrectas; 0 errores.
- **Fuera de dominio (6):** 5 abstenciones por umbral, **0 por el LLM**, 1 respuestas indebidas, 0 errores.
- **Llamadas:** 0 reales al proveedor + 17 reutilizadas de la caché; 0 preguntas no ejecutadas.
- **Costo REAL:** USD 0.0000 (en la capa gratuita se cobra 0). **Costo de REFERENCIA** (precio de pago del modelo, pricing.yaml): USD 0.0141 en total = USD 0.000829 por llamada (22,403 tokens de entrada, 2,949 de salida).

| Id | Tipo | Desenlace | Cita correcta | Mejor sim. | Costo ref. USD | Latencia ms | Avisos versión | Caché |
|---|---|---|---|---|---|---|---|---|
| q01 | in_domain | abstuvo_umbral | False | 0.843 | 0.000000 | 147 | 0 | False |
| q02 | in_domain | respondida | True | 0.874 | 0.000877 | 85 | 2 | True |
| q03 | in_domain | respondida | True | 0.880 | 0.000699 | 30 | 0 | True |
| q04 | in_domain | abstuvo_umbral | False | 0.856 | 0.000000 | 15 | 0 | False |
| q05 | in_domain | respondida | True | 0.885 | 0.000927 | 32 | 1 | True |
| q06 | in_domain | respondida | True | 0.872 | 0.001253 | 34 | 1 | True |
| q07 | in_domain | abstuvo_umbral | False | 0.864 | 0.000000 | 15 | 0 | False |
| q08 | in_domain | abstuvo_umbral | False | 0.860 | 0.000000 | 16 | 0 | False |
| q09 | in_domain | respondida | True | 0.901 | 0.000728 | 30 | 0 | True |
| q10 | in_domain | abstuvo_umbral | False | 0.837 | 0.000000 | 15 | 0 | False |
| q11 | in_domain | respondida | True | 0.869 | 0.000977 | 30 | 1 | True |
| q12 | in_domain | respondida | True | 0.911 | 0.000795 | 32 | 2 | True |
| q13 | in_domain | respondida | True | 0.925 | 0.000752 | 33 | 0 | True |
| q14 | in_domain | respondida | True | 0.909 | 0.001011 | 28 | 0 | True |
| q15 | in_domain | respondida | True | 0.873 | 0.000577 | 29 | 0 | True |
| q16 | in_domain | respondida | True | 0.931 | 0.000639 | 31 | 1 | True |
| q17 | in_domain | respondida | True | 0.903 | 0.000772 | 28 | 0 | True |
| q18 | in_domain | respondida | True | 0.913 | 0.000763 | 30 | 4 | True |
| q19 | in_domain | respondida | True | 0.900 | 0.000821 | 31 | 3 | True |
| q20 | in_domain | respondida | True | 0.885 | 0.000767 | 30 | 2 | True |
| q21 | in_domain | respondida | True | 0.910 | 0.000818 | 28 | 0 | True |
| o01 | out_of_domain | abstuvo_umbral | — | 0.841 | 0.000000 | 14 | 0 | False |
| o02 | out_of_domain | abstuvo_umbral | — | 0.856 | 0.000000 | 15 | 0 | False |
| o03 | out_of_domain | abstuvo_umbral | — | 0.854 | 0.000000 | 16 | 0 | False |
| o04 | out_of_domain | abstuvo_umbral | — | 0.795 | 0.000000 | 15 | 0 | False |
| o05 | out_of_domain | respondida | — | 0.893 | 0.000917 | 31 | 0 | True |
| o06 | out_of_domain | abstuvo_umbral | — | 0.830 | 0.000000 | 15 | 0 | False |
