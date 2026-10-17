"""Cerebro PC — recibe órdenes firmadas de la skill de Alexa (vía ntfy.sh) y las ejecuta en esta PC.

Solo ejecuta acciones de una lista cerrada. Cada orden llega firmada con HMAC; las que no validan se ignoran.
Corre en segundo plano con pythonw (sin ventana). Log: cerebro_pc.log junto a este archivo.
"""
import ctypes
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
VERSION = "2026-10-17"       # se ve en "estado": asi se sabe si la actualizacion quedo instalada
CONFIG = json.loads((BASE / "config_pc.json").read_text(encoding="utf-8"))
TOPIC, SECRET = CONFIG["cerebro_link"].split(":", 1)
VAULT = Path(CONFIG.get("carpeta_notas") or (Path.home() / "Cerebro"))


def _buscar_claude():
    """Claude Code puede estar en distintas rutas según la PC."""
    candidatos = [CONFIG.get("claude_exe") or "",
                  str(Path.home() / r"AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe"),
                  str(Path.home() / r"AppData\Local\Programs\claude\claude.exe")]
    for c in candidatos:
        if c and Path(c).exists():
            return c
    return shutil.which("claude") or ""


STATE_FILE = BASE / "estado.json"

from logging.handlers import RotatingFileHandler  # noqa: E402

