# Cómo usar Cerebro

Todo empieza con **"Alexa, abrí cerebro"**. Desde ahí hablás normal; no hace falta repetir
"Alexa" ni "cerebro" hasta que la conversación termine. Para cerrar: *"eso es todo"*, *"chau"*,
o simplemente dejá de hablar.

También podés decirlo todo junto: *"Alexa, preguntale a cerebro a cuánto está el dólar"*.

---

## Conversar

Le podés preguntar cualquier cosa. Responde corto porque lo que dice se escucha, no se lee: una o
dos frases, y más solo si pedís detalle.

> *"explicame la computación cuántica de forma simple"*
> *"¿qué puedo cocinar con arroz, huevo y cebolla?"*
> *"dame una idea para un regalo de cumpleaños de quince"*

Entiende cómo hablás: voseo, "la compu", "el celu", "un toque", "dale". Y como lo que le llega es
voz transcrita, interpreta por contexto en vez de pedir que repitas.

## Memoria

Lo que le contás sobre vos se guarda entre conversaciones, sin que se lo pidas.

> *"mi vieja se llama Marta"* → una semana después: *"¿cómo se llama mi vieja?"*
> *"trabajo de nueve a seis"*
> *"no me gusta el cilantro"*

Para manejarla:

- *"¿qué sabés de mí?"* — te lee lo que tiene guardado.
- *"olvidate de lo del cilantro"* — borra lo que contenga ese texto.
- Si se equivoca y lo corregís (*"no, eso no, lo que quería era…"*), lo guarda como aprendizaje
  para no repetirlo.

Guarda hasta 60 datos fijos y recuerda los últimos 10 mensajes de la charla anterior.

## Recordatorios y alarmas

Se crean como recordatorios reales de Alexa: suenan en el Echo aunque la skill esté cerrada.

| Decís | Pasa |
|---|---|
| *"recordame en veinte minutos sacar la pizza"* | Un recordatorio en 20 min |
| *"recordame mañana a las diez llamar al dentista"* | Fecha y hora concretas |
| *"despertame a las siete"* | Una alarma |
| *"todos los días a las nueve, tomar la pastilla"* | Se repite a diario |
| *"los lunes y jueves a las ocho, sacar la basura"* | Se repite esos días |
| *"cada dos horas de nueve a veintiuno, tomar agua"* | Se repite por intervalo |
| *"¿qué recordatorios tengo?"* | Te los lee |
| *"borrá el recordatorio de la pizza"* / *"borrá todos"* | Los elimina |

La primera vez, Alexa te pide permiso desde la app. Es una sola vez.

## Temporizadores

> *"poné diez minutos"*, *"poné un temporizador de una hora y media para el horno"*
> *"¿cuánto falta?"*, *"cancelá el temporizador"*

Los temporizadores y las alarmas van por la **vía rápida**: no pasan por la IA y responden en un
segundo.

## Argentina en vivo

Todo gratis y sin claves, de APIs públicas.

| Decís | Fuente |
|---|---|
| *"¿a cuánto está el dólar?"* — oficial, blue, MEP y tarjeta | DolarApi |
| *"¿a cuánto está el euro?"*, *"el real"*, *"el bitcoin"* | DolarApi, CoinGecko |
| *"¿cuántos pesos son cien dólares?"*, *"¿cuántos euros son cincuenta mil pesos?"* | conversión con la cotización del momento |
| *"¿cuándo es el próximo feriado?"* | ArgentinaDatos |
| *"¿cómo va el riesgo país?"*, *"¿cuánto fue la inflación?"* | ArgentinaDatos |
| *"¿qué tiempo hace?"*, *"¿llueve mañana?"*, *"¿qué tiempo hace el finde en Córdoba?"* | Open-Meteo |
| *"¿qué pasó hoy?"*, *"noticias de economía"* | Google News |
| *"¿cómo salió Boca?"*, *"¿cuándo juega River?"*, *"partidos de la fecha"* | ESPN, TheSportsDB |

## Radio

> *"poné Mitre"*, *"poné La 100"*, *"poné Rock and Pop"*, *"poné una radio de jazz"*
> *"pausá"*, *"seguí"*, *"siguiente"*

Suena en el Echo como cualquier radio de Alexa. Busca en el directorio público Radio Browser.

## Resumen del día

> *"buenos días"*, *"dame el resumen del día"*

Una sola frase con la hora, el clima, el dólar blue, tu agenda de hoy y tus pendientes (si tenés
el agente de PC), y el feriado si cae esta semana. Se arma en un segundo, sin IA.

