"""Cerebro · panel de escritorio: una ventana en tu PC principal para manejar el agente que corre en la OTRA PC.

  python panel_escritorio.py                 abre el panel (la primera vez pide dónde está la otra PC)
  python panel_escritorio.py --configurar    vuelve a pedir la dirección, el puerto y el token
  python panel_escritorio.py --buscar        busca agentes de Cerebro en la red de casa y los lista

Se instala con instalar-panel-escritorio.bat, que deja un acceso directo "Cerebro Panel" en el Escritorio y en el
menú Inicio. La configuración queda en panel_escritorio.json junto a este archivo (lleva el token: no lo compartas).

En la otra PC, el agente tiene que tener "panel_en_red": true en config_pc.json (si no, el panel solo escucha en
127.0.0.1 de esa PC). El token lo da el agente: escribile "panel" al bot de Telegram, o miralo en su estado.json
("panel_token"). Si las dos PCs están en la misma red, "Buscar en la red" encuentra la otra PC sola.

La ventana: usa pywebview si está instalado (ventana nativa), si no Microsoft Edge o Chrome en modo aplicación
(una ventana sin barra de direcciones), y si no hay nada de eso, el navegador que tengas.
"""
import json
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "panel_escritorio.json"
PUERTO_DEFECTO = 8765
TITULO = "Cerebro · panel"

