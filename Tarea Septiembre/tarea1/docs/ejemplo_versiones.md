# Ejemplo de manejo de versiones (datos reales, sin llamar al LLM)

Generado por `scripts/ejemplo_versiones.py`. Para cada pregunta que depende de un artículo modificado por el DS 001-2026-EF se muestra lo que hace el motor **antes** de llamar al modelo: recuperar, marcar el texto original como posiblemente desactualizado, **forzar** los fragmentos de la modificatoria y ordenar el contexto con la modificatoria primero.

## q05 — No tengo carta fianza: siendo pequeña empresa, ¿cómo puedo garantizar el cumplimiento del contrato y cómo se aplica esa garantía?

Esperado: `ds_001_2026_ef` p. [14], `ds_009_2025_ef` p. [30], `ley_32069` p. [29]

**Recuperados (top-5):**

1. `ley_32069` p. 29 · versión `ley_vigente` · similitud 0.885 — a) El fideicomiso, constituido tanto para el adelanto de pago como para el fiel cumplimiento del contrato. b) La carta fianza fina…
2. `ley_32069` p. 29 · versión `ley_vigente` · similitud 0.884 — garantía de fiel cumplimiento del contrato y de fiel cumplimiento de las prestaciones accesorias. 61.3. Las entidades contratantes…
3. `ds_001_2026_ef` p. 5 · versión `modificatoria_2026-01` · similitud 0.882 — a la entidad contratante, sin perjuicio de iniciarse el respectivo deslinde de responsabilidades.” “Artículo 113. Tipos de garantí…
4. `ds_009_2025_ef` p. 30 · versión `reglamento_original_2025` · similitud 0.880 — garantias de fiel cumplimiento de varios contralos con la misma entidad contratante, de serel caso 116.6. En el caso que el contra…
5. `ley_32069` p. 28 · versión `ley_vigente` · similitud 0.876 — y el fiel cumplimiento del contrato, así como el fiel cumplimiento de las prestaciones accesorias. 61.2. Los mecanismos de garantí…

**Artículos del Reglamento mencionados y modificados:** [113]

**Advertencias de versión que recibe la interfaz:**

- El artículo 113 del Reglamento fue modificado por el DS 001-2026-EF (numerales 113.1 y 113.3 (modificado)); prevalece el texto de la modificatoria.

**Fragmentos FORZADOS en el contexto (2):**

- Reglamento ORIGINAL · `ds_009_2025_ef` p. 29 (similitud 0.871): y eficiencia y vigencia tecnológica, entre otros. que resulten aplicables. d) Por norma expresa. SUBCAPÍTULO 2 Garantías Artículo 143. Tipos de garantias contractuales 1131 Garantía de fiel cumplimiento: El postor ganador entrega a la entidad contratante, como…
- Reglamento ORIGINAL · `ds_009_2025_ef` p. 29 (similitud 0.863): y 61.5 del artículo 61 de la Ley. 113.2: Garantía de fiel cumplimiento por prestaciones accesorias: En las contrataciones que conllevan la ejecución de prestaciones accesoñas, tales como mantenimiento, reparación o actividades afines, se entrega una garantia a…

---

## q11 — ¿Qué tanto pesa el precio al calificar las ofertas? ¿Cuántos puntos puede valer como máximo?

Esperado: `ds_001_2026_ef` p. [4], `ds_009_2025_ef` p. [18]

**Recuperados (top-5):**

1. `ds_009_2025_ef` p. 18 · versión `reglamento_original_2025` · similitud 0.869 — orden de prelación de los postores considerando que la buena pro se otorga al menor monto otestado. Articulo 75. Determinación del…
2. `ds_009_2025_ef` p. 34 · versión `reglamento_original_2025` · similitud 0.864 — indicados y cuenta con un premio o reconocimiento internacional en la profesión de arquitectura. 135.5. La evaluación de ofertas t…
3. `ds_001_2026_ef` p. 4 · versión `modificatoria_2026-01` · similitud 0.862 — son revisados por la DEC, para lo cual puede solicitar opinión a los miembros del jurado. (…)” “Artículo 75. Determinación del pun…
4. `ds_009_2025_ef` p. 40 · versión `reglamento_original_2025` · similitud 0.860 — 166.2. La evaluación económica se realiza sobre cien puntos únicamente respecto al rubro: correspondiente al costo del diseño, mie…
5. `ds_009_2025_ef` p. 18 · versión `reglamento_original_2025` · similitud 0.860 — de lances sucesivos en línea. La mejora de precios de la oferta queda a criterio de cada postor, 742. A fin de determinar el punta…