## Mandarte cosas al celular

Cuando la respuesta es larga (una receta, una lista, un dato para copiar), la manda a tu celular en
vez de leerla entera:

> *"pasame eso al celular"*, *"mandame la receta"*

Llega por Telegram si configuraste el agente de PC; si no, por notificación de ntfy.

---

## Con el agente de PC

Todo lo de esta sección necesita el agente corriendo en tu computadora
([cómo instalarlo](INSTALACION.md#6-el-agente-de-pc-opcional)). Si la PC está apagada, las notas
y los pendientes se guardan y se procesan cuando la prendas.

### Notas y pendientes

> *"anotá que tengo que llamar a Marta por el presupuesto"*
> *"agregá a pendientes comprar pilas"*, *"¿qué tengo pendiente?"*, *"listo lo de las pilas"*
> *"buscá en mis notas lo del presupuesto"*
> *"agregá leche a las compras"*, *"¿qué hay en la lista de compras?"*

Quedan en archivos Markdown en `C:\Users\<vos>\Cerebro`, así que los podés abrir con cualquier cosa.

### Abrir y controlar

> *"abrí YouTube"*, *"abrí Spotify"*, *"cerrá Chrome"*
> *"poné música de Soda Stereo"* — arranca en YouTube y sigue con temas parecidos
> *"poné Ciro en Spotify"*, *"pausá"*, *"seguí"*, *"siguiente"*, *"¿qué está sonando?"*
> *"subí el volumen"*, *"poné el volumen al treinta"*, *"silenciá la compu"*
> *"sacá una captura"*, *"¿cómo está la compu?"* — disco, memoria, procesador, internet, hace cuánto está prendida
> *"bloqueá la pc"*, *"suspendé"*, *"apagá la compu"*, *"reiniciá"* — **piden confirmación**: "¿Seguro?" → *"sí"*

### WhatsApp

Usa la app de WhatsApp de escritorio que ya tenés abierta. Mira la pantalla con la IA para elegir
el chat correcto: si hay dos "Juan", te pregunta cuál. **Nunca manda nada sin tu "sí".**

> *"mandale un WhatsApp a Juan que llego veinte minutos tarde"* → te lee contacto y mensaje, y espera el "sí"
> *"mandale a Laura el pdf del presupuesto"* → busca el archivo y lo manda (con "sí")
> *"corregí el mensaje a Juan: voy en diez"* → edita tu último mensaje (con "sí")
> *"¿qué mensajes tengo?"* → resumen de los chats sin leer
> *"¿qué me escribió Laura?"* → te lee y resume lo último de ese chat

Si no sabe quién es "mi vieja", no adivina: contale una vez (*"mi vieja se llama Marta"*) y listo.

### Agenda y mails

> *"¿qué tengo hoy?"*, *"¿qué tengo mañana?"*, *"¿qué tengo el viernes?"*, *"agenda de la semana"*
> *"¿tengo mails?"*, *"resumime los mails"* — primero los importantes; por voz te dice cuántos y de quién, el resumen completo te llega al celular

La agenda se lee de Google Calendar y los mails de Gmail, solo lectura (se conectan con
`configurar.bat`). Treinta minutos antes de cada evento te avisa por Telegram, y también cuando
llega un mail que Gmail marca como importante.

### Casa (luces y enchufes)

> *"prendé la luz del living"*, *"apagá todo"*, *"poné la luz en azul"*, *"la luz al treinta"*, *"modo cine"*
> *"buscá aparatos"* — descubre luces WiZ y dispositivos TP-Link en la red
> *"a la luz nueva llamala luz del living"*

Cada seis horas busca aparatos nuevos solo y te avisa si aparece uno.

### Resumen de la mañana

Todas las mañanas (a las 8, o a la hora que elijas) te llega por Telegram: clima, agenda del día,
si juega tu equipo, pendientes, mails sin leer, dólar y titulares. Si la PC estaba apagada, llega
igual cuando prende (hasta tres horas después).

> *"resumen"* — te lo manda en el momento
> *"mandame el resumen a las siete y media"*, *"el resumen de lunes a viernes a las siete"*, *"desactivá el resumen"*
> *"soy de River, avisame en el resumen si juega"*

### Avisos solos

Te escribe por Telegram sin que le preguntes:

- **Dólar:** si el blue se mueve 2 % o más (y al menos 15 pesos) desde el cierre anterior o el último aviso, de lunes a viernes de 9 a 21.
- **Lluvia:** a la mañana si va a llover en el día, y un aviso si se viene lluvia en la próxima hora y media.
- **Salud de la PC:** disco llenándose, memoria al límite, se cortó internet (y cuánto duró), la PC se reinició.
- **Mails importantes** y **eventos de la agenda** (30 minutos antes).

> *"desactivá las alertas del dólar"*, *"activá todas las alertas"*, *"¿qué alertas tengo?"*

### Programar cosas

> *"todos los viernes a las seis, mandame el resumen de la semana"*
> *"de lunes a viernes a las siete prendé la luz"* — la PC lo hace sola a esa hora
> *"recordame tomar agua cada dos horas"* — aviso repetido al celular
> *"¿qué tengo programado?"*, *"borrá lo del viernes"*

### Tareas con Claude Code

Cerebro le pasa trabajo a [Claude Code](https://claude.com/claude-code) en tu PC:

> *"pedile a Claude que ordene mi carpeta de descargas"*
> *"investigá las mejores estrategias de marketing para apps"* → el informe te llega al celular
> *"fijate en Instagram si tengo mensajes nuevos"* → maneja la pantalla, y te manda una foto al terminar
> *"subí a Facebook una publicación que diga que mañana abrimos a las nueve"* → la deja lista **sin publicar** hasta que digas *"confirmá la publicación"*
> *"¿cómo va la tarea?"*, *"cancelá la tarea"*

Las consultas corren con herramientas de solo lectura. Los cambios primero se planifican: el plan
te llega al celular y se ejecuta cuando decís *"confirmá la tarea"*. Lo que Claude "borra" va a la
Papelera, y cada comando queda en `Cerebro\Registro\`.

### Desde Telegram, sin el Echo

Escribile al bot (o mandale una nota de voz) como le hablarías a alguien. Hace lo mismo que por
voz, y además:

> *"armame un Excel con los gastos y mandamelo"* → Claude lo hace, te va contando cómo va y te manda el archivo
> *"pantalla"* → te manda una captura. *"mandame el archivo presupuesto"* → te lo manda
> Mandale una foto o un archivo → lo guarda en `Descargas\Cerebro`; con una indicación (*"guardalo en el escritorio como factura"*), la hace
> *"¿cuánto está el dólar?"*, *"¿cuándo juega Boca?"*, *"noticias"* — los mismos datos en vivo que por voz

Solo acepta órdenes de **tu** chat: los mensajes de otras personas se ignoran.

### El panel en la PC

Todo lo de arriba, pero con botones: una página local con todas las acciones de la PC (cada una con su
formulario y sus ejemplos de voz), una consola para escribir órdenes como por Telegram, y las
automatizaciones (rutinas por horario, avisos, alertas, resumen de la mañana). También notas, compras,
tareas de Claude Code con sus informes, luces, memoria y el registro.

> `abrir-panel.bat` en la PC, o escribile *"panel"* al bot y te manda el link
> Con `"panel_en_red": true` en `config_pc.json` lo usás desde tu otra PC o el celular en la misma red

Para dejar algo automatizado: en **Acciones** completás la acción, tocás **Automatizar**, elegís cuándo
(a una hora y qué días, cada tantos minutos, o dentro de tantos minutos) y listo: la PC la ejecuta sola con
esos datos exactos y te manda el resultado al celular. La guía completa está en [PANEL.md](PANEL.md).

### Aprende solo

No hay frases fijas: entiende cada pedido con la IA. Si se equivoca, decile *"no, eso no, quería…"*:
hace lo correcto y lo tiene en cuenta la próxima vez. Lo que le contás (nombres, gustos, cómo
llamás a tus cosas) lo guarda solo. *"¿qué aprendiste?"* y *"olvidate de…"* para ver o borrar.

---

## Consejos

- **Hablá natural.** No hay comandos fijos; el modelo interpreta. Si algo no lo entiende, decilo
  de otra forma.
- **Las cosas rápidas, directas.** "poné cinco minutos" responde al instante. "¿podrías ponerme
  un temporizador de cinco minutos por favor?" también funciona, pero pasa por la IA y tarda un
  par de segundos más.
- **Si dice "un segundo"**, es que Gemini está lento; espera hasta el límite de Alexa y te
  responde igual.
- **Si dice "me quedé sin cupo"**, se agotó la cuota gratuita del día. Los temporizadores, alarmas
  y datos en vivo siguen funcionando porque no usan IA.
