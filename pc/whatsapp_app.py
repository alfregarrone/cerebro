"""WhatsApp de escritorio para Cerebro: maneja la app que ya tenés abierta y logueada.

Mira la pantalla con la IA (VER) para elegir el contacto correcto, verificar el chat antes de escribir
y leer mensajes. Sin VER funciona como antes (abre el primer resultado), pero NO envía: exige la IA.

Uso a mano:
  python whatsapp_app.py abrir_chat "Juan Perez"
"""
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
CAPTURAS = BASE / "capturas"

import pyautogui
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import pygetwindow
except ImportError:
    pygetwindow = None

VER = None      # ver(ruta_imagen, pregunta) -> texto. La pone el agente (IA gratis de Google que lee imágenes).
YO = ("yo", "mi", "a mi", "mi mismo", "mi chat", "mi numero", "mensaje a mi", "mi propio chat", "tu", "vos")


class WhatsAppError(Exception):
    pass


def norm(t):
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9@ ]+", " ", t).strip()


def _ventana():
    if pygetwindow is None:
        return None
    for w in pygetwindow.getAllWindows():
        if (w.title or "").strip() == "WhatsApp":
            return w
    for w in pygetwindow.getWindowsWithTitle("WhatsApp"):
        if w.title.strip():
            return w
    return None


