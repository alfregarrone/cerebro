"""Panel web local de Cerebro PC: ver y ejecutar todo lo que sabe hacer el agente, y dejarlo automatizado.

Lo arranca cerebro_pc.py en un hilo (``panel.iniciar(modulo)``) y escucha en http://127.0.0.1:8765/ (o en el
siguiente puerto libre). Solo biblioteca estándar. La página (panel.html, al lado de este archivo) se lee del
disco en cada pedido, así se puede retocar sin reiniciar el agente.

Configuración en config_pc.json (claves planas, como el resto):
  "panel_activo": true      false apaga el panel.
  "panel_puerto": 8765      si está ocupado, prueba los 9 siguientes y anota en el log cuál quedó.
  "panel_en_red": false     true escucha en todas las interfaces: sirve desde otra PC o el celular en la misma red.
  "panel_token": ""         vacío = se genera uno la primera vez y se guarda en estado.json ("panel_token").

Seguridad: token obligatorio (en la URL una vez, después en una cookie HttpOnly o como Bearer), cabecera
X-Cerebro-Panel en todo lo que modifica algo (POST/DELETE), cuerpo máximo de 64 KB, nada de archivos
arbitrarios (solo "/" y "/api/..."), y las acciones peligrosas exigen "confirmar": true.
"""
import hmac
import json
import logging
import os
import platform
import re
import secrets
import socket
import threading
import time
import urllib.parse
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
PAGINA = BASE / "panel.html"
PUERTO_DEFECTO = 8765
INTENTOS_PUERTO = 10
MAX_CUERPO = 64 * 1024
TIMEOUT_ACCION = 120
COOKIE = "cerebro_panel"
CABECERA_CSRF = "X-Cerebro-Panel"
log = logging.getLogger("cerebro.panel")

A = None                                   # el módulo del agente (cerebro_pc), recibido en iniciar()
_PANEL = {"servidor": None, "puerto": None, "en_red": False}
_SALUD = {"ts": 0.0, "internet": None, "cpu": None}   # lo lento (internet, procesador) se mide aparte


# ---------- catálogo: una entrada por acción de ACCIONES ----------

def _c(nombre, etiqueta, tipo="texto", opciones=None, obligatorio=False, ayuda="", defecto=None):
    campo = {"nombre": nombre, "etiqueta": etiqueta, "tipo": tipo, "obligatorio": bool(obligatorio)}
    if opciones:
        campo["opciones"] = list(opciones)
    if ayuda:
        campo["ayuda"] = ayuda
    if defecto is not None:
        campo["valor_defecto"] = defecto
    return campo


def _e(grupo, etiqueta, descripcion, ejemplos=(), campos=(), peligrosa=False, resultado="corto", **extra):
    entrada = {"grupo": grupo, "etiqueta": etiqueta, "descripcion": descripcion, "ejemplos": list(ejemplos),
               "campos": list(campos), "peligrosa": bool(peligrosa), "resultado": resultado}
    entrada.update(extra)
    return entrada


_SI_NO_VER = [["", "ver cómo está"], ["true", "prender"], ["false", "apagar"]]
_DIAS_CUANDO = ["hoy", "mañana", "pasado mañana", "semana", "lunes", "martes", "miércoles", "jueves", "viernes",
                "sábado", "domingo"]

