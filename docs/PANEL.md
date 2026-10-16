# El panel de la PC

Es una página web que corre adentro del agente de PC (`pc/panel.py` + `pc/panel.html`). Desde ahí ves y
ejecutás **todo lo que la PC sabe hacer** (cada acción de `ACCIONES`, con su formulario) y lo dejás
**automatizado**: rutinas por horario, avisos al celular, alertas y el resumen de la mañana. Anda sin internet,
no instala nada y se usa desde la misma PC o, si querés, desde tu otra PC o el celular en la misma red.

Necesita el agente corriendo ([cómo instalarlo](INSTALACION.md#6-el-agente-de-pc-opcional)). La skill de Alexa
no interviene: el panel le habla directo al agente.

## Abrirlo

- **En la PC donde corre el agente:** doble clic en **`abrir-panel.bat`**. Abre el navegador ya con el token.
- **Por Telegram:** escribile `panel` al bot y te manda el link con el token. Sirve para abrirlo desde el celular
  o desde la otra PC (ver más abajo).
- **A mano:** entrá a `http://127.0.0.1:8765/` y pegá el token. Está en `estado.json` (clave `panel_token`),
  en la carpeta del agente.

El token se guarda en una cookie del navegador por 30 días, así que lo pegás una sola vez por dispositivo.

## Desde tu otra PC o el celular

Por defecto el panel escucha **solo en la PC donde corre** (`127.0.0.1`). Para usarlo desde otra computadora o
desde el celular en la misma red de tu casa:

1. En `config_pc.json` poné `"panel_en_red": true` y reiniciá el agente (`configurar.bat` lo reinicia, o
   `ACTUALIZAR.bat`).
2. Escribile `panel` al bot de Telegram: el link ya trae la dirección de la PC en tu red (algo como
   `http://192.168.1.20:8765/?token=…`). Abrilo en el otro dispositivo.
3. La primera vez, Windows puede preguntar si dejás que Python acepte conexiones: permitilo en **redes privadas**.
   Si no preguntó y desde el celular no entra, abrí el puerto a mano (PowerShell como administrador):

   ```powershell
   netsh advfirewall firewall add rule name="Cerebro panel" dir=in action=allow protocol=TCP localport=8765 profile=private
   ```

Funciona solo dentro de tu red (el WiFi de casa). **No abras el puerto en el router ni lo publiques en internet**:
el panel está pensado para una red de confianza, no para estar expuesto.

## Qué hay en cada pestaña

| Pestaña | Qué tiene |
|---|---|
| **Inicio** | Estado de la PC y del agente (disco, memoria, procesador, internet, Telegram, Claude Code, agenda, mails, última señal), lo que está esperando (un plan de Claude, un WhatsApp preparado, una tarea en curso), accesos rápidos, y una **consola** para escribir una orden libre como se la escribirías por Telegram. |
| **Acciones** | El catálogo completo, con buscador y filtro por grupo. Cada acción es una tarjeta con su descripción, ejemplos de lo que le dirías por voz, un formulario con sus datos, **Ejecutar** y **Automatizar**. |
| **Automatizaciones** | Las rutinas y avisos (qué, cuándo suena y el próximo disparo; ejecutar ahora, borrar), el formulario para crear una nueva, los interruptores de las **alertas automáticas** (dólar, lluvia, PC, mails, agenda) y el **resumen de la mañana** (hora, días, equipo, activarlo, mandarlo ahora, verlo ahora). |
| **Notas** | Pendientes (tildar como hecho, agregar), lista de compras (agregar, sacar, vaciar, mandar al celular) e Inbox. Son los mismos archivos Markdown de `Cerebro\`. |
| **Tareas** | Claude Code: nueva tarea en modo consulta, cambios o pantalla; las que están en curso con su progreso y un botón para frenarlas; el plan pendiente para aprobar o descartar; y los informes guardados en `Cerebro\Tareas`, con vista del contenido. |
| **Casa** | Los dispositivos conocidos (WiZ, Kasa, Tapo) con prender, apagar, estado, brillo, color, escena y temperatura; buscar dispositivos; ponerles nombre. |
| **Memoria** | Lo que sabe de vos (recordar, olvidar), las lecciones aprendidas de tus correcciones, y los últimos mensajes. |
| **Registro** | Las últimas líneas del registro del día (`Cerebro\Registro\`) y del log del agente (`cerebro_pc.log`), actualizándose solas. |

El resultado de cada cosa que ejecutás aparece en una barra abajo (y los textos largos, en una ventana). La
consola de Inicio guarda las últimas respuestas. Las pestañas de estado se refrescan solas cada 5 segundos.

## Automatizar una acción, paso a paso

Por ejemplo, prender la luz del living de lunes a viernes a las 7:

1. **Acciones** → buscá "luces" → en la tarjeta **Luces y enchufes** completá *Dispositivo:* `luz del living`,
   *Qué hacer:* `prender`.
2. Tocá **Automatizar**. Te lleva a **Automatizaciones** con la acción y sus datos ya cargados.
3. Elegí **Cuándo**: *A una hora* (hora `07:00`, días `L a V`), *Cada tantos minutos* (con una franja horaria),
   o *Dentro de tantos minutos* (una sola vez).
4. **Programar**. Queda en la lista con el próximo disparo. Desde ahí la podés **Ejecutar ahora** para probarla
   o **Borrar**.

Cuando vence, la PC ejecuta la acción con esos datos exactos (sin pasar por la IA), lo anota en el registro y
te manda el resultado por Telegram. Lo mismo podés hacer con cualquier acción: la lista de compras al celular
todos los sábados, una captura de pantalla cada hora, bloquear la PC a las 23, un aviso de "tomá agua" cada dos
horas, el clima de mañana a las 21…

Las otras dos opciones de **Qué** son las de siempre: un *aviso al celular* (solo texto) o una *orden en texto
libre* que la PC interpreta a esa hora como si se la escribieras por Telegram.

## Configuración

Claves en `config_pc.json` (todas opcionales):

| Clave | Por defecto | Qué hace |
|---|---|---|
| `panel_activo` | `true` | `false` apaga el panel. |
| `panel_puerto` | `8765` | Si está ocupado, prueba los 9 siguientes y anota en `cerebro_pc.log` cuál quedó. `abrir-panel.bat` lee el puerto real de `estado.json`. |
| `panel_en_red` | `false` | `true` escucha en todas las interfaces, para usarlo desde otra PC o el celular en la misma red. |
| `panel_token` | `""` | Vacío: se genera uno la primera vez y queda en `estado.json`. Si ponés uno propio, usá letras y números (va en una URL). |

`panel.html` se lee del disco en cada pedido: lo podés retocar sin reiniciar el agente.

## Seguridad

- **Solo local por defecto.** Escucha en `127.0.0.1`: nada de fuera de esa PC puede llegar. Con `panel_en_red`
  queda disponible en tu red local, y nada más. Nunca lo expongas a internet (ni reenvío de puertos ni túneles).
- **Token obligatorio.** Sin él, la página pide el token y la API responde 401. El token viaja una sola vez en la
  URL y después en una cookie `HttpOnly` con `SameSite=Strict`. Si se filtró, borrá `panel_token` de
  `estado.json` y reiniciá el agente: se genera uno nuevo.
- **Nada de archivos arbitrarios.** El servidor solo responde `/` (la página) y `/api/…`; cualquier otra ruta es
  404. Los informes de tareas se leen únicamente desde `Cerebro\Tareas`, sin `../`.
- **Lo peligroso pide confirmación.** Apagar, reiniciar o suspender la PC, mandar el WhatsApp preparado, aprobar
  un plan de Claude Code o confirmar algo que quedó listo en pantalla piden un "¿Seguro?" en el panel y, además,
  la API exige `confirmar: true`.
- **Las escrituras llevan una cabecera propia** (`X-Cerebro-Panel: 1`), así una página de otro sitio no puede
  mandar órdenes usando tu cookie. El cuerpo de cada pedido tiene un máximo de 64 KB.
- Todo lo que el panel ejecuta pasa por las mismas funciones del agente y queda en `cerebro_pc.log` y en el
  registro del día, igual que si viniera del Echo o de Telegram.

## Si algo no anda

- **No abre nada / "no llego al agente":** el agente no está corriendo. Mirá `cerebro_pc.log`; `instalar.bat` lo
  arranca.
- **Puerto ocupado:** el log dice `panel web en http://127.0.0.1:8766/`; `abrir-panel.bat` y el link de Telegram
  ya usan ese puerto.
- **Desde el celular no entra:** falta `panel_en_red: true`, el firewall, o no están en la misma red.
- **"Ese token no es":** el de `estado.json` cambió (por ejemplo, si borraste el archivo). Pedile el link nuevo al
  bot con `panel`.