def enfocar():
    """Trae WhatsApp al frente; si no está abierto, lo abre. Devuelve True si quedó al frente."""
    w = _ventana()
    if w is None:
        subprocess.Popen(["cmd", "/c", "start", "", "whatsapp:"], creationflags=0x08000000)
        for _ in range(30):
            time.sleep(0.3)
            w = _ventana()
            if w:
                break
        time.sleep(2.0)            # que termine de cargar la primera vez
    if w is None:
        return False
    try:
        if w.isMinimized:
            w.restore()
            time.sleep(0.5)
        w.activate()
    except Exception:
        try:                       # si Windows no deja robar el foco, un clic en la barra de título
            pyautogui.click(max(0, w.left) + w.width // 2, max(0, w.top) + 12)
        except Exception:
            return False
    time.sleep(0.5)
    return True


def region():
    """(izquierda, arriba, ancho, alto) de la ventana de WhatsApp, recortada a la pantalla."""
    w = _ventana()
    ancho_pantalla, alto_pantalla = pyautogui.size()
    izq, arr = max(0, w.left), max(0, w.top)
    return izq, arr, min(w.width - (izq - w.left), ancho_pantalla - izq), min(w.height - (arr - w.top), alto_pantalla - arr)


def captura(nombre=None, ventana=True):
    CAPTURAS.mkdir(exist_ok=True)
    destino = CAPTURAS / (nombre or f"wa_{datetime.now():%H%M%S}.png")
    (pyautogui.screenshot(region=region()) if ventana and _ventana() else pyautogui.screenshot()).save(destino)
    return destino


def _pegar(texto):
    if pyperclip:
        pyperclip.copy(texto)
        pyautogui.hotkey("ctrl", "v")
    else:
        pyautogui.write(texto, interval=0.01)


def _json(texto):
    """Primer JSON (objeto o lista) de la respuesta de la IA."""
    texto = texto or ""
    decodificador = json.JSONDecoder()
    for i, letra in enumerate(texto):
        if letra in "{[":
            try:
                return decodificador.raw_decode(texto[i:])[0]
            except ValueError:
                continue
    return None


def _ver(ruta, pregunta):
    if VER is None:
        raise WhatsAppError("no tengo la IA para mirar la pantalla")
    for _ in range(2):
        datos = _json(VER(ruta, pregunta))
        if datos is not None:
            return datos
    raise WhatsAppError("la IA no pudo leer la pantalla de WhatsApp")


def _caja(v):
    """La caja que devuelve la IA, como [ymin, xmin, ymax, xmax] (a veces viene anidada o dentro de un dict)."""
    if isinstance(v, dict):
        v = v.get("box_2d") or v.get("caja") or v.get("box") or list(v.values())
    while isinstance(v, list) and v and isinstance(v[0], list):
        v = v[0]
    try:
        if isinstance(v, list) and len(v) >= 4:
            return [float(x) for x in v[:4]]
    except (TypeError, ValueError):
        pass
    return None


def _clic_en(caja, reg):
    """Clic en el centro de una caja [ymin, xmin, ymax, xmax] (0-1000) de una captura de la región reg."""
    izq, arr, ancho, alto = reg
    c = _caja(caja)
    if not c:
        raise WhatsAppError("no pude ubicar dónde hacer clic en WhatsApp")
    ymin, xmin, ymax, xmax = c
    pyautogui.click(int(izq + (xmin + xmax) / 2 / 1000 * ancho), int(arr + (ymin + ymax) / 2 / 1000 * alto))


def _elegir(contacto, resultados):
    """Elige el resultado correcto. Devuelve (resultado, None) o (None, motivo)."""
    objetivo = norm(contacto)
    if not resultados:
        return None, f"No encontré a {contacto} en WhatsApp."
    if objetivo in YO:
        propios = [r for r in resultados if r.get("es_uno_mismo")]
        return (propios[0], None) if propios else (None, "No encontré tu propio chat en WhatsApp.")
    nombres = [(r, norm(re.sub(r"\((tu|tú|you)\)", "", str(r.get("nombre", ""))))) for r in resultados]
    exactos = [r for r, n in nombres if n == objetivo]
    if len(exactos) == 1:
        return exactos[0], None
    palabras = objetivo.split()
    parecidos = [r for r, n in nombres if all(p in n.split() or p in n for p in palabras)]
    if len(parecidos) == 1:
        return parecidos[0], None
    if len(parecidos) > 1 or len(exactos) > 1:
        opciones = ", ".join(str(r.get("nombre")) for r in (exactos or parecidos)[:5])
        return None, f"Hay varios contactos parecidos a {contacto}: {opciones}. Decime cuál, con el nombre completo."
    return None, f"No encontré a {contacto} en WhatsApp (aparecen: " + \
        ", ".join(str(r.get("nombre")) for r in resultados[:4]) + ")."


PREGUNTA_RESULTADOS = (
    'Es WhatsApp de escritorio: buscaste "{contacto}". Listá cada resultado de la columna izquierda (chats, '
    'contactos o grupos; no el cuadro de búsqueda ni los títulos de sección). Respondé SOLO JSON: '
    '{{"resultados": [{{"nombre": "...", "es_uno_mismo": true/false, "box_2d": [ymin, xmin, ymax, xmax]}}]}} '
    'con coordenadas normalizadas 0-1000. es_uno_mismo es true solo si dice "(Tú)", "(You)" o "Mensaje para ti".')
PREGUNTA_ENCABEZADO = (
    'Es WhatsApp de escritorio. ¿Qué chat está abierto? Mirá el encabezado de la conversación (arriba, a la derecha '
    'de la lista de chats). Ubicá también la caja para escribir el mensaje (abajo, dice "Escribe un mensaje"). '
    'Respondé SOLO JSON: {"chat": "nombre exacto o null si no hay chat abierto", "es_uno_mismo": true/false, '
    '"caja": [ymin, xmin, ymax, xmax] normalizado 0-1000 o null}')
_CAJA = {}      # dónde quedó la caja de texto del chat abierto (la ubica la verificación)
_PROPIO = {}    # cómo se llama el chat propio del usuario (se aprende la primera vez)


def abrir_chat(contacto, verificar=True):
    """Busca el contacto y abre el chat CORRECTO. Devuelve (ok, texto, nombre_del_chat)."""
    if not enfocar():
        return False, "No pude abrir la aplicación de WhatsApp.", None
    pyautogui.press("esc")
    pyautogui.press("esc")
    pyautogui.hotkey("ctrl", "n")                  # "Nuevo chat": busca contactos, grupos y a uno mismo
    time.sleep(1.0)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.press("backspace")
    if norm(contacto) not in YO:
        _pegar(contacto)
    elif _PROPIO.get("nombre"):                    # el propio chat, por el nombre que ya aprendió
        _pegar(_PROPIO["nombre"])
    time.sleep(1.6)                                # que filtre los resultados
    if VER is None:
        pyautogui.press("enter")
        time.sleep(0.8)
        return True, f"Abrí el chat con {contacto}.", contacto
    reg = region()
    datos = _ver(captura("wa_busqueda.png"), PREGUNTA_RESULTADOS.format(contacto=contacto))
    resultados = [r for r in (datos.get("resultados") if isinstance(datos, dict) else datos) or []
                  if isinstance(r, dict) and r.get("box_2d")]
    elegido, motivo = _elegir(contacto, resultados)
    if not elegido and norm(contacto) in YO:       # si no estaba arriba, se busca como "Tú"
        pyautogui.hotkey("ctrl", "a")
        _pegar("Tú")
        time.sleep(1.4)
        datos = _ver(captura("wa_busqueda.png"), PREGUNTA_RESULTADOS.format(contacto=contacto))
        resultados = [r for r in (datos.get("resultados") if isinstance(datos, dict) else datos) or []
                      if isinstance(r, dict) and r.get("box_2d")]
        elegido, motivo = _elegir(contacto, resultados)
    if not elegido:
        pyautogui.press("esc")
        pyautogui.press("esc")
        return False, motivo, None
    _clic_en(elegido["box_2d"], reg)
    time.sleep(1.2)
    nombre = str(elegido.get("nombre"))
    if elegido.get("es_uno_mismo"):
        _PROPIO["nombre"] = re.sub(r"\s*\((tu|tú|you)\)\s*", "", nombre, flags=re.I).strip() or nombre
    if verificar and not chat_abierto_es(nombre, uno_mismo=bool(elegido.get("es_uno_mismo"))):
        return False, f"No pude confirmar que se abrió el chat de {nombre}; no hice nada.", None
    return True, f"Abrí el chat con {nombre}.", nombre


def chat_abierto_es(nombre, uno_mismo=False):
    """Mira el encabezado y confirma que el chat abierto es el que corresponde (para no escribirle a otro)."""
    reg = region()
    datos = _ver(captura("wa_encabezado.png"), PREGUNTA_ENCABEZADO)
    _CAJA.clear()
    if isinstance(datos, dict) and _caja(datos.get("caja")):
        _CAJA.update(caja=_caja(datos["caja"]), reg=reg)
    if not isinstance(datos, dict) or not datos.get("chat"):
        return False
    if uno_mismo and datos.get("es_uno_mismo"):
        return True
    a = norm(re.sub(r"\((tu|tú|you)\)", "", str(datos.get("chat"))))
    b = norm(re.sub(r"\((tu|tú|you)\)", "", nombre))
    return bool(a) and (a == b or a in b or b in a)


def _ir_a_la_caja():
    """Pone el cursor en la caja de texto del chat abierto."""
    if _CAJA.get("caja"):
        _clic_en(_CAJA["caja"], _CAJA["reg"])
    else:
        reg = region()
        datos = _ver(captura("wa_caja.png"), 'Es WhatsApp de escritorio con un chat abierto. Ubicá la caja de texto '
                                              'para escribir (abajo). Respondé SOLO JSON: {"box_2d": [ymin, xmin, '
                                              'ymax, xmax]} normalizado 0-1000.')
        if _caja(datos):
            _clic_en(datos, reg)
    time.sleep(0.3)


def _escribir_y_enviar(texto):
    _ir_a_la_caja()
    _pegar(texto)
    time.sleep(0.3)
    pyautogui.press("enter")


def enviar(contacto, mensaje, con_foto=False):
    """Manda un mensaje. Nunca envía sin la IA: tiene que confirmar que el chat abierto es el correcto."""
    if VER is None:
        return False, "No puedo verificar el contacto sin la IA; no mandé nada.", None
    ok, texto, nombre = abrir_chat(contacto)
    if not ok:
        return False, texto, None
    _escribir_y_enviar(mensaje)
    time.sleep(1.0)
    foto = captura("wa_despues.png") if con_foto else None
    return True, f"Enviado a {nombre}: {mensaje}", foto


def editar_ultimo(contacto, nuevo_texto, con_foto=False):
    """Edita tu último mensaje en ese chat (WhatsApp lo permite hasta 15 minutos después)."""
    if VER is None:
        return False, "No puedo verificar el contacto sin la IA; no cambié nada.", None
    ok, texto, nombre = abrir_chat(contacto)
    if not ok:
        return False, texto, None
    _ir_a_la_caja()
    pyautogui.press("up")                          # flecha arriba en la caja vacía: editar el último mensaje propio
    time.sleep(0.8)
    pyautogui.hotkey("ctrl", "a")
    _pegar(nuevo_texto)
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(1.0)
    foto = captura("wa_despues.png") if con_foto else None
    return True, f"Corregí el último mensaje a {nombre}: {nuevo_texto}", foto


def _copiar_archivo(ruta):
    """Pone el archivo en el portapapeles (como copiarlo en el Explorador) para pegarlo en el chat."""
    ruta_ps = str(ruta).replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-Command", f"Set-Clipboard -LiteralPath '{ruta_ps}'"],
                   capture_output=True, timeout=20, creationflags=0x08000000)


