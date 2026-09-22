# Cómo crear el bot de Telegram y probarlo en local (Fase 10) [MANUAL]

## 1. Crear el bot con @BotFather
1. En Telegram, abre una conversación con **@BotFather**.
2. Envía `/newbot`, elige un nombre visible y un usuario que termine en `bot` (p. ej. `contratacionespe_bot`).
3. BotFather te da un **token** (formato `123456789:AA...`). Guárdalo con:
   ```
   python scripts/set_env_key.py TELEGRAM_BOT_TOKEN
   ```
   Nunca lo pegues en el chat ni en un archivo del repositorio.

## 2. Averiguar tu ID numérico de usuario
Escríbele a **@userinfobot** (o a tu propio bot, una vez creado) y te responde con tu ID numérico. Guárdalo:
```
python scripts/set_env_key.py TELEGRAM_ALLOWED_USER_IDS
```
Para varios usuarios, sepáralos por coma al pegarlos (p. ej. `111111111,222222222`).

## 3. Probar en local (modo polling)
```
python scripts/run_telegram_bot.py
```
Dile a tu propio bot algo como «¿Cuál es el plazo máximo para que me paguen?». Debe responder citando documento y página, con botones 👍/👎 debajo.
Comandos: `/ayuda`, `/fuente` (fuentes de tu última consulta), `/costo` (costo de tu última consulta y lo acumulado hoy).
Un usuario que **no** esté en `TELEGRAM_ALLOWED_USER_IDS` recibe el mensaje de acceso restringido y no gasta ninguna llamada al modelo.
Detén el bot con Ctrl+C.

## Qué falta verificar (no se pudo probar en este entorno: no había token)
- [ ] Una consulta de un usuario autorizado responde con citas.
- [ ] Un usuario no autorizado es rechazado.
- [ ] Al superar `bot.limite_consultas_por_usuario_dia` (10 por defecto), aparece el aviso de límite.
- [ ] `/ayuda`, `/fuente` y `/costo` funcionan.
- [ ] Tocar 👍 o 👎 guarda el voto (verificable con `sqlite3 data/bot.db "select * from feedback;"`) y el bot agradece.
