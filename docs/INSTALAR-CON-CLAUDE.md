# Instalar Cerebro en la segunda PC (instructivo para Claude Code)

Este documento está escrito para que **Claude Code, corriendo en Windows en la segunda PC**, haga la
instalación paso a paso. Cada paso dice qué hacer, cómo verificarlo y qué pedirle a la persona cuando
hace falta un dato que solo ella tiene (claves, tokens). Las cosas que pasan en la consola de Alexa las
hace la persona a mano: Claude prepara los archivos y le dice exactamente qué pegar.

Reglas para Claude:

- Trabajá en PowerShell. No instales nada fuera de lo que dice acá.
- **Nunca** pongas claves, tokens ni el enlace `cerebro_link` en archivos que vayan a git ni los
  muestres enteros en pantalla: `config_pc.json`, `panel_escritorio.json`, `estado.json` y
  `lambda/config.py` están en `.gitignore` y se quedan en esta PC.
- Si un paso falla, leé `C:\Cerebro\cerebro_pc.log` antes de reintentar y contá qué dice.
- Preguntale a la persona lo que no sepas (por ejemplo, si ya tiene un `cerebro_link` en la skill).

---

## 0. Qué va en cada PC

| | Segunda PC (esta) | PC principal |
|---|---|---|
| Agente `cerebro_pc.py` | sí | **no** |
| Panel web (lo sirve el agente) | sí, en la red de casa | se usa desde acá con la ventana "Cerebro Panel" |
| Orbe (la bola en pantalla) | sí | sí |

## 1. Requisitos

1. **Python 3.11 o más nuevo** con "Add python.exe to PATH". Verificar: `python --version` y
   `where pythonw.exe`. Si falta, instalarlo desde https://www.python.org/downloads/windows/ y volver a
   abrir PowerShell.
2. **Git** (opcional; si no está, se baja el ZIP). Verificar: `git --version`.
3. Para las tareas largas (opcional): **Node.js** y Claude Code (`instalar-claude.bat` lo instala).

## 2. Bajar el código

Con git:

```powershell
git clone -b claude/dreamy-ride-3ipp3w https://github.com/alfregarrone/cerebro.git C:\CerebroRepo
```

Sin git: bajar y descomprimir
`https://github.com/alfregarrone/cerebro/archive/refs/heads/claude/dreamy-ride-3ipp3w.zip` en
`C:\CerebroRepo` (queda una carpeta `cerebro-claude-dreamy-ride-3ipp3w`; usar esa como `C:\CerebroRepo`).

Copiar el agente a su carpeta definitiva (no en OneDrive ni en el Escritorio):

```powershell
New-Item -ItemType Directory -Force C:\Cerebro | Out-Null
Copy-Item C:\CerebroRepo\pc\* C:\Cerebro -Recurse -Force
```

## 3. Configurar el agente (`C:\Cerebro\config_pc.json`)

```powershell
Copy-Item C:\Cerebro\config.example.json C:\Cerebro\config_pc.json
```

Editar `config_pc.json` y completar:

- `cerebro_link`: el enlace con la skill, con la forma `topico:clave`. **Tiene que ser el mismo valor
  que `CEREBRO_LINK` en el `config.py` de la skill.** Preguntarle a la persona si ya tiene uno. Si no,
  generarlo con:
  ```powershell
  python -c "import secrets; print(f'cerebro-{secrets.token_hex(10)}:{secrets.token_hex(24)}')"
  ```
  y guardarlo: va acá y en la skill (paso 7).
- `gemini_api_key`: la clave gratuita de https://aistudio.google.com/apikey (pedírsela a la persona).
- `telegram_token`: opcional pero recomendado. Se crea hablándole a @BotFather en Telegram con `/newbot`.
- `panel_en_red`: ponerlo en `true`, así el panel se usa desde la PC principal.
- `equipos_prohibidos`: opcional; el nombre de la PC principal (`hostname` allá) para que el agente
  nunca arranque ahí aunque se copie la carpeta.
- Todo lo demás se puede dejar como está.

Verificar que sea JSON válido:

```powershell
python -c "import json; c=json.load(open(r'C:\Cerebro\config_pc.json', encoding='utf-8')); print('ok', len(c), 'claves; panel_en_red =', c.get('panel_en_red'))"
```

## 4. Instalar y arrancar el agente

```powershell
cd C:\Cerebro
.\instalar.bat
```

Tiene que terminar con "LISTO: Cerebro esta corriendo y arrancara solo con Windows". Verificar:

```powershell
Get-Content C:\Cerebro\cerebro_pc.log -Tail 15
```

