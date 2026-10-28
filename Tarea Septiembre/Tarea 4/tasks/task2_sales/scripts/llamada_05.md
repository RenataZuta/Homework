# Llamada 05 — Trampas: C + T + D

Dominio: restaurante. Trampas plantadas: correcciones del cliente (C), total incorrecto a propósito (T), dirección con dígitos (D).

A = operador (tú) · B = cliente (compañero)

A: El Buen Sabor, ¿en qué le ayudo?
B: Buenas, quiero cinco porciones de causa limeña y... a ver, tres sopas de la casa. Ah no, espera, que sean dos sopas nomás.
A: Cinco causas y dos sopas. ¿Algo de tomar?
B: Tres limonadas.
A: Tenemos happy hour: las limonadas están a mitad de precio, tres soles en vez de seis.
B: Perfecto, aplícalo.
A: Entonces cinco causas a quince soles, dos sopas a doce, y tres limonadas a tres soles con la promo. Su total es ciento diez soles.
B: La dirección es Pasaje Los Olivos 28, interior B, Surquillo.
A: ¿Método de pago?
B: Transferencia bancaria.

## Ground truth

- items = [
  {"plato": "causa limeña", "tamaño": "porción", "cantidad": 5, "precio_unitario": 15},
  {"plato": "sopa de la casa", "tamaño": "normal", "cantidad": 2, "precio_unitario": 12},
  {"plato": "limonada", "tamaño": "normal", "cantidad": 3, "precio_unitario": 3}
  ]
- promocion = "Happy hour: limonadas a mitad de precio (3 en vez de 6)"
- direccion_entrega = "Pasaje Los Olivos 28, interior B, Surquillo"
- metodo_pago = "Transferencia bancaria"
- total_dicho = 110
- total_correcto = 108 (75 + 24 + 9 = 108)
- tiene_correccion = Sí (3→2 sopas)
- total_es_incorrecto = Sí
