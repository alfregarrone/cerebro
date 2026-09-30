"""Música de la PC: qué está sonando (el mismo panel de Windows que muestra la canción), pausa, siguiente y anterior,
y reproducir de verdad en YouTube (el primer video + una lista automática para que siga sonando).

  python medios.py sonando
"""
import ctypes
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

CREATE_NO_WINDOW = 0x08000000
TECLAS = {"pausa": 0xB3, "seguir": 0xB3, "play_pausa": 0xB3, "siguiente": 0xB0, "anterior": 0xB1, "parar": 0xB2}

# Lee las sesiones de audio de Windows (Spotify, Chrome con YouTube, etc.) con WinRT desde PowerShell 5.
_PS_SESIONES = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Esperar($op, $tipo) { $t = $asTask.MakeGenericMethod($tipo).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime] | Out-Null
$mgr = Esperar ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$actual = $mgr.GetCurrentSession()
$lista = @()
foreach ($s in $mgr.GetSessions()) {
  $p = Esperar ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
  $lista += [pscustomobject]@{ app = $s.SourceAppUserModelId; titulo = $p.Title; artista = $p.Artist;
    estado = $s.GetPlaybackInfo().PlaybackStatus.ToString();
    actual = ($actual -ne $null -and $s.SourceAppUserModelId -eq $actual.SourceAppUserModelId) }
}
ConvertTo-Json -InputObject @($lista) -Compress
"""


def sesiones(timeout=8):
    """[{app, titulo, artista, estado ('Playing'/'Paused'/...), actual}] de lo que Windows sabe que suena."""
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS_SESIONES],
                       capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    salida = r.stdout.decode("utf-8", errors="replace").strip()
    if r.returncode != 0 or not salida.startswith("["):
        raise RuntimeError((r.stderr.decode("utf-8", errors="replace") or salida or "sin datos")[:200])
    return json.loads(salida)


def nombre_app(app_id):
    a = str(app_id or "").lower()
    for clave, nombre in (("spotify", "Spotify"), ("chrome", "Chrome"), ("msedge", "Edge"), ("firefox", "Firefox"),
                          ("zunemusic", "Reproductor multimedia"), ("vlc", "VLC"), ("youtube", "YouTube")):
        if clave in a:
            return nombre
    return app_id.split("!")[0].split("_")[0] if app_id else "la PC"


def principal(lista):
    """La sesión que importa: la que está sonando; si no, la que Windows marca como actual."""
    sonando = [s for s in lista if s.get("estado") == "Playing"]
    return (sonando or [s for s in lista if s.get("actual")] or lista or [None])[0]


def describir(s):
    if not s:
        return "No está sonando nada en la PC."
    donde = nombre_app(s.get("app"))
    if not (s.get("titulo") or "").strip():
        return f"Está sonando algo en {donde}, pero no dice qué es." if s.get("estado") == "Playing" \
            else "No está sonando nada en la PC."
    que = s["titulo"].strip() + (f", de {s['artista'].strip()}" if (s.get("artista") or "").strip() else "")
    if s.get("estado") == "Playing":
        return f"Está sonando {que} en {donde}."
    return f"Está en pausa: {que} en {donde}."


def tecla(nombre):
    codigo = TECLAS[nombre]
    ctypes.windll.user32.keybd_event(codigo, 0, 0, 0)
    ctypes.windll.user32.keybd_event(codigo, 0, 2, 0)


def primer_video(busqueda, timeout=6):
    """El id del primer video de YouTube para esa búsqueda (sin claves: lee la página de resultados)."""
    url = "https://www.youtube.com/results?hl=es&search_query=" + urllib.parse.quote(busqueda)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
                                               "Accept-Language": "es-AR,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        pagina = r.read().decode("utf-8", errors="replace")
    inicio = pagina.find('"contents":')                 # saltea los anuncios del principio si los hay
    for m in re.finditer(r'"videoRenderer":\{"videoId":"([\w-]{11})"', pagina[max(0, inicio):]):
        return m.group(1)
    m = re.search(r'"videoId":"([\w-]{11})"', pagina)
    return m.group(1) if m else None


def link_youtube(busqueda):
    """Link que empieza a sonar solo y sigue con temas parecidos (lista automática 'Mix' de YouTube)."""
    try:
        vid = primer_video(busqueda)
    except Exception:
        vid = None
    if not vid:
        return "https://www.youtube.com/results?search_query=" + urllib.parse.quote(busqueda), False
    return f"https://www.youtube.com/watch?v={vid}&list=RD{vid}&start_radio=1", True


# ---------- Spotify: buscar y darle play mirando la pantalla ----------

VER = None      # la IA que mira capturas: la pone cerebro_pc.py (ver_imagen)
PREGUNTA_TARJETA = ('Es una captura de la app de Spotify con resultados de búsqueda. Devolvé en JSON '
                    '{"caja": [ymin, xmin, ymax, xmax]} (escala 0-1000) de la tarjeta grande "Resultado principal" '
                    '("Top result"); si no está, la de la primera canción de la lista. Si no hay resultados: {"caja": null}.')
PREGUNTA_PLAY = ('Captura de Spotify: el mouse está sobre la tarjeta "Resultado principal" y apareció un botón verde '
                 'redondo con un triángulo de reproducir. Devolvé {"caja": [ymin, xmin, ymax, xmax]} (0-1000) de ESE '
                 'botón verde. Si no se ve: {"caja": null}.')
PREGUNTA_PLAY_GRANDE = ('Captura de Spotify en la página de un artista, álbum, lista o canción. Devolvé '
                        '{"caja": [ymin, xmin, ymax, xmax]} (0-1000) del botón verde grande y redondo de reproducir '
                        '(triángulo) de la página, no el de la barra de abajo. Si no se ve: {"caja": null}.')


def _pids(exe):
    r = subprocess.run(["tasklist", "/fi", f"imagename eq {exe}", "/fo", "csv", "/nh"], capture_output=True,
                       text=True, creationflags=CREATE_NO_WINDOW)
    pids = set()
    for linea in r.stdout.splitlines():
        partes = linea.strip().strip('"').split('","')
        if len(partes) > 1 and partes[1].isdigit():
            pids.add(int(partes[1]))
    return pids


def ventana_de(exe):
    """(hwnd, (izquierda, arriba, ancho, alto)) de la ventana principal de un programa, aunque esté minimizada;
    o None. Prefiere la que está a la vista y más grande."""
    import ctypes.wintypes as wt
    pids = _pids(exe)
    if not pids:
        return None
    user32 = ctypes.windll.user32
    halladas = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cada(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                r = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                minimizada = bool(user32.IsIconic(hwnd))
                if minimizada or (r.right - r.left > 300 and r.bottom - r.top > 200):
                    halladas.append((hwnd, (r.left, r.top, r.right - r.left, r.bottom - r.top), minimizada))
        return True

    user32.EnumWindows(cada, 0)
    if not halladas:
        return None
    hwnd, caja, _ = max(halladas, key=lambda x: (not x[2], x[1][2] * x[1][3]))
    return hwnd, caja


def ventana_con_titulo(texto):
    """hwnd de una ventana visible cuyo título contiene `texto` (por ejemplo 'YouTube'), o None."""
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    halladas = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cada(hwnd, _):
        largo = user32.GetWindowTextLengthW(hwnd)
        if user32.IsWindowVisible(hwnd) and largo > 0:
            buf = ctypes.create_unicode_buffer(largo + 1)
            user32.GetWindowTextW(hwnd, buf, largo + 1)
            if texto.lower() in buf.value.lower():
                halladas.append(hwnd)
        return True

    user32.EnumWindows(cada, 0)
    return halladas[0] if halladas else None


def play_en_youtube():
    """Si el navegador no dejó que el video arranque solo: trae la pestaña de YouTube al frente y aprieta play ('k').
    Devuelve True si lo intentó."""
    import pyautogui
    hwnd = ventana_con_titulo("YouTube")
    if not hwnd:
        return False
    import ctypes.wintypes as wt
    _enfocar(hwnd)
    time.sleep(0.8)
    r = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    pyautogui.click(r.left + (r.right - r.left) // 3, r.top + (r.bottom - r.top) // 3)   # sobre el video: le da play
    return True


def _enfocar(hwnd, ancho_minimo=0):
    """Trae la ventana al frente (restaurándola si estaba minimizada). Si es chica, la maximiza para poder verla."""
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)                    # restaurar si estaba minimizada
    try:
        import pygetwindow
        pygetwindow.Win32Window(hwnd).activate()
    except Exception:
        user32.SetForegroundWindow(hwnd)
    for _ in range(20):                               # esperar a que termine de restaurarse
        time.sleep(0.1)
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if not user32.IsIconic(hwnd) and r.right - r.left > 300:
            break
    if ancho_minimo and r.right - r.left < ancho_minimo:
        user32.ShowWindow(hwnd, 3)                    # maximizar
        time.sleep(0.6)
    time.sleep(0.3)


def _region(reg):
    import pyautogui
    ancho, alto = pyautogui.size()
    izq, arr = max(0, reg[0]), max(0, reg[1])
    return izq, arr, min(reg[2] - (izq - reg[0]), ancho - izq), min(reg[3] - (arr - reg[1]), alto - arr)


def _caja(v):
    if isinstance(v, dict):
        v = v.get("caja") or v.get("box_2d") or v.get("box")
    while isinstance(v, list) and v and isinstance(v[0], list):
        v = v[0]
    try:
        return [float(x) for x in v[:4]] if isinstance(v, list) and len(v) >= 4 else None
    except (TypeError, ValueError):
        return None


def _mirar(reg, pregunta, fx=0.5, fy=0.5):
    """Pregunta a la IA dónde está algo en la ventana; devuelve un punto (x, y) de la pantalla dentro de esa caja
    (fx, fy = qué parte de la caja: 0.5 es el centro), o None."""
    import os
    import tempfile
    import pyautogui
    if not VER:
        return None
    ruta = os.path.join(tempfile.gettempdir(), "cerebro_spotify.png")
    pyautogui.screenshot(region=reg).save(ruta)
    texto = VER(ruta, pregunta) or ""
    try:
        inicio = min(i for i in (texto.find("{"), texto.find("[")) if i >= 0)
        c = _caja(json.JSONDecoder().raw_decode(texto[inicio:])[0])
    except ValueError:
        c = None
    if not c:
        return None
    ymin, xmin, ymax, xmax = c
    return (int(reg[0] + (xmin + (xmax - xmin) * fx) / 1000 * reg[2]),
            int(reg[1] + (ymin + (ymax - ymin) * fy) / 1000 * reg[3]))


def _spotify_actual():
    """(título, artista, estado) de lo que tiene cargado Spotify, o None."""
    try:
        for s in sesiones():
            if "spotify" in str(s.get("app")).lower():
                return s.get("titulo"), s.get("artista"), s.get("estado")
    except Exception:
        pass
    return None


def _espera_que_suene(previo, segundos=5.0):
    """True si Spotify empieza a sonar algo distinto de lo que tenía cargado antes."""
    limite = time.time() + segundos
    while time.time() < limite:
        time.sleep(0.5)
        ahora = _spotify_actual()
        if ahora and ahora[2] == "Playing" and (not previo or ahora[:2] != previo[:2]):
            return True
    return False


PREGUNTA_CANCION = ('Es una captura de la app de Spotify con resultados de búsqueda. Devolvé en JSON '
                    '{"caja": [ymin, xmin, ymax, xmax]} (escala 0-1000) de la FILA COMPLETA de la primera canción de '
                    'la lista "Canciones" ("Songs"): desde el título hasta la duración. Si no hay lista de canciones: '
                    '{"caja": null}.')


def spotify_reproducir(busqueda):
    """Busca en la app de Spotify y le da play. Devuelve (ok, texto); si falla, texto es el motivo, en minúscula."""
    import os
    import pyautogui
    previo = _spotify_actual()
    try:
        os.startfile("spotify:search:" + urllib.parse.quote(busqueda))
    except OSError:
        return False, "no encontré la app de Spotify"
    v = None
    for _ in range(24):
        time.sleep(0.5)
        v = ventana_de("Spotify.exe")
        if v:
            break
    if not v:
        return False, "no apareció la ventana de Spotify"
    _enfocar(v[0], ancho_minimo=900)
    time.sleep(1.5)                                   # que carguen los resultados
    actual = ventana_de("Spotify.exe")
    if not actual or actual[1][2] < 300 or actual[1][0] < -1000:
        return False, "no pude traer la ventana de Spotify al frente"
    reg = _region(actual[1])
    fila = _mirar(reg, PREGUNTA_CANCION, fx=0.6)      # doble clic en una canción = la reproduce
    if fila:
        pyautogui.doubleClick(*fila)
        if _espera_que_suene(previo):
            return True, f"Pongo {busqueda} en Spotify."
    tarjeta = _mirar(reg, PREGUNTA_TARJETA)           # si no: el botón verde del resultado principal
    if tarjeta:
        pyautogui.moveTo(*tarjeta)
        time.sleep(0.8)                               # al pasar el mouse aparece el botón verde
        boton = _mirar(reg, PREGUNTA_PLAY)
        if boton:
            pyautogui.click(*boton)
            if _espera_que_suene(previo):
                return True, f"Pongo {busqueda} en Spotify."
    if not fila and not tarjeta:
        return False, "no vi resultados de la búsqueda en la pantalla de Spotify"
    return False, "le di play pero Spotify no arrancó"


if __name__ == "__main__":
    if (sys.argv[1:] or ["sonando"])[0] == "sonando":
        t0 = time.time()
        lista = sesiones()
        print(json.dumps(lista, ensure_ascii=False), f"({time.time() - t0:.1f} s)")
        print(describir(principal(lista)))
    elif sys.argv[1] == "video":
        print(link_youtube(" ".join(sys.argv[2:])))
