# Llamada 02 — Trampas: C + T

Dominio: restaurante. Trampas plantadas: correcciones del cliente (C), total incorrecto a propósito (T), dirección con dígitos (D).

A = operador (tú) · B = cliente (compañero)

A: Buenas tardes, El Buen Sabor, ¿qué va a pedir?
B: Hola, quiero un ceviche mixto y dos arroces con mariscos.
A: ¿El ceviche es personal o para compartir?
B: Para compartir. Y los arroces, eh, la verdad solo quiero uno, me confundí. Un arroz con mariscos nomás.
A: Ok, un ceviche mixto para compartir y un arroz con mariscos. ¿Algo de tomar?
B: Dos Inca Kolas de medio litro.
A: Listo. El ceviche para compartir son cuarenta y cinco soles, el arroz con mariscos treinta y ocho, y las Inca Kolas cinco soles cada una. Su total son ochenta soles.
B: La dirección es Calle Las Palmeras 456, Miraflores.
A: ¿Forma de pago?
B: Con tarjeta, al momento de la entrega.

## Ground truth

- items = [
  {"plato": "ceviche mixto", "tamaño": "para compartir", "cantidad": 1, "precio_unitario": 45},
  {"plato": "arroz con mariscos", "tamaño": "normal", "cantidad": 1, "precio_unitario": 38},
  {"plato": "Inca Kola", "tamaño": "medio litro", "cantidad": 2, "precio_unitario": 5}
  ]
- promocion = null
- direccion_entrega = "Calle Las Palmeras 456, Miraflores"
- metodo_pago = "Tarjeta"
- total_dicho = 80
- total_correcto = 93 (45 + 38 + 10 = 93)
- tiene_correccion = Sí (2→1 arroz)
- total_es_incorrecto = Sí
