# Llamada 03 — Trampas: T + D

Dominio: restaurante. Trampas plantadas: correcciones del cliente (C), total incorrecto a propósito (T), dirección con dígitos (D).

A = operador (tú) · B = cliente (compañero)

A: El Buen Sabor, buenas noches.
B: Buenas, quiero pedir cuatro cuartos de pollo a la brasa con papas, y dos ensaladas.
A: ¿Los cuartos son de pecho o pierna?
B: Dos de pecho y dos de pierna.
A: Perfecto. ¿Y para tomar?
B: Una gaseosa de litro y medio, Coca-Cola.
A: Tenemos la promo familiar: cuatro cuartos más la gaseosa grande por setenta soles en vez de ochenta.
B: Ah, ya, aplícame esa promo entonces.
A: Listo, la promo familiar setenta soles, más las dos ensaladas a ocho soles cada una. Su total serían noventa soles.
B: La dirección es Jirón Huallaga 782, piso 4, Cercado de Lima.
A: ¿Método de pago?
B: Efectivo, con billete de cien.

## Ground truth

- items = [
  {"plato": "cuarto de pollo a la brasa", "tamaño": "pecho", "cantidad": 2, "precio_unitario": 20},
  {"plato": "cuarto de pollo a la brasa", "tamaño": "pierna", "cantidad": 2, "precio_unitario": 20},
  {"plato": "ensalada", "tamaño": "normal", "cantidad": 2, "precio_unitario": 8},
  {"plato": "Coca-Cola", "tamaño": "1.5L", "cantidad": 1, "precio_unitario": 10}
  ]
- promocion = "Promo familiar: 4 cuartos + gaseosa por 70 (descuento de 10)"
- direccion_entrega = "Jr. Huallaga 782, piso 4, Cercado de Lima"
- metodo_pago = "Efectivo"
- total_dicho = 90
- total_correcto = 86 (70 + 16 = 86)
- tiene_correccion = No
- total_es_incorrecto = Sí