CATALOGO = {
    # --- Notas ---
    "nota": _e("Notas", "Anotar", "Guarda una nota o idea en Inbox.md, o un pendiente en Pendientes.md.",
               ["anotá que tengo que llamar a Marta", "anotá la idea de hacer un video sobre ahorro",
                "agregá a pendientes comprar pilas"],
               [_c("texto", "Texto", "texto_largo", obligatorio=True),
                _c("categoria", "Tipo", "opciones", ["nota", "idea", "pendiente"], defecto="nota")]),
    "buscar_notas": _e("Notas", "Buscar en las notas", "Busca palabras en todas tus notas (Inbox, pendientes, tareas).",
                       ["buscá en mis notas lo del presupuesto", "¿qué anoté sobre el viaje?"],
                       [_c("consulta", "Qué buscar", obligatorio=True)], resultado="largo"),
    "pendientes": _e("Notas", "Pendientes", "Lee los pendientes abiertos.", ["¿qué tengo pendiente?"],
                     resultado="largo"),
    "completar_pendiente": _e("Notas", "Tildar un pendiente",
                              "Marca como hecho el pendiente que más se parezca al texto.",
                              ["listo lo de las pilas", "ya llamé a Marta"],
                              [_c("texto", "Palabras del pendiente", obligatorio=True)]),
    "compras": _e("Notas", "Lista de compras", "Agrega, quita, vacía o lee la lista de compras (Compras.md).",
                  ["agregá leche y pan a las compras", "sacá el pan de la lista",
                   "¿qué hay en la lista de compras?"],
                  [_c("agregar", "Agregar", "lista", ayuda="Separá con comas"),
                   _c("quitar", "Quitar", "lista", ayuda="Separá con comas"),
                   _c("vaciar", "Vaciar la lista", "booleano"),
                   _c("al_celular", "Mandar la lista al celular", "booleano")], resultado="largo"),
    # --- PC ---
    "abrir_web": _e("PC", "Abrir una página", "Abre una dirección en el navegador, o busca en Google.",
                    ["abrí YouTube", "buscá recetas con arroz"],
                    [_c("url", "Dirección", ayuda="ej. mercadolibre.com.ar"), _c("busqueda", "O buscar en Google")]),
    "abrir_app": _e("PC", "Abrir un programa", "Abre un programa o app instalada (también las de la Microsoft Store).",
                    ["abrí Spotify", "abrí la calculadora", "abrí WhatsApp"],
                    [_c("nombre", "Programa", obligatorio=True)]),
    "cerrar_app": _e("PC", "Cerrar un programa", "Cierra las ventanas de un programa, como tocar la X.",
                     ["cerrá Chrome"], [_c("nombre", "Programa", obligatorio=True)]),
    "volumen": _e("PC", "Volumen", "Sube, baja, silencia o fija el volumen de la PC.",
                  ["subí el volumen", "poné el volumen al treinta", "silenciá la compu"],
                  [_c("cambio", "Cambio", "opciones", ["subir", "bajar", "silenciar"], defecto="subir"),
                   _c("pasos", "Pasos", "numero", defecto=5, ayuda="Cada paso es 2 %"),
                   _c("nivel", "O fijar en (0 a 100)", "numero", ayuda="Si lo completás, manda sobre el cambio")]),
    "sistema": _e("PC", "Bloquear, suspender, apagar, reiniciar",
                  "Bloquea la sesión, suspende, apaga o reinicia la PC (con un minuto de margen), "
                  "o cancela el apagado.",
                  ["bloqueá la pc", "suspendé", "apagá la compu", "reiniciá", "cancelá el apagado"],
                  [_c("orden", "Orden", "opciones",
                      ["bloquear", "suspender", "apagar", "reiniciar", "cancelar_apagado"],
                      obligatorio=True, defecto="bloquear")],
                  peligrosa=True, peligrosa_si={"orden": ["apagar", "reiniciar", "suspender"]}),
    "captura": _e("PC", "Captura de pantalla", "Saca una foto de la pantalla y la manda al celular por Telegram.",
                  ["sacá una captura", "pantalla"]),
    "enviar_archivo": _e("PC", "Mandar un archivo al celular",
                         "Busca un archivo por nombre (Escritorio, Documentos, Descargas, notas) y lo manda "
                         "por Telegram.",
                         ["mandame el archivo presupuesto", "pasame el pdf de la factura"],
                         [_c("nombre", "Nombre del archivo", obligatorio=True)]),
    "info_pc": _e("PC", "Hora, disco y equipo", "Hora exacta de la PC, espacio libre en disco y nombre del equipo.",
                  ["estado", "¿cuánto espacio queda en el disco?"]),
    "salud_pc": _e("PC", "Salud de la PC", "Disco, memoria, procesador, internet y hace cuánto está prendida.",
                   ["¿cómo está la compu?", "la pc anda lenta"],
                   [_c("lenta", "Anda lenta: decime qué la carga", "booleano")], resultado="largo"),
    "estado": _e("PC", "¿Está conectada?", "Responde si el agente está vivo y qué versión corre.", ["estado"]),
    "diagnostico": _e("PC", "Diagnóstico", "Estado de Telegram y últimas líneas del registro y del log, al celular.",
                      ["diagnóstico", "¿qué pasó?"], resultado="largo"),
    # --- Música ---
    "musica": _e("Música", "Poner música", "Reproduce en YouTube (y sigue con temas parecidos) o en Spotify.",
                 ["poné música de Soda Stereo", "poné Ciro en Spotify"],
                 [_c("busqueda", "Qué escuchar", obligatorio=True),
                  _c("servicio", "Dónde", "opciones", ["youtube", "spotify"], defecto="youtube")]),
    "musica_control": _e("Música", "Controlar lo que suena", "Pausa, sigue, pasa de tema o dice qué está sonando.",
                         ["pausá", "seguí", "siguiente", "¿qué está sonando?"],
                         [_c("accion", "Qué hacer", "opciones",
                             ["que_suena", "pausa", "seguir", "siguiente", "anterior"], defecto="que_suena")]),
    # --- WhatsApp ---
    "whatsapp": _e("WhatsApp", "Preparar un mensaje",
                   "Deja listo un WhatsApp (app de escritorio). Se manda recién cuando confirmás.",
                   ["mandale un WhatsApp a Juan que llego tarde"],
                   [_c("contacto", "Contacto", obligatorio=True),
                    _c("mensaje", "Mensaje", "texto_largo", obligatorio=True)],
                   confirma_con="whatsapp_confirmar"),
    "whatsapp_editar": _e("WhatsApp", "Corregir el último mensaje",
                          "Deja lista la corrección de tu último mensaje en ese chat. Se aplica cuando confirmás.",
                          ["corregí el mensaje a Juan: voy en diez"],
                          [_c("contacto", "Contacto", obligatorio=True),
                           _c("mensaje", "Texto nuevo", "texto_largo", obligatorio=True)],
                          confirma_con="whatsapp_confirmar"),
    "whatsapp_archivo": _e("WhatsApp", "Preparar el envío de un archivo",
                           "Busca un archivo o foto de la PC y lo deja listo para mandarlo por WhatsApp "
                           "(con confirmación).",
                           ["mandale a Laura el pdf del presupuesto"],
                           [_c("contacto", "Contacto", obligatorio=True), _c("archivo", "Archivo", obligatorio=True),
                            _c("mensaje", "Comentario (opcional)")], confirma_con="whatsapp_confirmar"),
    "whatsapp_confirmar": _e("WhatsApp", "Confirmar el envío",
                             "Manda el WhatsApp que quedó preparado (dura 10 minutos).", ["sí", "mandalo"],
                             peligrosa=True),
    "whatsapp_cancelar": _e("WhatsApp", "Descartar el mensaje preparado",
                            "Cancela el mensaje de WhatsApp que quedó esperando el \"sí\".", ["no", "cancelá"]),
    "whatsapp_leer": _e("WhatsApp", "Leer un chat", "Abre el chat y te manda al celular lo que dice (lo lee la IA).",
                        ["¿qué me escribió Laura?"], [_c("contacto", "Contacto", obligatorio=True)]),
    "whatsapp_resumen": _e("WhatsApp", "Mensajes sin leer", "Resume los chats sin leer y te lo manda al celular.",
                           ["¿qué mensajes tengo?"]),
    # --- Casa ---
    "casa": _e("Casa", "Luces y enchufes",
               "Prende, apaga o regula una luz o enchufe (WiZ, Kasa, Tapo) por la red local.",
               ["prendé la luz del living", "apagá todo", "poné la luz en azul", "la luz al treinta", "modo cine"],
               [_c("dispositivo", "Dispositivo", obligatorio=True, defecto="luz",
                   ayuda="'luz' o 'luces' si hay una sola o todas"),
                _c("accion", "Qué hacer", "opciones",
                   ["prender", "apagar", "estado", "brillo", "color", "temperatura", "escena"], defecto="prender"),
                _c("valor", "Valor", ayuda="brillo 1 a 100 · color: rojo, azul… · temperatura: cálida, neutra, fría "
                                           "· escena: fiesta, relax, película…")]),
    "casa_descubrir": _e("Casa", "Buscar dispositivos", "Busca luces y enchufes en la red y manda la lista al celular.",
                         ["buscá aparatos"]),
    "buscar_aparatos": _e("Casa", "Buscar aparatos nuevos",
                          "Busca aparatos nuevos en la casa y avisa solo si apareció alguno.",
                          ["¿hay aparatos nuevos?"]),
    "nombrar_aparato": _e("Casa", "Ponerle nombre a un aparato",
                          "Le pone un apodo a una luz o enchufe para pedirlo por ese nombre.",
                          ["a la luz nueva llamala luz del living"],
                          [_c("aparato", "Aparato (como está ahora)", obligatorio=True, defecto="luz"),
                           _c("nombre", "Nombre nuevo", obligatorio=True)]),
    # --- Claude Code ---
    "tarea": _e("Claude Code", "Nueva tarea",
                "Le pasa trabajo a Claude Code en la PC. Consulta: solo lectura. Cambios: arma un plan que aprobás. "
                "Pantalla: maneja mouse y teclado y manda una foto al terminar.",
                ["pedile a Claude que ordene mi carpeta de descargas", "investigá estrategias de marketing para apps",
                 "fijate en Instagram si tengo mensajes"],
                [_c("instruccion", "Qué hacer", "texto_largo", obligatorio=True),
                 _c("modo", "Modo", "opciones", ["consulta", "cambios", "pantalla"], defecto="consulta")]),
    "confirmar_tarea": _e("Claude Code", "Aprobar el plan", "Ejecuta el plan que quedó esperando tu aprobación.",
                          ["confirmá la tarea", "aprobá el plan"], peligrosa=True),
    "pantalla_confirmar": _e("Claude Code", "Confirmar lo que quedó en pantalla",
                             "Envía o publica lo que la tarea de pantalla dejó listo sin mandar.",
                             ["confirmá la publicación", "sí, publicalo"], peligrosa=True),
    "tareas_estado": _e("Claude Code", "¿Qué está haciendo?", "Qué tareas están en curso y en qué paso van.",
                        ["¿cómo va la tarea?"]),
    "cancelar_tarea": _e("Claude Code", "Frenar las tareas", "Frena todas las tareas de Claude en curso.",
                         ["cancelá la tarea"]),
    # --- Memoria ---
    "recordar": _e("Memoria", "Recordar un dato",
                   "Guarda para siempre algo tuyo (nombres, gustos, cómo llamás a tus cosas).",
                   ["acordate que mi hermana se llama Laura"], [_c("dato", "Dato", obligatorio=True)]),
    "olvidar": _e("Memoria", "Olvidar", "Borra los datos guardados que contengan ese texto.",
                  ["olvidate de lo del cilantro"], [_c("dato", "Texto a olvidar", obligatorio=True)]),
    "que_sabes": _e("Memoria", "¿Qué sabés de mí?", "Lee lo que tiene guardado sobre vos.",
                    ["¿qué sabés de mí?"], resultado="largo"),
    "aprender": _e("Memoria", "Enseñarle una lección",
                   "Cuando entendió mal: guarda qué querías decir con una frase y lo hace ahora.",
                   ["no, eso no, lo que quería era poner la luz roja", "cuando diga modo cine, poné la luz al 10"],
                   [_c("frase", "Tu frase", obligatorio=True),
                    _c("pasos", "Qué tiene que hacer", "lista", obligatorio=True,
                       ayuda="Órdenes cortas separadas por comas"),
                    _c("ejecutar", "Hacerlo ahora", "booleano", defecto=True)]),
    "aprendidos": _e("Memoria", "Lecciones aprendidas", "Lista las lecciones (en JSON, como se las pasa a Alexa).",
                     ["¿qué aprendiste?"], resultado="largo"),
    "frase": _e("Memoria", "Frase suelta",
                "Una frase libre: la PC ve si es algo que le enseñaste y, si no, la interpreta.",
                ["modo fiesta", "luz cálida"], [_c("texto", "Frase", obligatorio=True)]),
    # --- Avisos y rutinas ---
    "programar": _e("Avisos y rutinas", "Programar un aviso o una rutina",
                    "Aviso al celular por Telegram, o una orden que la PC hace sola a esa hora.",
                    ["recordame tomar agua cada dos horas", "de lunes a viernes a las siete prendé la luz",
                     "mañana a las ocho avisame que pague el gas"],
                    [_c("texto", "Texto del aviso o la orden", obligatorio=True),
                     _c("tipo", "Tipo", "opciones", [["aviso", "aviso al celular"], ["orden", "orden para la PC"]],
                        defecto="aviso"),
                     _c("hora", "A las", "hora"), _c("dias", "Días", "dias"),
                     _c("cada_minutos", "O cada (minutos)", "numero"),
                     _c("en_minutos", "O dentro de (minutos)", "numero"),
                     _c("desde", "Desde", "hora", ayuda="Para los 'cada X minutos'"), _c("hasta", "Hasta", "hora"),
                     _c("frecuencia", "Repetir", "opciones", [["", "siempre"], ["una_vez", "una sola vez"]])]),
    "programados": _e("Avisos y rutinas", "Ver lo programado", "Lista los avisos y rutinas y cuándo suenan.",
                      ["¿qué tengo programado?"], resultado="largo"),
    "borrar_programado": _e("Avisos y rutinas", "Borrar un aviso o rutina",
                            "Borra lo programado que contenga ese texto.",
                            ["borrá lo del agua", "borrá todos los avisos"],
                            [_c("texto", "Texto (o 'todos')", obligatorio=True)]),
    "alertas": _e("Avisos y rutinas", "Alertas automáticas",
                  "Prende o apaga los avisos solos: dólar, lluvia, salud de la PC, mails importantes, agenda.",
                  ["desactivá las alertas del dólar", "¿qué alertas tengo?"],
                  [_c("tipo", "Cuál", "opciones", ["todas", "dolar", "lluvia", "pc", "mails", "agenda"],
                      defecto="todas"),
                   _c("activar", "Qué hacer", "opciones", _SI_NO_VER)], resultado="largo"),
    "resumen_manana": _e("Avisos y rutinas", "Resumen de la mañana",
                         "Configura el resumen que llega cada mañana al celular; sin cambios, lo arma y lo muestra.",
                         ["resumen", "mandame el resumen a las siete y media", "desactivá el resumen",
                          "soy de River, avisame si juega"],
                         [_c("hora", "Hora", "hora"), _c("activar", "Activo", "opciones", _SI_NO_VER),
                          _c("dias", "Días", "opciones",
                             [["", "sin cambios"], ["todos", "todos los días"], ["semana", "de lunes a viernes"]]),
                          _c("equipo", "Tu equipo", ayuda="Avisa si juega hoy")], resultado="largo"),
    "avisar": _e("Avisos y rutinas", "Mandar un texto al celular", "Manda un texto a tu Telegram.",
                 ["pasame eso al celular"], [_c("texto", "Texto", "texto_largo", obligatorio=True)]),
    # --- Agenda y mails ---
    "agenda": _e("Agenda y mails", "Agenda", "Qué hay en tu Google Calendar (hoy, mañana, un día o la semana).",
                 ["¿qué tengo hoy?", "¿qué tengo el viernes?", "agenda de la semana"],
                 [_c("cuando", "Cuándo", "opciones", _DIAS_CUANDO, defecto="hoy"),
                  _c("fecha", "O una fecha (AAAA-MM-DD)")], resultado="largo"),
    "mails": _e("Agenda y mails", "Mails sin leer", "Resume los mails sin leer de Gmail (primero los importantes).",
                ["¿tengo mails?", "resumime los mails"],
                [_c("voz", "Versión corta (el resumen completo va al celular)", "booleano")], resultado="largo"),
    # --- Datos en vivo ---
    "clima": _e("Datos en vivo", "Clima", "Pronóstico de hoy o de los próximos días (Open-Meteo).",
                ["¿qué tiempo hace?", "¿llueve mañana?", "clima el sábado en Mar del Plata"],
                [_c("ciudad", "Ciudad", ayuda="Vacío = la tuya"),
                 _c("dia", "Día", "opciones",
                    [["0", "hoy"], ["1", "mañana"], ["2", "pasado"], ["3", "en 3 días"], ["4", "en 4 días"],
                     ["5", "en 5 días"], ["6", "en 6 días"]], defecto="0")]),
    "dolar": _e("Datos en vivo", "Dólar", "Oficial, blue, MEP y tarjeta (DolarApi).",
                ["¿a cuánto está el dólar?"]),
    "noticias": _e("Datos en vivo", "Noticias", "Titulares del día o sobre un tema (Google News).",
                   ["¿qué pasó hoy?", "noticias de tecnología"],
                   [_c("tema", "Tema", ayuda="Vacío = titulares"),
                    _c("con_links", "Una por línea", "booleano", defecto=True)],
                   resultado="largo"),
    "argentina": _e("Datos en vivo", "Feriado, riesgo país, inflación", "Datos de Argentina (ArgentinaDatos).",
                    ["¿cuándo es el próximo feriado?", "¿cómo va el riesgo país?",
                     "¿cuánto fue la inflación?"],
                    [_c("dato", "Dato", "opciones", ["feriado", "riesgo_pais", "inflacion"], defecto="feriado")]),
    "futbol": _e("Datos en vivo", "Fútbol", "Último y próximo partido de un equipo (TheSportsDB).",
                 ["¿cómo salió Boca?", "¿cuándo juega River?"], [_c("equipo", "Equipo", defecto="Boca")]),
    "cotizacion": _e("Datos en vivo", "Otras monedas", "Euro, real, pesos chileno y uruguayo, bitcoin, ethereum.",
                     ["¿a cuánto está el euro?", "¿cuánto vale el bitcoin?"],
                     [_c("moneda", "Moneda", "opciones",
                         ["euro", "real", "peso chileno", "peso uruguayo", "bitcoin", "ethereum"], defecto="euro")]),
    "convertir": _e("Datos en vivo", "Convertir", "Convierte entre pesos, dólares (oficial y blue), euros y reales.",
                    ["¿cuántos pesos son cien dólares?", "¿cuántos euros son cincuenta mil pesos?"],
                    [_c("monto", "Monto", "numero", obligatorio=True, defecto=100),
                     _c("de", "De", "opciones", ["dolar", "euro", "real", "peso"], defecto="dolar"),
                     _c("a", "A", "opciones", ["dolar", "euro", "real", "peso"], defecto="peso")]),
}