_LOG_HANDLER = RotatingFileHandler(BASE / "cerebro_pc.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[_LOG_HANDLER])
log = logging.getLogger("cerebro")

MAX_AGE_LIVE = 120                         # órdenes en vivo más viejas se ignoran (la PC estaba apagada)
QUEUEABLE = {"nota", "completar_pendiente"}  # estas sí se procesan aunque lleguen tarde (ntfy guarda 12 h)
SIN_RESPUESTA = {"hud"}                     # mensajes informativos para el orbe en pantalla: se ignoran acá
PLAN_TTL = 24 * 3600
CREATE_NO_WINDOW = 0x08000000
TASK_TIMEOUT = 30 * 60

READ_TOOLS = "Read,Glob,Grep,WebSearch,WebFetch,PowerShell(Get-Date),PowerShell(Get-Date *),PowerShell(Get-Date:*),PowerShell(Get-ChildItem),PowerShell(Get-ChildItem *),PowerShell(Get-ChildItem:*),PowerShell(Get-Content),PowerShell(Get-Content *),PowerShell(Get-Content:*),PowerShell(Get-Item),PowerShell(Get-Item *),PowerShell(Get-Item:*),PowerShell(Get-Volume),PowerShell(Get-Volume *),PowerShell(Get-Volume:*),PowerShell(Get-ComputerInfo),PowerShell(Get-ComputerInfo *),PowerShell(Get-ComputerInfo:*),PowerShell(Get-PSDrive),PowerShell(Get-PSDrive *),PowerShell(Get-PSDrive:*),PowerShell(Test-Path),PowerShell(Test-Path *),PowerShell(Test-Path:*),PowerShell(Measure-Object),PowerShell(Measure-Object *),PowerShell(Measure-Object:*),PowerShell(Select-String),PowerShell(Select-String *),PowerShell(Select-String:*),PowerShell(Where-Object),PowerShell(Where-Object *),PowerShell(Where-Object:*),PowerShell(Select-Object),PowerShell(Select-Object *),PowerShell(Select-Object:*),PowerShell(Sort-Object),PowerShell(Sort-Object *),PowerShell(Sort-Object:*),Bash(date),Bash(date *),Bash(date:*),Bash(ls),Bash(ls *),Bash(ls:*),Bash(dir),Bash(dir *),Bash(dir:*),Bash(cat),Bash(cat *),Bash(cat:*),Bash(find),Bash(find *),Bash(find:*),Bash(wc),Bash(wc *),Bash(wc:*),Bash(head),Bash(head *),Bash(head:*),Bash(tail),Bash(tail *),Bash(tail:*),Bash(pwd),Bash(pwd *),Bash(pwd:*),Bash(df),Bash(df *),Bash(df:*)"

_state_lock = threading.RLock()


# ---------- utilidades ----------

def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _escribir_json(path, objeto):
    """Escritura atómica: primero a un archivo temporal y después se reemplaza. Un corte de luz no deja un JSON a medias."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(objeto, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def cargar_estado():
    with _state_lock:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}


def guardar_estado(estado):
    with _state_lock:
        _escribir_json(STATE_FILE, estado)


def estado_cambiar(fn):
    """Lee, modifica y guarda estado.json de una vez, sin pisar lo que otro hilo guardó en el medio."""
    with _state_lock:
        estado = cargar_estado()
        resultado = fn(estado)
        guardar_estado(estado)
        return resultado


def firmar(texto):
    return hmac.new(SECRET.encode(), texto.encode(), hashlib.sha256).hexdigest()


def publicar(topic, texto, titulo=None):
    headers = {"Title": titulo} if titulo else {}
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=texto.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def responder(msg_id, ok, texto):
    body = {"id": msg_id, "ok": ok, "texto": texto, "firma": firmar(f"{msg_id}|{ok}|{texto}")}
    publicar(f"{TOPIC}-r", json.dumps(body, ensure_ascii=False))


def _telegram(metodo, datos=None, timeout=10):
    token = str(CONFIG.get("telegram_token") or "").strip()
    if not token:
        return None
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{metodo}",
                                 data=json.dumps(datos or {}).encode("utf-8"),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _telegram_chat_id():
    """La primera vez lo averigua solo: alcanza con que le escribas /start al bot."""
    def valido(v):
        """El chat de Telegram es un número (o @canal). Un nombre de bot no sirve."""
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        if s.lstrip("-").isdigit():
            return int(s)
        if s.startswith("@"):
            return s
        log.warning("telegram_chat_id inválido en la configuración: %s (lo ignoro)", s[:40])
        return None

    estado = cargar_estado()
    cid = valido(CONFIG.get("telegram_chat_id")) or valido(estado.get("telegram_chat_id"))
    if cid:
        return cid
    try:
        datos = _telegram("getUpdates", {"limit": 20})
        for u in reversed((datos or {}).get("result", []) or []):
            mensaje = u.get("message") or u.get("channel_post") or {}
            chat = mensaje.get("chat") or {}
            # Solo un "/start" ata el bot a un chat: cualquier otro mensaje de un desconocido no sirve para eso.
            if chat.get("id") and str(mensaje.get("text") or "").strip().lower().startswith("/start"):
                estado = cargar_estado()
                estado["telegram_chat_id"] = chat["id"]
                guardar_estado(estado)
                log.info("telegram: chat detectado")
                return chat["id"]
    except Exception:
        log.exception("telegram getUpdates")
    return None


def _telegram_enviar(texto, titulo):
    cid = _telegram_chat_id()
    if not cid:
        raise RuntimeError("no tengo el chat de Telegram (mandale /start al bot)")
    _telegram("sendMessage", {"chat_id": cid, "text": titulo + chr(10) + chr(10) + texto[:3800],
                              "disable_web_page_preview": True})


def avisar_celular(texto, titulo="Cerebro"):
    """Avisa por Telegram. Si falla, reintenta detectando el chat de nuevo y lo deja anotado en el log."""
    try:
        _telegram_enviar(texto, titulo)
        return True
    except Exception as e:
        log.warning("Telegram falló (%s)", str(e)[:150])
        error = e

    if not (isinstance(error, urllib.error.HTTPError) and error.code in (400, 403)):
        # sin internet o Telegram caído: el chat guardado está bien, no hay que olvidarlo
        registrar("aviso", "NO SE PUDO AVISAR POR TELEGRAM: " + str(error)[:150] + " | mensaje: " + texto[:150])
        return False
    anterior = cargar_estado().get("telegram_chat_id")
    try:                                   # el chat guardado puede ser de un bot viejo
        estado_cambiar(lambda e: e.pop("telegram_chat_id", None))
        _telegram_enviar(texto, titulo)
        return True
    except Exception as e:
        if anterior and not cargar_estado().get("telegram_chat_id"):
            estado_cambiar(lambda x: x.__setitem__("telegram_chat_id", anterior))
        log.error("no pude avisar por Telegram: %s", str(e)[:200])
        registrar("aviso", "NO SE PUDO AVISAR POR TELEGRAM: " + str(e)[:150] + " | mensaje: " + texto[:150])
        return False


def _telegram_foto(ruta, texto=""):
    """Manda una imagen al Telegram del usuario (prueba de lo que hizo)."""
    return _telegram_subir("sendPhoto", "photo", ruta, texto, "image/png")


def _casa_modulo():
    """Importa casa.py una sola vez (corre dentro de este mismo programa)."""
    import importlib
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    return importlib.import_module("casa")


def accion_casa(d, remoto=False):
    """Prende, apaga o regula una luz o enchufe de la casa por la red local."""
    import asyncio
    dispositivo = str(d.get("dispositivo") or "").strip()
    if re.search(r"\b(pc|compu|computadora|maquina|notebook)\b", norm(dispositivo)):
        return False, "Eso es la computadora, no una luz. Decime: apagá la PC, y te pido confirmación."
    accion = norm(d.get("accion"))
    if not dispositivo or accion not in ("prender", "apagar", "estado", "brillo",
                                        "color", "temperatura", "escena"):
        return False, "No entendí qué dispositivo ni qué hacer con él."
    valor = d.get("valor") if accion in ("brillo", "color", "temperatura", "escena") else None
    salida = ""
    try:
        casa = _casa_modulo()
        salida = str(asyncio.run(casa._accion(dispositivo, accion, valor)) or "").strip()
    except Exception as e:
        log.exception("casa")
        salida = ""
        error = str(e)[:150]
        registrar("casa", accion + " " + dispositivo + " -> ERROR: " + error)
    else:
        registrar("casa", accion + " " + dispositivo + " -> " + salida[:150])

    if salida and not salida.startswith("No encontré"):
        generico = any(g in norm(dispositivo) for g in ("luz", "luces", "lampara"))
        paso = {"dispositivo": "luz" if generico else dispositivo, "accion": accion}
        if valor is not None:
            paso["valor"] = str(valor)
        anotar_accion("casa", paso)
        return True, salida[:250]

    # Hay dispositivos en la red pero ninguno se llama así: avisamos rápido, sin dar rodeos.
    try:
        conocidos = list(_casa_modulo()._guardados())
    except Exception:
        conocidos = []
    if conocidos:
        return False, ("No manejo " + dispositivo + " desde la PC: solo conozco " + ", ".join(
            _casa_modulo()._amigable(x) for x in conocidos[:5]) + ". Si está en la app de Alexa, pedíselo a Alexa.")

    if not remoto:
        # Estás en casa: pedírselo a Alexa es instantáneo; dar la vuelta por la pantalla tarda un minuto.
        return False, "Ese no lo manejo por la red. Pedíselo a Alexa directamente, que es al instante."

    # Desde el celular, fuera de casa: vale la pena el rodeo por la app de Alexa.
    que = {"prender": "prender", "apagar": "apagar", "brillo": "regular el brillo de"}.get(accion, "ver el estado de")
    orden = ("Abrí la aplicación de Alexa en esta PC, buscá el dispositivo llamado '" + dispositivo +
             "' en Dispositivos, y " + que + " ese dispositivo. Verificá con una captura que haya quedado bien.")
    threading.Thread(target=hilo_pantalla, args=(orden,), daemon=True).start()
    return True, ("No lo encontré en la red local, así que lo intento por la app de Alexa. "
                  "Tarda un minuto y te aviso al celular.")


def _estado_telegram():
    token = str(CONFIG.get("telegram_token") or "").strip()
    if not token:
        return "Telegram: no hay token en config_pc.json."
    partes = ["Telegram: token de " + str(len(token)) + " caracteres"]
    try:
        yo = _telegram("getMe") or {}
        if yo.get("ok"):
            partes.append("bot @" + str((yo.get("result") or {}).get("username")))
        else:
            partes.append("getMe respondió: " + str(yo)[:120])
    except Exception as e:
        partes.append("getMe falló: " + str(e)[:120])
    try:
        cid = _telegram_chat_id()
        partes.append("chat detectado: " + str(cid) if cid else
                      "sin chat: mandale /start al bot desde tu Telegram")
    except Exception as e:
        partes.append("no pude detectar el chat: " + str(e)[:120])
    return " | ".join(partes)


def accion_frase(d):
    """Frase suelta desde la voz: puede ser algo que el usuario enseñó."""
    texto = str(d.get("texto") or "").strip()
    if not texto:
        return False, "No entendí qué querés."
    comandos = _buscar_aprendido(texto)
    if comandos:
        return True, _ejecutar_pasos(comandos)[:250]
    r = str(_orden_telegram(texto, 1) or "")          # "modo fiesta", "luz cálida"...: lo de siempre
    if r and not r.startswith("No supe hacer"):
        return True, r[:250]
    estado = cargar_estado()
    estado["ultimo_no_entendido"] = texto
    estado["ultimo_no_entendido_ts"] = int(time.time())
    guardar_estado(estado)
    return False, "No sé hacer eso todavía. Decime qué querías que haga y lo aprendo."


def accion_diagnostico(d):
    """Estado de Telegram y últimas líneas del registro y del log."""
    partes = [_estado_telegram()]
    try:
        carpeta = VAULT / "Registro"
        logs = sorted(carpeta.glob("*.log")) if carpeta.exists() else []
        if logs:
            lineas = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()
            partes.append("Registro (últimas 10):" + chr(10) + chr(10).join(lineas[-10:]))
    except Exception as e:
        partes.append("no pude leer el registro: " + str(e)[:100])
    try:
        lineas = (BASE / "cerebro_pc.log").read_text(encoding="utf-8", errors="replace").splitlines()
        partes.append("Log del programa (últimas 12):" + chr(10) + chr(10).join(lineas[-12:]))
    except Exception as e:
        partes.append("no pude leer el log: " + str(e)[:100])

    avisar_celular((chr(10) + chr(10)).join(partes)[:3500], "Cerebro: diagnóstico")
    return True, "Te mandé el diagnóstico al celular. " + partes[0][:180]


def accion_casa_descubrir(d):
    def trabajo():
        import asyncio
        try:
            casa = _casa_modulo()
            datos = asyncio.run(casa._descubrir())
            lista = chr(10).join("- " + a + "  (" + str(i.get("marca", "")) + ", " + str(i.get("host", "")) + ")"
                                 for a, i in datos.items()) or "ninguno"
            avisar_celular("Dispositivos encontrados en tu red:" + chr(10) + lista)
        except Exception as e:
            log.exception("descubrir casa")
            avisar_celular("No pude buscar dispositivos: " + str(e)[:200])

    threading.Thread(target=trabajo, daemon=True).start()
    return True, "Busco los dispositivos de tu red y te mando la lista al celular."


def accion_avisar(d):
    texto = str(d.get("texto") or "").strip()
    if not texto:
        return False, "No recibí el texto para mandar al celular."
    avisar_celular(texto)
    return True, ""


def agregar_linea(path, linea, encabezado):
    VAULT.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(encabezado, encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(linea + "\n")


def limpiar_para_voz(linea):
    linea = re.sub(r"^\s*-\s*(\[[ xX]\]\s*)?", "", linea)
    linea = re.sub(r"_\(agregado [^)]*\)_", "", linea)
    linea = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}\s*", "", linea)
    return linea.replace("**", "").replace("#", "").strip(" :")


# ---------- memoria permanente ----------

MEMORIA = None
MAX_DATOS = 200
MAX_HISTORIAL = 40
_MEM_LOCK = threading.RLock()       # Telegram, ntfy y los hilos de avisos escriben la memoria a la vez


def _memoria():
    with _MEM_LOCK:
        try:
            datos = json.loads((BASE / "memoria.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            datos = {}
    datos.setdefault("datos", [])
    datos.setdefault("historial", [])
    return datos


def _guardar_memoria(m):
    m["datos"] = m["datos"][-MAX_DATOS:]
    m["historial"] = m["historial"][-MAX_HISTORIAL:]
    with _MEM_LOCK:
        _escribir_json(BASE / "memoria.json", m)


def recordar_dato(texto):
    texto = str(texto or "").strip()
    if not texto:
        return False
    with _MEM_LOCK:
        m = _memoria()
        if texto not in m["datos"]:
            m["datos"].append(texto)
            _guardar_memoria(m)
            registrar("memoria", "recordar: " + texto[:150])
    return True


def olvidar_dato(texto):
    objetivo = norm(texto)
    with _MEM_LOCK:
        m = _memoria()
        antes = len(m["datos"])
        m["datos"] = [d for d in m["datos"] if objetivo not in norm(d)]
        _guardar_memoria(m)
    registrar("memoria", "olvidar: " + str(texto)[:100])
    return antes - len(m["datos"])


def anotar_charla(rol, texto):
    with _MEM_LOCK:
        m = _memoria()
        m["historial"].append({"rol": rol, "texto": str(texto)[:800], "cuando": ahora()})
        _guardar_memoria(m)


def contexto_memoria(con_historial=True):
    """Lo que Cerebro sabe, para pasárselo a Claude o a quien lo necesite."""
    m = _memoria()
    partes = []
    if m["datos"]:
        partes.append("Lo que sé del usuario:" + chr(10) +
                      chr(10).join("- " + d for d in m["datos"][-40:]))
    if con_historial and m["historial"]:
        ultimos = m["historial"][-12:]
        partes.append("Últimos mensajes con él:" + chr(10) +
                      chr(10).join(("Usuario: " if h["rol"] == "user" else "Vos: ") + h["texto"][:200]
                                   for h in ultimos))
    return (chr(10) + chr(10)).join(partes)


def accion_recordar(d):
    dato = str(d.get("dato") or d.get("texto") or "").strip()
    if not dato:
        return False, "No recibí qué recordar."
    recordar_dato(dato)
    return True, ""


def accion_olvidar(d):
    borrados = olvidar_dato(str(d.get("dato") or d.get("texto") or ""))
    return True, ("Listo, lo olvidé." if borrados else "No tenía nada guardado sobre eso.")


def accion_que_sabes(d):
    datos = [x for x in _memoria()["datos"] if not x.startswith("Cuando el usuario dice")]
    if not datos:
        return True, "Todavía no guardé nada sobre vos."
    return True, "Esto es lo que sé: " + "; ".join(_a_vos(x) for x in datos[-10:]) + "."


def _a_vos(dato):
    """'la hermana del usuario se llama Laura' -> 'tu hermana se llama Laura'."""
    dato = re.sub(r"\b(?:el|la) ([\wáéíóúñ]+) del usuario\b", r"tu \1", dato, flags=re.I)
    dato = re.sub(r"\b(?:los|las) ([\wáéíóúñ]+) del usuario\b", r"tus \1", dato, flags=re.I)
    dato = re.sub(r"\bal usuario le\b", "te", dato, flags=re.I)
    dato = re.sub(r"^su(s?) ", r"tu\1 ", dato, flags=re.I)
    return dato[:1].lower() + dato[1:] if dato[:2] in ("Tu", "Te") else dato


# ---------- segundo cerebro ----------

def accion_nota(d):
    texto = str(d.get("texto") or "").strip()
    categoria = str(d.get("categoria") or "nota").strip().lower()
    if not texto:
        return False, "No recibí el texto de la nota."
    if categoria == "pendiente":
        agregar_linea(VAULT / "Pendientes.md", f"- [ ] {texto} _(agregado {ahora()})_", "# Pendientes\n\n")
        return True, "Pendiente agregado."
    agregar_linea(VAULT / "Inbox.md", f"- {ahora()} **{categoria}**: {texto}",
                  "# Inbox\n\nIdeas y notas dictadas por voz.\n\n")
    return True, "Nota guardada."


def leer_pendientes():
    path = VAULT / "Pendientes.md"
    if not path.exists():
        return path, []
    return path, path.read_text(encoding="utf-8").splitlines()


def accion_pendientes(d):
    _, lineas = leer_pendientes()
    abiertos = [limpiar_para_voz(l) for l in lineas if l.strip().startswith("- [ ]")]
    if not abiertos:
        return True, "No tenés pendientes."
    visibles = abiertos[:7]
    texto = f"Tenés {len(abiertos)} pendiente{'s' if len(abiertos) != 1 else ''}: " + "; ".join(visibles)
    if len(abiertos) > 7:
        texto += f"; y {len(abiertos) - 7} más"
    return True, texto + "."


def mejor_coincidencia(consulta, lineas):
    palabras = [w for w in norm(consulta).split() if len(w) > 3] or norm(consulta).split()
    mejor, puntaje = None, 0
    for i, linea in enumerate(lineas):
        p = sum(1 for w in palabras if w in norm(linea))
        if p > puntaje:
            mejor, puntaje = i, p
    return mejor


def accion_completar_pendiente(d):
    path, lineas = leer_pendientes()
    abiertos = [i for i, l in enumerate(lineas) if l.strip().startswith("- [ ]")]
    idx = mejor_coincidencia(d.get("texto", ""), [lineas[i] for i in abiertos])
    if idx is None:
        return False, "No encontré ese pendiente."
    i = abiertos[idx]
    lineas[i] = lineas[i].replace("- [ ]", "- [x]", 1)
    path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return True, f"Marqué como hecho: {limpiar_para_voz(lineas[i].replace('- [x]', ''))}."


def accion_buscar_notas(d):
    consulta = str(d.get("consulta") or "").strip()
    if not consulta:
        return False, "¿Qué quieres que busque en tus notas?"
    palabras = [w for w in norm(consulta).split() if len(w) > 3] or norm(consulta).split()
    encontrados = []
    for path in VAULT.rglob("*.md") if VAULT.exists() else []:
        if "Papelera" in path.parts:
            continue
        try:
            lineas = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for linea in lineas:
            p = sum(1 for w in palabras if w in norm(linea))
            if p and linea.strip() and not linea.startswith("#"):
                encontrados.append((p, path.stat().st_mtime, limpiar_para_voz(linea)[:180]))
    if not encontrados:
        return True, "No encontré nada sobre eso en tus notas."
    encontrados.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return True, "Esto encontré en tus notas: " + " | ".join(t for _, _, t in encontrados[:3])


# ---------- control de la PC ----------

APPS = {
    "calculadora": "calc.exe", "bloc de notas": "notepad.exe", "notepad": "notepad.exe",
    "explorador": "explorer.exe", "explorador de archivos": "explorer.exe", "archivos": "explorer.exe",
    "configuracion": "ms-settings:", "ajustes": "ms-settings:", "paint": "mspaint.exe",
    "administrador de tareas": "taskmgr.exe", "terminal": "wt.exe",
}


def accesos_menu_inicio():
    carpetas = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
                Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs"]
    for carpeta in carpetas:
        if carpeta.exists():
            yield from carpeta.rglob("*.lnk")


_APPS_CACHE = {"ts": 0.0, "apps": []}
SITIOS_APPS = {"claude": "https://claude.ai", "chatgpt": "https://chatgpt.com", "gmail": "https://mail.google.com",
               "youtube": "https://www.youtube.com", "netflix": "https://www.netflix.com",
               "instagram": "https://www.instagram.com", "facebook": "https://www.facebook.com",
               "mercado libre": "https://www.mercadolibre.com.ar", "whatsapp web": "https://web.whatsapp.com"}
ALIAS_APPS = {"wpp": "whatsapp", "whats": "whatsapp", "guasap": "whatsapp", "navegador": "chrome",
              "google chrome": "chrome", "calcu": "calculadora", "spoti": "spotify", "el word": "word",
              "el excel": "excel", "la terminal": "terminal", "vs code": "visual studio code", "vscode": "visual studio code"}


def _apps_instaladas():
    """Todas las apps del menú Inicio, también las de la Microsoft Store, con el ID para abrirlas (cache 10 min)."""
    if _APPS_CACHE["apps"] and time.time() - _APPS_CACHE["ts"] < 600:
        return _APPS_CACHE["apps"]
    apps = []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
                           capture_output=True, text=True, encoding="utf-8", timeout=25, creationflags=CREATE_NO_WINDOW)
        datos = json.loads(r.stdout or "[]")
        datos = [datos] if isinstance(datos, dict) else datos
        apps = [(str(x.get("Name") or ""), str(x.get("AppID") or "")) for x in datos if x.get("AppID")]
    except Exception:
        log.exception("Get-StartApps")
    _APPS_CACHE.update(ts=time.time(), apps=apps)
    return apps


def _mejor_app(nombre):
    import difflib
    objetivo = ALIAS_APPS.get(nombre, nombre)
    mejor, puntaje = None, 0.0
    for titulo, appid in _apps_instaladas():
        n = norm(titulo)
        if not n or "desinstal" in n or "uninstall" in n:
            continue
        if n == objetivo:
            return titulo, appid
        p = (0.95 if n.startswith(objetivo + " ") else 0.9 if objetivo in n.split() else
             0.8 if objetivo in n else difflib.SequenceMatcher(None, n, objetivo).ratio())
        if p > puntaje:
            mejor, puntaje = (titulo, appid), p
    return mejor if puntaje >= 0.78 else None


def accion_abrir_app(d):
    nombre = norm(d.get("nombre")).strip()
    nombre = re.sub(r"^(la |el |los |las )?(app |aplicacion |programa )?(de |del )?", "", nombre).strip()
    if not nombre:
        return False, "¿Qué aplicación querés que abra?"
    if nombre in APPS:
        os.startfile(APPS[nombre])
        return True, f"Abrí {d.get('nombre')}."
    hallada = _mejor_app(nombre)
    if hallada:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + hallada[1]], creationflags=CREATE_NO_WINDOW)
        return True, f"Abrí {hallada[0]}."
    candidatos = []
    for lnk in accesos_menu_inicio():
        titulo = norm(lnk.stem)
        if "desinstalar" in titulo or "uninstall" in titulo:
            continue
        if nombre == titulo:
            candidatos.append((0, lnk))
        elif nombre in titulo:
            candidatos.append((len(titulo), lnk))
    if candidatos:
        candidatos.sort(key=lambda x: x[0])
        os.startfile(str(candidatos[0][1]))
        return True, f"Abrí {candidatos[0][1].stem}."
    sitio = SITIOS_APPS.get(ALIAS_APPS.get(nombre, nombre))
    if sitio:
        webbrowser.open(sitio)
        return True, f"No tenés la app de {d.get('nombre')} instalada, así que te abrí {sitio} en el navegador."
    return False, f"No encontré {d.get('nombre')} instalada en la PC."


def accion_abrir_web(d):
    url = str(d.get("url") or "").strip()
    busqueda = str(d.get("busqueda") or "").strip()
    if url and not re.match(r"^https?://", url) and re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", url, re.I):
        url = "https://" + url
    if url.startswith(("http://", "https://")):
        webbrowser.open(url)
        return True, ""
    q = busqueda or url
    if not q:
        return False, "¿Qué página quieres abrir?"
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(q))
    return True, ""


def _medios():
    m = _mod("medios")
    m.VER = ver_imagen
    return m


def _mod(nombre):
    import importlib
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    return importlib.import_module(nombre)


def _pausar_lo_que_suena(medios):
    """Antes de poner otra música, pausa la que está sonando (si no, suenan dos a la vez)."""
    try:
        s = medios.principal(medios.sesiones())
        if s and s.get("estado") == "Playing":
            medios.tecla("pausa")
            time.sleep(0.4)
    except Exception:
        log.warning("no pude ver qué sonaba")


def _asegurar_que_suene(medios, espera=12):
    """Si el navegador bloqueó que arranque solo (Chrome lo hace seguido), le da play en la ventana de YouTube."""
    navegadores = ("Chrome", "Edge", "Firefox")

    def del_navegador():
        try:
            return [s for s in medios.sesiones() if medios.nombre_app(s.get("app")) in navegadores]
        except Exception:
            return None

    intento_play = False
    for segundo in range(espera):
        time.sleep(1)
        sesiones = del_navegador()
        if sesiones is None:
            return
        if any(s.get("estado") == "Playing" for s in sesiones):
            return                                   # ya suena
        if segundo >= 5 and not intento_play:        # 5 s sin sonar: play a mano en la pestaña de YouTube
            intento_play = True
            try:
                if not medios.play_en_youtube():
                    log.info("no encontré la ventana de YouTube para darle play")
            except Exception:
                log.exception("play en YouTube")


def accion_musica(d):
    q = str(d.get("busqueda") or "").strip()
    if not q:
        return False, "¿Qué música querés escuchar?"
    servicio = "spotify" if norm(d.get("servicio")) == "spotify" else "youtube"
    estado_cambiar(lambda e: e.__setitem__("ultima_musica", {"busqueda": q, "servicio": servicio}))
    medios = _medios()
    _pausar_lo_que_suena(medios)
    if servicio == "spotify":
        try:
            ok, texto = medios.spotify_reproducir(q)
        except Exception as e:
            log.exception("spotify")
            ok, texto = False, "falló el manejo de Spotify: " + str(e)[:80]
        if ok:
            return True, texto
        log.warning("spotify no pudo (%s): uso YouTube", texto)
        motivo = f"No pude darle play en Spotify ({texto}), así que "
    else:
        motivo = ""
    link, directo = medios.link_youtube(q)
    webbrowser.open(link)
    if directo:
        threading.Thread(target=_asegurar_que_suene, args=(medios,), daemon=True).start()
        return True, (motivo + "lo pongo en YouTube.") if motivo else f"Pongo {q} en YouTube."
    return True, (motivo + "te abrí la búsqueda en YouTube.") if motivo else f"Te abrí la búsqueda de {q} en YouTube."


def accion_musica_control(d):
    """Pausa, seguir, siguiente, anterior o qué está sonando, con lo que suene en la PC (Spotify, YouTube...)."""
    que = norm(d.get("accion") or "que_suena").replace(" ", "_")
    que = {"pausar": "pausa", "parar": "pausa", "stop": "pausa", "reanudar": "seguir", "play": "seguir",
           "continuar": "seguir", "proxima": "siguiente", "siguiente_tema": "siguiente", "que_esta_sonando": "que_suena",
           "sonando": "que_suena"}.get(que, que)
    if que not in ("pausa", "seguir", "siguiente", "anterior", "que_suena"):
        return False, "No entendí qué hacer con la música."
    medios = _medios()
    if que in ("siguiente", "anterior"):               # rápido: la voz no puede esperar más de unos segundos
        medios.tecla(que)
        time.sleep(0.8)
        try:
            nuevo = medios.principal(medios.sesiones())
        except Exception:
            nuevo = None
        if nuevo and nuevo.get("titulo") and nuevo.get("estado") == "Playing":
            return True, "Ahora suena " + nuevo["titulo"] + (", de " + nuevo["artista"] if nuevo.get("artista") else "") + "."
        return True, "Listo, pasé de tema."
    try:
        actual = medios.principal(medios.sesiones())
    except Exception:
        log.warning("no pude leer lo que suena")
        if que == "que_suena":
            return False, "No pude ver qué está sonando."
        medios.tecla(que)
        return True, "Listo."
    if que == "que_suena":
        return True, medios.describir(actual)
    if que == "pausa":
        if not actual or actual.get("estado") != "Playing":
            return True, "No está sonando nada."
        medios.tecla("pausa")
        return True, "Pausado."
    if que == "seguir":
        if actual and actual.get("estado") == "Playing":
            return True, medios.describir(actual)
        if not actual:                                  # no hay nada abierto: vuelve a poner lo último
            ultima = cargar_estado().get("ultima_musica") or {}
            if not ultima.get("busqueda"):
                return True, "No hay nada para seguir escuchando. Decime qué música poner."
            ok, _ = accion_musica(ultima)
            return ok, "Vuelvo a poner lo último: " + ultima["busqueda"] + "."
        medios.tecla("seguir")
        return True, "Sigue sonando" + (": " + actual["titulo"] if actual.get("titulo") else "") + "."
    if not actual:
        return True, "No está sonando nada."
    medios.tecla(que)
    for _ in range(4):                                  # esperar a que cambie el tema para decir cuál es
        time.sleep(0.5)
        try:
            nuevo = medios.principal(medios.sesiones())
        except Exception:
            break
        if nuevo and nuevo.get("titulo") and nuevo.get("titulo") != actual.get("titulo"):
            return True, "Ahora suena " + nuevo["titulo"] + (", de " + nuevo["artista"] if nuevo.get("artista") else "") + "."
    return True, "Listo."


def accion_volumen(d):
    teclas = {"subir": 0xAF, "bajar": 0xAE, "silenciar": 0xAD}
    cambio = norm(d.get("cambio"))
    nivel = d.get("nivel") if d.get("nivel") is not None else (
        d.get("pasos") or d.get("valor") if cambio in ("porcentaje", "fijar", "nivel", "poner") else None)
    if nivel is not None:                  # "poné el volumen al 50": baja a cero y sube hasta ese nivel
        nivel = max(0, min(100, int(float(nivel))))
        for tecla, veces in ((0xAE, 50), (0xAF, nivel // 2)):
            for _ in range(veces):
                ctypes.windll.user32.keybd_event(tecla, 0, 0, 0)
                ctypes.windll.user32.keybd_event(tecla, 0, 2, 0)
                time.sleep(0.01)
        return True, f"Volumen al {nivel} por ciento."
    if cambio not in teclas:
        return False, "No entendí el cambio de volumen."
    veces = 1 if cambio == "silenciar" else max(1, min(50, int(float(d.get("pasos") or 5))))
    for _ in range(veces):
        ctypes.windll.user32.keybd_event(teclas[cambio], 0, 0, 0)
        ctypes.windll.user32.keybd_event(teclas[cambio], 0, 2, 0)
        time.sleep(0.02)
    return True, ""


def accion_sistema(d):
    orden = norm(d.get("orden"))
    if orden == "bloquear":
        ctypes.windll.user32.LockWorkStation()
    elif orden == "suspender":
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=CREATE_NO_WINDOW)
    elif orden == "apagar":
        subprocess.run(["shutdown", "/s", "/t", "60"], creationflags=CREATE_NO_WINDOW)
        avisar_celular("Tu PC se apagará en 60 segundos. Para cancelar, pide 'cancelar apagado'.")
        return True, "Tu PC se apagará en un minuto."
    elif orden == "reiniciar":
        estado_cambiar(lambda e: e.__setitem__("reinicio_pedido_ts", time.time()))
        subprocess.run(["shutdown", "/r", "/t", "60"], creationflags=CREATE_NO_WINDOW)
        return True, "Tu PC se reiniciará en un minuto."
    elif orden == "cancelar_apagado":
        subprocess.run(["shutdown", "/a"], creationflags=CREATE_NO_WINDOW)
        return True, "Cancelé el apagado."
    else:
        return False, "No conozco esa orden del sistema."
    return True, ""


def accion_estado(d):
    return True, f"Tu PC está conectada. Cerebro versión {VERSION}."


# ---------- tareas con Claude Code ----------

def datos_sistema():
    """Datos que Claude no puede leer solo: hora exacta, equipo y disco."""
    import platform
    libre = total = 0
    try:
        uso = shutil.disk_usage("C:\\")
        libre, total = uso.free / 1e9, uso.total / 1e9
    except OSError:
        pass
    return {
        "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "equipo": platform.node(),
        "usuario": os.environ.get("USERNAME", ""),
        "disco_c_libre_gb": round(libre, 1),
        "disco_c_total_gb": round(total, 1),
        "carpeta_notas": str(VAULT),
    }


def accion_info_pc(d):
    i = datos_sistema()
    return True, (f"Son las {i['fecha_hora'][11:16]} del {i['fecha_hora'][:10]}. "
                  f"El disco C tiene {i['disco_c_libre_gb']} gigas libres de {i['disco_c_total_gb']}. "
                  f"La PC es {i['equipo']}, usuario {i['usuario']}.")


def ver_imagen(ruta, pregunta, timeout=20):
    """La IA gratis de Google mira una captura de pantalla y responde (en JSON). None si no pudo."""
    import base64
    import io
    clave = _clave_gemini()
    if not clave:
        return None
    try:                                           # achicada y en JPG: viaja y se procesa mucho más rápido
        from PIL import Image
        img = Image.open(ruta).convert("RGB")
        if img.width > 1600:
            img = img.resize((1600, int(img.height * 1600 / img.width)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        datos, tipo = buf.getvalue(), "image/jpeg"
    except Exception:
        datos, tipo = Path(ruta).read_bytes(), "image/png"
    cuerpo = {"contents": [{"role": "user", "parts": [
        {"inline_data": {"mime_type": tipo, "data": base64.b64encode(datos).decode()}}, {"text": pregunta}]}],
        "generationConfig": {"maxOutputTokens": 2000, "temperature": 0, "responseMimeType": "application/json"}}
    for intento in range(2):
        texto = _carrera(lambda m: cuerpo, clave, timeout,
                         lambda x: _json_de(x) is not None or x.strip().startswith("["), TANDAS_IMAGEN)
        if texto:
            return texto
        if intento == 0:
            time.sleep(1.0)
    return None


def _wa():
    """Importa whatsapp_app.py una sola vez (dentro de este programa) y le da la IA para mirar la pantalla."""
    import importlib
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    wa = importlib.import_module("whatsapp_app")
    wa.VER = ver_imagen
    return wa


WA_LOCK = threading.Lock()      # un solo manejo de WhatsApp a la vez: si no, se pisan los teclazos


def _preparar_whatsapp(d, tipo):
    contacto = str(d.get("contacto") or "").strip()
    mensaje = str(d.get("mensaje") or "").strip()
    if not contacto or not mensaje:
        return False, "Me falta el contacto o el mensaje."
    estado = cargar_estado()
    estado["whatsapp_pendiente"] = {"tipo": tipo, "contacto": contacto, "mensaje": mensaje,
                                    "foto": bool(d.get("foto")), "ts": int(time.time())}
    guardar_estado(estado)
    if tipo == "editar":
        return True, f"Voy a corregir tu último mensaje a {contacto} para que diga: {mensaje}."
    return True, f"Le voy a mandar a {contacto}: {mensaje}."


def accion_whatsapp_archivo(d):
    """Prepara mandar un archivo o foto de la PC por WhatsApp; se envía cuando el usuario dice 'sí'."""
    contacto = str(d.get("contacto") or "").strip()
    nombre = str(d.get("archivo") or d.get("nombre") or "").strip()
    if not contacto or not nombre:
        return False, "Me falta a quién o qué archivo."
    directo = Path(nombre.strip('"'))
    encontrados = [directo] if directo.is_file() else _buscar_archivo(nombre)
    if not encontrados:
        return False, f"No encontré ningún archivo parecido a {nombre} en el Escritorio, Documentos ni Descargas."
    archivo = encontrados[0]
    estado = cargar_estado()
    estado["whatsapp_pendiente"] = {"tipo": "archivo", "contacto": contacto, "mensaje": str(d.get("mensaje") or ""),
                                    "archivo": str(archivo), "ts": int(time.time())}
    guardar_estado(estado)
    return True, f"Le voy a mandar a {contacto} el archivo {archivo.name}."


def accion_whatsapp(d):
    """Prepara el envío: guarda el pedido y devuelve el texto para que Alexa lo confirme."""
    return _preparar_whatsapp(d, "enviar")


def accion_whatsapp_editar(d):
    """Prepara la corrección del último mensaje propio en ese chat."""
    return _preparar_whatsapp(d, "editar")


def _hilo_whatsapp(pend):
    contacto, mensaje = pend["contacto"], pend["mensaje"]
    try:
        with WA_LOCK:
            wa = _wa()
            if pend.get("tipo") == "editar":
                ok, texto, foto = wa.editar_ultimo(contacto, mensaje, con_foto=pend.get("foto"))
            elif pend.get("tipo") == "archivo":
                ok, texto, foto = wa.enviar_archivo(contacto, pend["archivo"], mensaje, con_foto=pend.get("foto"))
            else:
                ok, texto, foto = wa.enviar(contacto, mensaje, con_foto=pend.get("foto"))
        registrar("whatsapp", pend.get("tipo", "enviar") + " " + contacto + ": " + mensaje[:120] + " -> " + texto[:120])
        if not ok:
            avisar_celular("No lo mandé. " + texto)
        elif foto:
            _telegram_foto(foto, texto[:900])
        else:
            avisar_celular("✅ " + texto)
    except Exception as e:
        log.exception("whatsapp falló")
        avisar_celular("Falló WhatsApp con " + contacto + ": " + str(e)[:200])


def accion_whatsapp_confirmar(d):
    estado = cargar_estado()
    pend = estado.get("whatsapp_pendiente")
    if not pend or time.time() - pend.get("ts", 0) > 600:
        return False, "No hay ningún mensaje esperando confirmación."
    estado.pop("whatsapp_pendiente", None)
    guardar_estado(estado)
    threading.Thread(target=_hilo_whatsapp, args=(pend,), daemon=True).start()
    return True, "Corrigiendo." if pend.get("tipo") == "editar" else "Enviando."


def accion_whatsapp_cancelar(d):
    """El usuario dijo "no" (o cambió de tema) al "¿lo envío?": el mensaje preparado se descarta."""
    habia = estado_cambiar(lambda e: e.pop("whatsapp_pendiente", None))
    return True, "Descarté el mensaje." if habia else "No había ningún mensaje esperando."


def accion_whatsapp_leer(d):
    """Abre el chat y te manda por Telegram lo que dice (la IA lo lee de la pantalla)."""
    contacto = str(d.get("contacto") or "").strip()
    if not contacto:
        return False, "¿De qué chat querés ver los mensajes?"

    def trabajo():
        try:
            with WA_LOCK:
                ok, texto, foto = _wa().leer_chat(contacto)
            avisar_celular(texto)
            if ok and foto and "no pude leerlo" in texto:
                _telegram_foto(foto, "Chat con " + contacto)
        except Exception as e:
            log.exception("whatsapp leer")
            avisar_celular(f"No pude leer el chat con {contacto}: {str(e)[:200]}")

    threading.Thread(target=trabajo, daemon=True).start()
    return True, f"Leo el chat con {contacto} y te lo mando al celular."


def accion_whatsapp_resumen(d):
    """Resume los chats sin leer SIN abrirlos (no quedan marcados como leídos)."""
    def trabajo():
        try:
            with WA_LOCK:
                ok, texto = _wa().no_leidos()
            avisar_celular(texto)
        except Exception as e:
            log.exception("whatsapp resumen")
            avisar_celular("No pude revisar WhatsApp: " + str(e)[:200])

    threading.Thread(target=trabajo, daemon=True).start()
    return True, "Reviso tus mensajes sin leer y te mando el resumen al celular."


def reglas_claude():
    return (
        "Trabajas en la PC del usuario, que te habla por su asistente de voz. Responde siempre en español." + chr(10) +
        "Tienes permisos completos sobre esta PC para trabajar: comandos, instalaciones, código, archivos e internet." + chr(10) +
        "PROHIBIDO: comprar, pagar, suscribirte, transferir dinero o ingresar datos de tarjeta, claves o "
        "contraseñas en ningún sitio. Si una tarea lo necesita, detente y explícalo en tu respuesta." + chr(10) +
        "Para borrar NO uses rm ni Remove-Item: manda a la papelera con" + chr(10) +
        '  powershell -ExecutionPolicy Bypass -File "' + str(BASE / "papelera.ps1") + '" -Path "<ruta>"' + chr(10) +
        "así el usuario puede recuperar lo que se borre por error." + chr(10) +
        "Tu respuesta final: máximo 10 líneas, sin tablas, diciendo qué hiciste y listando los archivos que "
        "creaste, modificaste, moviste o borraste."
    )


def registrar(etiqueta, linea):
    """Historial de todo lo que ejecuta Claude, para poder revisarlo después."""
    try:
        carpeta = VAULT / "Registro"
        carpeta.mkdir(parents=True, exist_ok=True)
        with (carpeta / f"{datetime.now():%Y-%m-%d}.log").open("a", encoding="utf-8") as f:
            f.write(ahora() + " [" + etiqueta + "] " + linea + chr(10))
    except OSError:
        log.exception("no pude escribir el registro")


def _resumen_uso(bloque):
    """Texto corto de una herramienta usada por Claude, para el registro."""
    nombre = bloque.get("name", "?")
    e = bloque.get("input") or {}
    for campo in ("command", "file_path", "path", "pattern", "url", "query", "prompt"):
        if e.get(campo):
            return nombre + ": " + str(e[campo])[:300]
    return nombre


def correr_claude(prompt, tools=None, permisos_totales=False, etiqueta="tarea", progreso=None, descripcion=None):
    """Ejecuta Claude Code y devuelve (texto, hubo_error, cantidad_de_acciones).

    Va leyendo lo que hace en vivo: progreso(texto) se llama cada tanto para contarte en qué anda,
    y la tarea queda anotada en TAREAS_ACTIVAS para poder verla o cancelarla desde Telegram.
    """
    exe = _buscar_claude()   # se busca en cada tarea: puede haberse instalado después de arrancar
    if not exe:
        raise RuntimeError("No encontré Claude Code en esta PC.")
    cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
           "--append-system-prompt", reglas_claude() + chr(10) + REGLA_ARCHIVOS]
    if permisos_totales:
        cmd += ["--permission-mode", "bypassPermissions"]
    else:
        cmd += ["--permission-mode", "dontAsk", "--allowedTools", tools or READ_TOOLS]

    # Entorno limpio: que Claude use el login normal del usuario y no variables heredadas de otra sesión.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_", "CLAUDECODE"))}
    i = datos_sistema()
    contexto = ("[Datos de esta PC, ya verificados: fecha y hora " + i["fecha_hora"] + "; equipo " + i["equipo"] +
                "; usuario " + i["usuario"] + "; disco C con " + str(i["disco_c_libre_gb"]) + " GB libres de " +
                str(i["disco_c_total_gb"]) + " GB; carpeta de notas " + i["carpeta_notas"] +
                ". Usalos directamente, no intentes consultarlos.]" + chr(10) + chr(10))
    memoria = contexto_memoria(con_historial=(etiqueta == "telegram"))
    if memoria:
        contexto += memoria + chr(10) + chr(10)
    registrar(etiqueta, "INICIO (" + ("permisos totales" if permisos_totales else "solo lectura") + "): " + prompt[:200])

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env, cwd=str(Path.home()),
                            creationflags=CREATE_NO_WINDOW)
    tid = os.urandom(3).hex()
    info = {"proc": proc, "descripcion": str(descripcion or prompt)[:90], "inicio": time.time(),
            "ultimo": "Arrancando", "cancelada": False}
    with TAREAS_LOCK:
        TAREAS_ACTIVAS[tid] = info
    vigilante = threading.Timer(TASK_TIMEOUT, _matar_tarea, args=(info,))
    vigilante.daemon = True
    vigilante.start()

    texto, error, acciones, crudo = "", True, 0, []
    ultimo_aviso = time.time()
    try:
        proc.stdin.write(contexto + prompt)
        proc.stdin.close()
        for linea in proc.stdout:
            crudo.append(linea)
            try:
                ev = json.loads(linea)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                for bloque in (ev.get("message", {}) or {}).get("content", []) or []:
                    if bloque.get("type") == "tool_use":
                        acciones += 1
                        registrar(etiqueta, _resumen_uso(bloque))
                        info["ultimo"] = _paso_legible(bloque)
                        if progreso and time.time() - ultimo_aviso > AVISO_CADA:
                            ultimo_aviso = time.time()
                            try:
                                progreso(f"{info['ultimo']} ({acciones} pasos, {_duracion_corta(time.time() - info['inicio'])})")
                            except Exception:
                                log.exception("aviso de avance")
            elif ev.get("type") == "result":
                texto = str(ev.get("result") or "").strip()
                error = bool(ev.get("is_error"))
        proc.wait(timeout=30)
    finally:
        vigilante.cancel()
        with TAREAS_LOCK:
            TAREAS_ACTIVAS.pop(tid, None)
    if info["cancelada"]:
        texto, error = "La frené antes de que terminara. Lo último que estaba haciendo: " + info["ultimo"] + ".", True
    if not texto:
        texto = "".join(crudo).strip()[-1500:] or "sin salida"
    registrar(etiqueta, "FIN (" + str(acciones) + " acciones, " + ("con error" if error else "ok") + "): " + texto[:300])
    return texto, error, acciones


# ---------- tareas en la PC: en vivo, cancelables y con archivos ----------

TAREAS_ACTIVAS = {}          # id -> {"proc", "descripcion", "inicio", "ultimo", "cancelada"}
TAREAS_LOCK = threading.Lock()
AVISO_CADA = 25              # segundos entre avisos de avance al celular
REGLA_ARCHIVOS = ("Si creaste o encontraste un archivo que el usuario tiene que recibir en el celular (un Excel, un PDF, "
                  "una imagen, un informe), agregá al final de tu respuesta una línea por archivo, exactamente así: "
                  "ENVIAR_ARCHIVO: <ruta completa>. Cerebro se lo manda por Telegram.")


def _duracion_corta(seg):
    seg = int(seg)
    return f"{seg} s" if seg < 60 else f"{seg // 60} min"


def _paso_legible(bloque):
    """Lo que está haciendo Claude, en castellano, para contártelo mientras trabaja."""
    nombre = bloque.get("name", "")
    e = bloque.get("input") or {}
    archivo = Path(str(e.get("file_path") or e.get("path") or "")).name
    if nombre == "Read":
        return "Leyendo " + (archivo or "un archivo")
    if nombre in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return "Escribiendo " + (archivo or "un archivo")
    if nombre in ("Glob", "Grep"):
        return "Buscando archivos"
    if nombre == "WebSearch":
        return "Buscando en internet: " + str(e.get("query") or "")[:80]
    if nombre == "WebFetch":
        return "Leyendo la página " + str(e.get("url") or "")[:80]
    if nombre in ("Bash", "PowerShell"):
        comando = str(e.get("command") or "")
        if "escritorio.py" in comando:
            return "Manejando la pantalla (" + comando.split("escritorio.py", 1)[1].strip(' "')[:60] + ")"
        return "Ejecutando: " + comando[:90]
    if nombre == "TodoWrite":
        return "Organizando los pasos"
    return nombre or "Trabajando"


def _matar_tarea(info):
    """Frena una tarea y todo lo que lanzó (taskkill con /T mata el árbol de procesos)."""
    info["cancelada"] = True
    try:
        subprocess.run(["taskkill", "/PID", str(info["proc"].pid), "/T", "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, timeout=20)
    except Exception:
        try:
            info["proc"].kill()
        except Exception:
            pass


def accion_tareas_estado(d):
    with TAREAS_LOCK:
        activas = list(TAREAS_ACTIVAS.values())
    if not activas:
        return True, "No estoy haciendo ninguna tarea ahora."
    partes = [f"{x['descripcion'][:70]}: {x['ultimo']} (hace {_duracion_corta(time.time() - x['inicio'])})"
              for x in activas]
    return True, "Estoy trabajando en: " + "; ".join(partes) + "."


def accion_cancelar_tarea(d):
    with TAREAS_LOCK:
        activas = list(TAREAS_ACTIVAS.values())
    if not activas:
        return True, "No hay ninguna tarea para frenar."
    for x in activas:
        _matar_tarea(x)
    return True, "Listo, frené " + ("la tarea." if len(activas) == 1 else f"las {len(activas)} tareas.")


def _progreso_telegram(texto):
    avisar_celular("⏳ " + texto, "Cerebro trabajando")


def _entregar(titulo, instruccion, resultado, error, acciones):
    """Manda el resultado al celular: corto en el mensaje, largo como archivo, y los archivos que pidió Claude."""
    archivos = [Path(x.strip().strip('"').strip("'")) for x in re.findall(r"ENVIAR_ARCHIVO:\s*(.+)", resultado)]
    limpio = re.sub(r"(?m)^.*ENVIAR_ARCHIVO:.*$", "", resultado).strip() or "Listo."
    path = guardar_resultado(titulo + ": " + instruccion, limpio)
    cabeza = ("No pude terminar" if error else "Listo") + ": " + instruccion[:80] + f" ({acciones} pasos)"
    if len(limpio) > 3300:
        avisar_celular(cabeza + nl2() + limpio[:1500] + nl2() + "Te mando el informe completo en un archivo.")
        _telegram_documento(path, cabeza[:900])
    else:
        avisar_celular(cabeza + nl2() + limpio)
    for archivo in archivos[:5]:
        if archivo.exists() and archivo.is_file() and archivo.stat().st_size < 49 * 1024 * 1024:
            _telegram_documento(archivo, archivo.name)
        else:
            avisar_celular("No pude mandarte " + str(archivo) + " (no existe o pesa más de 50 MB).")


def guardar_resultado(titulo, contenido):
    carpeta = VAULT / "Tareas"
    carpeta.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", norm(titulo))[:50].strip("-") or "tarea"
    path = carpeta / f"{datetime.now():%Y-%m-%d_%H%M%S}_{slug}.md"
    path.write_text("# " + titulo + nl2() + "_" + ahora() + "_" + nl2() + str(contenido) + chr(10), encoding="utf-8")
    return path


def hilo_consulta(instruccion):
    """Consulta sin tocar nada: leer, investigar en internet, resumir."""
    try:
        resultado, error, acciones = correr_claude(
            "Investigá o respondé esto sin modificar nada en la PC (podés leer archivos y buscar en internet). "
            "Contestá en español, claro y ordenado. Pedido: " + instruccion,
            etiqueta="consulta", progreso=_progreso_telegram, descripcion=instruccion)
        _entregar("Consulta", instruccion, resultado, error, acciones)
    except Exception as e:
        log.exception("consulta falló")
        avisar_celular("La consulta falló: " + instruccion[:80] + chr(10) + str(e)[:300])


def hilo_plan(instruccion):
    """Tareas que cambian cosas: primero un plan que el usuario aprueba."""
    try:
        plan, error, _ = correr_claude(
            "NO modifiques nada todavía. Analizá lo necesario y devolvé solo un plan numerado y concreto "
            "(máximo 10 pasos, con las rutas exactas) para esta tarea:" + chr(10) + instruccion,
            etiqueta="plan", progreso=_progreso_telegram, descripcion="Plan: " + instruccion)
        if error or not plan:
            avisar_celular("No pude preparar el plan para: " + instruccion[:80] + chr(10) + plan[:1500])
            return
        estado = cargar_estado()
        estado["plan_pendiente"] = {"instruccion": instruccion, "plan": plan, "ts": int(time.time())}
        guardar_estado(estado)
        avisar_celular("Plan listo para aprobar: " + instruccion[:80] + nl2() + plan[:2800] + nl2() +
                       "Para ejecutarlo respondé: sí   (o: no, para descartarlo)." + chr(10) +
                       "También podés decirle a Alexa: confirmá la tarea.", titulo="Cerebro: plan para aprobar")
    except Exception as e:
        log.exception("plan falló")
        avisar_celular("No pude preparar el plan: " + instruccion[:80] + chr(10) + str(e)[:300])


def hilo_ejecutar(pendiente):
    instruccion, plan = pendiente["instruccion"], pendiente["plan"]
    try:
        resultado, error, acciones = correr_claude(
            "Ejecutá exactamente este plan aprobado por el usuario, sin agregar pasos. Si algo no coincide con lo "
            "esperado, detenete y explicá." + nl2() + "Tarea: " + instruccion + nl2() + "Plan:" + chr(10) + plan,
            permisos_totales=True, etiqueta="tarea", progreso=_progreso_telegram, descripcion=instruccion)
        _entregar("Ejecutado", instruccion, resultado, error, acciones)
    except Exception as e:
        log.exception("ejecución falló")
        avisar_celular("La ejecución falló: " + instruccion[:80] + chr(10) + str(e)[:300])


# ---------- pantalla, archivos, programas y apagado desde el celular ----------

def accion_captura(d):
    """Saca una foto de la pantalla de la PC y la manda al celular."""
    try:
        import pyautogui
        carpeta = BASE / "capturas"
        carpeta.mkdir(exist_ok=True)
        ruta = carpeta / f"pantalla_{datetime.now():%H%M%S}.png"
        pyautogui.screenshot().save(ruta)
    except Exception as e:
        return False, "No pude sacar la captura: " + str(e)[:120]
    if _telegram_foto(ruta, "Pantalla de la PC, " + datetime.now().strftime("%H:%M")):
        return True, "Te mandé la captura al celular."
    return False, "Saqué la captura pero no pude mandarla por Telegram."


def _buscar_archivo(nombre, carpetas=None):
    """Busca un archivo por nombre en Escritorio, Documentos, Descargas y notas. El más reciente primero."""
    objetivo = norm(nombre)
    palabras = [p for p in re.split(r"[\s._-]+", objetivo)
                if len(p) > 2 and p not in ("archivo", "del", "las", "los", "que", "tengo", "pdf")] or [objetivo]
    extension = re.search(r"\b(pdf|xlsx?|docx?|pptx?|csv|txt|jpg|png|mp3|mp4|zip)\b", objetivo)
    carpetas = carpetas or [Path.home() / "Desktop", Path.home() / "OneDrive" / "Desktop", Path.home() / "Documents",
                            Path.home() / "OneDrive" / "Documentos", Path.home() / "Downloads", VAULT]
    candidatos, vistos = [], 0
    for c in carpetas:
        if not c.exists():
            continue
        for f in c.rglob("*"):
            vistos += 1
            if vistos > 30000:
                break
            if any(parte.startswith(".") or parte in ("node_modules", "AppData", "__pycache__")
                   for parte in f.relative_to(c).parts):
                continue
            if not f.is_file():
                continue
            n = norm(f.name)
            puntos = sum(1 for p in palabras if p in n) + (1 if extension and n.endswith("." + extension.group(1)) else 0)
            if puntos:
                candidatos.append((puntos, f.stat().st_mtime, f))
    candidatos.sort(key=lambda x: (-x[0], -x[1]))
    return [f for _, _, f in candidatos[:5]]


def accion_enviar_archivo(d):
    nombre = str(d.get("nombre") or d.get("archivo") or d.get("ruta") or "").strip()
    if not nombre:
        return False, "¿Qué archivo querés que te mande?"
    directo = Path(nombre.strip('"'))
    encontrados = [directo] if directo.is_file() else _buscar_archivo(nombre)
    if not encontrados:
        return False, f"No encontré ningún archivo parecido a {nombre} en el Escritorio, Documentos ni Descargas."
    elegido = encontrados[0]
    if elegido.stat().st_size >= 49 * 1024 * 1024:
        return False, f"{elegido.name} pesa más de 50 MB y Telegram no lo deja mandar."
    if not _telegram_documento(elegido, elegido.name):
        return False, "Encontré " + elegido.name + " pero no pude mandarlo por Telegram."
    otros = [f.name for f in encontrados[1:4]]
    return True, "Te mandé " + elegido.name + "." + (" También encontré: " + ", ".join(otros) + "." if otros else "")


def accion_cerrar_app(d):
    """Cierra las ventanas de un programa (como tocar la X: no fuerza nada)."""
    nombre = norm(d.get("nombre"))
    if not nombre:
        return False, "¿Qué programa querés que cierre?"
    try:
        import pygetwindow
    except ImportError:
        return False, "Falta un componente: ejecutá instalar-extras.bat en la PC."
    cerradas = []
    for w in pygetwindow.getAllWindows():
        titulo = (w.title or "").strip()
        if titulo and nombre in norm(titulo):
            try:
                w.close()
                cerradas.append(titulo)
            except Exception:
                pass
    if not cerradas:
        return False, f"No encontré ninguna ventana de {d.get('nombre')} abierta."
    return True, "Cerré " + (cerradas[0][:60] if len(cerradas) == 1 else f"{len(cerradas)} ventanas de {d.get('nombre')}") + "."


def accion_sistema_remoto(d):
    """Desde el celular: bloquear es directo; apagar, reiniciar o suspender piden un 'sí'."""
    orden = norm(d.get("orden"))
    if orden in ("apagar", "reiniciar", "suspender"):
        estado = cargar_estado()
        estado["sistema_pendiente"] = {"orden": orden, "ts": int(time.time())}
        guardar_estado(estado)
        ojo = " Ojo: apagada no la vas a poder prender desde acá." if orden in ("apagar", "suspender") else ""
        return True, f"¿Seguro que querés {orden} la PC?{ojo} Respondé: sí"
    return accion_sistema(d)


def _telegram_subir(metodo, campo_archivo, ruta, texto="", tipo="application/octet-stream"):
    """Sube un archivo al Telegram del usuario (foto o documento)."""
    token = str(CONFIG.get("telegram_token") or "").strip()
    cid = _telegram_chat_id()
    ruta = Path(ruta)
    if not token or not cid or not ruta.exists():
        return False
    limite = "----cerebro" + os.urandom(8).hex()
    salto = chr(13) + chr(10)

    def campo(nombre, valor):
        return (f"--{limite}{salto}Content-Disposition: form-data; name=\"{nombre}\""
                f"{salto}{salto}{valor}{salto}").encode()

    cuerpo = campo("chat_id", cid) + campo("caption", texto[:900])
    cuerpo += (f"--{limite}{salto}Content-Disposition: form-data; name=\"{campo_archivo}\"; "
               f"filename=\"{ruta.name}\"{salto}Content-Type: {tipo}{salto}{salto}").encode()
    cuerpo += ruta.read_bytes() + f"{salto}--{limite}--{salto}".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{metodo}", data=cuerpo,
                                 headers={"content-type": f"multipart/form-data; boundary={limite}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return bool(json.load(r).get("ok"))
    except Exception:
        log.exception("no pude mandar %s", ruta.name)
        return False


def _telegram_documento(ruta, texto=""):
    return _telegram_subir("sendDocument", "document", ruta, texto)


def _descargar_de_telegram(msg, carpeta=None):
    """Guarda en la PC la foto, archivo o audio que le mandaste al bot. Devuelve la ruta."""
    token = str(CONFIG.get("telegram_token") or "").strip()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    if msg.get("document"):
        x, nombre = msg["document"], msg["document"].get("file_name") or f"archivo_{sello}"
    elif msg.get("photo"):
        x, nombre = msg["photo"][-1], f"foto_{sello}.jpg"
    elif msg.get("voice"):
        x, nombre = msg["voice"], f"audio_{sello}.ogg"
    elif msg.get("audio"):
        x, nombre = msg["audio"], msg["audio"].get("file_name") or f"audio_{sello}.mp3"
    elif msg.get("video"):
        x, nombre = msg["video"], msg["video"].get("file_name") or f"video_{sello}.mp4"
    else:
        return None
    info = (_telegram("getFile", {"file_id": x["file_id"]}, timeout=20) or {}).get("result") or {}
    if not info.get("file_path"):
        raise RuntimeError("Telegram no me dio el archivo (el límite para bots es 20 MB)")
    carpeta = carpeta or (Path.home() / "Downloads" / "Cerebro")
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = re.sub(r'[\\/:*?"<>|]', "_", nombre)
    destino = carpeta / nombre
    if destino.exists():
        destino = carpeta / f"{destino.stem}_{sello}{destino.suffix}"
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{token}/{info['file_path']}", timeout=120) as r:
        destino.write_bytes(r.read())
    registrar("telegram", "archivo recibido: " + str(destino))
    return destino


def transcribir_audio(ruta):
    """Pasa a texto una nota de voz (IA gratis de Google). Devuelve el texto o None."""
    import base64
    clave = _clave_gemini()
    if not clave:
        return None
    ruta = Path(ruta)
    tipo = {".ogg": "audio/ogg", ".oga": "audio/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav",
            ".m4a": "audio/mp4"}.get(ruta.suffix.lower(), "audio/ogg")
    cuerpo = {"contents": [{"role": "user", "parts": [
        {"inline_data": {"mime_type": tipo, "data": base64.b64encode(ruta.read_bytes()).decode()}},
        {"text": "Transcribí exactamente lo que dice este audio, en español rioplatense. Devolvé solo el texto."}]}],
        "generationConfig": {"maxOutputTokens": 500, "temperature": 0}}
    texto = _carrera(lambda m: cuerpo, clave, 20, None, TANDAS_IMAGEN)
    return texto.strip().strip('"') if texto else None


SI_TELEGRAM = ("si", "dale", "ok", "confirmo", "hacelo", "si, hacelo", "si hacelo", "ejecutalo", "ejecuta",
               "aprobado", "apruebo", "si, ejecutalo", "de una", "mandale")
NO_TELEGRAM = ("no", "cancela", "cancelalo", "dejalo", "no, dejalo", "mejor no", "descartalo")


VENCIMIENTOS = {"sistema_pendiente": 300, "whatsapp_pendiente": 600, "plan_pendiente": PLAN_TTL}


def _pendientes_vigentes(estado):
    """Lo que está esperando un 'sí', del más reciente al más viejo. Lo vencido se borra del estado."""
    vigentes = []
    for clave, ttl in VENCIMIENTOS.items():
        p = estado.get(clave)
        if not p:
            continue
        if time.time() - float(p.get("ts", 0)) > ttl:
            estado.pop(clave, None)
            continue
        vigentes.append((float(p.get("ts", 0)), clave, p))
    vigentes.sort(reverse=True)
    return vigentes


def _confirmaciones_telegram(t):
    """'sí' / 'no' para lo que quedó esperando: apagar la PC, un plan de tarea o un WhatsApp.

    Si hay más de una cosa esperando, el 'sí' va para la última pregunta que se hizo (la más reciente).
    """
    t = t.strip(" .!")
    estado = cargar_estado()
    vigentes = _pendientes_vigentes(estado)
    if not vigentes:
        guardar_estado(estado)                         # lo vencido ya no molesta
        return None
    if t in NO_TELEGRAM:
        for _, clave, _p in vigentes:
            estado.pop(clave, None)
        guardar_estado(estado)
        return "Listo, lo descarté."
    if t in SI_TELEGRAM or t in ("mandalo", "envialo", "enviar", "si, mandalo", "si mandalo", "corregilo"):
        _, clave, p = vigentes[0]
        if clave == "sistema_pendiente":
            estado.pop("sistema_pendiente", None)
            guardar_estado(estado)
            return accion_sistema({"orden": p["orden"]})[1] or "Hecho."
        if clave == "whatsapp_pendiente":
            return accion_whatsapp_confirmar({})[1]
        return accion_confirmar_tarea({})[1]
    return None


def panel_url():
    """Dirección del panel web local con su token (pc/panel.py), para abrirlo desde Telegram."""
    try:
        return _mod("panel").url_para_telegram()
    except Exception as e:
        return "No pude armar la dirección del panel: " + str(e)[:120]


def _atajos_telegram(t):
    """Pedidos de la PC que no necesitan IA."""
    t = t.strip(" .!?¿¡")
    if t in ("panel", "el panel", "abri el panel", "abrir el panel", "abrime el panel", "url del panel",
             "link del panel", "direccion del panel", "panel web"):
        return panel_url()
    if t in ("pantalla", "captura", "mandame la pantalla", "mandame una captura", "captura de pantalla",
             "que hay en la pantalla", "sacale foto a la pantalla", "mostrame la pantalla", "que se ve en la pantalla"):
        return accion_captura({})[1]
    if t in ("que mensajes tengo", "mensajes nuevos", "whatsapp", "novedades de whatsapp", "que hay en whatsapp",
             "tengo mensajes", "resumime whatsapp", "mensajes sin leer", "que me escribieron"):
        return accion_whatsapp_resumen({})[1]
    if t in ("que estas haciendo", "estado de la tarea", "como va la tarea", "tareas", "como vas", "en que andas",
             "que tareas hay", "como va eso"):
        return accion_tareas_estado({})[1]
    if t.startswith(("cancela la tarea", "para la tarea", "frena la tarea", "cancela todo", "para todo", "frena todo",
                     "cancelala", "frenala")):
        return accion_cancelar_tarea({})[1]
    m = re.match(r"(mandame|pasame|enviame)\s+(el |la |los |las )?(archivo |documento |pdf |excel )?(.+)$", t)
    if m and re.search(r"\b(archivo|documento|pdf|excel|word|planilla|foto|\.\w{2,4})\b", t):
        return accion_enviar_archivo({"nombre": (m.group(3) or "") + m.group(4)})[1]
    m = re.match(r"(cerra|cerrame|cerrar)\s+(el |la )?(.+)$", t)
    if m and len(m.group(3).split()) <= 3:
        return accion_cerrar_app({"nombre": m.group(3)})[1]
    if t in ("bloquea la pc", "bloquea la compu", "bloquear la pc"):
        return accion_sistema({"orden": "bloquear"})[1] or "Listo, la bloqueé."
    m = re.match(r"(apaga|apagame|apagala|reinicia|reiniciame|reiniciala|suspende|suspendela)\s+(la\s+)?"
                 r"(pc|compu|computadora|maquina)$", t)
    if m:
        orden = "apagar" if m.group(1).startswith("apaga") else "reiniciar" if m.group(1).startswith("reinicia") else "suspender"
        return accion_sistema_remoto({"orden": orden})[1]
    return None


def _guia_pantalla():
    ayudante = str(BASE / "escritorio.py")
    return (
        "TAREA DE PANTALLA: manejás esta PC como una persona, con mouse y teclado. Sirve para cualquier "
        "programa o sitio: navegador, Instagram, Facebook, Gmail, Excel, Spotify, lo que sea." + chr(10) +
        'Ayudante: python "' + ayudante + '" <comando>' + chr(10) +
        "Comandos: captura | clic X Y | doble-clic X Y | derecho X Y | escribir \"texto\" | tecla enter | "
        "atajo ctrl v | scroll -5 | abrir \"nombre de app\" | esperar 2 | ventanas | foco \"titulo\"" + chr(10) +
        "MÉTODO: sacá una captura, LEELA con la herramienta Read, decidí dónde hacer clic según esa imagen, "
        "actuá, y volvé a sacar otra captura para verificar. Nunca supongas dónde está algo sin mirar." + chr(10) +
        "Si algo tarda, esperá unos segundos y sacá otra captura: puede estar cargando." + chr(10) +
        "Las sesiones del usuario ya están iniciadas en sus apps y navegador: usalas." + chr(10) +
        "PROHIBIDO: escribir contraseñas, crear cuentas, comprar o pagar. Si una app pide iniciar sesión, "
        "detenete y explicá que hace falta que el usuario lo haga." + chr(10) +
        "ANTES DE PUBLICAR O ENVIAR algo que vean otras personas (un posteo, un comentario, un mensaje, un mail): "
        "dejá todo escrito y listo, sacá una captura, y TERMINÁ SIN ENVIAR. Explicá en tu respuesta que quedó "
        "listo para confirmar. El usuario lo aprueba por voz y recién ahí se envía."
    )


def _ultima_captura():
    carpeta = BASE / "capturas"
    fotos = sorted(carpeta.glob("*.png"), key=lambda f: f.stat().st_mtime) if carpeta.exists() else []
    return fotos[-1] if fotos else None


def hilo_pantalla(instruccion):
    try:
        resultado, error, acciones = correr_claude(_guia_pantalla() + nl2() + "Tarea: " + instruccion,
                                                   permisos_totales=True, etiqueta="pantalla",
                                                   progreso=_progreso_telegram, descripcion="Pantalla: " + instruccion)
        guardar_resultado("Pantalla: " + instruccion, resultado)
        estado = "no pudo terminar" if error else "terminó"
        aviso = ("La tarea de pantalla " + estado + " (" + str(acciones) + " acciones): "
                 + instruccion[:80] + nl2() + resultado[:2500])
        foto = _ultima_captura()
        if not (foto and _telegram_foto(foto, aviso[:900])):
            avisar_celular(aviso)
    except Exception as e:
        log.exception("tarea de pantalla falló")
        avisar_celular("La tarea de pantalla falló: " + instruccion[:80] + chr(10) + str(e))


def nl2():
    return chr(10) + chr(10)


def accion_pantalla_confirmar(d):
    """El usuario aprobó por voz lo que quedó listo en pantalla: ahora sí se envía."""
    threading.Thread(target=hilo_pantalla, args=(
        "El usuario YA APROBÓ el envío. Mirá la pantalla con una captura: hay algo escrito y listo para "
        "publicar o enviar. Hacé clic en el botón de enviar o publicar, verificá con otra captura que se "
        "haya enviado, y contá qué pasó.",), daemon=True).start()
    return True, "Confirmado. Lo envío y te mando la foto al celular."


def accion_tarea(d):
    instruccion = str(d.get("instruccion") or "").strip()
    if not instruccion:
        return False, "¿Qué tarea quieres que haga?"
    if not _buscar_claude():
        return False, "No encontré Claude Code instalado en tu PC. Instálalo y volvé a pedirlo."
    if norm(d.get("modo")) == "pantalla":
        threading.Thread(target=hilo_pantalla, args=(instruccion,), daemon=True).start()
        return True, "Voy a manejar la pantalla de tu PC. Te aviso al celular cuando termine."
    if norm(d.get("modo")) == "cambios":
        threading.Thread(target=hilo_plan, args=(instruccion,), daemon=True).start()
        return True, "Tu PC está preparando un plan. Te lo mando al celular para que lo apruebes."
    threading.Thread(target=hilo_consulta, args=(instruccion,), daemon=True).start()
    return True, "Tu PC ya está trabajando en eso. Te aviso al celular cuando termine."


def accion_confirmar_tarea(d):
    estado = cargar_estado()
    pendiente = estado.get("plan_pendiente")
    if not pendiente or time.time() - pendiente.get("ts", 0) > PLAN_TTL:
        return False, "No hay ningún plan esperando tu aprobación."
    estado.pop("plan_pendiente", None)
    guardar_estado(estado)
    threading.Thread(target=hilo_ejecutar, args=(pendiente,), daemon=True).start()
    return True, "Ejecutando el plan aprobado. Te aviso al celular cuando termine."


# ---------- avisos que se repiten, rutinas y lista de compras ----------

PROG_LOCK = threading.Lock()
DIAS_SEMANA = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
               "MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
NOMBRES_DIA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
VENTANA_DEFECTO = ("08:00", "23:00")     # los avisos "cada X tiempo" no suenan de madrugada


def _programados():
    try:
        return json.loads((BASE / "programados.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _guardar_programados(lista):
    _escribir_json(BASE / "programados.json", lista)


def _hm(valor, defecto):
    m = re.match(r"(\d{1,2})(?:[:.](\d{2}))?", str(valor or defecto).strip())
    if not m:
        m = re.match(r"(\d{1,2})(?:[:.](\d{2}))?", defecto)
    return min(23, int(m.group(1))), min(59, int(m.group(2) or 0))


def _dias(valor):
    if isinstance(valor, str):
        valor = re.split(r"[,\s]+", valor)
    salida = []
    for d in valor or []:
        crudo = str(d).strip()
        plano = re.sub(r"^(los|el)\s+", "", norm(crudo))
        n = DIAS_SEMANA.get(crudo) if crudo in DIAS_SEMANA else DIAS_SEMANA.get(plano, DIAS_SEMANA.get(plano.rstrip("s")))
        if n is not None and n not in salida:
            salida.append(n)
    return sorted(salida)


def _proximo(p, desde_ts=None):
    """Próxima vez que tiene que sonar este aviso (timestamp)."""
    from datetime import timedelta
    base = datetime.fromtimestamp(desde_ts or time.time())
    if p.get("cada_minutos"):
        h1, m1 = _hm(p.get("desde"), VENTANA_DEFECTO[0])
        h2, m2 = _hm(p.get("hasta"), VENTANA_DEFECTO[1])
        n = base + timedelta(minutes=int(p["cada_minutos"]))
        inicio = n.replace(hour=h1, minute=m1, second=0, microsecond=0)
        fin = n.replace(hour=h2, minute=m2, second=0, microsecond=0)
        if n < inicio:
            n = inicio
        elif n > fin:
            n = inicio + timedelta(days=1)
        return n.timestamp()
    h, m = _hm(p.get("hora"), "09:00")
    dias = p.get("dias_n") or list(range(7))
    for extra in range(0, 8):
        n = (base + timedelta(days=extra)).replace(hour=h, minute=m, second=0, microsecond=0)
        if n > base and n.weekday() in dias:
            return n.timestamp()
    return (base + timedelta(days=1)).timestamp()


def _cuando(p):
    """Texto de cuándo suena, para contarlo."""
    if p.get("una_vez"):
        return "el " + datetime.fromtimestamp(p["proximo"]).strftime("%d/%m a las %H:%M")
    if p.get("cada_minutos"):
        mins = int(p["cada_minutos"])
        cada = (f"cada {mins // 60} horas" if mins % 60 == 0 and mins > 60 else
                "cada una hora" if mins == 60 else f"cada {mins} minutos")
        return cada + " de " + str(p.get("desde") or VENTANA_DEFECTO[0]) + " a " + str(p.get("hasta") or VENTANA_DEFECTO[1])
    h, m = _hm(p.get("hora"), "09:00")
    dias = p.get("dias_n") or list(range(7))
    quien = ("todos los días" if len(dias) == 7 else "de lunes a viernes" if dias == [0, 1, 2, 3, 4] else
             "los " + ", ".join(NOMBRES_DIA[d] for d in dias))
    return f"{quien} a las {h}:{m:02d}"


def _texto_de_accion(accion, datos):
    """'casa' + {"dispositivo": "luz living", "accion": "prender"} -> 'casa: prender luz living' (para mostrarlo)."""
    def plano(k, v):
        if v is True:
            return k
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v)
    vacio = (None, "", [], {}, False)
    primero = ("accion", "orden", "cambio", "modo")
    partes = [plano(k, datos[k]) for k in primero if datos.get(k) not in vacio]
    partes += [plano(k, v) for k, v in datos.items() if k not in primero and v not in vacio]
    return (accion + ": " + " ".join(partes)).strip(": ")[:150]


def accion_programar(d):
    """Aviso al celular o rutina que se repite. Datos: texto, tipo (aviso|orden), cada_minutos, cada_horas,
    hora, dias, desde, hasta, en_minutos, frecuencia. Una rutina también puede traer "accion" + "datos" (una
    acción exacta de ACCIONES, como las programa el panel) en vez de texto libre."""
    texto = str(d.get("texto") or "").strip()
    accion = str(d.get("accion") or "").strip()
    datos = d.get("datos") if isinstance(d.get("datos"), dict) else {}
    if accion and accion not in ACCIONES:
        return False, f"No conozco la acción {accion}."
    if accion and not texto:
        texto = _texto_de_accion(accion, datos)
    if not texto:
        return False, "¿Qué querés que te avise o que haga?"
    p = {"id": os.urandom(3).hex(), "texto": texto,
         "tipo": "orden" if (d.get("tipo") == "orden" or accion) else "aviso", "creado": ahora()}
    if accion:
        p["accion"], p["datos"] = accion, datos
    for k in ("hora", "desde", "hasta"):
        if d.get(k):
            p[k] = str(d[k])
    if d.get("dias"):
        p["dias_n"] = _dias(d["dias"])
    try:
        cada = float(d.get("cada_minutos") or 0) or float(d.get("cada_horas") or 0) * 60
    except (TypeError, ValueError):
        cada = 0
    if cada:
        p["cada_minutos"] = max(1, int(cada))
    frecuencia = norm(d.get("frecuencia"))
    if d.get("en_minutos") and not cada and not d.get("hora"):
        p["una_vez"] = True
        p["proximo"] = time.time() + float(d["en_minutos"]) * 60
    else:
        if "una" in frecuencia:
            p["una_vez"] = True
        desde = None
        if d.get("manana"):                      # "mañana a las 8": que no suene hoy
            desde = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 86399
        p["proximo"] = _proximo(p, desde)
    with PROG_LOCK:
        lista = _programados()
        lista.append(p)
        _guardar_programados(lista)
    registrar("programar", json.dumps(p, ensure_ascii=False)[:250])
    if p["tipo"] == "orden":
        return True, f"Listo, {_cuando(p)} voy a hacer esto: {texto}."
    return True, f"Listo, te aviso al celular {_cuando(p)}: {texto}."


def accion_programados(d):
    lista = _programados()
    if not lista:
        return True, "No tenés avisos ni rutinas programadas."
    return True, "Tenés esto programado: " + "; ".join(
        f"{p['texto']}, {_cuando(p)}" for p in lista[:10]) + "."


def accion_borrar_programado(d):
    objetivo = norm(d.get("texto"))
    if not objetivo:
        return False, "¿Qué aviso querés borrar?"
    with PROG_LOCK:
        lista = _programados()
        quedan = [] if objetivo in ("todos", "todo", "todos los avisos") else [
            p for p in lista if objetivo not in norm(p["texto"])]
        _guardar_programados(quedan)
    borrados = len(lista) - len(quedan)
    if not borrados:
        return False, "No encontré ningún aviso con eso."
    return True, f"Listo, borré {borrados} aviso{'s' if borrados > 1 else ''}."


def ejecutar_programado(p):
    """Dispara ya un aviso o una rutina (lo usa el programador cuando vence, y el panel con "ejecutar ahora")."""
    if p.get("accion") in ACCIONES:                    # acción exacta, con sus datos (programada desde el panel)
        try:
            r = ACCIONES[p["accion"]](p.get("datos") or {})[1] or "Listo."
        except Exception as e:
            log.exception("rutina %s", p["accion"])
            r = "Falló: " + str(e)[:150]
    elif p.get("tipo") == "orden":
        r = _orden_telegram(p["texto"], 1)
    else:
        avisar_celular("⏰ " + p["texto"])
        return "Aviso mandado al celular."
    registrar("rutina", p["texto"] + " -> " + str(r)[:150])
    avisar_celular("Rutina: " + p["texto"] + chr(10) + str(r)[:300])
    return str(r)


def revisar_programados(ahora_ts=None):
    """Una vuelta del programador: lo vencido se dispara y se recalcula su próximo. Devuelve lo disparado."""
    ahora_ts = ahora_ts or time.time()
    vencidos = []
    with PROG_LOCK:
        lista = _programados()
        cambio = False
        for p in list(lista):
            if p.get("proximo", 0) <= ahora_ts:
                vencidos.append(dict(p))
                cambio = True
                if p.get("una_vez"):
                    lista.remove(p)
                else:
                    p["proximo"] = _proximo(p, ahora_ts)   # si la PC estuvo apagada, no los acumula
        if cambio:
            _guardar_programados(lista)
    disparados = []
    for p in vencidos:
        atraso = ahora_ts - p.get("proximo", ahora_ts)
        if atraso > 3600 and not p.get("una_vez"):
            continue                                          # uno viejo que se perdió: sigue el próximo
        if p.get("una_vez") and (p.get("tipo") == "orden" or p.get("accion")) and atraso > 900:
            # "apagá la PC a las 23" no se ejecuta a las 9 de la mañana porque la PC estaba apagada a las 23
            avisar_celular("No hice esto porque la PC estaba apagada a esa hora: " + p["texto"])
            registrar("rutina", "omitida por atraso (" + str(int(atraso // 60)) + " min): " + p["texto"])
            continue
        ejecutar_programado(p)
        disparados.append(p)
    return disparados


def hilo_programador():
    """Revisa cada 15 segundos si toca algún aviso o rutina."""
    while True:
        try:
            revisar_programados()
        except Exception:
            log.exception("programador")
        time.sleep(15)


def _patron(expresion):
    """Hace que una expresión regular acepte vocales con o sin tilde."""
    for vocal, clase in (("a", "[aá]"), ("e", "[eé]"), ("i", "[ií]"), ("o", "[oó]"), ("u", "[uúü]")):
        expresion = expresion.replace(vocal, clase)
    return expresion


NUMEROS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "diez": 10,
           "quince": 15, "veinte": 20, "treinta": 30, "cuarenta": 40, "media": 0.5}


def _programa_desde_texto(texto):
    """'recordame cada 2 horas tomar agua', 'todos los días a las 7 prendé la luz' -> datos para programar."""
    t = norm(texto)
    if not t.startswith(("recorda", "avisa", "cada ", "todos los", "todas las", "los lunes", "los martes",
                         "los miercoles", "los jueves", "los viernes", "los sabados", "los domingos",
                         "de lunes a", "manana a las", "hoy a las", "a las ", "en ")):
        return None
    datos, resto = {}, texto
    num = r"(\d+(?:[.,]\d+)?|un|una|uno|dos|tres|cuatro|cinco|seis|diez|quince|veinte|treinta|cuarenta|media)"

    def valor(s):
        return NUMEROS.get(s, None) or float(str(s).replace(",", "."))

    m = re.search(_patron(r"\bcada\s+" + num + r"?\s*(minutos?|min|horas?|hs)\b"), resto, re.I)
    if m:
        n = valor(norm(m.group(1))) if m.group(1) else 1
        datos["cada_minutos"] = n * 60 if norm(m.group(2)).startswith("h") else n
        resto = resto[:m.start()] + resto[m.end():]
    m = re.search(_patron(r"\ben\s+" + num + r"\s*(minutos?|min|horas?)\b"), resto, re.I)
    if m and not datos:
        n = valor(norm(m.group(1)))
        datos["en_minutos"] = n * 60 if norm(m.group(2)).startswith("h") else n
        resto = resto[:m.start()] + resto[m.end():]
    m = re.search(_patron(r"\ba\s+las?\s+(\d{1,2})(?:[:.](\d{2}))?(\s*(?:hs|horas))?"
                          r"(\s+de\s+la\s+(tarde|noche|manana|madrugada))?"), resto, re.I)
    if m:
        h = int(m.group(1))
        if m.group(5) and norm(m.group(5)) in ("tarde", "noche") and h < 12:
            h += 12
        if m.group(5) and norm(m.group(5)) in ("noche", "madrugada") and h == 12:
            h = 0
        datos["hora"] = f"{h}:{m.group(2) or '00'}"
        resto = resto[:m.start()] + resto[m.end():]
    tn = norm(resto)
    if "de lunes a viernes" in tn:
        datos["dias"] = ["lunes", "martes", "miercoles", "jueves", "viernes"]
    else:
        dias = [d for d in ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo") if d in tn]
        if dias:
            datos["dias"] = dias
            if re.search(r"\bel\s+(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", tn):
                datos["frecuencia"] = "una_vez"      # "el lunes" es una vez; "los lunes", todas las semanas
    if datos.get("hora") and not datos.get("dias") and not re.search(r"todos los dias|cada dia|todas las", tn):
        datos["frecuencia"] = "una_vez"          # "mañana a las 8" / "a las 17": una sola vez
    if not any(k in datos for k in ("cada_minutos", "en_minutos", "hora")):
        return None
    dia_re = r"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bados?|domingos?)"
    for basura in (r"\b(todos|todas)\s+(los|las)\s+(dias|días|mañanas|mananas|tardes|noches)\b",
                   r"\bde\s+lunes\s+a\s+viernes\b",
                   r"(?:\b(?:los|el)\s+)?\b" + dia_re + r"(?:\s*(?:,|y)\s*" + dia_re + r")*\b",
                   r"^\s*(ma[nñ]ana|hoy)\b"):
        resto = re.sub(basura, " ", resto, flags=re.I)
    resto = re.sub(_patron(r"^\s*(recordame|recordarme|recorda|avisame|avisarme|avisa)\b"), " ", resto, flags=re.I)
    resto = re.sub(r"^\s*(ma[nñ]ana|hoy)\b", " ", resto, flags=re.I)
    resto = re.sub(r"\s+", " ", resto).strip(" ,.:")
    resto = re.sub(r"^(que|de|a)\s+", "", resto, flags=re.I).strip()
    if not resto:
        return None
    datos["texto"] = resto
    verbos = ("prende", "apaga", "pone", "poner", "modo ", "escena", "anota", "abri", "subi", "baja",
              "whatsapp", "mandale", "luz")
    es_orden = norm(resto).startswith(verbos) or bool(_buscar_aprendido(resto))
    datos["tipo"] = "orden" if es_orden and not t.startswith(("recorda", "avisa")) else "aviso"
    if datos.get("frecuencia") == "una_vez" and re.search(r"\bmanana\b", t):
        datos["manana"] = True
    return datos


def accion_compras(d):
    """Lista de compras en Compras.md: agregar, quitar, vaciar o leer."""
    archivo = VAULT / "Compras.md"
    try:
        items = [l[2:].strip() for l in archivo.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    except OSError:
        items = []

    def lista(v):
        if isinstance(v, str):
            v = re.split(r",| y ", v)
        return [str(x).strip(" .") for x in (v or []) if str(x).strip(" .")]

    agregar, quitar = lista(d.get("agregar")), lista(d.get("quitar"))
    if d.get("vaciar"):
        items = []
    for x in agregar:
        if norm(x) not in [norm(i) for i in items]:
            items.append(x)
    for x in quitar:
        items = [i for i in items if norm(x) not in norm(i)]
    VAULT.mkdir(parents=True, exist_ok=True)
    archivo.write_text("# Lista de compras" + chr(10) + chr(10) + "".join("- " + i + chr(10) for i in items),
                       encoding="utf-8")
    if d.get("al_celular"):
        avisar_celular("🛒 Lista de compras:" + chr(10) + (chr(10).join("• " + i for i in items) or "(vacía)"))
    if agregar:
        return True, "Agregué " + ", ".join(agregar) + " a la lista de compras."
    if quitar:
        return True, "Saqué " + ", ".join(quitar) + " de la lista."
    if d.get("vaciar"):
        return True, "Vacié la lista de compras."
    if not items:
        return True, "La lista de compras está vacía."
    return True, "En la lista de compras tenés: " + ", ".join(items) + "."


def _info():
    import importlib
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    return importlib.import_module("info")


def accion_clima(d):
    return True, _info().clima(d.get("ciudad"), d.get("dia", 0))


def accion_dolar(d):
    return True, _info().dolar()


def accion_noticias(d):
    return True, _info().noticias(d.get("tema") or "", con_links=bool(d.get("con_links")))


# ---------- avisos solos: dólar y lluvia ----------

UMBRAL_DOLAR = 2.0            # % de movimiento del blue para avisar
NOMBRES_ALERTA = {"dolar": "del dólar", "lluvia": "de lluvia", "pc": "de la PC", "mails": "de mails importantes",
                  "agenda": "de la agenda"}
SINONIMOS_ALERTA = {"compu": "pc", "computadora": "pc", "disco": "pc", "internet": "pc", "mail": "mails",
                    "correo": "mails", "gmail": "mails", "calendario": "agenda", "evento": "agenda", "reunion": "agenda"}


def _alertas():
    return {**{k: True for k in NOMBRES_ALERTA}, **(cargar_estado().get("alertas") or {})}


def accion_alertas(d):
    """Prender, apagar o consultar las alertas automáticas."""
    tipo = norm(d.get("tipo") or "todas")
    for palabra, clave in SINONIMOS_ALERTA.items():
        tipo = re.sub(r"\b" + palabra + r"s?\b", clave, tipo)
    activar = d.get("activar")
    if isinstance(activar, str):
        activar = None if not activar.strip() else norm(activar) in ("true", "si", "activar", "prender", "on", "1")
    estado = cargar_estado()
    alertas = {k: v for k, v in _alertas().items() if k in NOMBRES_ALERTA}
    claves = [k for k in alertas if re.search(r"\b" + k + r"\b", tipo)] or list(alertas)
    if activar is None:
        falta = {"mails": not _mod("correo").configurado(CONFIG), "agenda": not _mod("agenda").links(CONFIG)}
        return True, "Alertas: " + ", ".join(
            f"{NOMBRES_ALERTA[k]} {'prendida' if v else 'apagada'}" + (" (falta conectarla)" if falta.get(k) else "")
            for k, v in alertas.items()) + "."
    for k in claves:
        alertas[k] = bool(activar)
    estado["alertas"] = alertas
    guardar_estado(estado)
    return True, f"Listo, {'activé' if activar else 'desactivé'} las alertas " + \
        " y ".join(NOMBRES_ALERTA[k] for k in claves) + "."


def _revisar_dolar(ahora_dt=None):
    """Avisa si el blue se movió fuerte desde el último aviso (o desde el cierre anterior)."""
    ahora_dt = ahora_dt or datetime.now()
    if ahora_dt.weekday() >= 5 or not (9 <= ahora_dt.hour < 21):
        return None
    venta = float(json.loads(_info()._leer("https://dolarapi.com/v1/dolares/blue"))["venta"])
    estado = cargar_estado()
    ref = estado.get("dolar_ref") or {}
    hoy = ahora_dt.strftime("%Y-%m-%d")
    if ref.get("fecha") != hoy:                    # día nuevo: se compara contra el cierre anterior
        anterior = float(ref.get("cierre") or venta)
        ref = {"fecha": hoy, "apertura": anterior, "avisado": anterior}
    ref["cierre"] = venta
    base = float(ref.get("avisado") or venta)
    mensaje = None
    if base and abs(venta - base) / base * 100 >= UMBRAL_DOLAR and abs(venta - base) >= 15:
        apertura = float(ref.get("apertura") or base)
        cambio_dia = f"{(venta - apertura) / apertura * 100:+.1f}".replace(".", ",")
        mensaje = f"💵 El dólar blue {'subió' if venta > base else 'bajó'} a ${round(venta)} ({cambio_dia} % en el día)."
        avisar_celular(mensaje, "Cerebro: alerta")
        ref["avisado"] = venta
    estado["dolar_ref"] = ref
    guardar_estado(estado)
    return mensaje


def _revisar_lluvia(ahora_dt=None, horas=None):
    """A la mañana avisa si hoy llueve; durante el día, si empieza a llover en la próxima hora."""
    ahora_dt = ahora_dt or datetime.now()
    if not (7 <= ahora_dt.hour < 22):
        return None
    horas = horas if horas is not None else _info().lluvia_por_hora()
    estado = cargar_estado()
    ll = estado.get("lluvia") or {}
    hoy = ahora_dt.strftime("%Y-%m-%d")
    mensajes = []
    if ll.get("dia") != hoy:                       # una vez por día: el pronóstico de lo que queda de hoy
        ll["dia"] = hoy
        resto = [h for h in horas if h[0].date() == ahora_dt.date() and h[0].hour >= ahora_dt.hour]
        lluviosas = [h for h in resto if h[1] >= 60 and h[2] >= 0.2]
        if lluviosas:
            mensajes.append(f"🌧️ Hoy llueve ({max(h[1] for h in resto)} %), entre las {lluviosas[0][0].hour} y las "
                            f"{lluviosas[-1][0].hour + 1}. Llevá paraguas.")
    actual = [h for h in horas if h[0] <= ahora_dt < h[0] + timedelta(hours=1)]
    proximas = [h for h in horas if ahora_dt < h[0] <= ahora_dt + timedelta(minutes=90)]
    llueve_ya = bool(actual and actual[0][2] >= 0.2)
    if not llueve_ya and any(h[1] >= 70 and h[2] >= 0.3 for h in proximas) \
            and time.time() - float(ll.get("inminente_ts", 0)) > 4 * 3600:
        ll["inminente_ts"] = time.time()
        mensajes.append("🌧️ En la próxima hora empieza a llover. Si tenés ropa afuera, es el momento.")
    estado["lluvia"] = ll
    guardar_estado(estado)
    for m in mensajes:
        avisar_celular(m, "Cerebro: alerta")
    return mensajes


def hilo_alertas():
    """Cada 15 minutos revisa el dólar y la lluvia (solo las alertas prendidas)."""
    time.sleep(90)
    while True:
        alertas = _alertas()
        for clave, revisar in (("dolar", _revisar_dolar), ("lluvia", _revisar_lluvia), ("pc", _revisar_pc)):
            if alertas.get(clave):
                try:
                    revisar()
                except Exception:
                    log.exception("alerta %s", clave)
        time.sleep(15 * 60)


# ---------- aparatos de la casa: se detectan solos ----------

def _descubrir_nuevos(avisar=True):
    import asyncio
    casa = _casa_modulo()
    antes = set(casa._guardados())
    encontrados = asyncio.run(casa._descubrir())
    nuevos = [a for a in encontrados if a not in antes]
    if nuevos and avisar:
        avisar_celular("🏠 Encontré " + ("un aparato nuevo" if len(nuevos) == 1 else f"{len(nuevos)} aparatos nuevos") +
                       " en tu casa: " + ", ".join(nuevos) + (". Ya lo podés manejar." if len(nuevos) == 1 else ". Ya los podés manejar.") + chr(10) +
                       "Si querés ponerle un nombre, escribime por ejemplo: a la luz nueva llamala luz del living.")
    return nuevos


def hilo_aparatos():
    """Cada 6 horas busca aparatos nuevos (WiZ y TP-Link) y los agrega solos."""
    time.sleep(180)
    while True:
        try:
            _descubrir_nuevos()
        except Exception:
            log.exception("buscar aparatos")
        time.sleep(6 * 3600)


def accion_nombrar_aparato(d):
    casa = _casa_modulo()
    nombre = str(d.get("nombre") or "").strip()
    alias = casa.nombrar(str(d.get("aparato") or "luz"), nombre)
    if not alias:
        conocidos = ", ".join(casa._amigable(x) for x in list(casa._guardados())[:5]) or "ninguno"
        return False, "No encontré ese aparato. Los que conozco: " + conocidos + "."
    return True, f"Listo, desde ahora le digo {nombre}."


def accion_buscar_aparatos(d):
    def trabajo():
        try:
            if not _descubrir_nuevos():
                avisar_celular("Busqué en tu red y no hay aparatos nuevos.")
        except Exception as e:
            avisar_celular("No pude buscar aparatos: " + str(e)[:150])

    threading.Thread(target=trabajo, daemon=True).start()
    return True, "Busco aparatos en tu casa y te aviso."


# ---------- agenda (Google Calendar por link secreto) ----------

def _fecha_de_texto(t, hoy=None):
    """'hoy', 'mañana', 'pasado mañana', 'el viernes' -> date; 'semana' -> 'semana'; nada -> hoy."""
    hoy = hoy or datetime.now().date()
    t = norm(t)
    if "semana" in t:
        return "semana"
    if "pasado manana" in t:
        return hoy + timedelta(days=2)
    if re.search(r"\bmanana\b", re.sub(r"\b(de|a|por) la manana\b|\besta manana\b", "", t)):
        return hoy + timedelta(days=1)
    for nombre, numero in DIAS_SEMANA.items():
        if len(nombre) > 2 and re.search(r"\b" + nombre + r"\b", t):
            return hoy + timedelta(days=(numero - hoy.weekday()) % 7)
    return hoy


def accion_agenda(d):
    """Lo que hay en el calendario: {"dia": 0 hoy, 1 mañana...} o {"fecha": "AAAA-MM-DD"} o {"semana": true}."""
    agenda = _mod("agenda")
    try:
        if d.get("semana") or "semana" in norm(d.get("cuando")):
            return True, agenda.semana(CONFIG)
        fecha = None
        if d.get("fecha"):
            try:
                fecha = datetime.strptime(str(d["fecha"])[:10], "%Y-%m-%d").date()
            except ValueError:
                fecha = None
        if fecha is None and d.get("cuando"):
            f = _fecha_de_texto(d["cuando"])
            fecha = None if f == "semana" else f
        if fecha is None:
            try:
                fecha = (datetime.now() + timedelta(days=int(float(d.get("dia") or 0)))).date()
            except (TypeError, ValueError):
                fecha = datetime.now().date()
        return True, agenda.del_dia(CONFIG, fecha)
    except agenda.AgendaError as e:
        if not agenda.links(CONFIG):                 # sin calendario: al menos los pendientes
            _, pend = accion_pendientes({})
            return True, "Todavía no conectaste tu Google Calendar (se hace una vez con configurar.bat en la PC). " + pend
        return False, str(e)


def _revisar_agenda(ahora_dt=None):
    """Avisa por Telegram un rato antes de cada evento del calendario."""
    agenda = _mod("agenda")
    minutos = int(CONFIG.get("agenda_aviso_minutos") or 30)
    proximos = agenda.proximos(CONFIG, minutos, ahora_dt)
    avisados = cargar_estado().get("agenda_avisados") or []
    nuevos = [e for e in proximos if e["uid"] not in avisados]
    for e in nuevos:
        faltan = max(1, round((e["inicio"] - (ahora_dt or datetime.now())).total_seconds() / 60))
        lugar = f", en {e['lugar'].split(',')[0]}" if e["lugar"] else ""
        avisar_celular(f"📅 En {faltan} minutos: {e['titulo']} (a las {agenda.hora_dicha(e['inicio'])}{lugar}).",
                       "Cerebro: agenda")
    if nuevos:
        estado_cambiar(lambda s: s.__setitem__("agenda_avisados", (avisados + [e["uid"] for e in nuevos])[-200:]))
    return nuevos


# ---------- mails (Gmail, solo lectura) ----------

def accion_mails(d):
    correo = _mod("correo")
    if d.get("voz"):                    # por voz: rápido (remitentes y asuntos) y el resumen completo al celular
        try:
            total, mails = correo.encabezados(CONFIG, 3)
        except correo.CorreoError as e:
            return False, str(e)
        except Exception as e:
            log.exception("mails por voz")
            return False, "No pude revisar el mail: " + str(e)[:120]
        if not total:
            return True, "No tenés mails sin leer."
        threading.Thread(target=lambda: avisar_celular(accion_mails({})[1], "Cerebro: mails"), daemon=True).start()
        return True, (f"Tenés {total} mail{'s' if total != 1 else ''} sin leer. " +
                      " ".join(f"De {m['de']}: {m['asunto']}" + ("" if m["asunto"][-1:] in ".!?" else ".") for m in mails) +
                      (f" Y {total - len(mails)} más." if total > len(mails) else "") + " Te mandé el resumen al celular.")
    try:
        total, mails = correo.no_leidos(CONFIG, 8)
    except correo.CorreoError as e:
        return False, str(e)
    except Exception as e:
        log.exception("mails")
        return False, "No pude revisar el mail: " + str(e)[:120]
    if not total:
        return True, "No tenés mails sin leer en Principal."
    cabeza = f"Tenés {total} mail{'s' if total != 1 else ''} sin leer en Principal"
    if total > len(mails):
        cabeza += f" (te cuento los {len(mails)} más nuevos)"
    lista = chr(10).join(f"{i + 1}. " + correo.renglon(m, 400) for i, m in enumerate(mails))
    resumen = preguntar_ia(
        "Resumí estos mails sin leer para el usuario, en español rioplatense y cortito. Primero los importantes o "
        "personales (de personas, trabajo, bancos, turnos, vencimientos, envíos), uno por línea: 'De X: de qué se "
        "trata'. Después, en una sola línea, lo demás (promociones, avisos automáticos). No inventes nada. Texto "
        "plano, sin markdown ni asteriscos.", lista, timeout=10)
    return True, cabeza + "." + chr(10) + (resumen.strip() if resumen else
                                          chr(10).join(correo.renglon(m, 100) for m in mails))


def _revisar_mails():
    """Avisa por Telegram cuando llega un mail que Gmail marca como importante (en Principal)."""
    correo = _mod("correo")
    estado = cargar_estado()
    primera_vez = "mails_vistos" not in estado
    actuales, nuevos = correo.nuevos_importantes(CONFIG, estado.get("mails_vistos") or [])
    if not primera_vez:                         # la primera vez solo anota lo que ya había: no llena de avisos
        for m in nuevos:
            avisar_celular("📧 Mail importante de " + m["de"] + ": " + m["asunto"] +
                           (chr(10) + m["texto"][:300] if m["texto"] else ""), "Cerebro: mail")
    estado_cambiar(lambda s: s.__setitem__("mails_vistos", actuales[-300:]))
    return [] if primera_vez else nuevos


# ---------- salud de la PC ----------

class _EstadoMemoria(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _memoria_pc():
    m = _EstadoMemoria()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return int(m.dwMemoryLoad), m.ullTotalPhys / 1e9


def _cpu_pc(espera=0.6):
    def tiempos():
        libre, nucleo, usuario = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(libre), ctypes.byref(nucleo), ctypes.byref(usuario))
        return libre.value, nucleo.value + usuario.value
    a = tiempos()
    time.sleep(espera)
    b = tiempos()
    total = b[1] - a[1]
    return max(0, min(100, round(100 * (1 - (b[0] - a[0]) / total)))) if total else 0


def _encendida_seg():
    ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    return ctypes.windll.kernel32.GetTickCount64() / 1000


def _disco():
    uso = shutil.disk_usage("C:\\")
    return uso.free / 1e9, uso.total / 1e9


def _hay_internet(timeout=5):
    for url in ("https://www.google.com/generate_204", "https://1.1.1.1"):
        try:
            urllib.request.urlopen(url, timeout=timeout).close()
            return True
        except Exception:
            continue
    return False


def _duracion(seg):
    seg = int(seg)
    dias, horas, minutos = seg // 86400, seg % 86400 // 3600, seg % 3600 // 60
    if dias:
        return f"{dias} día{'s' if dias != 1 else ''}" + (f" y {horas} hora{'s' if horas != 1 else ''}" if horas else "")
    if horas:
        return f"{horas} hora{'s' if horas != 1 else ''}" + (f" y {minutos} minuto{'s' if minutos != 1 else ''}" if minutos else "")
    minutos = max(1, minutos)
    return f"{minutos} minuto{'s' if minutos != 1 else ''}"


def _lo_que_mas_memoria():
    r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, errors="replace",
                       creationflags=CREATE_NO_WINDOW)
    suma = {}
    for linea in r.stdout.splitlines():
        partes = linea.strip().strip('"').split('","')
        if len(partes) >= 5:
            kb = int(re.sub(r"\D", "", partes[4]) or 0)
            nombre = partes[0].rsplit(".", 1)[0]
            suma[nombre] = suma.get(nombre, 0) + kb
    if not suma:
        return ""
    nombre, kb = max(suma.items(), key=lambda x: x[1])
    return f"{nombre} ({kb / 1e6:.1f} GB)".replace(".", ",")


def _disco_escaso(libre, total):
    return libre < 10 or libre / total < 0.08


def accion_salud_pc(d):
    libre, total = _disco()
    ram, _ = _memoria_pc()
    cpu = _cpu_pc()
    red = _hay_internet()
    problemas = []
    if _disco_escaso(libre, total):
        problemas.append(f"al disco C le quedan solo {libre:.0f} GB libres de {total:.0f}")
    if ram >= 90:
        problemas.append(f"la memoria está al {ram} % (lo que más usa: {_lo_que_mas_memoria()})")
    if cpu >= 90:
        problemas.append(f"el procesador está al {cpu} %")
    if not red:
        problemas.append("no tiene internet")
    datos = (f"disco C con {libre:.0f} GB libres de {total:.0f}, memoria al {ram} %, procesador al {cpu} %, "
             f"prendida hace {_duracion(_encendida_seg())}")
    consejo = ""
    if d.get("lenta"):                  # "anda lenta": decir qué la está cargando y cómo seguir
        pesado = _lo_que_mas_memoria()
        consejo = ((f" Lo que más memoria usa es {pesado}." if pesado and ram < 90 else "") +
                   (" Hace varios días que no se reinicia: reiniciarla suele ayudar (decime 'reiniciá la pc')."
                    if _encendida_seg() > 3 * 86400 else "") +
                   " Si querés que lo revise a fondo, decime 'fijate qué la pone lenta'.")
    if problemas:
        return True, "Ojo: " + "; ".join(problemas) + ". Lo demás: " + datos + "." + consejo
    return True, "La PC anda bien: " + datos + ", con internet." + consejo


def _revisar_pc(ahora_dt=None, disco=None, ram=None):
    """Disco casi lleno (una vez por día; si es grave, cada 6 horas) y memoria al límite un buen rato."""
    ahora_dt = ahora_dt or datetime.now()
    ahora_ts = ahora_dt.timestamp()
    libre, total = disco or _disco()
    ram = ram if ram is not None else _memoria_pc()[0]
    mensajes = []

    def cambio(e):
        s = e.setdefault("salud", {})
        hoy = ahora_dt.strftime("%Y-%m-%d")
        if _disco_escaso(libre, total):
            grave = libre < 3
            if (grave and ahora_ts - float(s.get("disco_grave_ts", 0)) > 6 * 3600) or (not grave and s.get("disco_dia") != hoy):
                s["disco_dia"] = hoy
                if grave:
                    s["disco_grave_ts"] = ahora_ts
                mensajes.append(f"💾 {'URGENTE: a' if grave else 'A'}l disco C de la PC le quedan {libre:.1f} GB libres "
                                f"de {total:.0f}. Si querés, escribime \"fijate qué ocupa lugar en el disco\" y lo reviso.")
        s["ram_altas"] = s.get("ram_altas", 0) + 1 if ram >= 92 else 0
        if s["ram_altas"] >= 3 and ahora_ts - float(s.get("ram_ts", 0)) > 6 * 3600:
            s["ram_ts"] = ahora_ts
            mensajes.append(f"🧠 La memoria de la PC está al {ram} % hace un rato. Lo que más usa: "
                            f"{_lo_que_mas_memoria() or 'no sé'}. Si anda lenta, cerrá ese programa o pedímelo.")

    estado_cambiar(cambio)
    for m in mensajes:
        avisar_celular(m, "Cerebro: alerta")
    return mensajes


LATIDO = BASE / "latido.txt"        # cada minuto: así, al arrancar, se sabe hasta cuándo estuvo prendida


def _aviso_arranque():
    """Si la PC se reinició o se apagó (corte de luz, actualización), avisa cuando vuelve."""
    try:
        previo = float(LATIDO.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    arranque = time.time() - _encendida_seg()
    if arranque < previo:                 # la PC no se apagó: solo se reinició Cerebro
        return
    pedido = float(cargar_estado().get("reinicio_pedido_ts") or 0)
    if 0 < arranque - pedido < 15 * 60:
        mensaje = "✅ La PC ya arrancó de nuevo después del reinicio que pediste."
    else:
        antes, despues = datetime.fromtimestamp(previo), datetime.fromtimestamp(arranque)
        dia = "" if antes.date() == despues.date() else antes.strftime(" del %d/%m")
        mensaje = (f"🔌 La PC se reinició: estuvo apagada desde las {antes:%H:%M}{dia} hasta las {despues:%H:%M}. "
                   "Puede haber sido un corte de luz o una actualización de Windows. Ya estoy andando de nuevo.")
    if not _alertas().get("pc"):
        return
    for _ in range(30):                   # al arrancar puede tardar en haber internet
        if avisar_celular(mensaje, "Cerebro"):
            return
        time.sleep(60)


# ---------- resumen de la mañana ----------

MESES_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
            "noviembre", "diciembre")


def _equipo_de_memoria():
    """El equipo del usuario si lo contó alguna vez ("soy de River", "soy hincha de Boca"), aunque no lo configure."""
    try:
        equipos = _info().EQUIPOS_AR
    except Exception:
        return ""
    for dato in reversed(_memoria()["datos"]):
        d = norm(dato)
        if re.search(r"\b(hincha|fan|simpatizante|equipo|soy de|es de|sigue a)\b", d):
            for clave in sorted(equipos, key=len, reverse=True):
                if clave not in ("argentina", "seleccion") and re.search(r"\b" + clave + r"\b", d):
                    return equipos[clave]
    return ""


def _config_resumen():
    r = {"activo": True, "hora": str(CONFIG.get("resumen_hora") or "08:00"), "dias": "todos",
         "equipo": str(CONFIG.get("equipo") or "")}
    r.update(cargar_estado().get("resumen") or {})
    if not r.get("equipo"):
        r["equipo"] = _equipo_de_memoria()
    return r


def armar_resumen(ahora_dt=None, voz=False):
    """Clima, agenda, partido, pendientes, mails, dólar y titulares; todo a la vez para que tarde poco."""
    from concurrent.futures import ThreadPoolExecutor
    ahora_dt = ahora_dt or datetime.now()
    cfg = _config_resumen()
    info = _info()
    e = (lambda s: "") if voz else (lambda s: s + " ")

    def feriado():
        nombre = info.feriado_de(ahora_dt.date())
        return e("🇦🇷") + f"Hoy es feriado: {nombre}." if nombre else ""

    def clima():
        return e("🌤️") + info.clima("", 0)

    def agenda():
        mod = _mod("agenda")
        if not mod.links(CONFIG):
            return ""
        try:
            return e("📅") + mod.del_dia(CONFIG, ahora_dt.date(), ahora_dt)
        except mod.AgendaError as ex:
            return e("📅") + str(ex)

    def futbol():
        partido = info.partido_de_hoy(cfg["equipo"], ahora_dt.date()) if cfg.get("equipo") else None
        return e("⚽") + partido if partido else ""

    def pendientes():
        _, lineas = leer_pendientes()
        abiertos = [limpiar_para_voz(x) for x in lineas if x.strip().startswith("- [ ]")]
        if not abiertos:
            return ""
        return e("📝") + "Pendientes: " + "; ".join(abiertos[:5]) + (f"; y {len(abiertos) - 5} más" if len(abiertos) > 5 else "") + "."

    def mails():
        correo = _mod("correo")
        if not correo.configurado(CONFIG):
            return ""
        total, lista = correo.no_leidos(CONFIG, 3)
        if not total:
            return e("📧") + "No tenés mails sin leer."
        return e("📧") + f"Tenés {total} mail{'s' if total != 1 else ''} sin leer. Los últimos: " + \
            "; ".join(f"de {m['de']}: {m['asunto']}" for m in lista) + "."

    def dolar():
        datos = {x.get("casa"): x for x in json.loads(info._leer("https://dolarapi.com/v1/dolares"))}
        return e("💵") + f"Dólar blue {round(datos['blue']['venta'])} y oficial {round(datos['oficial']['venta'])}."

    def noticias():
        titulos = [x for x, _ in info.titulares("", 3)]
        return e("📰") + "Titulares: " + "; ".join(titulos) + "." if titulos else ""

    def disco():
        libre, total = _disco()
        return e("💾") + f"Ojo: al disco C de la PC le quedan {libre:.0f} GB libres." if _disco_escaso(libre, total) else ""

    partes_f = (feriado, clima, agenda, futbol, pendientes, mails, dolar, noticias, disco)
    with ThreadPoolExecutor(max_workers=len(partes_f)) as pool:
        futuros = [pool.submit(f) for f in partes_f]
        partes = []
        for f, fut in zip(partes_f, futuros):
            try:
                r = fut.result(timeout=25)
            except Exception as ex:
                log.warning("resumen %s: %s", f.__name__, str(ex)[:100])
                r = ""
            if r:
                partes.append(r)
    saludo = ("Buen día. " if ahora_dt.hour < 13 else "Hola. ") + \
        f"Hoy es {NOMBRES_DIA[ahora_dt.weekday()]} {ahora_dt.day} de {MESES_ES[ahora_dt.month - 1]}."
    if voz:
        return " ".join([saludo] + partes)
    return (chr(10) * 2).join([e("☀️") + saludo] + partes)


def _hora_de(valor):
    """'7', '7:30', '07.30', '7 y media', 'siete y media', '19 hs' -> 'HH:MM' (o None)."""
    t = norm(valor)
    for palabra, numero in (("una", 1), ("uno", 1), ("dos", 2), ("tres", 3), ("cuatro", 4), ("cinco", 5), ("seis", 6),
                            ("siete", 7), ("ocho", 8), ("nueve", 9), ("diez", 10), ("once", 11), ("doce", 12)):
        t = re.sub(r"\b" + palabra + r"\b", str(numero), t)
    m = re.search(r"(\d{1,2})(?:\s*[:.h]\s*(\d{2})|\s+y\s+(media|cuarto))?", t)
    if not m:
        return None
    hora = int(m.group(1))
    minutos = int(m.group(2)) if m.group(2) else 30 if m.group(3) == "media" else 15 if m.group(3) == "cuarto" else 0
    if re.search(r"\b(de la tarde|de la noche|pm)\b", t) and hora < 12:
        hora += 12
    return f"{hora:02d}:{minutos:02d}" if hora < 24 and minutos < 60 else None


def accion_resumen_manana(d):
    """{"ahora": true} lo arma ya; si no, configura el que llega solo: hora, activar, dias (todos|semana), equipo."""
    cambios = {}
    if d.get("hora"):
        hora = _hora_de(d["hora"])
        if not hora:
            return False, "No entendí a qué hora querés el resumen."
        cambios["hora"], cambios["activo"] = hora, True
    if d.get("activar") is not None and str(d.get("activar")).strip() != "":
        cambios["activo"] = d["activar"] if isinstance(d["activar"], bool) else \
            norm(d["activar"]) in ("true", "si", "activar", "prender", "1")
    if d.get("dias"):
        cambios["dias"] = "semana" if any(x in norm(d["dias"]) for x in ("semana", "habil", "lunes a viernes")) else "todos"
    if d.get("equipo") is not None:
        cambios["equipo"] = str(d["equipo"]).strip()
    if not cambios:
        return True, armar_resumen(voz=bool(d.get("voz")))
    estado_cambiar(lambda e: e.setdefault("resumen", {}).update(cambios))
    cfg = _config_resumen()
    if not cfg["activo"]:
        return True, "Listo, no te mando más el resumen de la mañana. Si lo querés de nuevo, pedímelo."
    dias = "de lunes a viernes" if cfg["dias"] == "semana" else "todos los días"
    extra = f" Incluye cuándo juega {cfg['equipo']}." if cambios.get("equipo") else ""
    return True, f"Listo, te mando el resumen {dias} a las {cfg['hora']}.{extra}"


def _toca_resumen(ahora_dt, cfg):
    if not cfg.get("activo") or cfg.get("ultimo") == ahora_dt.strftime("%Y-%m-%d"):
        return False
    if cfg.get("dias") == "semana" and ahora_dt.weekday() >= 5:
        return False
    hora = datetime.strptime(_hora_de(cfg.get("hora")) or "08:00", "%H:%M").replace(
        year=ahora_dt.year, month=ahora_dt.month, day=ahora_dt.day)
    return hora <= ahora_dt < hora + timedelta(hours=3)     # si la PC estaba apagada a esa hora, llega igual un rato después


def _mandar_resumen_si_toca(ahora_dt=None):
    ahora_dt = ahora_dt or datetime.now()
    if not _toca_resumen(ahora_dt, _config_resumen()):
        return False
    # Se marca como mandado recién cuando salió: si al arrancar todavía no hay internet, se reintenta después.
    if not avisar_celular(armar_resumen(ahora_dt), "Cerebro: resumen del día"):
        return False
    estado_cambiar(lambda e: e.setdefault("resumen", {}).__setitem__("ultimo", ahora_dt.strftime("%Y-%m-%d")))
    return True


def hilo_minutero():
    """Cada 30 segundos: resumen de la mañana, avisos de la agenda, mails importantes y cortes de internet."""
    time.sleep(20)
    ultimo = {"red": 0, "agenda": 0, "mails": 0}
    sin_red_desde = None
    while True:
        ahora_ts = time.time()
        try:
            LATIDO.write_text(str(ahora_ts), encoding="utf-8")
        except OSError:
            pass
        alertas = _alertas()
        try:
            _mandar_resumen_si_toca()
        except Exception:
            log.exception("resumen de la mañana")
        if ahora_ts - ultimo["red"] >= 60:
            ultimo["red"] = ahora_ts
            try:
                if not _hay_internet():
                    sin_red_desde = sin_red_desde or ahora_ts
                elif sin_red_desde:
                    caida = ahora_ts - sin_red_desde
                    if caida >= 120 and alertas.get("pc"):
                        avisar_celular(f"🌐 Se cortó internet en la PC de {datetime.fromtimestamp(sin_red_desde):%H:%M} "
                                       f"a {datetime.fromtimestamp(ahora_ts):%H:%M} ({_duracion(caida)}). Ya volvió.",
                                       "Cerebro: alerta")
                    sin_red_desde = None
            except Exception:
                log.exception("internet")
        if alertas.get("agenda") and ahora_ts - ultimo["agenda"] >= 120 and _mod("agenda").links(CONFIG):
            ultimo["agenda"] = ahora_ts
            try:
                _revisar_agenda()
            except Exception as ex:
                log.warning("agenda: %s", str(ex)[:150])
        if alertas.get("mails") and ahora_ts - ultimo["mails"] >= 300 and _mod("correo").configurado(CONFIG):
            ultimo["mails"] = ahora_ts
            try:
                _revisar_mails()
            except Exception as ex:
                log.warning("mails: %s", str(ex)[:150])
        time.sleep(30)


ACCIONES = {
    "nota": accion_nota, "buscar_notas": accion_buscar_notas, "pendientes": accion_pendientes,
    "completar_pendiente": accion_completar_pendiente, "abrir_web": accion_abrir_web, "abrir_app": accion_abrir_app,
    "musica": accion_musica, "volumen": accion_volumen, "sistema": accion_sistema, "tarea": accion_tarea,
    "confirmar_tarea": accion_confirmar_tarea, "estado": accion_estado,
    "info_pc": accion_info_pc, "avisar": accion_avisar,
    "whatsapp": accion_whatsapp, "whatsapp_confirmar": accion_whatsapp_confirmar,
    "whatsapp_editar": accion_whatsapp_editar,
    "whatsapp_archivo": accion_whatsapp_archivo, "whatsapp_resumen": accion_whatsapp_resumen,
    "whatsapp_leer": accion_whatsapp_leer, "whatsapp_cancelar": accion_whatsapp_cancelar,
    "pantalla_confirmar": accion_pantalla_confirmar,
    "casa": accion_casa, "casa_descubrir": accion_casa_descubrir,
    "diagnostico": accion_diagnostico, "frase": accion_frase, "aprender": lambda d: accion_aprender(d),   # definida más abajo
    "recordar": accion_recordar, "olvidar": accion_olvidar, "que_sabes": accion_que_sabes,
    "programar": accion_programar, "programados": accion_programados, "borrar_programado": accion_borrar_programado,
    "compras": accion_compras, "clima": accion_clima, "dolar": accion_dolar, "noticias": accion_noticias,
    "aprendidos": lambda d: accion_aprendidos(d),
    "captura": accion_captura, "enviar_archivo": accion_enviar_archivo, "cerrar_app": accion_cerrar_app,
    "tareas_estado": accion_tareas_estado, "cancelar_tarea": accion_cancelar_tarea,
    "alertas": accion_alertas, "nombrar_aparato": accion_nombrar_aparato, "buscar_aparatos": accion_buscar_aparatos,
    "argentina": lambda d: (True, _info().riesgo_pais() if "riesgo" in norm(d.get("dato"))
                            else _info().inflacion() if "infla" in norm(d.get("dato"))
                            else _info().proximo_feriado()),
    "futbol": lambda d: (True, _info().futbol(d.get("equipo") or "Boca")),
    "cotizacion": lambda d: (True, _info().cotizacion(d.get("moneda") or "euro")),
    "convertir": lambda d: (True, _info().convertir(d.get("monto") or 1, d.get("de") or "dolar", d.get("a") or "peso")),
    "agenda": accion_agenda, "mails": accion_mails, "salud_pc": accion_salud_pc,
    "musica_control": accion_musica_control, "resumen_manana": accion_resumen_manana,
}


# ---------- bucle principal ----------

def procesar(evento, estado):
    try:
        msg = json.loads(evento.get("message", ""))
    except ValueError:
        return
    if not isinstance(msg, dict) or not all(k in msg for k in ("id", "ts", "accion", "datos", "firma")):
        return
    datos = msg["datos"] if isinstance(msg["datos"], dict) else {}
    esperado = firmar(f'{msg["id"]}|{msg["ts"]}|{msg["accion"]}|{json.dumps(datos, sort_keys=True, ensure_ascii=False)}')
    if not hmac.compare_digest(esperado, str(msg["firma"])):
        log.warning("orden con firma inválida ignorada")
        return
    vistos = estado.setdefault("vistos", [])
    if msg["id"] in vistos:
        return
    vistos.append(msg["id"])
    del vistos[:-300]

    accion = msg["accion"]
    if accion in SIN_RESPUESTA:                 # avisos para el orbe (pc/orbe.py): no son órdenes, no se contestan
        return
    edad = time.time() - float(msg["ts"])
    if edad > MAX_AGE_LIVE and accion not in QUEUEABLE:
        log.info("orden vieja ignorada: %s (%.0fs)", accion, edad)
        return
    handler = ACCIONES.get(accion)
    if not handler:
        responder(msg["id"], False, "Esa acción no está permitida en tu PC.")
        return
    log.info("ejecutando %s %s", accion, datos)
    try:
        ok, texto = handler(datos)
        if ok and accion != "casa":        # casa se anota sola, venga de voz o de Telegram
            anotar_accion(accion, datos)
    except Exception as e:
        log.exception("acción %s falló", accion)
        ok, texto = False, f"Falló la acción en tu PC: {e}"
    try:
        responder(msg["id"], ok, texto)
    except Exception:
        log.exception("no pude responder")


def escuchar():
    estado = cargar_estado()
    estado.setdefault("since", int(time.time()))
    while True:
        since = max(int(estado["since"]), int(time.time()) - 12 * 3600)
        url = f"https://ntfy.sh/{TOPIC}/json?since={since}"
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                log.info("conectado a ntfy")
                for raw in resp:
                    try:
                        evento = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        continue
                    if evento.get("event") != "message":
                        continue
                    procesar(evento, estado)
                    estado["since"] = max(int(estado.get("since", 0)), int(evento.get("time", 0)))
                    guardar_estado({**cargar_estado(), "since": estado["since"], "vistos": estado["vistos"]})
        except Exception as e:
            log.warning("conexión perdida (%s); reintento en 5 s", e)
            time.sleep(5)


# ---------- órdenes por Telegram (control remoto) ----------

AYUDA_TELEGRAM = (
    "Podés escribirme, por ejemplo:" + chr(10) +
    "• prendé la luz / apagá la luz / poné la luz al 30" + chr(10) +
    "• poné la luz azul / luz cálida / escena fiesta" + chr(10) +
    "• anotá: comprar café   (o) pendiente: llamar al contador" + chr(10) +
    "• pendientes" + chr(10) +
    "• qué anoté sobre el viaje" + chr(10) +
    "• estado   (hora, disco y equipo)" + chr(10) +
    "• whatsapp a Juan: llego en 10   /   corregí el mensaje a Juan: llego en 20" + chr(10) +
    "• recordame cada 2 horas tomar agua   /   todos los días a las 7 prendé la luz" + chr(10) +
    "• mis avisos   /   borrá el aviso de agua" + chr(10) +
    "• agregá leche y pan a la lista   /   lista de compras" + chr(10) +
    "• clima   /   clima mañana en Córdoba   /   dólar   /   noticias de Boca" + chr(10) +
    "• aprendo solo: si me equivoco, decime qué querías y lo tengo en cuenta   /   qué aprendiste" + chr(10) +
    "• abrí whatsapp   /   entrá al chat de Laura   /   abrí claude" + chr(10) +
    "• qué sabés hacer   (lo que te enseñé)   /   qué sabés de mí" + chr(10) +
    "• acordate que mi hermana se llama Laura" + chr(10) +
    "• pantalla   (te mando una captura)   /   mandame el archivo presupuesto" + chr(10) +
    "• cerrá chrome   /   bloqueá la pc   /   apagá la pc (te pido confirmación)" + chr(10) +
    "• qué estás haciendo   /   cancelá la tarea" + chr(10) +
    "• qué mensajes tengo   /   qué me escribió Laura   /   mandale a Laura el pdf del presupuesto" + chr(10) +
    "• desactivá las alertas del dólar   /   qué alertas tengo" + chr(10) +
    "• qué tengo hoy   /   qué tengo el viernes   /   agenda de la semana   (tu Google Calendar)" + chr(10) +
    "• tengo mails?   /   resumime los mails" + chr(10) +
    "• pausa   /   siguiente   /   anterior   /   seguí   /   qué está sonando" + chr(10) +
    "• cómo está la pc   (disco, memoria, internet)" + chr(10) +
    "• resumen   /   mandame el resumen a las 7:30   /   desactivá el resumen" + chr(10) +
    "• a la luz nueva llamala luz del living   /   buscá aparatos nuevos" + chr(10) +
    "• mandame una nota de voz, una foto o un archivo (con una indicación si querés que haga algo)" + chr(10) +
    "• cualquier otra cosa se la paso a Claude, que la hace en la PC y te va contando cómo va"
)


def _telegram_responder(texto):
    try:
        _telegram_enviar(texto, "Cerebro")
    except Exception:
        log.exception("no pude responder por Telegram")


APRENDIDO = None


def _aprendidos():
    """Frases que el usuario le enseñó: {frase: [comandos a ejecutar]}."""
    try:
        return json.loads((BASE / "aprendido.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_aprendido(frase, comandos):
    """comandos: lista de textos ("poné la luz al 10") o de acciones ({"accion": ..., "datos": ...})."""
    datos = _aprendidos()
    datos[norm(frase)] = comandos
    _escribir_json(BASE / "aprendido.json", datos)
    registrar("aprendizaje", frase + " = " + " ; ".join(_describir(c) for c in comandos))


def _describir(c):
    """Texto corto de un paso aprendido, para mostrarlo."""
    if not isinstance(c, dict):
        return str(c)
    accion, d = c.get("accion"), c.get("datos") or {}
    if accion == "casa":
        que = d.get("accion", "")
        valor = d.get("valor")
        nombres = {"prender": "prender la luz", "apagar": "apagar la luz", "brillo": "luz al",
                   "color": "luz", "escena": "modo", "temperatura": "luz"}
        return nombres.get(que, que) + ("" if valor is None else " " + str(valor))
    if accion == "sistema":
        return str(d.get("orden", "")) + " la PC"
    if accion == "volumen":
        return "volumen " + str(d.get("cambio") or d.get("nivel") or "")
    if accion == "musica":
        return "música: " + str(d.get("busqueda") or d.get("consulta") or "")
    if accion in ("abrir_app", "abrir_web"):
        return "abrir " + str(d.get("nombre") or d.get("url") or d.get("busqueda") or "")
    return str(accion)


ATAJO = threading.local()       # mientras corre un atajo, no anotamos sus pasos como "repetidos"


def _ejecutar_pasos(pasos, profundidad=1):
    respuestas = []
    ATAJO.activo = True
    try:
        for c in pasos:
            try:
                if isinstance(c, dict):
                    r = ACCIONES[c["accion"]](c.get("datos") or {})[1]
                else:
                    r = _orden_telegram(str(c), profundidad)
            except Exception as e:
                r = "No pude: " + _describir(c) + " (" + str(e)[:60] + ")"
            if r:
                respuestas.append(str(r))
    finally:
        ATAJO.activo = False
    return " ".join(respuestas)[:600] or "Listo."


def _partir_pasos(texto):
    """'poné la luz al 10 y después escena película' -> ['poné la luz al 10', 'escena película']"""
    s = " " + str(texto or "") + " "
    for sep in (" y despues ", " y después ", " y luego ", " luego ", ";", " y "):
        s = s.replace(sep, "|")
    return [x.strip(" ,.") for x in s.split("|") if x.strip(" ,.")]


RUTINARIAS = {"casa", "sistema", "volumen", "musica", "abrir_app", "abrir_web"}
VENTANA_REPETICION = 180        # segundos entre dos pasos para considerarlos "juntos"
VECES_PARA_SUGERIR = 2
VIGENCIA_SUGERENCIA = 1800      # la sugerencia espera respuesta media hora


def anotar_accion(accion, datos):
    """Guarda lo que se hizo, para darse cuenta de las cosas que repetís."""
    if accion not in RUTINARIAS or getattr(ATAJO, "activo", False):
        return
    try:
        m = _memoria()
        lista = m.setdefault("acciones", [])
        lista.append({"accion": accion, "datos": datos, "ts": time.time()})
        m["acciones"] = lista[-150:]
        _guardar_memoria(m)
    except Exception:
        log.exception("anotar acción")


def _clave(a, b):
    return json.dumps([[a["accion"], a["datos"]], [b["accion"], b["datos"]]], sort_keys=True, ensure_ascii=False)


def _revisar_repeticion(acciones):
    if len(acciones) < 2:
        return
    a, b = acciones[-2], acciones[-1]
    if b["ts"] - a["ts"] > VENTANA_REPETICION or _clave(a, a) == _clave(b, b):
        return
    if {a["datos"].get("accion"), b["datos"].get("accion")} == {"prender", "apagar"}:
        return                                  # prender y apagar no es una rutina
    clave = _clave(a, b)
    veces = sum(1 for i in range(1, len(acciones))
                if acciones[i]["ts"] - acciones[i - 1]["ts"] <= VENTANA_REPETICION
                and _clave(acciones[i - 1], acciones[i]) == clave)
    if veces < VECES_PARA_SUGERIR:
        return
    estado = cargar_estado()
    if clave in estado.get("sugeridos", []):
        return
    estado.setdefault("sugeridos", []).append(clave)
    pasos = [{"accion": a["accion"], "datos": a["datos"]}, {"accion": b["accion"], "datos": b["datos"]}]
    estado["sugerencia_pendiente"] = pasos
    estado["sugerencia_ts"] = int(time.time())
    estado.pop("esperando_nombre", None)
    guardar_estado(estado)
    avisar_celular("Noté que seguido hacés esto: " + _describir(pasos[0]) + ", y después " + _describir(pasos[1]) +
                   "." + chr(10) + chr(10) + "¿Lo guardo como un atajo? Respondeme por acá, por ejemplo: "
                   "sí, llamalo modo noche")


def _respuesta_a_sugerencia(texto):
    """Si hay una sugerencia de atajo esperando, interpreta 'sí, llamalo modo noche' o 'no'."""
    estado = cargar_estado()
    pasos = estado.get("sugerencia_pendiente")
    if not pasos:
        return None
    if time.time() - estado.get("sugerencia_ts", 0) > VIGENCIA_SUGERENCIA:
        estado.pop("sugerencia_pendiente", None)
        estado.pop("esperando_nombre", None)
        guardar_estado(estado)
        return None
    t = norm(texto).strip(" .!")

    def guardar(nombre):
        estado.pop("sugerencia_pendiente", None)
        estado.pop("esperando_nombre", None)
        guardar_estado(estado)
        _guardar_aprendido(nombre, pasos)
        return "Listo, guardé '" + nombre + "'. Decímelo cuando quieras, por voz o por acá."

    if estado.get("esperando_nombre"):
        if t in ("no", "dejalo", "nada", "cancelar"):
            estado.pop("sugerencia_pendiente", None)
            estado.pop("esperando_nombre", None)
            guardar_estado(estado)
            return "Ok, no lo guardo."
        return guardar(texto.strip(" .!"))
    if t in ("no", "nah", "no gracias", "dejalo", "no hace falta"):
        estado.pop("sugerencia_pendiente", None)
        guardar_estado(estado)
        return "Ok, no lo guardo."
    if t.startswith(("si", "dale", "ok", "guardalo", "bueno", "de una", "llamalo", "ponele")):
        for clave in ("llamalo ", "llamala ", "ponele ", "como ", "nombre "):
            if clave in t:
                return guardar(texto[t.index(clave) + len(clave):].strip(" .!'" + chr(34)))
        estado["esperando_nombre"] = True
        guardar_estado(estado)
        return "¿Cómo lo querés llamar? Por ejemplo: modo noche."
    return None


def _correccion(texto):
    """'no, lo que quería era poner la luz roja' -> aprende lo último que no entendió, y lo hace."""
    t = norm(texto)
    if not (t.startswith(("no,", "no quise", "no era", "me equivoque")) or
            (t.startswith("no ") and ("queria" in t or "quise" in t))) or "cuando dig" in t:
        return None
    estado = cargar_estado()
    anterior = estado.get("ultimo_no_entendido")
    if not anterior or time.time() - estado.get("ultimo_no_entendido_ts", 0) > 600:
        return None
    resto = ""
    for clave in ("quise decir", "queria decir", "lo que queria era", "lo que queria es", "lo que quiero es",
                  "queria que", "quiero que", "queria", "quiero"):
        if clave in t:
            resto = texto[t.index(clave) + len(clave):]
            break
    else:
        if "," in texto:
            resto = texto.split(",", 1)[1]
    resto = resto.strip(" ,.:")
    if norm(resto).startswith("eso"):
        resto = resto[3:].strip(" ,.:")
    pasos = _partir_pasos(resto)
    if not pasos:
        return None
    estado.pop("ultimo_no_entendido", None)
    guardar_estado(estado)
    _guardar_aprendido(anterior, pasos)
    hecho = _ejecutar_pasos(pasos)
    return hecho + " Y ya aprendí: la próxima vez que digas '" + anterior + "', hago eso."


PREFIJO_LECCION = "Cuando el usuario dice"


def _guardar_leccion(frase, pasos):
    """Lo aprendido de una corrección: conocimiento para que la IA entienda mejor, NO un atajo que se dispara solo."""
    frase = str(frase).strip(' "\'.')
    pasos_txt = "; ".join(_describir(x) for x in pasos)
    prefijo = f'{PREFIJO_LECCION} "{frase}"'
    m = _memoria()
    m["datos"] = [d for d in m["datos"] if not d.startswith(prefijo)] + [f"{prefijo}, quiere: {pasos_txt}."]
    _guardar_memoria(m)
    registrar("aprendizaje", "lección: " + frase + " -> " + pasos_txt)


def _lecciones():
    return [d for d in _memoria()["datos"] if d.startswith(PREFIJO_LECCION)]


def _migrar_frases():
    """Las frases fijas de antes se archivan: el usuario no quiere atajos que se disparen solos ni que se repitan
    como lecciones. Quedan en un respaldo por si alguna vez las quiere ver."""
    datos = _aprendidos()
    if not datos:
        return
    (BASE / "aprendido.json").rename(BASE / f"aprendido_respaldo_{datetime.now():%Y%m%d%H%M%S}.json")
    log.info("frases fijas archivadas: %s", ", ".join(datos))


def accion_aprender(d):
    """Desde la voz: Alexa entendió una corrección ('no, cuando digo X quiero Y')."""
    frase = str(d.get("frase") or "").strip()
    if norm(frase) in ("", "eso", "lo anterior", "lo que dije", "eso que dije"):
        estado = cargar_estado()
        if time.time() - estado.get("ultimo_no_entendido_ts", 0) < 900:
            frase = str(estado.get("ultimo_no_entendido") or "")
    pasos = d.get("pasos") or []
    if isinstance(pasos, str):
        pasos = _partir_pasos(pasos)
    pasos = [x for x in pasos if x]
    if not frase or not pasos:
        return False, "No entendí qué aprender."
    _guardar_leccion(frase, pasos)
    hecho = _ejecutar_pasos(pasos) if d.get("ejecutar", True) else ""
    estado = cargar_estado()
    estado.pop("ultimo_no_entendido", None)
    guardar_estado(estado)
    return True, (hecho + " " if hecho and hecho != "Listo." else "") + "Entendido, lo tengo en cuenta para la próxima."


def _buscar_aprendido(texto):
    import difflib
    objetivo = norm(texto).strip(" .!?¡¿,")
    datos = _aprendidos()
    if objetivo in datos:
        return datos[objetivo]
    mejor, puntaje = None, 0.0
    for frase, comandos in datos.items():       # que tolere cómo lo digas
        if not frase:
            continue
        if len(frase) >= 5 and re.search(r"(^|\s)" + re.escape(frase) + r"($|\s)", objetivo):
            sobra = objetivo.replace(frase, " ").split()
            if all(w in RELLENO for w in sobra):
                return comandos                 # "poné modo cine porfa"
        r = difflib.SequenceMatcher(None, frase, objetivo).ratio()
        if r > puntaje:
            mejor, puntaje = comandos, r
    return mejor if puntaje >= 0.85 else None   # "modo sine" -> "modo cine"


def _enseñanza(texto):
    """Entiende 'aprendé: modo cine = poné la luz al 10 y escena película'."""
    t = norm(texto)
    if not t.startswith(("aprende", "aprendé", "ensena", "enseña", "cuando diga", "cuando te diga",
                         "cuando digo", "cuando te digo", "no, cuando digo", "no cuando digo")):
        return None
    if ":" in texto and not t.startswith(("cuando", "no")):
        cuerpo = texto.split(":", 1)[1]
    else:
        palabras = texto.split()
        salto = 1 if t.startswith(("aprend", "ensen", "enseñ")) else 2
        while salto < len(palabras) and norm(palabras[salto - 1]) in ("te", "cuando", "no", "no,"):
            salto += 1
        cuerpo = " ".join(palabras[salto:]).lstrip(": ")
    for separador in ("=", " quiero que ", " quiero ", " hace ", " hacé ", " significa ", ",", " es ", " ->"):
        if separador in cuerpo.lower():
            i = cuerpo.lower().index(separador)
            frase, acciones = cuerpo[:i].strip(), cuerpo[i + len(separador):].strip()
            break
    else:
        return ("No entendí qué enseñarme. Decímelo así: cuando diga modo cine, poné la luz al 10 "
                "y después escena película")
    frase = frase.strip(' "\'')
    comandos = _partir_pasos(acciones)
    if not frase or not comandos:
        return "Me falta la frase o lo que tengo que hacer."
    _guardar_leccion(frase, comandos)
    return "Entendido: cuando digas '" + frase + "', " + " y después ".join(comandos) + ". Lo tengo en cuenta."


RELLENO = {"porfa", "por", "favor", "che", "dale", "ahora", "ya", "plis", "please", "rapido", "loco", "amigo"}


def _olvidar_frase(texto):
    """'olvidá lo de abrir whatsapp', 'borrá la frase modo cine', 'olvidá todas las frases'."""
    import difflib
    datos = _aprendidos()
    objetivo = norm(re.sub(r"^(olvidate|olvida|olvidá|borra|borrá|elimina|eliminá)\s+(de\s+)?(la\s+|las\s+)?"
                           r"(frases?\s+)?(lo\s+de\s+|eso\s+de\s+)?", "", texto.strip(), flags=re.I)).strip(' ".')
    todas = objetivo in ("todo", "todas", "todas las frases", "todas las frases que te ensene", "frases",
                         "lo que aprendiste", "todo lo que aprendiste")

    def coincide(f):
        return todas or bool(objetivo and (objetivo in f or f in objetivo
                                           or difflib.SequenceMatcher(None, f, objetivo).ratio() >= 0.7))

    quedan = {f: c for f, c in datos.items() if not coincide(f)}
    borradas = [f for f in datos if f not in quedan]
    m = _memoria()
    for d in list(m["datos"]):
        x = re.match(PREFIJO_LECCION + r' "(.+?)"', d)
        if x and coincide(norm(x.group(1))):
            m["datos"].remove(d)
            borradas.append(x.group(1))
    if not borradas:
        return None
    _guardar_memoria(m)
    if datos:
        (BASE / "aprendido.json").write_text(json.dumps(quedan, indent=2, ensure_ascii=False), encoding="utf-8")
    registrar("aprendizaje", "olvidé: " + ", ".join(borradas))
    return "Listo, me olvidé de: " + ", ".join(borradas) + "."


def _es_luz(objetivo):
    """¿El pedido nombra una luz o un dispositivo de la casa que conozco?"""
    if re.search(r"\b(luz|luces|lampara|lamparita|velador|foco|led|enchufe)\b", objetivo):
        return True
    try:
        conocidos = [norm(x) for x in _casa_modulo()._guardados()] + [norm(x) for x in (CONFIG.get("casa_apodos") or {})]
    except Exception:
        conocidos = []
    return any(c and (c in objetivo or objetivo in c) for c in conocidos if len(c) > 3)


def _orden_telegram(texto, profundidad=0):
    """Interpreta lo que escribiste. Lo inequívoco se resuelve al toque; todo lo demás lo entiende la IA."""
    t = norm(texto).strip()
    if t.startswith("/"):
        t = t[1:].strip()
    if t in ("start", "ayuda", "help", "que podes hacer", "que sabes hacer vos"):
        return AYUDA_TELEGRAM

    if profundidad == 0:
        for paso in (_enseñanza,):                      # "cuando diga X, hacé Y" (se guarda como lección)
            r = paso(texto)
            if r:
                return r
        confirmado = _confirmaciones_telegram(t)      # "sí" / "no" a lo que quedó esperando
        if confirmado:
            return confirmado

    rapido_pc = _atajos_telegram(t)                  # captura, estado, cancelar, archivos, cerrar, apagar
    if rapido_pc:
        return rapido_pc

    # frases que me enseñaste (la frase entera, no metida en un pedido más largo)
    if profundidad < 2:
        comandos = _buscar_aprendido(texto)
        if comandos:
            return _ejecutar_pasos(comandos, profundidad + 1)

    # memoria y frases aprendidas
    if t in ("que sabes de mi", "que te acordas", "que recordas", "mi memoria", "que sabes de mi vida"):
        return accion_que_sabes({})[1]
    if t in ("que sabes hacer", "que aprendiste", "aprendidos", "mis frases", "que frases sabes", "frases",
             "que aprendiste de mi"):
        lecciones = _lecciones()
        if not lecciones:
            return "Todavía no aprendí nada especial. Lo voy haciendo solo: si me equivoco, decime qué querías."
        return "Esto aprendí de vos:" + chr(10) + chr(10).join("• " + x for x in lecciones[-25:]) + \
            chr(10) + chr(10) + "Para borrar algo: olvidá lo de <frase>."
    if t.startswith(("olvid", "borra la frase", "borra las frases", "elimina la frase")):
        if "frase" in t or not t.startswith(("olvidate de", "olvida que")):
            olvidada = _olvidar_frase(texto)
            if olvidada:
                return olvidada
        borrados = olvidar_dato(re.sub(r"^(olvidate|olvida|olvidá)\s+(de\s+|que\s+)?(lo\s+de\s+|eso\s+de\s+)?", "",
                                       texto.strip(), flags=re.I))
        if borrados:
            return "Listo, lo olvidé."
    if t.startswith(("acordate", "acuerdate", "recorda que", "no te olvides que")):
        dato = re.sub(r"^\S+\s+(que\s+)?", "", texto.strip()).strip()
        if dato:
            recordar_dato(dato)
            return "Listo, me lo guardo: " + dato[:150]

    # WhatsApp con dos puntos: "whatsapp a Juan: llego tarde" / "corregí el mensaje a Juan: ..."
    if ":" in texto and t.startswith(("whatsapp a ", "wpp a ", "mandale a ", "manda a ", "mensaje a ",
                                      "corregi ", "edita ", "cambia el mensaje")):
        cabeza, mensaje = texto.split(":", 1)
        contacto = cabeza.rsplit(" a ", 1)[-1].strip() if " a " in cabeza else ""
        tipo = "editar" if norm(cabeza).startswith(("corregi", "edita", "cambia")) else "enviar"
        ok, dicho = _preparar_whatsapp({"contacto": contacto, "mensaje": mensaje.strip()}, tipo)
        return dicho + (" ¿Lo hago? Respondé: sí" if ok else "")

    # avisos y rutinas: "recordame cada 2 horas tomar agua", "todos los días a las 7 prendé la luz"
    programa = _programa_desde_texto(texto) if profundidad == 0 else None
    if programa:
        return accion_programar(programa)[1]

    # avisos y rutinas (frases claras)
    if t.strip(" ?.") in ("avisos", "mis avisos", "programados", "rutinas", "mis rutinas", "que avisos tengo",
                          "que tengo programado", "mis recordatorios", "que recordatorios tengo"):
        return accion_programados({})[1]
    m = re.match(r"(borra|cancela|elimina|saca)r?\s+(el|la|los|las)?\s*(aviso|rutina|recordatorio)s?\s+"
                 r"(de\s+|del\s+|que\s+)?(.*)", t)
    if m:
        return accion_borrar_programado({"texto": m.group(5) or ""})[1]

    # alertas y aparatos (frases claras)
    if t.strip(" ?.") in ("que alertas tengo", "alertas", "mis alertas", "como estan las alertas"):
        return accion_alertas({})[1]
    m = re.match(r"(activa|desactiva|prende|apaga|saca|pone)r?\s+(las\s+|la\s+)?(alertas?|avisos?)\s*(de\s+la\s+|del\s+|de\s+)?"
                 r"([a-z]+)?", t)
    if m and "alerta" in t:
        return accion_alertas({"tipo": m.group(5) or "todas",
                               "activar": m.group(1) in ("activa", "prende", "pone")})[1]
    if t.strip(" ?.") in ("busca aparatos", "busca aparatos nuevos", "buscar aparatos", "hay aparatos nuevos"):
        return accion_buscar_aparatos({})[1]

    # lista de compras (frases claras)
    if t.strip(" ?.") in ("compras", "lista de compras", "la lista", "la lista de compras", "que tengo que comprar"):
        return accion_compras({})[1]
    m = re.match(r"(agrega|suma|anota|pone)r?\s+(.+?)\s+(a|en)\s+(la\s+)?lista(\s+de\s+compras)?$", t)
    if m:
        return accion_compras({"agregar": texto.split(" ", 1)[1][:len(m.group(2)) + 1].strip()})[1]
    m = re.match(r"(saca|borra|quita)r?\s+(el |la |los |las )?(.+?)\s+de\s+(la\s+)?lista", t)
    if m:
        return accion_compras({"quitar": m.group(3)})[1]
    if t.strip(" .") in ("vacia la lista", "vaciar la lista", "borra la lista de compras", "borra toda la lista"):
        return accion_compras({"vaciar": True})[1]

    # luces: solo si el pedido nombra una luz o un dispositivo conocido
    for verbo, accion in (("prende", "prender"), ("prendi", "prender"), ("encende", "prender"),
                          ("apaga", "apagar"), ("apagu", "apagar")):
        if t.startswith(verbo):
            objetivo = t.split(" ", 1)[1] if " " in t else "luz"
            if _es_luz(objetivo) and " y " not in objetivo:
                return accion_casa({"dispositivo": objetivo, "accion": accion}, remoto=True)[1]
    if re.search(r"\b(luz|luces|lampara|velador)\b", t) and re.search(
            r"\b(esta|estan|quedo|quedaron|sigue|siguen)\s+(prendid|encendid|apagad)|^como (esta|estan) la", t):
        m = re.search(r"\b(?:la|las|el)\s+((?:luz|luces|lampara|velador)(?:\s+del?\s+\w+)?)", t)
        return accion_casa({"dispositivo": m.group(1) if m else "luz", "accion": "estado"}, remoto=True)[1]
    if re.search(r"\b(luz|luces)\b", t) and " y " not in t:
        if any(x in t for x in (" baja", " tenue", " suave")):
            return accion_casa({"dispositivo": "luz", "accion": "brillo", "valor": 20}, remoto=True)[1]
        if any(x in t for x in (" alta", " maxima", " fuerte", " a full")):
            return accion_casa({"dispositivo": "luz", "accion": "brillo", "valor": 100}, remoto=True)[1]
        numeros = re.findall(r"\b\d{1,3}\b", t)
        if numeros and re.search(r"\b(al|a|en)\s+\d{1,3}", t):
            return accion_casa({"dispositivo": "luz", "accion": "brillo", "valor": int(numeros[-1])}, remoto=True)[1]
        for palabra in t.replace(",", " ").split():
            try:
                if _casa_modulo()._color(palabra):
                    return accion_casa({"dispositivo": "luz", "accion": "color", "valor": palabra}, remoto=True)[1]
            except Exception:
                break
        if any(x in t for x in ("calida", "calido", "fria", "frio", "neutra")):
            return accion_casa({"dispositivo": "luz", "accion": "temperatura", "valor": t}, remoto=True)[1]
    m = re.match(r"(escena|modo)\s+(.+)$", t)
    if m:
        try:
            if _casa_modulo()._id_escena(m.group(2))[0] is not None:
                return accion_casa({"dispositivo": "luz", "accion": "escena", "valor": m.group(2)}, remoto=True)[1]
        except Exception:
            pass

    # charla simple: no hace falta la IA
    corto = t.strip(" .!?¡¿")
    if corto in ("gracias", "gracias crack", "gracias genio", "mil gracias", "muchas gracias", "genio", "crack",
                 "joya", "perfecto", "buenisimo", "excelente", "de diez", "10 puntos"):
        return "¡De nada! Cualquier cosa, acá estoy."
    if corto in ("ok", "okey", "oka", "dale", "listo", "bueno", "de una", "buenisimo gracias", "ok gracias", "👍"):
        return "👍"
    if corto in ("hola", "buenas", "buen dia", "buenos dias", "buenas tardes", "buenas noches", "que tal", "hola cerebro",
                 "estas", "estas ahi"):
        return "¡Hola! ¿En qué te ayudo?"

    # música que ya suena
    for patron, que in MUSICA_CONTROL:
        if re.match(patron, corto):
            return accion_musica_control({"accion": que})[1]

    # agenda, mails, salud de la PC y resumen
    m = re.match(r"(que|q) (tengo|hay)( en (la|mi) agenda)?( para)?( (hoy|manana|pasado manana|esta semana|la semana|"
                 r"el (lunes|martes|miercoles|jueves|viernes|sabado|domingo)))$|(mi |la )?agenda( de| para)?( (hoy|"
                 r"manana|pasado manana|la semana|esta semana|el \w+))?$|tengo algo( para)? (hoy|manana|pasado manana|"
                 r"el \w+)$", corto)
    if m and not re.match(r"(que|q) (tengo|hay)$", corto):
        cuando = _fecha_de_texto(corto)
        return accion_agenda({"semana": True} if cuando == "semana" else {"fecha": cuando.isoformat()})[1]
    if re.match(r"(tengo )?(algun )?(mails?|correos?|e-?mails?)( nuevos?| sin leer)?$|(que|q) (mails|correos) tengo$|"
                r"(revisa|revisame|resumi|resumime|lee|leeme|chequea|fijate)( el| los| mi| mis)? (mail|mails|correo|"
                r"correos|e-?mails?|gmail)$|me (llego|llegaron) (algun |mails|correos|mail|correo)", corto):
        return accion_mails({})[1]
    if re.match(r"(como (esta|anda|va) la (pc|compu|computadora|maquina)|salud de la (pc|compu)|esta bien la "
                r"(pc|compu)|cuanto espacio (libre )?(queda|hay|tiene|me queda)( en)?( el disco| la pc| la compu)?)$|"
                r"cuanto (espacio|lugar)\b.*\b(disco|pc|compu|computadora)\b", corto):
        return accion_salud_pc({})[1]
    if re.search(r"\b(pc|compu|computadora|maquina)\b.*\b(lent[ao]|trabad[ao]|colgad[ao]|tildad[ao]|pesad[ao])\b|"
                 r"\b(lent[ao]|trabad[ao]|colgad[ao]|tildad[ao])\b.*\b(pc|compu|computadora|maquina)\b", corto) \
            and not re.search(r"\b(revisa a fondo|fijate que la pone|arregla|optimiza|limpia)\b", corto):
        return accion_salud_pc({"lenta": True})[1]
    if corto in ("resumen", "el resumen", "resumen del dia", "resumen de hoy", "resumen de la manana",
                 "mandame el resumen", "dame el resumen", "pasame el resumen"):
        return accion_resumen_manana({"ahora": True})[1]
    if re.search(r"\bresumen\b", t) and re.search(r"\b(a las|alas)\s+\d", t):
        dias = "semana" if re.search(r"lunes a viernes|dias de semana|dias habiles", t) else None
        return accion_resumen_manana({"hora": t.split("a las", 1)[-1] if "a las" in t else t.split("alas", 1)[-1],
                                      **({"dias": dias} if dias else {})})[1]
    if re.search(r"\bresumen\b", t) and re.match(r"(desactiva|saca|apaga|frena|cancela|no me mandes)", t):
        return accion_resumen_manana({"activar": False})[1]

    # datos en vivo (frases claras)
    conversion = _conversion(t)
    if conversion:
        return conversion
    m = re.search(r"\b(euro|real|bitcoin|ethereum|chileno|uruguayo|cripto)s?\b", t)
    if m and len(t) < 50 and not re.search(r"\d", t):
        return _info().cotizacion(m.group(1))
    m = re.match(r"(como salio|cuando juega|contra quien juega|a que hora juega|resultado de|como le fue a|"
                 r"como va el partido de)\s+(el |la )?(.+?)[?!. ]*$", t)
    if m:
        r = _info().futbol(m.group(3))
        if not r.startswith("No encontr"):
            return r
    if re.search(r"\bferiados?\b", t) and len(t) < 60:
        return _info().proximo_feriado()
    if "riesgo pais" in t and len(t) < 45:
        return _info().riesgo_pais()
    if "inflacion" in t and len(t) < 45 and not t.startswith(("que es", "explicame")):
        return _info().inflacion()
    if t.startswith(("noticias", "titulares", "que noticias", "que paso hoy", "las noticias")):
        m = re.search(r"\b(sobre|de|del)\s+(.+)$", t)
        return _info().noticias(m.group(2) if m else "", con_links=True)
    if t.startswith(("clima", "el clima", "que tiempo", "como esta el tiempo", "va a llover", "pronostico")):
        ciudad = texto.rsplit(" en ", 1)[1].strip(" ?") if " en " in texto else ""
        return accion_clima({"ciudad": ciudad, "dia": 1 if "manana" in t else 0})[1]
    if t.strip(" ?") in ("dolar", "el dolar", "como esta el dolar", "a cuanto esta el dolar", "dolar blue",
                         "cuanto esta el dolar", "q onda el dolar", "que onda el dolar"):
        return accion_dolar({})[1]

    # notas y pendientes (frases claras)
    if t.startswith(("pendiente:", "pendiente ")):
        return accion_nota({"texto": texto.split(" ", 1)[1].lstrip(": "), "categoria": "pendiente"})[1]
    if t.startswith(("anota:", "anota ", "anotame ", "nota:", "idea:")):
        cuerpo = texto.split(" ", 1)[1].lstrip(": ") if " " in texto else ""
        if cuerpo:
            return accion_nota({"texto": cuerpo, "categoria": "idea"})[1]
    if t.strip(" ?") in ("pendientes", "mis pendientes", "que pendientes tengo"):
        return accion_pendientes({})[1]
    if t in ("estado", "info", "pc"):
        return accion_info_pc({})[1]
    if t in ("diagnostico", "log"):
        return accion_diagnostico({})[1]

    if profundidad > 0:      # un paso de una frase aprendida: lo entiende la IA (sin encadenar más frases)
        return interpretar_con_ia(texto, anidado=True) or ("No supe hacer: " + texto[:80])

    # todo lo demás lo entiende la IA; si hace falta trabajo largo, se lo pasa a Claude
    estado = cargar_estado()
    estado["mensaje_anterior"] = estado.get("ultimo_no_entendido", "")
    estado["ultimo_no_entendido"] = texto
    estado["ultimo_no_entendido_ts"] = int(time.time())
    guardar_estado(estado)
    respuesta_ia = interpretar_con_ia(texto)
    if respuesta_ia:
        return respuesta_ia
    threading.Thread(target=_reintentar_ia, args=(texto,), daemon=True).start()
    return "La IA está con mucha demanda en este momento. Te respondo apenas pueda."


MUSICA_CONTROL = (
    (r"(pausa|pausala|pausa la musica|pone pausa|para la musica|frena la musica|deten la musica|stop|parala)$", "pausa"),
    (r"(segui|reanuda|reanudala|continua|play|dale play|pone play|segui con la musica|volve a poner la musica|"
     r"segui con lo que estaba escuchando|pone lo ultimo que escuchaba|pone la musica de nuevo)$", "seguir"),
    (r"(siguiente|siguiente tema|siguiente cancion|pasala|otro tema|otra cancion|cambiala|salteala)$|"
     r"(pasa|pasame|salta|saltea|cambia|cambiame)( este| ese| el| la| de| al)? (tema|cancion|siguiente)\b", "siguiente"),
    (r"(anterior|tema anterior|cancion anterior|volve al tema anterior|la anterior|volve un tema)$", "anterior"),
    (r"(que (esta sonando|suena|tema es este|tema es esto|cancion es esta|cancion es esto|estoy escuchando|"
     r"musica esta sonando)|como se llama (este tema|esta cancion))$", "que_suena"),
)


VERBOS_TAREA = ("arma", "armame", "crea", "creame", "hace", "haceme", "busca", "buscame", "investiga", "ordena",
                "organiza", "descarga", "baja", "instala", "escribi", "redacta", "compara", "calcula", "revisa",
                "mové", "move", "copia", "renombra", "convertí", "converti", "prepara", "prepará")


def _conversion(t):
    """'cuántos pesos son 100 dólares', 'pasame 50 euros a pesos', 'cuántos dólares son 100000 pesos'."""
    m = re.search(r"(\d[\d.]*(?:,\d+)?)\s*(dolares?|euros?|reales?|pesos?)\b", t)
    if not m or not re.search(r"\b(cuant\w*|pasame|converti|pasa|cambiame|son|en pesos|a pesos|en dolares|a dolares)\b", t):
        return None
    monto = float(m.group(1).replace(".", "").replace(",", "."))
    de = m.group(2)
    otras = [x for x in ("dolar", "euro", "real", "peso") if x in t and not de.startswith(x)]
    return _info().convertir(monto, de, otras[0] if otras else ("peso" if not de.startswith("peso") else "dolar"))


def _reintentar_ia(texto):
    """La IA no contestó: se reintenta en un rato. Si no vuelve y era un trabajo, lo hace Claude."""
    for espera in (20, 45, 90):
        time.sleep(espera)
        r = interpretar_con_ia(texto)
        if r:
            _telegram_responder(r)
            return
    if norm(texto).split()[:1] and norm(texto).split()[0] in tuple(norm(v) for v in VERBOS_TAREA):
        _telegram_responder("La IA sigue caída, así que se lo paso a Claude en la PC.")
        hilo_consulta_remota(texto)
    else:
        _telegram_responder("Perdón, la IA de Google no me está respondiendo. Probá de nuevo en un rato.")


# ---------- entender lo que escribís, con la IA gratis de Google ----------

MODELOS_IA = (("gemini-flash-lite-latest", None), ("gemma-4-26b-a4b-it", None),
              ("gemini-3.5-flash-lite", "minimal"), ("gemini-3.6-flash", "minimal"))
# Primero los que tienen más cupo gratis y contestan rápido; los demás solo si esos fallan o tardan.
TANDAS_TEXTO = (MODELOS_IA[:2], MODELOS_IA[2:])
TANDAS_IMAGEN = ((("gemini-flash-lite-latest", None), ("gemini-3.5-flash-lite", "minimal")),
                 (("gemini-3.6-flash", "minimal"),))
_AGOTADOS = {}      # modelo -> hasta cuándo no llamarlo (se quedó sin cupo o está saturado)


def _carrera(cuerpo_para, clave, timeout, valida=None, tandas=TANDAS_TEXTO):
    """Prueba los modelos por tandas y devuelve la primera respuesta buena (o None)."""
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    pool = ThreadPoolExecutor(max_workers=4)
    pendientes = set()
    limite = time.time() + timeout
    try:
        for i, tanda in enumerate(tandas):
            for modelo, pensar in tanda:
                if _AGOTADOS.get(modelo, 0) < time.time():
                    pendientes.add(pool.submit(_llamar_gemini, modelo, pensar, cuerpo_para(modelo), clave, timeout))
            fin_tanda = limite if i == len(tandas) - 1 else min(limite, time.time() + 2.5)
            while pendientes and time.time() < fin_tanda:
                listos, pendientes = wait(pendientes, timeout=max(0.05, fin_tanda - time.time()),
                                          return_when=FIRST_COMPLETED)
                for f in listos:
                    try:
                        texto = f.result()
                    except Exception as e:
                        log.info("modelo de IA falló: %s", str(e)[:120])
                        continue
                    if valida is None or valida(texto):
                        return texto
                    log.info("respuesta de IA descartada: %s", texto[:120])
        while pendientes and time.time() < limite:  # lo último que quedó en camino
            listos, pendientes = wait(pendientes, timeout=max(0.05, limite - time.time()), return_when=FIRST_COMPLETED)
            for f in listos:
                try:
                    texto = f.result()
                except Exception:
                    continue
                if valida is None or valida(texto):
                    return texto
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return None

ACCIONES_IA = {
    "casa": '{"dispositivo": "luz", "accion": "prender|apagar|brillo|color|temperatura|escena|estado", "valor": ...} '
            'luces y enchufes (brillo 1 a 100; color "rojo"; temperatura "cálida|neutra|fría"; escena "fiesta", "relax"...)',
    "musica": '{"busqueda": "...", "servicio": "youtube|spotify"} poner música en la PC',
    "volumen": '{"cambio": "subir|bajar|silenciar", "pasos": 5} o {"nivel": 0 a 100} volumen de la PC '
               '(cada paso es 2 por ciento)',
    "abrir_app": '{"nombre": "..."} abrir un programa o app de la PC (WhatsApp, Claude, Chrome, Spotify, Excel...)',
    "abrir_web": '{"url": "..."} o {"busqueda": "..."}',
    "nota": '{"texto": "...", "categoria": "idea|nota|pendiente"}',
    "buscar_notas": '{"consulta": "..."}',
    "pendientes": "{} leer los pendientes",
    "completar_pendiente": '{"texto": "..."}',
    "whatsapp": '{"contacto": "...", "mensaje": "..."} preparar un WhatsApp (se envía cuando el usuario responde "sí")',
    "whatsapp_editar": '{"contacto": "...", "mensaje": "texto nuevo"} corregir el último mensaje enviado',
    "whatsapp_leer": '{"contacto": "..."} leer y resumir un chat de WhatsApp ("qué me escribió Laura", '
                     '"entrá al chat de Alfred"); "yo" es su propio chat',
    "whatsapp_resumen": "{} resumir los chats de WhatsApp sin leer (\"qué mensajes tengo\")",
    "whatsapp_archivo": '{"contacto": "...", "archivo": "nombre del archivo o ruta", "mensaje": "comentario opcional"} '
                        'mandar un archivo o foto de la PC por WhatsApp (se envía cuando dice "sí")',
    "recordar": '{"dato": "..."} guardar para siempre algo del usuario (nombres, gustos, apodos, cómo llama a sus cosas)',
    "olvidar": '{"dato": "..."}',
    "programar": '{"texto": "...", "tipo": "aviso|orden", "cada_minutos": N, "hora": "HH:MM", "dias": ["lunes"], '
                 '"en_minutos": N, "desde": "HH:MM", "hasta": "HH:MM"} avisos al celular o rutinas ("orden" = la PC '
                 'hace el texto a esa hora, ej "prendé la luz")',
    "programados": "{} ver avisos y rutinas",
    "borrar_programado": '{"texto": "..." | "todos"}',
    "compras": '{"agregar": [...]} | {"quitar": [...]} | {"vaciar": true} | {} para leer la lista',
    "clima": '{"ciudad": "...", "dia": 0} (0 hoy, 1 mañana, hasta 6)',
    "dolar": "{} cotización del dólar",
    "noticias": '{"tema": "..."}',
    "argentina": '{"dato": "feriado|riesgo_pais|inflacion"}',
    "futbol": '{"equipo": "..."} último y próximo partido',
    "cotizacion": '{"moneda": "euro|real|peso chileno|peso uruguayo|bitcoin|ethereum"}',
    "convertir": '{"monto": N, "de": "dolar|euro|real|peso", "a": "dolar|euro|real|peso"}',
    "aprender": '{"frase": "su pedido ANTERIOR, tal cual (no la corrección)", "pasos": ["solo lo que en '
                'realidad quería"]} cuando el usuario te corrige ("no, eso no", "te dije que...", "lo que quería '
                'era..."): además de hacer lo correcto, guardalo como lección para entenderlo mejor la próxima',
    "info_pc": "{} hora, disco y datos de la PC",
    "claude": '{"instruccion": "..."} trabajo largo en la PC: archivos, investigar en internet, programas, manejar '
              'la pantalla, crear un Excel o un documento y mandárselo, o cualquier cosa que no esté en esta lista. '
              'Si el mensaje trae la ruta de un archivo que mandó el usuario, pasala en la instrucción',
    "captura": "{} mandarle una foto de la pantalla de la PC",
    "enviar_archivo": '{"nombre": "..."} buscar un archivo en la PC (Escritorio, Documentos, Descargas) y mandárselo',
    "cerrar_app": '{"nombre": "..."} cerrar un programa abierto',
    "sistema": '{"orden": "bloquear|apagar|reiniciar|suspender|cancelar_apagado"} (apagar, reiniciar y suspender '
               'le piden confirmación)',
    "tareas_estado": "{} qué está haciendo la PC ahora",
    "alertas": '{"tipo": "dolar|lluvia|pc|mails|agenda|todas", "activar": true|false} prender o apagar los avisos '
               'automáticos (dólar, lluvia, problemas de la PC, mails importantes, eventos de la agenda); sin "activar" '
               '= decir cómo están',
    "agenda": '{"dia": 0} (0 hoy, 1 mañana...) o {"fecha": "AAAA-MM-DD"} o {"semana": true} qué tiene en su Google '
              'Calendar. No puede agregar eventos: para que le avise de algo usá "programar"',
    "mails": "{} resumen de los mails de Gmail sin leer",
    "salud_pc": '{"lenta": true si dice que anda lenta o trabada} cómo está la PC: disco, memoria, procesador, '
                'internet, hace cuánto está prendida',
    "musica_control": '{"accion": "pausa|seguir|siguiente|anterior|que_suena"} controlar la música que ya suena en la '
                      'PC (pausar, reanudar, pasar de tema, qué tema es)',
    "resumen_manana": '{"ahora": true} mandarle ya el resumen del día (clima, agenda, pendientes, mails, dólar...); o '
                      '{"hora": "HH:MM", "activar": true|false, "dias": "todos|semana", "equipo": "..."} configurar el '
                      'resumen que le llega solo cada mañana',
    "nombrar_aparato": '{"aparato": "...", "nombre": "..."} ponerle nombre a una luz o aparato ("a la luz nueva '
                       'llamala luz del living")',
    "buscar_aparatos": "{} buscar aparatos nuevos en la red de la casa",
    "cancelar_tarea": "{} frenar la tarea que está haciendo la PC",
}


def _clave_gemini():
    clave = str(CONFIG.get("gemini_api_key") or "").strip()
    if not clave:
        try:
            clave = (BASE / "gemini_key.txt").read_text(encoding="utf-8").strip()
        except OSError:
            clave = ""
    return clave


def _llamar_gemini(modelo, pensar, cuerpo, clave, timeout):
    gen = dict(cuerpo["generationConfig"])
    if pensar:
        gen["thinkingConfig"] = {"thinkingLevel": pensar}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
        data=json.dumps({**cuerpo, "generationConfig": gen}).encode(),
        headers={"x-goog-api-key": clave, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            datos = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 429:            # sin cupo (por minuto o por día): no insistir por un rato
            _AGOTADOS[modelo] = time.time() + (3600 if "PerDay" in e.read().decode(errors="ignore") else 30)
        elif e.code in (500, 503):   # saturado: un minuto de descanso
            _AGOTADOS[modelo] = time.time() + 60
        raise
    partes = datos["candidates"][0]["content"].get("parts", [])
    texto = "".join(p.get("text", "") for p in partes if not p.get("thought")).strip()
    if not texto:
        raise ValueError(modelo + ": respuesta vacía")
    return texto


def preguntar_ia(sistema, mensaje, timeout=8, valida=None, json_estricto=False):
    """Consulta varios modelos gratis a la vez y se queda con la primera respuesta BUENA.

    valida(texto) decide si una respuesta sirve; si un modelo contesta mal, se espera al siguiente.
    Si todos fallan (Google saturado), se reintenta una vez.
    """
    clave = _clave_gemini()
    if not clave:
        return None
    base = {"systemInstruction": {"parts": [{"text": sistema}]},
            "contents": [{"role": "user", "parts": [{"text": mensaje}]}],
            "generationConfig": {"maxOutputTokens": 700, "temperature": 0.2}}

    def cuerpo_para(modelo):
        if json_estricto and not modelo.startswith("gemma"):     # Gemma no acepta el modo JSON
            return {**base, "generationConfig": {**base["generationConfig"], "responseMimeType": "application/json"}}
        return base

    for intento in range(2):
        texto = _carrera(cuerpo_para, clave, timeout, valida)
        if texto:
            return texto
        if intento == 0:
            time.sleep(1.5)                  # Google saturado o respuestas malas: un reintento
    return None


def _json_de(texto):
    """Saca el primer objeto JSON de la respuesta, aunque venga con texto o ```json alrededor."""
    texto = texto or ""
    decodificador = json.JSONDecoder()
    for i, letra in enumerate(texto):
        if letra != "{":
            continue
        try:
            obj, _ = decodificador.raw_decode(texto[i:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _sistema_ia():
    return (
        "Sos Cerebro, el asistente personal del usuario. Te escribe por Telegram desde el celular, en español de "
        "Argentina: voseo, abreviaturas, sin tildes y con errores de tipeo. Entendé lo que quiere aunque lo diga "
        "mal o a medias; si es ambiguo, elegí lo más probable en vez de preguntar." + chr(10) +
        "Respondé SOLO con un JSON así:" + chr(10) +
        '{"respuesta": "texto corto para el usuario", "acciones": [{"accion": "...", "datos": {...}}]}' + chr(10) +
        "Acciones:" + chr(10) + chr(10).join("- " + k + " " + v for k, v in ACCIONES_IA.items()) + chr(10) +
        "Reglas:" + chr(10) +
        "- Si pide varias cosas, poné varias acciones en orden." + chr(10) +
        "- Si pregunta cómo está algo (\"¿está prendida la luz?\"), usá la acción que lo consulta (casa con "
        "\"estado\"). Nunca dejes respuesta y acciones vacías a la vez." + chr(10) +
        "- Si hay acciones, dejá \"respuesta\" vacía: el resultado de cada acción ya se le muestra." + chr(10) +
        "- Si es charla o una pregunta que sabés contestar, contestá en \"respuesta\" sin acciones." + chr(10) +
        "- Nunca digas que no podés: si ninguna acción sirve, usá \"claude\"." + chr(10) +
        "- Aprendé solo, sin preguntar: si te cuenta algo de él, de su gente o cómo llama a sus cosas, guardalo "
        "con \"recordar\"; si te corrige, hacé lo correcto y agregá \"aprender\"." + chr(10) +
        "- Tené en cuenta lo que ya aprendiste (\"Cuando el usuario dice...\"), pero entendé cada pedido completo: "
        "si pide algo distinto, hacé lo que pide ahora." + chr(10) +
        "- Prohibido comprar, pagar o escribir contraseñas." + chr(10) +
        "- En WhatsApp, el contacto es el que nombra el usuario en ESTE mensaje, o el nombre que ya sabés que le "
        "corresponde (\"mi vieja\" = Marta solo si te lo contó). Nunca uses otro nombre de la charla anterior." + chr(10) +
        "- Respuestas en español rioplatense, cortas, sin markdown, amables y respetuosas: nunca groserías ni "
        "insultos, aunque el usuario las use." + chr(10) +
        "- Si pide algo destructivo o riesgoso (borrar todo, formatear), no lo hagas: explicá con respeto por qué y "
        "ofrecé una alternativa segura." + chr(10) +
        "Fecha y hora: " + ahora() + " (" + NOMBRES_DIA[datetime.now().weekday()] + ")" + chr(10) +
        contexto_memoria(con_historial=True)
    )


RESPUESTAS_VACIAS = {"listo", "hecho", "ok", "okey", "dale", "ya esta", "listo hecho", "entendido", "perfecto"}


def _plan_valido(crudo):
    """Un plan sirve si hace algo o contesta algo de verdad: "Listo." sin ninguna acción es mentira."""
    plan = _json_de(crudo)
    if not isinstance(plan, dict):
        return False
    if plan.get("acciones"):
        return True
    respuesta = str(plan.get("respuesta") or "").strip()
    return bool(respuesta) and norm(respuesta).strip(" .!¡,") not in RESPUESTAS_VACIAS


def _contacto_nombrado(contacto, texto):
    """¿El contacto que eligió la IA sale del mensaje o de algo que el usuario contó? Nunca inventar destinatarios."""
    nombres = [w for w in re.findall(r"\w+", norm(contacto)) if len(w) > 2]
    if not nombres or norm(contacto).strip() in ("yo", "mi chat", "a mi", "mi"):
        return True
    t = norm(texto)
    if any(re.search(r"\b" + re.escape(w), t) for w in nombres):
        return True
    palabras = [w for w in re.findall(r"\w+", t) if len(w) > 3]
    for dato in _memoria()["datos"]:           # "mi vieja se llama Marta": la IA puede usar Marta
        d = norm(dato)
        if any(w in d for w in nombres) and any(re.search(r"\b" + re.escape(p) + r"\b", d) for p in palabras):
            return True
    return False


def interpretar_con_ia(texto, anidado=False):
    """Devuelve la respuesta para el usuario, o None si la IA no está disponible."""
    crudo = preguntar_ia(_sistema_ia(), texto, json_estricto=True, valida=_plan_valido)
    if not crudo:
        return None
    plan = _json_de(crudo)
    partes = [str(plan.get("respuesta") or "").strip()]
    aprendido = recordado = False
    acciones = plan.get("acciones") or []
    if isinstance(acciones, dict):                   # a veces manda una sola acción como objeto
        acciones = [acciones]
    if not isinstance(acciones, list):
        acciones = []
    for a in acciones[:6]:
        if not isinstance(a, dict):
            continue
        nombre = str(a.get("accion") or "")
        if nombre not in ACCIONES_IA and nombre.split("_")[0] in ACCIONES_IA:
            nombre = nombre.split("_")[0]          # "casa_estado" -> "casa"
        # a veces la IA manda los datos sueltos: {"accion": "musica", "busqueda": "..."}
        datos = a.get("datos") if isinstance(a.get("datos"), dict) else {
            k: v for k, v in a.items() if k != "accion"}
        if anidado and nombre in ("frase", "aprender"):
            continue
        if nombre == "aprender":                     # la IA ya hizo lo correcto: solo guardar la lección
            frase = str(datos.get("frase") or "").strip()
            if not frase or norm(frase) == norm(texto):
                frase = str(cargar_estado().get("mensaje_anterior") or "").strip()
            pasos = datos.get("pasos") or []
            if frase and pasos and norm(frase) != norm(texto):
                _guardar_leccion(frase, pasos if isinstance(pasos, list) else _partir_pasos(str(pasos)))
                aprendido = True
            continue
        try:
            if nombre == "claude":
                threading.Thread(target=hilo_consulta_remota, args=(str(datos.get("instruccion") or texto),),
                                 daemon=True).start()
                partes.append("Lo hago en la PC y te aviso cuando termine.")
            elif nombre == "casa":
                partes.append(accion_casa(datos, remoto=True)[1])
            elif nombre == "sistema":
                partes.append(accion_sistema_remoto(datos)[1] or "Hecho.")
            elif nombre in ("whatsapp", "whatsapp_editar", "whatsapp_archivo"):
                if not _contacto_nombrado(str(datos.get("contacto") or ""), texto):
                    partes.append("¿A quién se lo mando? Decime el nombre como lo tenés agendado en WhatsApp "
                                  "(y si querés, contame quién es, así lo recuerdo).")
                    continue
                ok, r = ACCIONES[nombre](datos)
                partes.append(r + (" ¿Lo hago? Respondé: sí" if ok else ""))
            elif nombre in ACCIONES_IA and nombre in ACCIONES:
                ok, r = ACCIONES[nombre](datos)
                recordado = recordado or (ok and nombre == "recordar")
                if ok:
                    anotar_accion(nombre, datos)
                partes.append(str(r or ""))
        except Exception as e:
            log.exception("acción de la IA %s", nombre)
            partes.append("No pude con " + nombre + ": " + str(e)[:80])
    registrar("ia", texto[:120] + " -> " + json.dumps(plan.get("acciones") or [], ensure_ascii=False)[:250])
    if len(partes) > 1 and any(partes[1:]) and len(partes[0]) < 60:
        partes = partes[1:]                          # la acción ya dice lo que pasó: sin "Listo." repetido
    if aprendido:
        partes.append("Lo tengo en cuenta para la próxima.")
    final = " ".join(p for p in partes if p).strip()
    if recordado and final.strip(" .!").lower() in ("", "listo", "ok", "dale", "hecho"):
        final = "Anotado, me lo acuerdo."
    return final or "Listo."


def accion_aprendidos(d):
    """Lo aprendido (lecciones), para que Alexa también lo tenga en cuenta."""
    return True, json.dumps(_lecciones()[-60:], ensure_ascii=False)


def hilo_consulta_remota(instruccion):
    try:
        resultado, error, acciones = correr_claude(
            "El usuario te escribe desde el celular. Hacé lo que pide en esta PC y contestale corto y claro. "
            "Si hace falta manejar la pantalla, usá " + str(BASE / "escritorio.py") + " (captura, clic, escribir, "
            "tecla, abrir). Pedido: " + instruccion,
            permisos_totales=True, etiqueta="telegram", progreso=_progreso_telegram, descripcion=instruccion)
        _entregar("Telegram", instruccion, resultado, error, acciones)
    except Exception as e:
        log.exception("orden de telegram falló")
        _telegram_responder("No pude hacerlo: " + str(e)[:300])


def escuchar_telegram():
    """Escucha los mensajes que le mandás al bot y los ejecuta."""
    if not str(CONFIG.get("telegram_token") or "").strip():
        return
    offset = None
    permitido = None
    inicio = time.time()
    while True:
        try:
            if permitido is None:
                permitido = _telegram_chat_id()
            datos = _telegram("getUpdates", {"timeout": 25, "offset": offset} if offset else {"timeout": 25},
                              timeout=35) or {}
            for u in datos.get("result", []) or []:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                texto = (msg.get("text") or msg.get("caption") or "").strip()
                chat = (msg.get("chat") or {}).get("id")
                llego_archivo = any(msg.get(k) for k in ("document", "photo", "voice", "audio", "video"))
                if (not texto and not llego_archivo) or not chat:
                    continue
                if not permitido:
                    # Hasta que no llegue un "/start", el bot no obedece a nadie: el primer "/start" lo ata a ese chat.
                    if texto.lower().startswith("/start"):
                        estado_cambiar(lambda e, chat=chat: e.__setitem__("telegram_chat_id", chat))
                        permitido = chat
                        log.info("telegram: chat autorizado")
                        _telegram_responder("Listo, desde ahora te hago caso solo a vos desde este chat." + chr(10) +
                                            AYUDA_TELEGRAM)
                    else:
                        log.warning("mensaje de un chat sin autorizar (falta /start): %s", chat)
                    continue
                if str(chat) != str(permitido):
                    log.warning("mensaje de un chat no autorizado: %s", chat)
                    continue
                if float(msg.get("date", 0)) < inicio - 300:   # mensajes viejos: no los ejecutamos
                    continue
                if msg.get("voice") and not texto:          # nota de voz: se pasa a texto y se trata igual
                    try:
                        audio = _descargar_de_telegram(msg, BASE / "audios")
                        texto = transcribir_audio(audio) or ""
                        audio.unlink(missing_ok=True)
                    except Exception:
                        log.exception("nota de voz")
                        texto = ""
                    if not texto:
                        _telegram_responder("No pude entender el audio. ¿Me lo escribís?")
                        continue
                    _telegram_responder("🎤 " + texto)
                elif llego_archivo:                         # foto o archivo: se guarda en Descargas\Cerebro
                    try:
                        guardado = _descargar_de_telegram(msg)
                    except Exception as e:
                        _telegram_responder("No pude bajar el archivo: " + str(e)[:200])
                        continue
                    if not texto:
                        _telegram_responder("Guardé " + guardado.name + " en " + str(guardado.parent) +
                                            ". Si querés que haga algo con él, mandámelo con una indicación.")
                        continue
                    texto += " (el archivo que te mandé está en: " + str(guardado) + ")"
                log.info("orden por telegram: %s", texto[:120])
                registrar("telegram", texto[:200])
                anotar_charla("user", texto)
                try:
                    respuesta = _orden_telegram(texto) or "Listo."
                    if not respuesta.startswith("Panel de Cerebro:"):   # el link lleva el token: no va a la memoria
                        anotar_charla("cerebro", respuesta)
                    _telegram_responder(respuesta)
                except Exception as e:
                    log.exception("orden telegram")
                    _telegram_responder("Se me complicó: " + str(e)[:200])
        except Exception as e:
            log.warning("telegram escucha: %s", str(e)[:150])
            time.sleep(10)


def una_sola_instancia():
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\CerebroPC_ntfy")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)


# PCs donde Cerebro no debe correr nunca (por ejemplo, tu PC principal si lo instalás en una secundaria).
# Se configura en config_pc.json: "equipos_prohibidos": ["NOMBRE-DE-LA-PC"]
EQUIPOS_PROHIBIDOS = {str(x).upper() for x in (CONFIG.get("equipos_prohibidos") or [])}


if __name__ == "__main__":
    if os.environ.get("COMPUTERNAME", "").upper() in EQUIPOS_PROHIBIDOS:
        sys.exit(0)
    una_sola_instancia()
    log.info("Cerebro PC %s iniciado desde %s. Notas en %s", VERSION, BASE, VAULT)
    try:
        _migrar_frases()
    except Exception:
        log.exception("migrar frases")
    # Precargamos el control de la casa: si no, el primer pedido tarda demasiado y Alexa lo corta.
    threading.Thread(target=lambda: _casa_modulo(), daemon=True).start()
    threading.Thread(target=escuchar_telegram, daemon=True).start()
    threading.Thread(target=hilo_programador, daemon=True).start()
    threading.Thread(target=hilo_alertas, daemon=True).start()
    threading.Thread(target=hilo_aparatos, daemon=True).start()
    threading.Thread(target=_aviso_arranque, daemon=True).start()
    threading.Thread(target=hilo_minutero, daemon=True).start()
    try:                                   # panel web local (pc/panel.py): si falla, el agente sigue igual
        _mod("panel").iniciar(sys.modules[__name__])
    except Exception:
        log.exception("panel")
    escuchar()
