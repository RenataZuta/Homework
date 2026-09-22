# BM25 frente a búsqueda semántica

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Los MISMOS 1674 fragmentos (`c750_o100`), modelo de embeddings `intfloat/multilingual-e5-small`, búsqueda exacta, 21 preguntas del dominio. BM25: k1=1.5, b=0.75; híbrido: RRF con k=60 sobre los 50 mejores de cada lista. Sin llamar al LLM.

| Variante | R@1 | R@3 | R@5 | MRR | R@3 coloquial | R@3 jurídico | R@3 modificatoria | R@3 con cifras | R@3 sin cifras | Fallos@3 |
|---|---|---|---|---|---|---|---|---|---|---|
| semantico | 0.762 | 0.905 | 0.905 | 0.825 | 0.818 | 1.000 | 0.800 | — | 0.905 | 2 |
| bm25 | 0.571 | 0.714 | 0.762 | 0.647 | 0.455 | 1.000 | 0.800 | — | 0.714 | 6 |
| bm25_stem | 0.619 | 0.762 | 0.810 | 0.694 | 0.545 | 1.000 | 0.800 | — | 0.762 | 5 |
| bm25_sin_encabezado | 0.524 | 0.667 | 0.762 | 0.614 | 0.364 | 1.000 | 0.800 | — | 0.667 | 7 |
| hibrido_rrf | 0.714 | 0.810 | 0.810 | 0.754 | 0.636 | 1.000 | 0.800 | — | 0.810 | 4 |
| hibrido_rrf_stem | 0.714 | 0.905 | 0.905 | 0.802 | 0.818 | 1.000 | 0.800 | — | 0.905 | 2 |

«Con cifras» = la pregunta contiene algún dígito (número de artículo, monto o plazo).

## Preguntas que acierta el semántico en el top-3 y BM25 no

- **q01** (coloquial): ¿Puedo venderle al Estado si mi empresa recién abrió? — rangos: semántico 1, BM25 None, híbrido 3
- **q02** (coloquial): Si la entidad se demora en pagarme, ¿en cuánto tiempo debe pagar y qué me tiene que reconocer por el atraso? — rangos: semántico 1, BM25 None, híbrido 1
- **q03** (coloquial): Soy microempresa: ¿puedo cobrar con una factura negociable a plazo cuando le vendo al Estado? — rangos: semántico 1, BM25 None, híbrido 1
- **q09** (coloquial): Si cometo una infracción, ¿la multa es menor por ser micro o pequeña empresa? — rangos: semántico 1, BM25 4, híbrido 1
- **q10** (coloquial): ¿Cuánto me pueden cobrar por cada día que entrego tarde? — rangos: semántico 3, BM25 None, híbrido 2

## Preguntas que acierta BM25 en el top-3 y el semántico no

- **q07** (coloquial): Si dos empresas presentan ofertas con el mismo puntaje, ¿quién se lleva el contrato? — rangos: semántico None, BM25 1, híbrido None

## Preguntas que acierta el híbrido en el top-3 y el semántico no

- (ninguna)

## Preguntas que acierta el semántico en el top-3 y el híbrido no

- (ninguna)

## Sonda sintética: búsqueda por número de artículo (96 consultas «artículo N de la Ley»)

No forma parte del set de evaluación (que no tiene ninguna pregunta con cifras): se genera a partir del propio índice. Una consulta acierta si alguna de las k páginas recuperadas es una donde el encabezado del fragmento es ese artículo.

| Variante | Consultas | R@1 | R@3 | R@5 |
|---|---|---|---|---|
| semantico | 96 | 0.271 | 0.448 | 0.542 |
| bm25 | 96 | 0.521 | 0.844 | 0.938 |
| bm25_stem | 96 | 0.521 | 0.844 | 0.938 |
| bm25_sin_encabezado | 96 | 0.302 | 0.698 | 0.833 |
| hibrido_rrf | 96 | 0.500 | 0.771 | 0.823 |
| hibrido_rrf_stem | 96 | 0.500 | 0.771 | 0.823 |

**Limitación:** con 21 preguntas, una pregunta pesa 4,8 puntos de Recall: las diferencias de un solo caso no son concluyentes.
