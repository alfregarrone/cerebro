# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Una sola persona en Argentina (habla en voseo rioplatense) que usa Cerebro en su casa: le habla al Echo, le escribe al bot de Telegram y abre el panel en la PC. Conoce bien el sistema, pero no quiere que el panel parezca una herramienta de programador. Usa el panel sobre todo en una ventana grande de escritorio (la ventana "Cerebro Panel" en la PC principal o el navegador en la PC del agente); el celular en la red de casa es secundario.

## Product Purpose

Cerebro conecta Alexa con un modelo de lenguaje y le da memoria, acciones y "manos" en la PC. El panel es la cara de esas manos: una página local, servida por el agente de PC, desde donde se ve si todo anda, se ejecuta cualquier cosa que la PC sabe hacer y se deja automatizado. Éxito: abrirlo, entender en un vistazo si algo necesita atención, y hacer lo que vino a hacer en uno o dos clics, sin esperas ni errores.

## Positioning

No es un tablero genérico de domótica ni una consola de servidor: es el mismo asistente con el que la persona habla por voz y por Telegram, visto en pantalla. Todo lo que muestra son cosas que también se le pueden pedir con palabras ("prendé la luz del living", "qué tengo pendiente"), y el panel lo hace explícito.

## Operating Context

- Lo sirve `pc/panel.py` dentro del agente `pc/cerebro_pc.py` (Python, biblioteca estándar), en `http://127.0.0.1:8765/` o en la red de casa. Sin internet, sin dependencias, un único `pc/panel.html`.
- Acceso con token (cookie de 30 días); las escrituras exigen la cabecera `X-Cerebro-Panel: 1`; las acciones peligrosas piden confirmación.
- Se refresca solo cada 5 segundos. Convive con Telegram y el Echo: lo que se hace por un lado aparece en los otros (registro, pendientes, avisos).
- Usos frecuentes, todos con el mismo peso: ver estado y avisos, acciones rápidas, notas/pendientes/compras, automatizaciones y tareas con Claude Code.

## Capabilities and Constraints

- Pestañas que la persona ya conoce y no quiere perder: Inicio, Acciones, Automatizaciones, Notas, Tareas, Casa, Memoria, Registro (ver `docs/PANEL.md`).
- El catálogo de acciones (unas 60) llega de `/api/acciones` con formularios generados por campos; las automatizaciones, alertas, resumen de la mañana, notas, tareas, casa, memoria y registro tienen su propia API.
- Tiene que ser rápido y no trabarse nunca: nada que bloquee la interfaz, respuestas inmediatas a cada clic, errores claros.
- Terminología del producto: "acción", "automatización", "rutina", "aviso", "alerta", "pendiente", "Inbox", "tarea" (de Claude Code), "plan", "informe", "agente".

## Brand Commitments

Nombre "Cerebro". Voz en español rioplatense, cercana y directa ("Anotado.", "¿Seguro?"). Sin jerga técnica a la vista salvo donde se pide (Registro).

## Evidence on Hand

Datos reales del agente vía la API local; no hay fotos ni logos aparte del ícono `pc/panel.ico` / `pc/panel.png`.

## Product Principles

1. Lo que necesita atención primero; el resto, a un clic.
2. Cada clic responde al instante y dice qué pasó, en palabras de persona.
3. Nunca trabarse: un agente lento o caído se muestra con calma y se recupera solo.
4. Mismo asistente, otra superficie: lo que se ve se puede pedir con palabras.
5. Poca información por pantalla; los detalles técnicos, guardados.

## Accessibility & Inclusion

Uso con teclado y lector de pantalla básico (foco visible, etiquetas en controles); contraste suficiente en claro y oscuro.
