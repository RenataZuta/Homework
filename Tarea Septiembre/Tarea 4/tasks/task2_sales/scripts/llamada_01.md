# Llamada 01 — Trampas: C + T + D

Dominio: restaurante. Trampas plantadas: correcciones del cliente (C), total incorrecto a propósito (T), dirección con dígitos (D).

A = operador (tú) · B = cliente (compañero)

A: Buenas noches, restaurante El Buen Sabor, ¿en qué le puedo ayudar?
B: Hola, quiero hacer un pedido para delivery. A ver, quiero dos lomos saltados grandes.
A: Dos lomos saltados grandes, perfecto. ¿Algo más?
B: Sí, y una... no, espera, mejor que sean tres lomos, no dos. Es que somos más gente de lo que pensé.
A: Ok, tres lomos saltados grandes entonces. ¿Algo más?
B: Sí, una jarra de chicha morada y una porción de arroz chaufa especial.
A: Perfecto. Tenemos una promoción de dos por uno en bebidas, así que la jarra de chicha le saldría gratis si pide otra.
B: Ah ya, entonces ponme dos jarras de chicha morada.
A: Listo. Entonces son tres lomos saltados grandes a treinta y cinco soles cada uno, dos jarras de chicha a doce soles, pero la segunda va gratis, y un arroz chaufa especial a veinticinco. ¿La dirección?
B: Avenida Javier Prado 1250, departamento 302, San Isidro.
A: ¿Método de pago?
B: Yape.
A: Perfecto. Su total sería ciento cuarenta soles.

## Ground truth

- items = [
  {"plato": "lomo saltado", "tamaño": "grande", "cantidad": 3, "precio_unitario": 35},
  {"plato": "chicha morada", "tamaño": "jarra", "cantidad": 2, "precio_unitario": 12},
  {"plato": "arroz chaufa especial", "tamaño": "porción", "cantidad": 1, "precio_unitario": 25}
  ]
- promocion = "2x1 en bebidas (segunda jarra gratis)"
- direccion_entrega = "Av. Javier Prado 1250, depto 302, San Isidro"
- metodo_pago = "Yape"
- total_dicho = 140
- total_correcto = 142 (3×35 + 12 + 25 = 142)
- tiene_correccion = Sí (2→3 lomos)
- total_es_incorrecto = Sí
