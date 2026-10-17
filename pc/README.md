# Agente de PC

Es el programa que corre en tu computadora (Windows) y ejecuta lo que le pedís a Cerebro desde el
Echo o desde Telegram: notas y pendientes, abrir apps y sitios, música, apagar o suspender,
WhatsApp de escritorio, luces y enchufes, capturas, agenda, mails, avisos automáticos y tareas
largas con Claude Code.

La skill funciona completa sin él (conversación, memoria, recordatorios, temporizadores, radio y
datos en vivo). Con él, Cerebro tiene manos.

**Instalación paso a paso:** [docs/INSTALACION.md](../docs/INSTALACION.md#6-el-agente-de-pc-opcional).
**Qué le podés pedir:** [docs/USO.md](../docs/USO.md#con-el-agente-de-pc).

## Archivos

| Archivo | Qué hace |
|---|---|
| `cerebro_pc.py` | El agente. Escucha ntfy.sh y Telegram, valida la firma de cada orden y la ejecuta. Corre sin ventana con `pythonw`. |
| `panel.py` / `panel.html` | El [panel web local](../docs/PANEL.md): todas las acciones con formulario, consola, automatizaciones, notas, tareas, casa, memoria y registro. Lo arranca el agente; solo biblioteca estándar. |
| `abrir-panel.bat` | Abre el panel en el navegador con el token puesto. |
| `panel_escritorio.py` / `instalar-panel-escritorio.bat` | Para tu **PC principal** cuando el agente corre en otra: instala la ventana "Cerebro Panel" que abre el panel de la otra PC (la encuentra en la red y guarda el token). |
| `config.example.json` | Plantilla de configuración. Copiala a `config_pc.json` (ese archivo nunca va al repo). |
| `instalar.bat` | Crea el acceso directo de inicio de Windows y arranca el agente. |
| `instalar-extras.bat` | Instala las dependencias opcionales: pantalla y WhatsApp, luces y enchufes, agenda. |
| `configurar.bat` / `configurar.py` | Asistente para conectar Google Calendar, Gmail, la hora del resumen y tu equipo. Prueba cada cosa en el momento. |
| `instalar-claude.bat` | Instala Claude Code, para las tareas largas y las de pantalla. |
| `ACTUALIZAR.bat` / `actualizar.ps1` | Actualiza una instalación existente sin tocar `config_pc.json` ni las claves. |
| `desinstalar.bat` | Detiene el agente y quita el arranque automático. No borra tus notas. |
| `agenda.py` | Lee Google Calendar (o cualquier calendario) por su link iCal secreto. Sin OAuth. |
| `correo.py` | Lee Gmail por IMAP con una contraseña de aplicación. Solo lee: nunca marca, borra ni manda. |
| `casa.py` | Luces WiZ y enchufes/luces TP-Link (Kasa y Tapo) por la red local. |
| `medios.py` | Qué está sonando, pausa, siguiente, anterior; reproducir en YouTube o Spotify. |
| `whatsapp_app.py` | Maneja la app de WhatsApp de escritorio que ya tenés abierta. Mira la pantalla con la IA para elegir el contacto correcto. |
| `escritorio.py` | Captura, mouse y teclado por línea de comandos. Lo usa Claude Code en las tareas de pantalla. |
| `info.py` | Clima, dólar y noticias, sin claves. |
| `papelera.ps1` | Manda a la Papelera en vez de borrar. Es lo único que Claude puede usar para "borrar". |

Cada módulo se puede probar solo desde la terminal (`python agenda.py hoy`, `python casa.py descubrir`,
`python medios.py sonando`…); el docstring de cada uno tiene los comandos.

## Cómo funciona

```
Echo ──► Skill de Alexa ──► ntfy.sh (tópico privado, mensaje firmado con HMAC-SHA256) ──► cerebro_pc.py
Celular ──► bot de Telegram ────────────────────────────────────────────────────────────► cerebro_pc.py
                                                                                             │
                                          notas · apps · música · sistema · WhatsApp · casa ◄─┤
                                          agenda · mails · capturas · avisos · Claude Code ◄──┘
```

- **Sin puertos abiertos a internet.** La PC solo hace conexiones salientes: escucha el tópico de ntfy.sh y
  el bot de Telegram. No hay que tocar el router ni tener IP fija. El panel web escucha solo en
  `127.0.0.1` (o en tu red de casa con `panel_en_red`), pide un token y lo peligroso exige confirmación.
- **Un panel para verlo y automatizarlo todo.** `panel.py` sirve `panel.html` en `http://127.0.0.1:8765/`:
  el catálogo completo de acciones con formulario, una consola de órdenes, rutinas por horario (también con
  una acción y sus datos exactos), alertas, resumen de la mañana, notas, tareas de Claude Code, luces,
  memoria y registro. Se abre con `abrir-panel.bat` o escribiendo "panel" al bot.
- **Lista cerrada de acciones.** `ACCIONES` en `cerebro_pc.py` es todo lo que la PC puede hacer.
  Una orden que no está ahí se rechaza, y una orden sin firma válida se ignora en silencio.
- **Lo delicado pide "sí".** Mandar un WhatsApp, apagar o reiniciar, y ejecutar un plan de
  Claude Code piden confirmación por voz o por Telegram.
- **Claude Code trabaja con red.** Las consultas corren con herramientas de solo lectura; los
  cambios primero se planifican, el plan te llega al celular, y se ejecuta cuando lo aprobás.
  Todo lo que Claude corre queda registrado en `Cerebro\Registro\AAAA-MM-DD.log`, y lo que
  "borra" va a la Papelera de reciclaje.
- **Solo tu chat de Telegram.** El bot detecta tu chat con el primer `/start` y desde ahí ignora
  a cualquier otro.
- **Si la PC estaba apagada**, las notas y los pendientes quedan en cola en ntfy.sh (hasta 12 horas)
  y se procesan al encender. El resto de las órdenes viejas se descarta.

## Protocolo, por si querés escribir tu propio agente

- **Ida:** la skill publica en `https://ntfy.sh/<topico>` un JSON `{"id", "ts", "accion", "datos", "firma"}`.
- **Firma:** `HMAC-SHA256(clave, f"{id}|{ts}|{accion}|{json.dumps(datos, sort_keys=True, ensure_ascii=False)}")`, en hexadecimal.
- **Vuelta:** el agente responde en `https://ntfy.sh/<topico>-r` con `{"id", "ok", "texto", "firma"}`,
  donde `firma = HMAC-SHA256(clave, f"{id}|{ok}|{texto}")`.
- **Tiempo:** la skill espera entre 1 y 4,5 segundos según lo que quede del presupuesto de Alexa.
- **Acciones:** la lista está en `PC_ACTIONS` dentro de `lambda/lambda_function.py`; el formato de
  `datos` de cada una, en el prompt `PERSONA` del mismo archivo y en `ACCIONES` de `cerebro_pc.py`.

`<topico>` y `clave` son las dos mitades de `CEREBRO_LINK` (`topico:clave`).

## Dónde queda todo

- Notas y pendientes: `C:\Users\<vos>\Cerebro` (`Inbox.md`, `Pendientes.md`, `Tareas\`, `Registro\`).
  Se puede cambiar con `carpeta_notas` en `config_pc.json`.
- Archivos que le mandás por Telegram: `Descargas\Cerebro`.
- Log del agente: `cerebro_pc.log`, junto a `cerebro_pc.py`.
- Token y puerto del panel: `estado.json` (`panel_token`, `panel_puerto`), junto a `cerebro_pc.py`.

## Limitaciones

Está hecho para **Windows** (usa `ctypes.windll`, accesos directos `.lnk`, `pythonw`). El control
de pantalla y WhatsApp dependen de la resolución y de que la app esté visible. Las pruebas en
[`pruebas/`](../pruebas) también son de Windows y usan la IA real.