GRUPOS = ["Notas", "PC", "Música", "WhatsApp", "Casa", "Claude Code", "Memoria", "Avisos y rutinas", "Agenda y mails",
          "Datos en vivo"]


def es_peligrosa(accion, datos):
    """¿Esta acción, con estos datos, pide confirmación? (apagar sí; bloquear no)."""
    entrada = CATALOGO.get(accion) or {}
    if not entrada.get("peligrosa"):
        return False
    condicion = entrada.get("peligrosa_si")
    if condicion:
        campo, valores = next(iter(condicion.items()))
        return A.norm((datos or {}).get(campo)) in valores
    return True


# ---------- token, direcciones y arranque ----------

def token():
    """El token del panel: el de config_pc.json o uno generado una vez y guardado en estado.json."""
    propio = str(A.CONFIG.get("panel_token") or "").strip()
    if propio:
        return propio
    guardado = str(A.cargar_estado().get("panel_token") or "").strip()
    if guardado:
        return guardado
    nuevo = secrets.token_urlsafe(24)

    def poner(e):                     # si otro hilo lo generó en el medio, queda el suyo
        e.setdefault("panel_token", nuevo)
        return e["panel_token"]

    return A.estado_cambiar(poner)


def _ip_local():
    """La IP de esta PC en la red de casa (para el link que se usa desde otra PC o el celular)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))        # no manda nada: solo elige la interfaz de salida
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def url(con_token=True):
    """Dirección del panel (vacía si no está corriendo)."""
    if not _PANEL["servidor"]:
        return ""
    host = _ip_local() if _PANEL["en_red"] else "127.0.0.1"
    base = "http://" + host + ":" + str(_PANEL["puerto"]) + "/"
    return base + "?token=" + urllib.parse.quote(token(), safe="") if con_token else base


def url_para_telegram():
    """Texto para responder "panel" por Telegram: el link con el token y una aclaración."""
    if not _PANEL["servidor"]:
        return "El panel no está corriendo. Revisá panel_activo en config_pc.json y el log del agente."
    partes = ["Panel de Cerebro: " + url()]
    if _PANEL["en_red"]:
        partes.append("Sirve desde cualquier PC o celular conectado a tu misma red.")
    else:
        partes.append("Solo abre en esa PC. Para usarlo desde otra o desde el celular, poné \"panel_en_red\": true "
                      "en config_pc.json y reiniciá el agente.")
    partes.append("No compartas el link: lleva tu token.")
    return chr(10).join(partes)


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"     # en Windows, reusar la dirección dejaría dos panels en un puerto

    def handle_error(self, request, client_address):
        log.exception("panel: error atendiendo a %s", client_address)


def iniciar(agente, puerto=None, en_red=None):
    """Arranca el panel en un hilo daemon. Devuelve (servidor, puerto real), o None si está apagado o no pudo.

    ``puerto`` y ``en_red`` sirven para las pruebas (puerto 0 = uno libre); si no se pasan, salen de config_pc.json.
    """
    global A
    A = agente
    try:
        cfg = agente.CONFIG
        if puerto is None and cfg.get("panel_activo") is False:
            log.info("panel: desactivado en config_pc.json")
            return None
        if puerto is None:
            puerto = int(cfg.get("panel_puerto") or PUERTO_DEFECTO)
        if en_red is None:
            en_red = bool(cfg.get("panel_en_red"))
        host = "0.0.0.0" if en_red else "127.0.0.1"
        servidor = None
        for intento in range(INTENTOS_PUERTO if puerto else 1):
            try:
                servidor = _Servidor((host, puerto + intento), Manejador)
                break
            except OSError as e:
                log.warning("panel: no pude escuchar en el puerto %s (%s)", puerto + intento, e)
        if servidor is None:
            log.error("panel: no encontré un puerto libre entre %s y %s; el panel queda apagado",
                      puerto, puerto + INTENTOS_PUERTO - 1)
            return None
        real = servidor.server_address[1]
        _PANEL.update(servidor=servidor, puerto=real, en_red=bool(en_red))
        tok = token()
        try:                                    # abrir-panel.bat lee el puerto real de estado.json
            A.estado_cambiar(lambda e: e.__setitem__("panel_puerto", real))
        except Exception:
            log.exception("panel: no pude anotar el puerto en estado.json")
        threading.Thread(target=_servir, args=(servidor,), daemon=True, name="panel").start()
        threading.Thread(target=_hilo_salud, args=(servidor,), daemon=True, name="panel-salud").start()
        log.info("panel web en http://%s:%s/ (%s; token termina en ...%s)", host, real,
                 "en la red" if en_red else "solo esta PC", tok[-4:])
        return servidor, real
    except Exception:
        log.exception("panel: no pudo arrancar")
        return None


def detener():
    """Apaga el panel (lo usan las pruebas)."""
    servidor = _PANEL.get("servidor")
    _PANEL.update(servidor=None, puerto=None)
    if servidor:
        servidor.shutdown()
        servidor.server_close()


def _servir(servidor):
    try:
        servidor.serve_forever(poll_interval=0.5)
    except Exception:
        log.exception("panel: el servidor se cayó")
    finally:
        if _PANEL.get("servidor") is servidor:
            _PANEL.update(servidor=None, puerto=None)


def _refrescar_salud():
    try:
        internet = bool(A._hay_internet(timeout=3))
    except Exception:
        internet = None
    try:
        cpu = A._cpu_pc(0.5)
    except Exception:
        cpu = None
    _SALUD.update(ts=time.time(), internet=internet, cpu=cpu)


def _hilo_salud(servidor):
    """Cada minuto mide lo que tarda (internet, procesador) para que /api/estado responda al instante."""
    while _PANEL.get("servidor") is servidor:
        try:
            _refrescar_salud()
        except Exception:
            log.exception("panel: salud")
        for _ in range(60):
            if _PANEL.get("servidor") is not servidor:
                return
            time.sleep(1)


# ---------- la API ----------

RUTAS = []


def ruta(metodo, patron):
    def registrar(fn):
        RUTAS.append((metodo, re.compile(patron), fn))
        return fn
    return registrar


def _con_timeout(fn, *args):
    """Corre fn en un hilo y espera hasta TIMEOUT_ACCION. Devuelve (terminó, resultado)."""
    caja = {}

    def trabajo():
        try:
            caja["r"] = fn(*args)
        except Exception as e:
            log.exception("panel: %s", getattr(fn, "__name__", "acción"))
            caja["error"] = str(e)[:200]

    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start()
    hilo.join(TIMEOUT_ACCION)
    if hilo.is_alive():
        return False, None
    if "error" in caja:
        raise RuntimeError(caja["error"])
    return True, caja.get("r")


def _seguro(fn, defecto=None):
    try:
        return fn()
    except Exception:
        return defecto


def _items_compras():
    try:
        return [x[2:].strip() for x in (A.VAULT / "Compras.md").read_text(encoding="utf-8").splitlines()
                if x.startswith("- ")]
    except OSError:
        return []


def _pendientes():
    _, lineas = A.leer_pendientes()
    salida = []
    for x in lineas:
        s = x.strip()
        if s.startswith("- [ ]") or s.lower().startswith("- [x]"):
            salida.append({"texto": A.limpiar_para_voz(x), "hecho": not s.startswith("- [ ]"), "crudo": x})
    return salida


def _inbox(maximo=200):
    try:
        lineas = (A.VAULT / "Inbox.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    notas = [x[2:].strip() for x in lineas if x.startswith("- ")]
    return list(reversed(notas[-maximo:]))


def _vigente(pendiente, segundos):
    return bool(pendiente) and time.time() - float(pendiente.get("ts", 0)) <= segundos


def _tareas_activas():
    with A.TAREAS_LOCK:
        activas = list(A.TAREAS_ACTIVAS.items())
    return [{"id": k, "descripcion": v.get("descripcion", ""), "ultimo": v.get("ultimo", ""),
             "segundos": int(time.time() - v.get("inicio", time.time())), "cancelada": bool(v.get("cancelada"))}
            for k, v in activas]


@ruta("GET", r"estado")
def api_estado(cuerpo, consulta):
    estado = A.cargar_estado()
    disco = _seguro(A._disco)
    memoria = _seguro(A._memoria_pc)
    encendida = _seguro(A._encendida_seg)
    latido = _seguro(lambda: float(A.LATIDO.read_text(encoding="utf-8").strip()))
    plan = estado.get("plan_pendiente") or {}
    wa = estado.get("whatsapp_pendiente") or {}
    sistema = estado.get("sistema_pendiente") or {}
    return {
        "ok": True, "version": A.VERSION, "hora": A.ahora(), "equipo": _seguro(platform.node, ""),
        "carpeta_notas": str(A.VAULT), "carpeta_agente": str(A.BASE),
        "disco": {"libre_gb": round(disco[0], 1), "total_gb": round(disco[1], 1)} if disco else None,
        "memoria_pct": memoria[0] if memoria else None,
        "cpu_pct": _SALUD["cpu"], "internet": _SALUD["internet"],
        "encendida": A._duracion(encendida) if encendida else None,
        "latido": datetime.fromtimestamp(latido).strftime("%H:%M:%S") if latido else None,
        "telegram": {"token": bool(str(A.CONFIG.get("telegram_token") or "").strip()),
                     "chat": bool(A.CONFIG.get("telegram_chat_id") or estado.get("telegram_chat_id"))},
        "claude": bool(_seguro(A._buscar_claude, "")), "gemini": bool(_seguro(A._clave_gemini, "")),
        "agenda": bool(_seguro(lambda: A._mod("agenda").links(A.CONFIG), [])),
        "mails": bool(_seguro(lambda: A._mod("correo").configurado(A.CONFIG), False)),
        "pendientes": sum(1 for p in _seguro(_pendientes, []) if not p["hecho"]),
        "compras": len(_items_compras()), "programados": len(_seguro(A._programados, [])),
        "tareas": _tareas_activas(),
        "plan_pendiente": {"instruccion": plan.get("instruccion", "")} if _vigente(plan, A.PLAN_TTL) else None,
        "whatsapp_pendiente": ({k: wa.get(k, "") for k in ("tipo", "contacto", "mensaje", "archivo")}
                               if _vigente(wa, 600) else None),
        "sistema_pendiente": sistema.get("orden") if _vigente(sistema, 300) else None,
        "alertas": {k: v for k, v in A._alertas().items() if k in A.NOMBRES_ALERTA},
        "resumen": _seguro(A._config_resumen, {}),
        "panel": {"puerto": _PANEL["puerto"], "en_red": _PANEL["en_red"], "url": url(con_token=False),
                  "url_red": "http://" + _ip_local() + ":" + str(_PANEL["puerto"]) + "/" if _PANEL["en_red"] else ""},
    }


@ruta("GET", r"acciones")
def api_acciones(cuerpo, consulta):
    acciones = [{"nombre": nombre, **entrada} for nombre, entrada in CATALOGO.items() if nombre in A.ACCIONES]
    return {"ok": True, "acciones": acciones, "grupos": GRUPOS}


@ruta("POST", r"ejecutar")
def api_ejecutar(cuerpo, consulta):
    accion = str(cuerpo.get("accion") or "").strip()
    datos = cuerpo.get("datos") if isinstance(cuerpo.get("datos"), dict) else {}
    if accion not in A.ACCIONES:
        return 400, {"ok": False, "error": "No conozco la acción " + (accion or "(vacía)") + "."}
    if es_peligrosa(accion, datos) and cuerpo.get("confirmar") is not True:
        return 400, {"ok": False, "confirmar": True,
                     "error": "Esta acción pide confirmación: volvé a mandarla con \"confirmar\": true."}
    A.log.info("panel: ejecutando %s %s", accion, json.dumps(datos, ensure_ascii=False)[:200])
    termino, resultado = _con_timeout(A.ACCIONES[accion], datos)
    if not termino:
        return {"ok": False, "en_curso": True, "accion": accion,
                "texto": "La acción sigue en curso (más de dos minutos). Mirá el registro o el celular."}
    ok, texto = resultado
    if ok and accion != "casa":                 # casa se anota sola (igual que en procesar())
        A.anotar_accion(accion, datos)
    return {"ok": bool(ok), "accion": accion, "texto": str(texto or ""),
            "confirma_con": (CATALOGO.get(accion) or {}).get("confirma_con") if ok else None}


@ruta("POST", r"orden")
def api_orden(cuerpo, consulta):
    texto = str(cuerpo.get("texto") or "").strip()
    if not texto:
        return 400, {"ok": False, "error": "Escribí qué querés que haga."}
    A.registrar("panel", texto[:200])
    A.anotar_charla("user", texto)
    termino, respuesta = _con_timeout(A._orden_telegram, texto)
    if not termino:
        return {"ok": False, "en_curso": True, "texto": "Sigue en curso. Si era un trabajo largo, te aviso al celular."}
    respuesta = str(respuesta or "Listo.")
    A.anotar_charla("cerebro", respuesta)
    return {"ok": True, "texto": respuesta}


# --- programados ---

def _lista_programados():
    ahora_ts = time.time()
    salida = []
    for p in A._programados():
        q = dict(p)
        q["cuando"] = _seguro(lambda p=p: A._cuando(p), "")
        q["proximo_texto"] = datetime.fromtimestamp(p["proximo"]).strftime("%d/%m %H:%M") if p.get("proximo") else ""
        q["faltan_seg"] = int(p["proximo"] - ahora_ts) if p.get("proximo") else None
        salida.append(q)
    salida.sort(key=lambda x: x.get("proximo") or 0)
    return salida


def _programado(pid):
    return next((p for p in A._programados() if p.get("id") == pid), None)


@ruta("GET", r"programados")
def api_programados(cuerpo, consulta):
    return {"ok": True, "programados": _lista_programados()}


@ruta("POST", r"programados")
def api_programar(cuerpo, consulta):
    if not (cuerpo.get("texto") or cuerpo.get("accion")):
        return 400, {"ok": False, "error": "Falta el texto del aviso, o la acción a programar."}
    ok, texto = A.accion_programar(cuerpo)
    return {"ok": bool(ok), "texto": texto, "programados": _lista_programados()}


@ruta("DELETE", r"programados/([0-9a-f]+)")
def api_borrar_programado(cuerpo, consulta, pid):
    with A.PROG_LOCK:
        lista = A._programados()
        quedan = [p for p in lista if p.get("id") != pid]
        if len(quedan) == len(lista):
            return 404, {"ok": False, "error": "No encontré ese aviso o rutina."}
        A._guardar_programados(quedan)
    A.registrar("programar", "borrado desde el panel: " + pid)
    return {"ok": True, "texto": "Borrado.", "programados": _lista_programados()}


@ruta("POST", r"programados/([0-9a-f]+)/ejecutar")
def api_ejecutar_programado(cuerpo, consulta, pid):
    p = _programado(pid)
    if not p:
        return 404, {"ok": False, "error": "No encontré ese aviso o rutina."}
    termino, r = _con_timeout(A.ejecutar_programado, p)
    if not termino:
        return {"ok": False, "en_curso": True, "texto": "Sigue en curso (más de dos minutos)."}
    return {"ok": True, "texto": str(r or "Listo.")}


# --- alertas y resumen ---

def _alertas():
    alertas = {k: v for k, v in A._alertas().items() if k in A.NOMBRES_ALERTA}
    faltan = {"mails": not _seguro(lambda: A._mod("correo").configurado(A.CONFIG), False),
              "agenda": not _seguro(lambda: A._mod("agenda").links(A.CONFIG), [])}
    return {"ok": True, "alertas": alertas, "nombres": A.NOMBRES_ALERTA, "faltan": faltan}


@ruta("GET", r"alertas")
def api_alertas(cuerpo, consulta):
    return _alertas()


@ruta("POST", r"alertas")
def api_alertas_cambiar(cuerpo, consulta):
    tipo = str(cuerpo.get("tipo") or "todas")
    if "activar" not in cuerpo:
        return 400, {"ok": False, "error": "Falta 'activar' (true o false)."}
    ok, texto = A.accion_alertas({"tipo": tipo, "activar": bool(cuerpo.get("activar"))})
    return {**_alertas(), "ok": bool(ok), "texto": texto}


@ruta("GET", r"resumen")
def api_resumen(cuerpo, consulta):
    return {"ok": True, "resumen": A._config_resumen()}


@ruta("POST", r"resumen")
def api_resumen_cambiar(cuerpo, consulta):
    cambios = {k: cuerpo[k] for k in ("hora", "activar", "dias", "equipo")
               if k in cuerpo and cuerpo[k] not in (None, "")}
    if not cambios:
        return 400, {"ok": False, "error": "No hay nada para cambiar (hora, activar, dias o equipo)."}
    ok, texto = A.accion_resumen_manana(cambios)
    return {"ok": bool(ok), "texto": texto, "resumen": A._config_resumen()}


@ruta("POST", r"resumen/vista")
def api_resumen_vista(cuerpo, consulta):
    termino, texto = _con_timeout(A.armar_resumen)
    if not termino:
        return {"ok": False, "en_curso": True, "texto": "El resumen está tardando demasiado."}
    return {"ok": True, "texto": str(texto)}


@ruta("POST", r"resumen/mandar")
def api_resumen_mandar(cuerpo, consulta):
    termino, texto = _con_timeout(A.armar_resumen)
    if not termino:
        return {"ok": False, "en_curso": True, "texto": "El resumen está tardando demasiado."}
    mandado = A.avisar_celular(str(texto), "Cerebro: resumen del día")
    return {"ok": bool(mandado), "texto": "Te lo mandé al celular." if mandado else
            "No pude mandarlo por Telegram (mirá el log). Este es el resumen:" + chr(10) + str(texto)}


# --- notas ---

@ruta("GET", r"notas")
def api_notas(cuerpo, consulta):
    return {"ok": True, "inbox": _inbox(), "pendientes": _pendientes(), "compras": _items_compras(),
            "carpeta": str(A.VAULT)}


@ruta("POST", r"notas")
def api_nota(cuerpo, consulta):
    ok, texto = A.accion_nota({"texto": cuerpo.get("texto"), "categoria": cuerpo.get("categoria") or "nota"})
    return {"ok": bool(ok), "texto": texto, "inbox": _inbox()}


@ruta("POST", r"pendientes")
def api_pendientes(cuerpo, consulta):
    if cuerpo.get("agregar"):
        ok, texto = A.accion_nota({"texto": cuerpo["agregar"], "categoria": "pendiente"})
    elif cuerpo.get("completar"):
        ok, texto = A.accion_completar_pendiente({"texto": cuerpo["completar"]})
    else:
        return 400, {"ok": False, "error": "Mandá 'agregar' o 'completar' con el texto."}
    return {"ok": bool(ok), "texto": texto, "pendientes": _pendientes()}


@ruta("POST", r"compras")
def api_compras(cuerpo, consulta):
    datos = {k: cuerpo[k] for k in ("agregar", "quitar", "vaciar", "al_celular") if k in cuerpo}
    ok, texto = A.accion_compras(datos)
    return {"ok": bool(ok), "texto": texto, "compras": _items_compras()}


# --- tareas (Claude Code) ---

_TITULOS = {}      # nombre -> (mtime, bytes, título): el panel pide la lista cada 5 s y no hace falta releer todo


def _titulo_informe(entrada, mtime, tam):
    guardado = _TITULOS.get(entrada.name)
    if guardado and guardado[0] == mtime and guardado[1] == tam:
        return guardado[2]
    try:
        with open(entrada.path, encoding="utf-8", errors="replace") as f:
            titulo = f.readline().lstrip("# ").strip()
    except OSError:
        titulo = ""
    _TITULOS[entrada.name] = (mtime, tam, titulo)
    return titulo


def _informes(maximo=60):
    carpeta = A.VAULT / "Tareas"
    try:
        entradas = [(e, e.stat()) for e in os.scandir(carpeta) if e.name.endswith(".md") and e.is_file()]
    except OSError:
        return []
    entradas.sort(key=lambda par: par[1].st_mtime, reverse=True)
    salida = []
    for e, st in entradas[:maximo]:
        titulo = _titulo_informe(e, st.st_mtime, st.st_size)
        salida.append({"nombre": e.name, "titulo": titulo or Path(e.name).stem, "bytes": st.st_size,
                       "fecha": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    vigentes = {e.name for e, _ in entradas}
    for nombre in [n for n in _TITULOS if n not in vigentes]:
        _TITULOS.pop(nombre, None)
    return salida


def _archivo_tarea(nombre):
    """Solo archivos .md directamente dentro de VAULT/Tareas: nada de ../ ni rutas."""
    nombre = str(nombre or "")
    if not nombre or re.search(r"[\\/\0]", nombre) or nombre.startswith(".") or not nombre.endswith(".md"):
        return None
    carpeta = (A.VAULT / "Tareas").resolve()
    ruta_archivo = (carpeta / nombre).resolve()
    if ruta_archivo.parent != carpeta or not ruta_archivo.is_file():
        return None
    return ruta_archivo


@ruta("GET", r"tareas")
def api_tareas(cuerpo, consulta):
    estado = A.cargar_estado()
    plan = estado.get("plan_pendiente") or {}
    return {"ok": True, "activas": _tareas_activas(), "claude": bool(_seguro(A._buscar_claude, "")),
            "plan": {"instruccion": plan.get("instruccion", ""), "plan": plan.get("plan", ""),
                     "cuando": datetime.fromtimestamp(plan.get("ts", 0)).strftime("%d/%m %H:%M")}
            if _vigente(plan, A.PLAN_TTL) else None,
            "informes": _informes()}


@ruta("GET", r"tareas/archivo")
def api_tarea_archivo(cuerpo, consulta):
    archivo = _archivo_tarea((consulta.get("nombre") or [""])[0])
    if not archivo:
        return 404, {"ok": False, "error": "No existe ese informe."}
    contenido = archivo.read_text(encoding="utf-8", errors="replace")[:200000]
    return {"ok": True, "nombre": archivo.name, "contenido": contenido}


@ruta("POST", r"tareas")
def api_tarea_nueva(cuerpo, consulta):
    ok, texto = A.accion_tarea({"instruccion": cuerpo.get("instruccion"), "modo": cuerpo.get("modo") or "consulta"})
    return {"ok": bool(ok), "texto": texto, "activas": _tareas_activas()}


@ruta("POST", r"tareas/cancelar")
def api_tarea_cancelar(cuerpo, consulta):
    ok, texto = A.accion_cancelar_tarea({})
    return {"ok": bool(ok), "texto": texto, "activas": _tareas_activas()}


@ruta("POST", r"tareas/confirmar")
def api_tarea_confirmar(cuerpo, consulta):
    if cuerpo.get("confirmar") is not True:
        return 400, {"ok": False, "confirmar": True, "error": "Aprobar el plan pide \"confirmar\": true."}
    ok, texto = A.accion_confirmar_tarea({})
    return {"ok": bool(ok), "texto": texto}


@ruta("POST", r"tareas/descartar")
def api_tarea_descartar(cuerpo, consulta):
    habia = A.estado_cambiar(lambda e: e.pop("plan_pendiente", None))
    if habia:
        A.registrar("plan", "descartado desde el panel: " + str(habia.get("instruccion", ""))[:120])
    return {"ok": True, "texto": "Plan descartado." if habia else "No había ningún plan esperando."}


# --- memoria ---

def _memoria():
    m = A._memoria()
    datos = [d for d in m["datos"] if not d.startswith(A.PREFIJO_LECCION)]
    return {"ok": True, "datos": list(reversed(datos)), "lecciones": list(reversed(A._lecciones())),
            "historial": m["historial"][-30:], "frases": A._aprendidos()}


@ruta("GET", r"memoria")
def api_memoria(cuerpo, consulta):
    return _memoria()


@ruta("POST", r"memoria/recordar")
def api_recordar(cuerpo, consulta):
    ok, texto = A.accion_recordar({"dato": cuerpo.get("dato")})
    return {**_memoria(), "ok": bool(ok), "texto": texto or "Guardado."}


@ruta("POST", r"memoria/olvidar")
def api_olvidar(cuerpo, consulta):
    dato = str(cuerpo.get("dato") or "").strip()
    if not dato:
        return 400, {"ok": False, "error": "Falta qué olvidar."}
    ok, texto = A.accion_olvidar({"dato": dato})
    return {**_memoria(), "ok": bool(ok), "texto": texto}


@ruta("POST", r"memoria/olvidar_frase")
def api_olvidar_frase(cuerpo, consulta):
    frase = str(cuerpo.get("frase") or "").strip()
    if not frase:
        return 400, {"ok": False, "error": "Falta la frase."}
    r = A._olvidar_frase(frase)
    return {**_memoria(), "ok": bool(r), "texto": r or "No encontré esa lección."}


# --- casa ---

@ruta("GET", r"casa")
def api_casa(cuerpo, consulta):
    try:
        casa = A._casa_modulo()
        if not getattr(casa, "DISPONIBLE", True):
            raise ImportError(casa.FALTAN)
    except (Exception, SystemExit):
        return {"ok": True, "disponible": False, "dispositivos": [], "apodos": {}, "colores": [], "escenas": [],
                "aviso": "Faltan las librerías de luces y enchufes: ejecutá instalar-extras.bat en la PC."}
    guardados = casa._guardados()
    apodos = casa._apodos()
    dispositivos = [{"alias": alias, "host": i.get("host", ""), "marca": i.get("marca", ""),
                     "modelo": i.get("modelo", ""),
                     "apodo": next((a for a, real in apodos.items() if real == alias), ""),
                     "amigable": casa._amigable(alias)} for alias, i in guardados.items()]
    return {"ok": True, "disponible": True, "dispositivos": dispositivos, "apodos": apodos,
            "colores": sorted(casa.COLORES), "escenas": sorted(set(casa.ESCENAS_ES)), "aviso": ""}


# --- registro ---

def _ultimas(archivo, n):
    try:
        return archivo.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


@ruta("GET", r"registro")
def api_registro(cuerpo, consulta):
    try:
        n = max(1, min(1000, int((consulta.get("n") or ["200"])[0])))
    except ValueError:
        n = 200
    carpeta = A.VAULT / "Registro"
    logs = sorted(carpeta.glob("*.log")) if carpeta.is_dir() else []
    return {"ok": True, "registro": _ultimas(logs[-1], n) if logs else [],
            "archivo_registro": logs[-1].name if logs else "", "log": _ultimas(A.BASE / "cerebro_pc.log", n)}


# ---------- el servidor HTTP ----------

PAGINA_ACCESO = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Cerebro: acceso</title>
<style>
body{font-family:system-ui,sans-serif;background:#f4f4f6;color:#1d1d22;display:grid;place-items:center;
min-height:100vh;margin:0}
@media(prefers-color-scheme:dark){body{background:#131318;color:#e8e8ee}
input{background:#1e1e26;color:#e8e8ee;border-color:#3a3a46}}
form{max-width:360px;padding:28px;border-radius:14px;background:rgba(127,127,127,.08);
border:1px solid rgba(127,127,127,.25)}
h1{margin:0 0 6px;font-size:22px}p{margin:8px 0;line-height:1.45}
input{width:100%%;box-sizing:border-box;padding:10px;font-size:15px;border:1px solid #bbb;border-radius:8px;
margin:10px 0}
button{width:100%%;padding:10px;font-size:15px;border:0;border-radius:8px;background:#2563eb;color:#fff;
cursor:pointer}
.err{color:#d33}.ayuda{font-size:13px;opacity:.8}
</style></head>
<body><form method="get" action="/"><h1>Cerebro</h1><p>El panel de tu PC. Pegá el token para entrar.</p>%s
<input name="token" placeholder="token del panel" autocomplete="off" autofocus><button>Entrar</button>
<p class="ayuda">El token está en <b>estado.json</b> (clave <b>panel_token</b>) en la carpeta del agente, o pedilo por
Telegram escribiendo <b>panel</b>. En esa PC, <b>abrir-panel.bat</b> entra solo.</p></form></body></html>"""