def enviar_archivo(contacto, ruta, texto="", con_foto=False):
    """Manda un archivo o foto al chat, con un texto opcional."""
    ruta = Path(ruta)
    if VER is None:
        return False, "No puedo verificar el contacto sin la IA; no mandé nada.", None
    if not ruta.is_file():
        return False, f"No encontré el archivo {ruta}.", None
    ok, msj, nombre = abrir_chat(contacto)
    if not ok:
        return False, msj, None
    _ir_a_la_caja()
    _copiar_archivo(ruta)
    pyautogui.hotkey("ctrl", "v")                  # abre la vista previa del archivo
    time.sleep(2.5)
    if texto:
        _pegar(texto)                              # queda como comentario del archivo
        time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(3.0)
    datos = _ver(captura("wa_despues.png"), 'Es WhatsApp de escritorio. ¿Se ve en la conversación un archivo o foto '
                                             f'recién enviado llamado parecido a "{ruta.name}", o todavía está abierta '
                                             'la vista previa sin enviar? Respondé SOLO JSON: {"enviado": true/false}')
    if isinstance(datos, dict) and not datos.get("enviado"):
        pyautogui.press("enter")                   # a veces la vista previa necesita un segundo Enter
        time.sleep(2.5)
    foto = captura("wa_despues.png") if con_foto else None
    return True, f"Le mandé {ruta.name} a {nombre}.", foto


