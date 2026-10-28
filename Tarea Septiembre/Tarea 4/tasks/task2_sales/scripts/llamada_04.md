# Llamada 04 — Trampas: C (sin total incorrecto)

Dominio: restaurante. Trampas plantadas: correcciones del cliente (C), total incorrecto a propósito (T), dirección con dígitos (D).

A = operador (tú) · B = cliente (compañero)

A: El Buen Sabor, buenas tardes.
B: Hola, a ver, quiero un chifa aeropuerto grande y un tallarin saltado... no, perdón, mejor cámbiame el tallarín por un arroz chaufa de pollo.
A: Ok, un aeropuerto grande y un arroz chaufa de pollo. ¿Algo para tomar?
B: Una chicha morada personal.
A: Listo. El aeropuerto grande son veintiocho soles, el chaufa de pollo veintidós, y la chicha ocho. Total: cincuenta y ocho soles.
B: La dirección es Av. Brasil 3100, Jesús María.
A: ¿Cómo paga?
B: Plin.

## Ground truth

- items = [
  {"plato": "chifa aeropuerto", "tamaño": "grande", "cantidad": 1, "precio_unitario": 28},
  {"plato": "arroz chaufa de pollo", "tamaño": "normal", "cantidad": 1, "precio_unitario": 22},
  {"plato": "chicha morada", "tamaño": "personal", "cantidad": 1, "precio_unitario": 8}
  ]
- promocion = null
- direccion_entrega = "Av. Brasil 3100, Jesús María"
- metodo_pago = "Plin"
- total_dicho = 58
- total_correcto = 58
- tiene_correccion = Sí (tallarín→chaufa)
- total_es_incorrecto = No