class Manejador(BaseHTTPRequestHandler):
    server_version = "CerebroPanel"
    sys_version = ""

    # Bajo pythonw no hay stderr: todo va al log del agente.
    def log_message(self, formato, *args):
        log.debug("panel %s " + formato, self.address_string(), *args)

    def log_error(self, formato, *args):
        log.warning("panel %s " + formato, self.address_string(), *args)

    def do_GET(self):
        self._atender("GET")

    def do_POST(self):
        self._atender("POST")

    def do_DELETE(self):
        self._atender("DELETE")

    # --- respuestas ---

    def _cabeceras_comunes(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _json(self, objeto, estado=200):
        cuerpo = json.dumps(objeto, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self._cabeceras_comunes()
        self.end_headers()
        self.wfile.write(cuerpo)

    def _html(self, texto, estado=200, cookie=None):
        cuerpo = texto.encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self._cabeceras_comunes()
        self.end_headers()
        self.wfile.write(cuerpo)

    def _cookie(self, valor, borrar=False):
        return (COOKIE + "=" + urllib.parse.quote(valor, safe="") + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=" +
                ("0" if borrar else str(30 * 86400)))

    # --- autenticación ---

    def _autorizado(self):
        esperado = token()
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[7:].strip(), esperado)
        galletas = SimpleCookie()
        try:
            galletas.load(self.headers.get("Cookie") or "")
        except Exception:
            return False
        if COOKIE in galletas:
            return hmac.compare_digest(urllib.parse.unquote(galletas[COOKIE].value), esperado)
        return False

    # --- rutas ---

    def _atender(self, metodo):
        try:
            partes = urllib.parse.urlsplit(self.path)
            consulta = urllib.parse.parse_qs(partes.query, keep_blank_values=True)
            camino = partes.path
            if camino == "/" and metodo == "GET":
                return self._pagina(consulta)
            if camino == "/api/ping" and metodo == "GET":     # sin token: solo dice "acá hay un Cerebro" (lo usa el
                return self._json({"cerebro": True, "equipo": platform.node(),   # panel de escritorio para encontrarlo)
                                   "version": str(getattr(A, "VERSION", "")), "en_red": bool(_PANEL["en_red"])})
            if camino.startswith("/api/"):
                return self._api(metodo, camino[5:].rstrip("/"), consulta)
            self._json({"ok": False, "error": "No existe."}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log.exception("panel: %s %s", metodo, self.path[:200])
            try:
                self._json({"ok": False, "error": "Error interno: " + str(e)[:200]}, 500)
            except Exception:
                pass

    def _pagina(self, consulta):
        if "token" in consulta:                      # ?token=...: lo que usa abrir-panel.bat y el link de Telegram
            if hmac.compare_digest((consulta["token"] or [""])[0], token()):
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", self._cookie(token()))
                self.send_header("Content-Length", "0")
                self._cabeceras_comunes()
                self.end_headers()
                return
            return self._html(PAGINA_ACCESO % '<p class="err">Ese token no es. Fijate en estado.json.</p>', 401,
                              self._cookie("", borrar=True))
        if not self._autorizado():
            return self._html(PAGINA_ACCESO % "", 401)
        try:
            pagina = PAGINA.read_text(encoding="utf-8")
        except OSError:
            return self._html("<!doctype html><meta charset=utf-8><p>Falta panel.html junto a panel.py.</p>", 500)
        self._html(pagina)

    def _api(self, metodo, camino, consulta):
        if not self._autorizado():
            return self._json({"ok": False, "error": "Falta el token del panel (cookie o Authorization: Bearer)."}, 401)
        cuerpo = {}
        if metodo in ("POST", "DELETE"):
            if self.headers.get(CABECERA_CSRF) != "1":
                return self._json({"ok": False, "error": "Falta la cabecera " + CABECERA_CSRF + ": 1."}, 403)
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                largo = 0
            if largo > MAX_CUERPO:
                if largo <= 16 * MAX_CUERPO:         # lo leemos y descartamos, así la conexión se cierra prolija
                    self.rfile.read(largo)
                return self._json({"ok": False, "error": "El cuerpo es demasiado grande (máximo 64 KB)."}, 413)
            crudo = self.rfile.read(largo) if largo else b""
            if crudo.strip():
                try:
                    cuerpo = json.loads(crudo.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return self._json({"ok": False, "error": "El cuerpo no es JSON válido."}, 400)
                if not isinstance(cuerpo, dict):
                    return self._json({"ok": False, "error": "El cuerpo tiene que ser un objeto JSON."}, 400)
        for metodo_ruta, patron, fn in RUTAS:
            m = patron.fullmatch(camino)
            if m and metodo_ruta == metodo:
                respuesta = fn(cuerpo, consulta, *m.groups())
                if isinstance(respuesta, tuple):
                    return self._json(respuesta[1], respuesta[0])
                return self._json(respuesta)
        self._json({"ok": False, "error": "No existe esa ruta de la API."}, 404)