NAVEGADORES = (
    ("msedge", (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")),
    ("chrome", (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")),
)


# ---------- configuración ----------

def cargar():
    try:
        datos = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    return {"host": str(datos.get("host") or "").strip(), "puerto": int(datos.get("puerto") or PUERTO_DEFECTO),
            "token": str(datos.get("token") or "").strip()}


def guardar(cfg):
    CONFIG.write_text(json.dumps({"host": cfg["host"], "puerto": int(cfg["puerto"]), "token": cfg["token"]},
                                 ensure_ascii=False, indent=2), encoding="utf-8")


def url(cfg, con_token=True):
    base = "http://" + cfg["host"] + ":" + str(int(cfg["puerto"])) + "/"
    if con_token and cfg.get("token"):
        return base + "?token=" + urllib.parse.quote(cfg["token"], safe="")
    return base


# ---------- encontrar y probar la otra PC ----------

def sondear(host, puerto=PUERTO_DEFECTO, timeout=0.5):
    """¿Hay un agente de Cerebro escuchando en host:puerto? Devuelve lo que contesta /api/ping, o None."""
    try:
        with urllib.request.urlopen("http://" + host + ":" + str(puerto) + "/api/ping", timeout=timeout) as r:
            datos = json.load(r)
        return datos if isinstance(datos, dict) and datos.get("cerebro") else None
    except Exception:
        return None


def _redes_locales():
    """Los prefijos /24 de las redes a las que está conectada esta PC ('192.168.0')."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))          # no manda nada: solo elige la interfaz de salida
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted({ip.rsplit(".", 1)[0] for ip in ips if not ip.startswith("127.")})


def buscar(puerto=PUERTO_DEFECTO, redes=None):
    """Recorre la red de casa buscando agentes de Cerebro. Devuelve [(host, datos_del_ping)]. Tarda unos segundos."""
    redes = redes if redes is not None else _redes_locales()
    candidatos = [red + "." + str(n) for red in redes for n in range(1, 255)]
    if not candidatos:
        return []
    with ThreadPoolExecutor(max_workers=64) as pool:
        resultados = list(pool.map(lambda h: (h, sondear(h, puerto)), candidatos))
    return [(h, d) for h, d in resultados if d]


def verificar(cfg):
    """Prueba la conexión y el token contra la otra PC. Devuelve (ok, texto para mostrar)."""
    if not cfg.get("host"):
        return False, "Falta la dirección de la otra PC."
    req = urllib.request.Request(url(cfg, con_token=False) + "api/estado",
                                 headers={"Authorization": "Bearer " + cfg.get("token", "")})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            datos = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "La PC respondió, pero el token no es el correcto. Pedíselo al bot con \"panel\"."
        return False, "La PC respondió con un error " + str(e.code) + "."
    except Exception as e:
        return False, ("No pude conectar con " + cfg["host"] + ":" + str(cfg["puerto"]) + " (" + str(e)[:80] + "). "
                       "Fijate que el agente esté corriendo allá y que tenga \"panel_en_red\": true en config_pc.json.")
    equipo = str(datos.get("equipo") or cfg["host"])
    version = str(datos.get("version") or "")
    return True, "Conectado con " + equipo + (" (Cerebro " + version + ")" if version else "") + "."


# ---------- la ventana ----------

def abrir(cfg):
    """Abre el panel en una ventana propia. Devuelve cómo lo abrió: 'webview', 'msedge', 'chrome' o 'navegador'."""
    destino = url(cfg)
    try:
        import webview
    except ImportError:
        webview = None
    if webview is not None:
        webview.create_window(TITULO, destino, width=1180, height=800, min_size=(720, 480))
        webview.start()
        return "webview"
    for nombre, rutas in NAVEGADORES:
        exe = shutil.which(nombre) or next((p for p in rutas if Path(p).exists()), None)
        if exe:
            # Modo aplicación: ventana sin barra de direcciones ni pestañas, con su propio perfil (guarda la sesión).
            subprocess.Popen([exe, "--app=" + destino, "--window-size=1180,800",
                              "--user-data-dir=" + str(BASE / "ventana_panel")])
            return nombre
    webbrowser.open(destino)
    return "navegador"


# ---------- configurar: ventanita o consola ----------

def configurar():
    """Pide host, puerto y token (con "Buscar en la red" y "Probar"). Devuelve la config guardada o None si canceló."""
    cfg = cargar()
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        return _configurar_consola(cfg)

    raiz = tk.Tk()
    raiz.title(TITULO + " · conexión con la otra PC")
    raiz.resizable(False, False)
    marco = ttk.Frame(raiz, padding=16)
    marco.grid()
    ttk.Label(marco, text="¿Dónde corre el agente de Cerebro?", font=("Segoe UI", 11, "bold")).grid(
        column=0, row=0, columnspan=3, sticky="w", pady=(0, 10))
    host = tk.StringVar(value=cfg["host"])
    puerto = tk.StringVar(value=str(cfg["puerto"]))
    token = tk.StringVar(value=cfg["token"])
    estado = tk.StringVar(value="Escribile \"panel\" al bot de Telegram para ver la dirección y el token.")
    for fila, (etiqueta, variable, ancho, oculto) in enumerate((("Dirección (IP o nombre)", host, 28, False),
                                                              ("Puerto", puerto, 8, False),
                                                              ("Token", token, 40, True)), start=1):
        ttk.Label(marco, text=etiqueta).grid(column=0, row=fila, sticky="w", pady=3)
        ttk.Entry(marco, textvariable=variable, width=ancho, show="•" if oculto else "").grid(
            column=1, row=fila, columnspan=2, sticky="w", pady=3)
    aviso = ttk.Label(marco, textvariable=estado, wraplength=420, foreground="#555")
    aviso.grid(column=0, row=5, columnspan=3, sticky="w", pady=(10, 6))
    resultado = {"cfg": None}

    def actual():
        try:
            p = int(puerto.get().strip() or PUERTO_DEFECTO)
        except ValueError:
            p = PUERTO_DEFECTO
        return {"host": host.get().strip(), "puerto": p, "token": token.get().strip()}

    def buscar_en_red():
        estado.set("Buscando en la red de casa… (unos segundos)")
        raiz.update_idletasks()
        hallados = buscar(actual()["puerto"])
        if not hallados:
            estado.set("No encontré ningún agente en la red. ¿Está corriendo y con \"panel_en_red\": true?")
            return
        h, d = hallados[0]
        host.set(h)
        extra = (" (también: " + ", ".join(x for x, _ in hallados[1:4]) + ")") if len(hallados) > 1 else ""
        estado.set("Encontré a " + str(d.get("equipo") or h) + " en " + h + extra + ". Falta el token.")

    def probar():
        ok, texto = verificar(actual())
        estado.set(texto)
        return ok

    def guardar_y_salir():
        c = actual()
        if not c["host"] or not c["token"]:
            estado.set("Faltan la dirección o el token.")
            return
        if not probar() and not messagebox.askyesno(TITULO, "No pude verificar la conexión. ¿Guardo igual?"):
            return
        guardar(c)
        resultado["cfg"] = c
        raiz.destroy()

    botones = ttk.Frame(marco)
    botones.grid(column=0, row=6, columnspan=3, sticky="e")
    ttk.Button(botones, text="Buscar en la red", command=buscar_en_red).grid(column=0, row=0, padx=4)
    ttk.Button(botones, text="Probar", command=probar).grid(column=1, row=0, padx=4)
    ttk.Button(botones, text="Guardar", command=guardar_y_salir).grid(column=2, row=0, padx=4)
    raiz.bind("<Return>", lambda e: guardar_y_salir())
    raiz.mainloop()
    return resultado["cfg"]


def _configurar_consola(cfg):
    print("¿Dónde corre el agente de Cerebro? (Enter deja el valor entre corchetes)")
    hallados = buscar(cfg["puerto"])
    if hallados:
        print("Encontré en la red:", ", ".join(h + " (" + str(d.get("equipo") or "") + ")" for h, d in hallados))
        cfg["host"] = cfg["host"] or hallados[0][0]
    host = input("Dirección [" + cfg["host"] + "]: ").strip() or cfg["host"]
    puerto = input("Puerto [" + str(cfg["puerto"]) + "]: ").strip() or cfg["puerto"]
    token = input("Token [" + ("…" + cfg["token"][-4:] if cfg["token"] else "") + "]: ").strip() or cfg["token"]
    nuevo = {"host": host, "puerto": int(puerto), "token": token}
    if not nuevo["host"] or not nuevo["token"]:
        print("Faltan la dirección o el token.")
        return None
    ok, texto = verificar(nuevo)
    print(texto)
    guardar(nuevo)
    return nuevo


def _avisar(texto):
    try:
        import tkinter as tk
        from tkinter import messagebox
        raiz = tk.Tk()
        raiz.withdraw()
        quiere = messagebox.askyesno(TITULO, texto + "\n\n¿Querés revisar la conexión?")
        raiz.destroy()
        return quiere
    except Exception:
        print(texto)
        return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--buscar" in argv:
        hallados = buscar()
        if not hallados:
            print("No encontré agentes de Cerebro en la red.")
            return 1
        for h, d in hallados:
            print(h, "->", d.get("equipo", ""), "Cerebro", d.get("version", ""), "(en red)" if d.get("en_red") else "")
        return 0
    cfg = cargar()
    if "--configurar" in argv or not cfg["host"] or not cfg["token"]:
        cfg = configurar()
        if not cfg:
            return 1
        if "--configurar" in argv:
            return 0
    ok, texto = verificar(cfg)
    if not ok and _avisar(texto):
        cfg = configurar() or cfg
    abrir(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
