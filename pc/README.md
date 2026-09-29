# Agente de PC

Acá va `cerebro_pc.py`, el programa que corre en tu computadora y ejecuta las órdenes que la
skill le manda por ntfy.sh: notas y pendientes, abrir apps y sitios, música, apagar o suspender,
WhatsApp, domótica, capturas, agenda, mails y tareas con Claude Code.

**Todavía no está publicado.** La skill funciona completa sin él (conversación, memoria,
recordatorios, temporizadores, radio y todos los datos en vivo); solo las acciones que empiezan
con "en la PC" quedan sin efecto y Cerebro responde "la conexión con tu PC todavía no está
configurada".

Cómo se comunica la skill con el agente, por si querés escribir el tuyo mientras tanto:

- **Canal de ida:** la skill publica en `https://ntfy.sh/<topico>` un JSON
  `{"id", "ts", "accion", "datos", "firma"}`.
- **Firma:** `HMAC-SHA256(clave, f"{id}|{ts}|{accion}|{json.dumps(datos, sort_keys=True, ensure_ascii=False)}")`,
  en hexadecimal.
- **Canal de vuelta:** el agente responde en `https://ntfy.sh/<topico>-r` con
  `{"id", "ok", "texto", "firma"}`, donde `firma = HMAC-SHA256(clave, f"{id}|{ok}|{texto}")`.
- **Tiempo:** la skill espera entre 1 y 4,5 segundos según lo que quede del presupuesto de Alexa.
  Las acciones `nota` y `completar_pendiente` se pueden procesar más tarde si la PC estaba apagada.
- **Acciones:** la lista completa está en `PC_ACTIONS` dentro de `lambda/lambda_function.py`, y el
  formato de `datos` de cada una, en el prompt `PERSONA` del mismo archivo.

`<topico>` y `clave` son las dos mitades de `CEREBRO_LINK` (`topico:clave`).
