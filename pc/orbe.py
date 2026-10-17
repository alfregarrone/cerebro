"""Cerebro · orbe: la "bola" de Cerebro en pantalla.

Cada vez que le hablás a Alexa, la skill avisa por el enlace firmado con la PC y acá aparece una esfera animada
que escucha, piensa (mientras Gemini contesta) y habla, con lo que dijiste y lo que respondió. Después se esconde
sola. También muestra qué está haciendo la PC cuando le llega una orden (anotar, luces, música...).

  python orbe.py                 arranca y queda escuchando (se instala con instalar-orbe.bat)
  python orbe.py --prueba        muestra una secuencia de ejemplo sin esperar a Alexa
  python orbe.py --configurar    pide el enlace (cerebro_link) y lo guarda, para una PC sin el agente

Corre en cualquiera de las dos PCs: lee el enlace de config_pc.json (la PC del agente) o de panel_escritorio.json
(la PC principal). Solo necesita la biblioteca estándar (tkinter viene con Python en Windows).

Teclas: Esc o doble clic la esconde; clic derecho la cierra; se puede arrastrar.
"""
import hashlib
import hmac
import json
import math
import queue
import sys
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

BASE = Path(__file__).resolve().parent
TITULO = "Cerebro · orbe"
MAX_EDAD = 60            # avisos más viejos (la PC estaba apagada) no se muestran

ETIQUETAS = {
    "nota": "Anotando", "buscar_notas": "Buscando en tus notas", "pendientes": "Leyendo tus pendientes",
    "completar_pendiente": "Tachando un pendiente", "compras": "Lista de compras", "casa": "Manejando la casa",
    "frase": "Haciendo lo que me enseñaste", "musica": "Poniendo música", "musica_control": "Controlando la música",
    "volumen": "Volumen", "abrir_app": "Abriendo un programa", "abrir_web": "Abriendo un sitio",
    "cerrar_app": "Cerrando un programa", "sistema": "Orden del sistema", "whatsapp": "Preparando un WhatsApp",
    "whatsapp_confirmar": "Mandando el WhatsApp", "whatsapp_leer": "Leyendo WhatsApp", "whatsapp_resumen": "Resumiendo WhatsApp",
    "tarea": "Pasándole trabajo a Claude", "confirmar_tarea": "Ejecutando el plan", "agenda": "Mirando tu agenda",
    "mails": "Revisando tus mails", "captura": "Sacando una captura", "programar": "Programando un aviso",
    "recordar": "Guardando en la memoria", "olvidar": "Olvidando", "avisar": "Avisando al celular",
    "salud_pc": "Revisando la PC", "info_pc": "Revisando la PC", "alertas": "Alertas", "resumen_manana": "Resumen del día",
    "aprendidos": None, "estado": None, "diagnostico": "Diagnóstico",
}
COLORES = {"escuchando": "#4fc3f7", "pensando": "#00e5ff", "hablando": "#ffffff", "haciendo": "#ffd166"}


# ---------- el enlace y los mensajes ----------