Se espera una línea `Cerebro PC <versión> iniciado`, `conectado a ntfy` y `panel web en http://0.0.0.0:8765/`.
Si dice `no pude escuchar en el puerto`, el agente prueba los siguientes; el puerto real queda en
`estado.json` (`panel_puerto`).

## 5. El panel

```powershell
.\abrir-panel.bat
```

Abre el panel en el navegador con el token. Probar en la pestaña **Acciones** la acción *Notas → Guardar
una nota*: tiene que aparecer en `C:\Users\<usuario>\Cerebro\Inbox.md`.

Para la PC principal se necesitan dos datos: la **IP de esta PC** (`ipconfig`, la dirección IPv4 de la
red de casa) y el **token** (`estado.json`, campo `panel_token`; o escribirle "panel" al bot de Telegram).
Anotarlos para el paso 9 sin publicarlos.

## 6. Extras (opcionales, todos en `C:\Cerebro`)

- `.\instalar-extras.bat`: pantalla y WhatsApp de escritorio, luces WiZ y TP-Link, agenda.
- `.\configurar.bat`: Google Calendar (link iCal secreto), Gmail (contraseña de aplicación), hora del
  resumen y equipo de fútbol. Prueba cada cosa en el momento.
- `.\instalar-claude.bat`: Claude Code para las tareas largas y de pantalla. Después, una vez:
  `claude` en una terminal para iniciar sesión.
- Telegram: después de poner el token, abrir el chat con el bot y mandarle `/start`. **Hasta ese
  `/start` el bot no obedece a nadie**, y después solo a ese chat.

## 7. La skill en la consola de Alexa (lo hace la persona)

Claude prepara el archivo y dice qué pegar; la persona lo hace en https://developer.amazon.com/alexa/console/ask.

1. Preparar `lambda/config.py` a partir de `C:\CerebroRepo\lambda\config.example.py` con:
   `GEMINI_API_KEY`, `CEREBRO_LINK` (el mismo del paso 3), `HUD = True`, y la ciudad y zona horaria.
   Dejarlo en `C:\CerebroRepo\lambda\config.py` (está en `.gitignore`).
2. En la consola, pestaña **Build → Interaction Model → JSON Editor**: pegar el contenido de
   `C:\CerebroRepo\skill-package\interactionModels\custom\es-US.json`, **Save Model** y **Build Model**.
   Esta versión agrega `AMAZON.YesIntent`, `AMAZON.NoIntent`, `AMAZON.NextIntent` y `AMAZON.PreviousIntent`.
3. Pestaña **Code**: reemplazar `lambda_function.py` y `requirements.txt` con los de
   `C:\CerebroRepo\lambda\`, crear `lambda/config.py` con el contenido preparado en el punto 1, y
   **Deploy**.
4. Probar en la pestaña **Test**: "abrí cerebro" → "Hola. ¿En qué te ayudo?"; "apagá la compu" →
   pide confirmación; "no" → "Cancelado."

## 8. El orbe en esta PC

```powershell
cd C:\Cerebro
.\instalar-orbe.bat
```

Arranca con una secuencia de prueba (escucha, piensa, habla). Queda en el Inicio de Windows. Esc o doble
clic lo esconde; clic derecho lo cierra.

## 9. La PC principal (ventana del panel y orbe)

En la PC principal, copiar desde el repo (o desde `C:\Cerebro` de esta PC) estos archivos a una carpeta,
por ejemplo `C:\CerebroPanel`: `panel_escritorio.py`, `instalar-panel-escritorio.bat`, `orbe.py`,
`instalar-orbe.bat`, `panel.ico`. **No ejecutar `instalar.bat` ahí.**

1. `instalar-panel-escritorio.bat`: pide la dirección de esta PC (el botón *Buscar en la red* la
   encuentra sola), el puerto y el token del paso 5; *Probar* verifica la conexión. Deja el acceso
   directo **Cerebro Panel** en el Escritorio y el menú Inicio.
2. `instalar-orbe.bat`: pide el `cerebro_link` (el mismo del paso 3) y deja el orbe en el Inicio.

## 10. Verificación final

- [ ] `Get-Content C:\Cerebro\cerebro_pc.log -Tail 5` sin errores recientes.
- [ ] Desde el Echo: "Alexa, abrí cerebro" → aparece el orbe escuchando; "anotá que tengo que comprar
      pilas" → "Anotado" y la nota en `Inbox.md`; "apagá la compu" → pide confirmación.
- [ ] Panel abierto desde la PC principal, pestaña *Registro* mostrando lo anterior.
- [ ] Telegram: "qué pendientes tengo" responde; "panel" devuelve el link.
- [ ] En el repo no quedó ningún archivo con claves: `git -C C:\CerebroRepo status` tiene que estar limpio.