**Artículos del Reglamento mencionados y modificados:** [75]

**Advertencias de versión que recibe la interfaz:**

- El artículo 75 del Reglamento fue modificado por el DS 001-2026-EF (numeral 75.1 (modificado)); prevalece el texto de la modificatoria.

No hizo falta forzar nada: el contexto recuperado ya trae lo necesario.

---

## q18 — ¿Quién revisa los requisitos de calificación cuando la evaluación de ofertas la hace un jurado?

Esperado: `ds_001_2026_ef` p. [4], `ds_009_2025_ef` p. [17]

**Recuperados (top-5):**

1. `ds_001_2026_ef` p. 4 · versión `modificatoria_2026-01` · similitud 0.913 — “Artículo 72. Requisitos de calificación (…) 72.2. Los evaluadores revisan los requisitos de calificación de las ofertas que sean …
2. `ds_009_2025_ef` p. 26 · versión `reglamento_original_2025` · similitud 0.884 — oferte el menor precio, conforme al procedimiento establecido en la directiva y las bases estandar. 96.5. El oficial de compra rev…
3. `ds_001_2026_ef` p. 4 · versión `modificatoria_2026-01` · similitud 0.883 — 96.5. El oficial de compra revisa los requisitos de calificación de los postores que ocuparon los primeros lugares en el orden de …
4. `ds_001_2026_ef` p. 3 · versión `modificatoria_2026-01` · similitud 0.880 — para que revisen la forma de evaluación, acreditación, puntaje y metodología para su asignación. En caso de que algún integrante p…
5. `ds_001_2026_ef` p. 5 · versión `modificatoria_2026-01` · similitud 0.874 — “Artículo 98. Evaluación de ofertas en la comparación de precios 98.1. El oficial de compra verifica que los postores que presenta…

**Artículos del Reglamento mencionados y modificados:** [72, 96, 55, 98]

**Advertencias de versión que recibe la interfaz:**

- El artículo 72 del Reglamento fue modificado por el DS 001-2026-EF (numeral 72.2 (modificado)); prevalece el texto de la modificatoria.
- El artículo 96 del Reglamento fue modificado por el DS 001-2026-EF (numeral 96.5 (modificado)); prevalece el texto de la modificatoria.
- El artículo 55 del Reglamento fue modificado por el DS 001-2026-EF (numeral 55.2 (modificado)); prevalece el texto de la modificatoria.
- El artículo 98 del Reglamento fue modificado por el DS 001-2026-EF (numeral 98.1 (modificado)); prevalece el texto de la modificatoria.

**Fragmentos FORZADOS en el contexto (2):**

- Reglamento ORIGINAL · `ds_009_2025_ef` p. 17 (similitud 0.860): consiste en la verificación de los documentos mínimos señalados en el numeral 69.1 del articulo 69. Artículo 72. Requisitos de calificación 72.1. Los requisitos de calificación permiten delerminar si los postores cuentan con las capacidades y aptitudes para ej…
- Reglamento ORIGINAL · `ds_009_2025_ef` p. 17 (similitud 0.858): de las ofertas que sean admitidas. 72.3, Los requisitos de calificación son de cinco fipos: a) Capacidad legal: encontrarse apto para ejecutar la actividad económica mateñía de contratación, para lo cual se debe contar con las habilitaciones que corresponda co…

---

## q19 — ¿Se pueden aprobar prestaciones adicionales de obra en vía de regularización?

Esperado: `ds_001_2026_ef` p. [8, 9], `ds_009_2025_ef` p. [47]

**Recuperados (top-5):**

1. `ley_32069` p. 31 · versión `ley_vigente` · similitud 0.900 — a fin de que inicien los procesos administrativos que correspondan de acuerdo con sus competencias. 64.7. En el caso de obras que …
2. `ds_009_2025_ef` p. 47 · versión `reglamento_original_2025` · similitud 0.898 — puede autorizar prestaciones adicionales hasta un 40% con el debido sustento técnico y legal. Excepcionalmente, puede autorizar la…
3. `ds_001_2026_ef` p. 9 · versión `modificatoria_2026-01` · similitud 0.898 — “Artículo 194. Prestaciones adicionales de obra bajo el sistema de entrega solo construcción (…) 194.3. No corresponde suscribir u…
4. `ds_001_2026_ef` p. 9 · versión `modificatoria_2026-01` · similitud 0.891 — adicionales en el componente de diseño se realiza conforme al numeral 193.1 del artículo 193. (…) 195.4. No corresponde suscribir …
5. `ds_001_2026_ef` p. 8 · versión `modificatoria_2026-01` · similitud 0.890 — en el que sustente su posición respecto a la necesidad de ejecutar la prestación adicional. d) La entidad contratante notifica la …