def enlace():
    """(tópico, clave) del enlace con la skill: config_pc.json en la PC del agente, panel_escritorio.json en la otra."""
    for nombre in ("config_pc.json", "panel_escritorio.json"):
        try:
            datos = json.loads((BASE / nombre).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        link = str(datos.get("cerebro_link") or "")
        if ":" in link:
            topic, secret = link.split(":", 1)
            return topic.strip(), secret.strip()
    return None, None


def guardar_enlace(link):
    """Guarda el enlace en panel_escritorio.json (sin pisar lo demás que haya ahí)."""
    archivo = BASE / "panel_escritorio.json"
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    datos["cerebro_link"] = link.strip()
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def firmar(secret, texto):
    return hmac.new(secret.encode(), texto.encode(), hashlib.sha256).hexdigest()


def interpretar(evento, secret, ahora=None):
    """Un evento del stream de ntfy -> {"accion", "datos", "ts", "id"} si la firma vale y es reciente; si no, None."""
    if not isinstance(evento, dict) or evento.get("event") != "message":
        return None
    try:
        msg = json.loads(evento.get("message", ""))
    except (ValueError, TypeError):
        return None
    if not isinstance(msg, dict) or not all(k in msg for k in ("id", "ts", "accion", "datos", "firma")):
        return None
    datos = msg["datos"] if isinstance(msg["datos"], dict) else {}
    esperado = firmar(secret, f'{msg["id"]}|{msg["ts"]}|{msg["accion"]}|{json.dumps(datos, sort_keys=True, ensure_ascii=False)}')
    if not hmac.compare_digest(esperado, str(msg["firma"])):
        return None
    try:
        ts = float(msg["ts"])
    except (TypeError, ValueError):
        return None
    if (ahora or time.time()) - ts > MAX_EDAD:
        return None
    return {"id": str(msg["id"]), "accion": str(msg["accion"]), "datos": datos, "ts": ts}


def escuchar(topic, secret, cola, parar):
    """Hilo: se queda conectado al tópico y encola cada orden válida. Reconecta solo."""
    since = int(time.time())
    vistos = deque(maxlen=200)
    while not parar.is_set():
        try:
            with urllib.request.urlopen(f"https://ntfy.sh/{topic}/json?since={since}", timeout=90) as resp:
                for crudo in resp:
                    if parar.is_set():
                        break
                    try:
                        evento = json.loads(crudo.decode("utf-8"))
                    except ValueError:
                        continue
                    if evento.get("time"):
                        since = max(since, int(evento["time"]))
                    orden = interpretar(evento, secret)
                    if orden and orden["id"] not in vistos:
                        vistos.append(orden["id"])
                        cola.put(orden)
        except Exception:
            time.sleep(5)


# ---------- qué muestra (sin ventana, para poder probarlo) ----------

def resumen(datos):
    """Lo más dicible de los datos de una orden: el texto, el dispositivo, la búsqueda..."""
    for clave in ("texto", "instruccion", "busqueda", "dispositivo", "nombre", "contacto", "consulta", "orden", "url"):
        v = datos.get(clave)
        if v:
            return str(v)
    agregar = datos.get("agregar")
    if isinstance(agregar, list) and agregar:
        return ", ".join(str(x) for x in agregar)
    return ""


def envolver(texto, ancho=44, lineas=4):
    palabras, salida, actual = str(texto or "").split(), [], ""
    for p in palabras:
        if actual and len(actual) + 1 + len(p) > ancho:
            salida.append(actual)
            actual = p
        else:
            actual = (actual + " " + p).strip()
    if actual:
        salida.append(actual)
    if len(salida) > lineas:
        salida = salida[:lineas]
        salida[-1] = salida[-1][:ancho - 1] + "…"
    return "\n".join(salida)


class Estado:
    """La máquina de estados del orbe: modo, título, texto y hasta cuándo se ve."""

    def __init__(self):
        self.modo, self.titulo, self.texto, self.desde, self.hasta = "oculto", "", "", 0.0, 0.0

    def aplicar(self, orden, ahora=None):
        """Devuelve True si hay algo nuevo para mostrar."""
        ahora = ahora or time.time()
        accion, datos = orden.get("accion"), orden.get("datos") or {}
        if accion == "hud":
            modo = str(datos.get("estado") or "pensando")
            texto = str(datos.get("texto") or "")
            if modo == "oculto":
                self.ocultar()
                return False
            if modo not in COLORES:
                modo = "pensando"
            self.modo, self.desde = modo, ahora
            if modo == "escuchando":
                self.titulo, self.texto, self.hasta = "", "Te escucho.", ahora + 20
            elif modo == "pensando":
                self.titulo, self.texto, self.hasta = "Vos", texto, ahora + 30
            else:
                self.titulo, self.texto = "Cerebro", texto
                self.hasta = ahora + max(5.0, min(25.0, 2.5 + len(texto) / 12))   # el tiempo que tarda en decirlo
            return True
        etiqueta = ETIQUETAS.get(accion, "Ejecutando: " + str(accion))
        if etiqueta is None:
            return False
        if self.modo == "oculto":
            self.modo, self.desde = "haciendo", ahora
        self.titulo, self.texto = etiqueta, resumen(datos)
        self.hasta = max(self.hasta, ahora + 6)
        return True

    def vencido(self, ahora=None):
        return self.modo != "oculto" and (ahora or time.time()) >= self.hasta

    def ocultar(self):
        self.modo, self.titulo, self.texto = "oculto", "", ""


# ---------- la ventana ----------

def _mezcla(color, factor):
    """Oscurece un color hex: factor 1 = igual, 0 = negro."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * factor), int(g * factor), int(b * factor))


class Ventana:
    ANCHO, ALTO = 440, 330

    def __init__(self, estado, cola):
        import tkinter as tk
        self.tk, self.estado, self.cola = tk, estado, cola
        self.fondo = "#010101"                      # este color exacto se vuelve transparente en Windows
        r = self.raiz = tk.Tk()
        r.title(TITULO)
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=self.fondo)
        try:
            r.attributes("-transparentcolor", self.fondo)
        except tk.TclError:
            pass
        x = r.winfo_screenwidth() - self.ANCHO - 24
        y = r.winfo_screenheight() - self.ALTO - 90
        r.geometry(f"{self.ANCHO}x{self.ALTO}+{x}+{y}")
        self.lienzo = tk.Canvas(r, width=self.ANCHO, height=self.ALTO, bg=self.fondo, highlightthickness=0)
        self.lienzo.pack()
        r.bind("<Escape>", lambda e: self.ocultar())
        self.lienzo.bind("<Double-Button-1>", lambda e: self.ocultar())
        self.lienzo.bind("<Button-3>", lambda e: r.destroy())
        self.lienzo.bind("<ButtonPress-1>", self._agarrar)
        self.lienzo.bind("<B1-Motion>", self._arrastrar)
        self.fase, self.visible, self._origen = 0.0, False, (0, 0)
        r.withdraw()
        self._tic()

    def _agarrar(self, e):
        self._origen = (e.x, e.y)

    def _arrastrar(self, e):
        self.raiz.geometry("+%d+%d" % (self.raiz.winfo_x() + e.x - self._origen[0],
                                       self.raiz.winfo_y() + e.y - self._origen[1]))

    def mostrar(self):
        if not self.visible:
            self.raiz.deiconify()
            self.raiz.attributes("-topmost", True)
            self.visible = True

    def ocultar(self):
        self.estado.ocultar()
        if self.visible:
            self.raiz.withdraw()
            self.visible = False

    def _tic(self):
        try:
            while True:
                orden = self.cola.get_nowait()
                if self.estado.aplicar(orden):
                    self.mostrar()
                elif self.estado.modo == "oculto":
                    self.ocultar()
        except queue.Empty:
            pass
        if self.estado.vencido():
            self.ocultar()
        if self.visible:
            self._dibujar()
        self.raiz.after(33, self._tic)

    def _dibujar(self):
        c, e = self.lienzo, self.estado
        c.delete("all")
        modo = e.modo
        self.fase += 0.18 if modo == "pensando" else 0.09
        color = COLORES.get(modo, COLORES["pensando"])
        cx, cy, radio = self.ANCHO / 2, 125, 62
        pulso = 1 + (0.08 if modo == "pensando" else 0.04) * math.sin(self.fase * 2)
        # halo y núcleo
        for k, f in ((1.75, 0.10), (1.45, 0.18), (1.2, 0.30), (1.0, 0.55), (0.72, 0.8), (0.42, 1.0)):
            rr = radio * k * pulso
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=_mezcla(color, f), outline="")
        if modo in ("pensando", "haciendo"):          # anillos que giran
            for i in range(3):
                rr = radio * 1.35 + i * 14
                inicio = (self.fase * 57 * (1 if i % 2 == 0 else -1) + i * 120) % 360
                c.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=inicio, extent=100 - i * 20,
                             style="arc", outline=_mezcla(color, 0.9 - i * 0.25), width=2)
        if modo == "hablando":                        # barras como de voz
            for i in range(11):
                h = 6 + 22 * abs(math.sin(self.fase * 3 + i * 0.6))
                x = cx - 60 + i * 12
                c.create_rectangle(x, cy + radio + 24 - h / 2, x + 6, cy + radio + 24 + h / 2, fill=color, outline="")
        if modo == "escuchando":                      # ondas que salen
            for i in range(3):
                rr = radio * (1.3 + ((self.fase * 0.5 + i * 0.33) % 1.0) * 0.9)
                c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=_mezcla(color, 0.5), width=1)
        y = cy + radio + 52
        if e.titulo:
            c.create_text(cx, y, text=e.titulo.upper(), fill=_mezcla(color, 0.85), font=("Segoe UI", 9, "bold"))
            y += 20
        if e.texto:
            c.create_text(cx, y, text=envolver(e.texto), fill="#f2f2f2", font=("Segoe UI", 11), justify="center",
                          anchor="n", width=self.ANCHO - 40)


# ---------- arranque ----------

def _secuencia_de_prueba(cola):
    pasos = [(0.3, {"accion": "hud", "datos": {"estado": "escuchando"}}),
             (2.0, {"accion": "hud", "datos": {"estado": "pensando", "texto": "¿a cuánto está el dólar y qué tiempo hace mañana?"}}),
             (3.5, {"accion": "hud", "datos": {"estado": "hablando",
                                                "texto": "El blue está a mil cuatrocientos ochenta. Mañana, parcialmente nublado, máxima de veintidós."}}),
             (4.0, {"accion": "nota", "datos": {"texto": "Llamar a Marta por el presupuesto", "categoria": "idea"}})]
    for espera, orden in pasos:
        time.sleep(espera)
        cola.put({**orden, "id": orden["accion"] + str(espera), "ts": time.time()})


def configurar():
    """Pide el enlace para una PC sin el agente y lo guarda en panel_escritorio.json."""
    actual = enlace()[0]
    try:
        import tkinter as tk
        from tkinter import simpledialog
        raiz = tk.Tk()
        raiz.withdraw()
        link = simpledialog.askstring(TITULO, "Pegá el enlace con la skill (cerebro_link, con la forma topico:clave).\n"
                                              "Es el mismo valor que tiene config.py de la skill y config_pc.json del agente.",
                                      parent=raiz)
        raiz.destroy()
    except Exception:
        link = input("Enlace con la skill (topico:clave)" + (" [guardado]" if actual else "") + ": ")
    link = (link or "").strip()
    if ":" not in link:
        print("No guardé nada: el enlace tiene que tener la forma topico:clave.")
        return 1
    guardar_enlace(link)
    print("Enlace guardado en panel_escritorio.json.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--configurar" in argv:
        return configurar()
    topic, secret = enlace()
    if not topic:
        print("Falta el enlace con la skill: en la PC del agente está en config_pc.json; en otra PC, corré "
              "python orbe.py --configurar")
        return 1
    cola, parar = queue.Queue(), threading.Event()
    threading.Thread(target=escuchar, args=(topic, secret, cola, parar), daemon=True).start()
    if "--prueba" in argv:
        threading.Thread(target=_secuencia_de_prueba, args=(cola,), daemon=True).start()
    ventana = Ventana(Estado(), cola)
    ventana.raiz.mainloop()
    parar.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
