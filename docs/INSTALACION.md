# Instalación

Tiempo estimado: **20 minutos** para la skill, **10 más** para el agente de PC. No hace falta
tarjeta de crédito en ningún paso.

Vas a necesitar:

- Una cuenta de Amazon (la misma con la que está configurado tu Echo).
- Una cuenta de Google para la clave gratuita de Gemini.
- Un Echo o la app de Alexa en el celular para probar.

---

## 1. La clave de Gemini

1. Entrá a [aistudio.google.com/apikey](https://aistudio.google.com/apikey) y creá una clave.
2. Guardala: la vas a pegar en el paso 4.

Es el único secreto que la skill necesita para funcionar. El nivel gratuito alcanza para uso
personal; si un día se agota la cuota, Cerebro te avisa por voz en vez de quedarse callado.

## 2. Crear la skill en la consola de Alexa

1. Entrá a [developer.amazon.com/alexa/console/ask](https://developer.amazon.com/alexa/console/ask)
   con tu cuenta de Amazon y tocá **Create Skill**.
2. Completá:
   - **Skill name:** el que quieras (ej. *Cerebro*). Es el nombre que ves en la consola.
   - **Primary locale:** **Spanish (US)** — `es-US`. Es el español que Alexa ofrece para
     Latinoamérica y el que usa el modelo de interacción.
   - **Type of experience:** *Other*.
   - **Model:** *Custom*.
   - **Hosting services:** **Alexa-hosted (Python)**. Esto te da la Lambda, la base de datos y
     el editor de código sin configurar nada de AWS.
3. En la siguiente pantalla elegí **Start from scratch** y tocá **Create Skill**. Tarda un minuto.

## 3. El modelo de interacción

Es lo que le dice a Alexa qué frases activan qué cosa.

1. En el menú de la izquierda, **Interaction Model → JSON Editor**.
2. Borrá lo que hay y pegá el contenido de
   [`skill-package/interactionModels/custom/es-US.json`](../skill-package/interactionModels/custom/es-US.json).
3. **Save Model** y después **Build Model**. El build tarda uno o dos minutos.

El nombre de invocación queda en **cerebro** ("Alexa, abrí cerebro"). Si querés otro, cambiá
`invocationName` en el JSON antes de pegarlo — tiene que ser en minúsculas, sin acentos, y de dos
palabras o una palabra que no sea de uso común.

### Permisos

Para que Cerebro pueda crear recordatorios y temporizadores:

1. Menú de la izquierda, abajo: **Permissions** (dentro de *Tools*).
2. Activá **Reminders** y **Timers**.

La primera vez que le pidas un recordatorio, Alexa te va a mandar una tarjeta a la app para que
confirmes el permiso. Es una sola vez.

### Audio (radio)

En **Interfaces**, activá **Audio Player**. Sin esto, "poné Mitre" no funciona.

## 4. El código

1. Pestaña **Code** arriba.
2. Vas a ver `lambda/lambda_function.py`, `requirements.txt` y `utils.py` de ejemplo. Reemplazá:
   - `lambda_function.py` → pegá el contenido de [`lambda/lambda_function.py`](../lambda/lambda_function.py)
   - `requirements.txt` → pegá el de [`lambda/requirements.txt`](../lambda/requirements.txt)
   - `utils.py` → podés dejarlo como está o pegar el del repo; no se usa.
3. Creá un archivo nuevo (**File → New File**) llamado `lambda/config.py` y pegá el contenido de
   [`lambda/config.example.py`](../lambda/config.example.py). Completá:

   ```python
   GEMINI_API_KEY = "tu-clave-de-aistudio"
   CITY = "Buenos Aires"          # para el clima y el resumen del día
   LATITUDE = -34.6037
   LONGITUDE = -58.3816
   UTC_OFFSET_HOURS = -3
   TIMEZONE_ID = "America/Argentina/Buenos_Aires"
   CEREBRO_LINK = ""              # se completa en el paso 6, si instalás el agente de PC
   ```

   `config.py` nunca va a un repositorio: contiene tu clave.

4. **Save** y **Deploy**. El primer deploy instala las dependencias y tarda dos o tres minutos.

## 5. Probar

1. Pestaña **Test**, cambiá *Off* por **Development**.
2. Escribí o decí: *abrí cerebro*. Tiene que responder "Hola. ¿En qué te ayudo?".
3. Probá: *¿a cuánto está el dólar?* y *poné dos minutos*.

Como la skill está en modo desarrollo bajo tu cuenta, **ya funciona en tu Echo** sin publicarla:
decile "Alexa, abrí cerebro". Si no te la reconoce, verificá que el Echo esté con el mismo Amazon
que la consola y que su idioma sea *Español (Estados Unidos)* — se cambia en la app de Alexa,
en la configuración del dispositivo.

## 6. El agente de PC *(opcional)*

Habilita todo lo que involucra tu computadora: notas y pendientes, abrir apps y sitios, música,
apagar o suspender, WhatsApp de escritorio, luces y enchufes, capturas, agenda, mails, avisos
automáticos al celular y tareas con Claude Code. También te deja **manejar la PC desde Telegram**
cuando no estás cerca del Echo. Está hecho para **Windows**.

### Cómo funciona el enlace

La skill y tu PC se hablan a través de [ntfy.sh](https://ntfy.sh), un servicio público de
mensajes. No hay que abrir puertos ni tener IP fija: la PC se conecta hacia afuera y escucha. Cada
mensaje va **firmado con HMAC-SHA256** usando una clave que solo conocen la skill y tu PC, así que
aunque alguien adivine el nombre del tópico no puede darle órdenes.

El enlace es un string con la forma `topico:clave`. Generá uno así (en cualquier terminal con
Python):

```bash
python -c "import secrets; print(f'cerebro-{secrets.token_hex(10)}:{secrets.token_hex(24)}')"
```

Te da algo como `cerebro-9e36…:6053…`. Ese valor va en **dos** lugares:

1. En `lambda/config.py` de la skill, en `CEREBRO_LINK = "..."`. Volvé a hacer **Deploy**.
2. En `config_pc.json` del agente, en `"cerebro_link"` (paso siguiente).

### Instalar el agente

1. Instalá Python 3.11 o más nuevo desde [python.org](https://www.python.org/downloads/windows/)
   marcando **Add python.exe to PATH**.
2. Copiá la carpeta [`pc/`](../pc) del repo a tu computadora, por ejemplo en `C:\Cerebro`. No la
   dejes dentro de OneDrive ni en el Escritorio: son carpetas que Windows sincroniza y mueve.
3. Copiá `config.example.json` a **`config_pc.json`** y completá:

   ```json
   {
     "cerebro_link": "cerebro-9e36…:6053…",
     "gemini_api_key": "tu-clave-de-aistudio",
     "telegram_token": "",
     "equipos_prohibidos": []
   }
   ```

   - `cerebro_link`: el enlace del paso anterior.
   - `gemini_api_key`: la misma clave que pusiste en la skill. La PC la usa para entender lo que
     le escribís por Telegram y para mirar la pantalla en WhatsApp. Si preferís no tenerla en el
     JSON, ponela sola en un archivo `gemini_key.txt` en la misma carpeta.
   - `telegram_token`: opcional pero muy recomendable, es el canal para los avisos al celular y
     para darle órdenes sin el Echo. Ver más abajo.
   - `equipos_prohibidos`: dejalo vacío. Sirve si instalás Cerebro en una segunda PC y querés
     asegurarte de que nunca corra en la principal: `["NOMBRE-DE-LA-PC-PRINCIPAL"]`.

   Todo lo demás se puede dejar como está o completar después con `configurar.bat`.

4. Doble clic en **`instalar.bat`**. Crea el acceso directo en la carpeta *Inicio* de Windows,
   arranca el agente sin ventana y te dice en verde si quedó corriendo.
5. Probalo desde el Echo: *"anotá que tengo que comprar pilas"* → "Anotado". La nota queda en
   `C:\Users\<vos>\Cerebro\Inbox.md`.

Si algo falla, el archivo `cerebro_pc.log` de esa carpeta dice por qué.

### Telegram *(recomendado)*

Con un bot de Telegram, Cerebro te manda al celular las cosas largas (recetas, listas, resultados
de tareas, fotos de la pantalla), te avisa solo (dólar, lluvia, mails importantes, agenda), y le
podés escribir o mandarle notas de voz para que haga cosas en la PC sin pasar por Alexa.

1. En Telegram, hablale a **@BotFather**, mandá `/newbot` y seguí los pasos. Te da un *token*.
2. Pegalo en `config_pc.json`, en `"telegram_token"`.
3. Abrí el chat con tu bot nuevo y mandale `/start`. El agente detecta tu chat con ese primer
   mensaje y **desde ahí ignora a cualquier otra persona**.
4. Reiniciá el agente (`configurar.bat` lo hace) y escribile: *"qué pendientes tengo"*.

### Extras: pantalla, WhatsApp, luces, agenda y mails

1. **`instalar-extras.bat`** instala las dependencias de pantalla y WhatsApp de escritorio
   (pyautogui, pillow, pyperclip, pygetwindow), luces y enchufes (python-kasa, pywizlight) y
   agenda (icalendar, recurring-ical-events).
2. **`configurar.bat`** abre un asistente que conecta y prueba en el momento:
   - **Google Calendar:** con el *link secreto iCal* del calendario (Configuración del calendario →
     *Dirección secreta en formato iCal*). Sin contraseña ni permisos de Google.
   - **Gmail:** con una [contraseña de aplicación](https://myaccount.google.com/apppasswords), no tu
     contraseña. Solo lee: nunca marca como leído, borra ni manda.
   - La **hora del resumen de la mañana** y **tu equipo** de fútbol, para que te avise si juega.
3. **WhatsApp** usa la app de WhatsApp de escritorio que ya tenés abierta y logueada: no hay QR ni
   WhatsApp Web. Necesita la clave de Gemini para mirar la pantalla y elegir el contacto correcto.
4. **Luces y enchufes:** *"buscá aparatos"* descubre luces WiZ y dispositivos TP-Link (Kasa/Tapo)
   en tu red. Para Tapo hace falta el usuario y la clave de la cuenta TP-Link en `tplink_usuario`
   y `tplink_clave`. Después les ponés nombre: *"a este llamalo lámpara del escritorio"*.

### Claude Code *(para las tareas largas)*

Las tareas ("pedile a Claude que ordene mi carpeta de descargas") y las tareas de pantalla ("fijate
en Instagram si tengo mensajes") las hace [Claude Code](https://claude.com/claude-code) en tu PC.
**`instalar-claude.bat`** lo instala (necesita Node.js); después iniciá sesión una vez con `claude`
en una terminal. Las consultas corren con herramientas de solo lectura; los cambios primero se
planifican, el plan te llega al celular y se ejecuta cuando lo aprobás.

### Actualizar y desinstalar

- **`ACTUALIZAR.bat`** desde una carpeta con la versión nueva: copia los archivos a donde está
  instalado, sin tocar `config_pc.json` ni las claves, y reinicia el agente.
- **`desinstalar.bat`** detiene el agente y quita el arranque automático. Tus notas quedan.

Si la PC está apagada cuando le hablás, las notas y los pendientes quedan en cola hasta 12 horas y
se procesan al encenderse. El resto de las acciones responde "no tengo conexión con la compu".

---

## Problemas frecuentes

**"No sé cómo ayudarte con eso" o Alexa abre otra cosa.**
El Echo no está en `es-US` o la skill no terminó el build. Revisá el idioma del dispositivo en la
app de Alexa y que en la consola diga *Build Successful*.

**Responde lento o se corta.**
Es la latencia de Gemini gratuito en horas pico. El código ya consulta varios modelos a la vez;
podés ajustar el orden en `MODELS` dentro de `config.py`. Los pedidos frecuentes (timers, dólar,
clima) no pasan por la IA y siempre responden en un segundo.

**"Me quedé sin cupo".**
Se agotó la cuota diaria gratuita de Gemini. Se renueva sola cada día.

**Los recordatorios no se crean.**
Falta aceptar el permiso en la app de Alexa: buscá la tarjeta que te mandó o entrá a *Skills →
Tus skills → Cerebro → Configuración*.

**La PC no responde.**
El agente no está corriendo, o el `CEREBRO_LINK` no es el mismo en los dos lados. Mirá la terminal
del agente: si no muestra nada al hablarle, el problema es el enlace.