**Artículos del Reglamento mencionados y modificados:** [194, 195, 193]

**Advertencias de versión que recibe la interfaz:**

- El artículo 194 del Reglamento fue modificado por el DS 001-2026-EF (numeral 194.3 (modificado)); prevalece el texto de la modificatoria.
- El artículo 195 del Reglamento fue modificado por el DS 001-2026-EF (numerales 195.2 y 195.4 (modificado)); prevalece el texto de la modificatoria.
- El artículo 193 del Reglamento fue modificado por el DS 001-2026-EF (numeral 193.1 (modificado)); prevalece el texto de la modificatoria.

**Fragmentos FORZADOS en el contexto (2):**

- Reglamento ORIGINAL · `ds_009_2025_ef` p. 47 (similitud 0.887): posterior al perfeccionamiento del contrato y que no son responsabilidad del contratista. 194.2. La aprobación de las prestaciones adicionales se realiza conforme a lo siguiente: 3) La necesidad de ejecutar una prestación adicionales anotada en el cuaderno de …
- Reglamento ORIGINAL · `ds_009_2025_ef` p. 47 (similitud 0.883): del adicional, bastando com su publicación en la Pladicop para que surta todos =us efecilos. 194.4. Enel caso de prestaciones adicionales de obra de carácter de emergencia, cuya falta de ejecución pueda afectar el ambiente o poner en peligro a la población, a …

---

## q20 — ¿Les son aplicables a los contratos menores las causales de nulidad del contrato previstas en la Ley?

Esperado: `ds_001_2026_ef` p. [15], `ds_009_2025_ef` p. [55], `ley_32069` p. [35]

**Recuperados (top-5):**

1. `ley_32069` p. 35 · versión `ley_vigente` · similitud 0.885 — ley, sin perjuicio del deslinde de responsabilidades que corresponda. Esta facultad es indelegable. 71.4. Cuando corresponda al tr…
2. `ds_001_2026_ef` p. 15 · versión `modificatoria_2026-01` · similitud 0.872 — Operación y Mantenimiento • Ejecutor de Obra y • Consultor de Obra y • Proveedor de servicios d) Gestión del diseño y construcción…
3. `ds_001_2026_ef` p. 15 · versión `modificatoria_2026-01` · similitud 0.867 — causales de nulidad del contrato del numeral 71.1 del artículo 71 de la Ley, según corresponda.” “Artículo 232. Iniciativa de comp…
4. `ds_009_2025_ef` p. 55 · versión `reglamento_original_2025` · similitud 0.865 — se perfecciona mediante un acta suscrita por ambas partes que se registra en la Pladicop. 2292 La entidad contratante puede establ…
5. `ley_32069` p. 43 · versión `ley_vigente` · similitud 0.862 — causal de nulidad de la medida cautelar en caso se conceda con inobservancia de tales requisitos. 86.3. En los casos que la medida…

**Artículos del Reglamento mencionados y modificados:** [218, 232]

**Advertencias de versión que recibe la interfaz:**

- El artículo 218 del Reglamento fue modificado por el DS 001-2026-EF (numeral 218.6 (incorporado); numeral 218.4 (modificado)); prevalece el texto de la modificatoria.
- El artículo 232 del Reglamento fue modificado por el DS 001-2026-EF (numeral 232.5 (incorporado)); prevalece el texto de la modificatoria.

**Fragmentos FORZADOS en el contexto (2):**

- Reglamento ORIGINAL · `ds_009_2025_ef` p. 53 (similitud 0.812): cuente con el soporte fécnico necesario para gestiomar el contrato estandarizado elegido. Articulo 248. Proceso de contratación de los contratos estandarizados 218.1. Las fases de actuaciones preparatorias y de selección de los contratos estandarizados de inge…
- Reglamento ORIGINAL · `ds_009_2025_ef` p. 53 (similitud 0.810): se establecen las condiciones, limites, requisitos y otros para la contratación de subcontratistas. 218.5. Para tomar decisiones durante la ejecución contractual, se toma en cuenta, en lo que corresponda, las buenas prácticas nacionales e internacionales que i…

---

## Resumen

| Pregunta | Advertencias | Fragmentos forzados | DS 001 ya recuperado |
|---|---:|---:|---:|
| q05 | 1 | 2 | 1 |
| q11 | 1 | 0 | 1 |
| q18 | 4 | 2 | 4 |
| q19 | 3 | 2 | 3 |
| q20 | 2 | 2 | 2 |
