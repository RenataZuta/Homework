# Evaluación de punta a punta (con LLM), umbral 0.000

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Proveedor `gemini`, modelo `gemini-3.5-flash-lite`, nivel `gratuito`. Cada pregunta pasa por el motor completo. Resumen:

- **In_domain (21):** 17 respondidas, de ellas **17 citando una página esperada**; 4 abstenciones incorrectas; 0 errores.
- **Fuera de dominio (6):** 0 abstenciones por umbral, **4 por el LLM**, 2 respuestas indebidas, 0 errores.
- **Llamadas:** 26 reales al proveedor + 1 reutilizadas de la caché; 0 preguntas no ejecutadas.
- **Costo REAL:** USD 0.0000 (en la capa gratuita se cobra 0). **Costo de REFERENCIA** (precio de pago del modelo, pricing.yaml): USD 0.0208 en total = USD 0.000772 por llamada (35,871 tokens de entrada, 4,031 de salida).

| Id | Tipo | Desenlace | Cita correcta | Mejor sim. | Costo ref. USD | Latencia ms | Avisos versión | Caché |
|---|---|---|---|---|---|---|---|---|
| q01 | in_domain | respondida | True | 0.843 | 0.000688 | 2749 | 1 | False |
| q02 | in_domain | respondida | True | 0.874 | 0.000793 | 4918 | 0 | False |
| q03 | in_domain | respondida | True | 0.880 | 0.000694 | 1901 | 0 | False |
| q04 | in_domain | abstuvo_llm | False | 0.854 | 0.000518 | 1757 | 0 | False |
| q05 | in_domain | respondida | True | 0.885 | 0.001006 | 1509 | 1 | False |
| q06 | in_domain | respondida | True | 0.872 | 0.001611 | 3212 | 0 | False |
| q07 | in_domain | abstuvo_llm | False | 0.863 | 0.000509 | 1767 | 1 | False |
| q08 | in_domain | respondida | True | 0.859 | 0.000864 | 2140 | 1 | False |
| q09 | in_domain | respondida | True | 0.901 | 0.000727 | 2616 | 0 | False |
| q10 | in_domain | abstuvo_llm | False | 0.837 | 0.000461 | 2103 | 0 | False |
| q11 | in_domain | respondida | True | 0.869 | 0.001229 | 37930 | 1 | False |
| q12 | in_domain | abstuvo_llm | False | 0.911 | 0.000638 | 1852 | 2 | False |
| q13 | in_domain | respondida | True | 0.925 | 0.000677 | 4470 | 0 | False |
| q14 | in_domain | respondida | True | 0.909 | 0.000922 | 2687 | 0 | False |
| q15 | in_domain | respondida | True | 0.873 | 0.000929 | 2559 | 0 | False |
| q16 | in_domain | respondida | True | 0.931 | 0.000581 | 998 | 1 | False |
| q17 | in_domain | respondida | True | 0.903 | 0.000941 | 2381 | 2 | False |
| q18 | in_domain | respondida | True | 0.913 | 0.000763 | 2252 | 4 | False |
| q19 | in_domain | respondida | True | 0.898 | 0.000893 | 2354 | 3 | False |
| q20 | in_domain | respondida | True | 0.885 | 0.000747 | 2326 | 2 | False |
| q21 | in_domain | respondida | True | 0.910 | 0.000883 | 38572 | 0 | False |
| o01 | out_of_domain | abstuvo_llm | — | 0.841 | 0.000515 | 1798 | 0 | False |
| o02 | out_of_domain | respondida | — | 0.856 | 0.000884 | 5011 | 1 | False |
| o03 | out_of_domain | abstuvo_llm | — | 0.854 | 0.000498 | 1954 | 0 | False |
| o04 | out_of_domain | abstuvo_llm | — | 0.795 | 0.000425 | 41 | 0 | True |
| o05 | out_of_domain | respondida | — | 0.893 | 0.000727 | 1376 | 1 | False |
| o06 | out_of_domain | abstuvo_llm | — | 0.828 | 0.000715 | 2698 | 3 | False |