def leer_chat(contacto, cantidad=15):
    """Abre el chat y devuelve (ok, resumen, captura) con los últimos mensajes leídos por la IA."""
    ok, texto, nombre = abrir_chat(contacto, verificar=False)
    if not ok:
        return False, texto, None
    time.sleep(0.8)
    foto = captura("wa_chat.png")
    datos = _ver(foto, 'Es una conversación de WhatsApp de escritorio. Transcribí los últimos mensajes visibles (hasta '
                       f'{cantidad}), del más viejo al más nuevo. Los mensajes enviados por el usuario están a la '
                       'derecha (en verde): poné "de": "Yo". En grupos, poné el nombre de quien escribe. Si hay audios, '
                       'fotos o stickers, decilo. Respondé SOLO JSON: {"mensajes": [{"de": "...", "texto": "...", '
                       '"hora": "..."}], "resumen": "resumen de 1 o 2 frases de lo último que se habló"}')
    if not isinstance(datos, dict):
        return True, f"Abrí el chat con {nombre} pero no pude leerlo.", foto
    lineas = [f"{m.get('hora', '')} {m.get('de', '?')}: {m.get('texto', '')}".strip()
              for m in (datos.get("mensajes") or [])[-cantidad:] if isinstance(m, dict)]
    resumen = str(datos.get("resumen") or "").strip()
    return True, (f"Chat con {nombre}:" + ("\n" + resumen if resumen else "") + "\n\n" + "\n".join(lineas)).strip(), foto


def no_leidos():
    """Resume los chats con mensajes sin leer SIN abrirlos (no quedan como leídos). Devuelve (ok, texto)."""
    if not enfocar():
        return False, "No pude abrir la aplicación de WhatsApp."
    pyautogui.press("esc")
    pyautogui.press("esc")
    time.sleep(0.4)
    reg = region()
    datos = _ver(captura("wa_lista.png"), 'Es WhatsApp de escritorio. Ubicá el filtro "No leídos" (o "Unread") arriba '
                                           'de la lista de chats y también el filtro "Todos" (o "All"). Respondé SOLO '
                                           'JSON: {"no_leidos": [ymin, xmin, ymax, xmax] o null, "todos": [ymin, xmin, '
                                           'ymax, xmax] o null} normalizado 0-1000.')
    filtro = isinstance(datos, dict) and datos.get("no_leidos")
    if filtro:
        _clic_en(datos["no_leidos"], reg)
        time.sleep(1.2)
    lista = _ver(captura("wa_no_leidos.png"), 'Es la lista de chats de WhatsApp de escritorio. Listá los chats que '
                                              'tienen mensajes SIN LEER (círculo verde con un número). Para cada uno: '
                                              'nombre, cantidad sin leer, si está silenciado (ícono de parlante '
                                              'tachado) y el último mensaje que se ve. Respondé SOLO JSON: {"chats": '
                                              '[{"nombre": "...", "sin_leer": N, "silenciado": true/false, '
                                              '"ultimo": "..."}]}')
    if filtro and isinstance(datos, dict) and datos.get("todos"):
        _clic_en(datos["todos"], reg)              # dejar WhatsApp como estaba
        time.sleep(0.4)
    chats = [c for c in ((lista or {}).get("chats") if isinstance(lista, dict) else lista) or []
             if isinstance(c, dict) and c.get("nombre")]
    if not chats:
        return True, "No tenés mensajes sin leer en WhatsApp."
    chats.sort(key=lambda c: (bool(c.get("silenciado")), -int(c.get("sin_leer") or 0)))
    importantes = [c for c in chats if not c.get("silenciado")]
    silenciados = [c for c in chats if c.get("silenciado")]
    lineas = [f"• {c['nombre']} ({c.get('sin_leer') or '?'}): {c.get('ultimo') or ''}".strip() for c in importantes]
    texto = f"Tenés {len(chats)} chats sin leer." + ("\n\n" + "\n".join(lineas) if lineas else "")
    if silenciados:
        texto += "\n\nSilenciados: " + ", ".join(f"{c['nombre']} ({c.get('sin_leer') or '?'})" for c in silenciados)
    return True, texto


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)
    if sys.argv[1].lower() == "abrir_chat":
        print(abrir_chat(sys.argv[2])[1])
    else:
        print(__doc__)
