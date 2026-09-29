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

Todo lo de esta sección necesita `pc/cerebro_pc.py` corriendo en tu computadora
([cómo instalarlo](INSTALACION.md#6-el-agente-de-pc-opcional)). Si la PC está apagada, las notas
y los pendientes se guardan y se procesan cuando la prendas.

### Notas y pendientes

> *"anotá que tengo que llamar a Marta por el presupuesto"*
> *"agregá a pendientes comprar pilas"*, *"¿qué tengo pendiente?"*, *"listo lo de las pilas"*
> *"buscá en mis notas lo del presupuesto"*
> *"agregá leche a las compras"*, *"¿qué hay en la lista de compras?"*

### Abrir y controlar

> *"abrí YouTube"*, *"abrí Spotify"*, *"cerrá Chrome"*
> *"poné música"*, *"poné algo de rock"*, *"subí el volumen"*, *"pausá la música"*
> *"sacá una captura"*, *"¿cómo anda la compu?"* — CPU, memoria, disco, temperatura
> *"apagá la compu"*, *"reiniciá"*, *"suspendé"* — **pide confirmación**: "¿Seguro?" → *"sí"*

### WhatsApp

> *"mandale un WhatsApp a Juan que llego veinte minutos tarde"* → te lee el mensaje y pide confirmación
> *"¿tengo mensajes de Juan?"*, *"leeme los últimos mensajes de mamá"*
> *"resumime el grupo de la familia"*
> *"mandale a Juan la foto del presupuesto"*

### Agenda y mails

> *"¿qué tengo hoy?"*, *"¿qué tengo mañana en la agenda?"*, *"¿qué tengo esta semana?"*
> *"¿tengo mails nuevos?"*, *"¿qué correos tengo?"*

### Casa (domótica)

> *"prendé la luz del living"*, *"apagá todo"*, *"poné la luz en azul"*, *"escena relax"*
> *"buscá aparatos"* — descubre dispositivos en la red
> *"a este llamalo lámpara del escritorio"*

### Tareas con Claude Code

Le podés pedir a Cerebro que le pase trabajo a Claude Code en tu PC:

> *"pedile a Claude que arregle el bug del login en pesito"*
> *"¿cómo va la tarea?"*, *"cancelá la tarea"*

Te confirma qué va a pedir antes de mandarlo, y te avisa al celular cuando termina.

### Programar cosas

> *"todos los viernes a las seis, mandame el resumen de la semana"*
> *"¿qué tengo programado?"*, *"borrá lo del viernes"*

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
