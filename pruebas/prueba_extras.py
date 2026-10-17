"""Pruebas de lo nuevo: agenda, mails, salud de la PC, resumen de la mañana, música y avisos que no se pierden.

Todo sobre una copia aislada: Gmail falso, calendario de prueba, Telegram falso, sin tocar la música ni la PC real
(solo se LEEN disco, memoria y procesador). Usa la IA real solo para resumir los mails.
"""
import email.message
import imaplib
import json
import re
import shutil
import sys
import types
import urllib.error
from datetime import datetime, date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
T = Path(__file__).resolve().parent / "_copia_extras"
shutil.rmtree(T, ignore_errors=True)
T.mkdir()
for f in ("cerebro_pc.py", "info.py", "agenda.py", "correo.py", "medios.py"):
    shutil.copy(RAIZ / "pc" / f, T / f)
ICS = (Path(__file__).resolve().parent / "prueba_agenda.py").read_text(encoding="utf-8").split('ICS = r"""')[1].split('"""')[0]
(T / "cal.ics").write_bytes(ICS.replace("\n", "\r\n").encode("utf-8"))
clave = re.search(r'GEMINI_API_KEY\s*=\s*"([^"]+)"', (RAIZ / "lambda" / "config.py").read_text(encoding="utf-8")).group(1)
(T / "config_pc.json").write_text(json.dumps({
    "cerebro_link": "prueba-falsa:x", "carpeta_notas": str(T / "notas"), "gemini_api_key": clave,
    "calendario_ical": (T / "cal.ics").as_uri(), "gmail_usuario": "yo@gmail.com", "gmail_clave_app": "clave buena",
    "equipo": "Boca"}), encoding="utf-8")
(T / "notas").mkdir()
(T / "notas" / "Pendientes.md").write_text("# Pendientes\n- [ ] llamar al contador\n- [ ] pagar la luz\n- [x] hecho\n",
                                            encoding="utf-8")
sys.path.insert(0, str(T))
sys.modules["casa"] = types.ModuleType("casa")


# ---------- Gmail falso ----------
def mail(de, asunto, texto=None, html=None, adjunto=False):
    m = email.message.EmailMessage()
    m["From"], m["Subject"], m["Date"] = de, asunto, "Tue, 29 Sep 2026 07:10:00 -0300"
    if texto:
        m.set_content(texto)
    if html:
        if texto:
            m.add_alternative(html, subtype="html")
        else:
            m.set_content(html, subtype="html")
    if adjunto:
        m.add_attachment(b"%PDF-1.4 falso" * 100, maintype="application", subtype="pdf", filename="factura.pdf")
    return m.as_bytes()


BUZON = {
    101: {"no_leido": True, "importante": False, "crudo": mail("Mercado Libre <noreply@ml.com>", "¡Ofertas imperdibles!",
                                                                html="<html><style>x{}</style><body><h1>Ofertas</h1><p>50% off en zapatillas</p></body></html>")},
    102: {"no_leido": True, "importante": True, "crudo": mail('"Laura Pérez" <laura@x.com>', "Turno del dentista",
                                                               "Hola! Te confirmo el turno del jueves a las 10.\n\nEl lun, 28 sept 2026, Alfre escribió:\n> dale\n> gracias")},
    103: {"no_leido": True, "importante": True, "crudo": mail("=?utf-8?b?QmFuY28gR2FsaWNpYQ==?= <avisos@galicia.com>",
                                                               "=?utf-8?q?Vencimiento_de_tu_tarjeta?=",
                                                               "Tu resumen vence el 5/10. Monto: $ 120.000.", "<p>Tu resumen vence</p>", adjunto=True)},
    90: {"no_leido": False, "importante": True, "crudo": mail("Viejo <v@x.com>", "Ya leído", "nada")},
}
USOS = {"readonly": [], "conexiones": 0, "consultas": []}


class GmailFalso:
    def __init__(self, host, port, timeout=None):
        assert host == "imap.gmail.com"
        USOS["conexiones"] += 1

    def login(self, usuario, clave_app):
        if clave_app != "clavebuena":            # correo.py le saca los espacios
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, buzon, readonly=False):
        USOS["readonly"].append(readonly)
        return "OK", [b"4"]

    def uid(self, comando, *args):
        if comando == "SEARCH":
            assert args[0] == "X-GM-RAW"
            consulta = args[1].strip('"')
            USOS["consultas"].append(consulta)
            uids = [u for u, m in sorted(BUZON.items()) if m["no_leido"] and ("is:important" not in consulta or m["importante"])]
            return "OK", [" ".join(map(str, uids)).encode()]
        if comando == "FETCH":
            assert "PEEK" in args[1], "tiene que usar BODY.PEEK para no marcar como leído"
            datos = []
            for i, u in enumerate(int(x) for x in args[0].split(",")):
                crudo = BUZON[u]["crudo"]
                datos += [(f"{i + 1} (UID {u} BODY[]<0> {{{len(crudo)}}}".encode(), crudo), b")"]
            return "OK", datos
        raise AssertionError(comando)

    def logout(self):
        pass


imaplib.IMAP4_SSL = GmailFalso

import cerebro_pc as c  # noqa: E402

AVISOS = []
AVISAR_REAL = c.avisar_celular
c.registrar = lambda *a, **k: None
c.avisar_celular = lambda texto, titulo="Cerebro": AVISOS.append(texto) or True
bien = mal = 0


def chequear(nombre, ok, detalle=""):
    global bien, mal
    bien += bool(ok)
    mal += not ok
    print(("OK " if ok else "MAL"), nombre, "->", str(detalle)[:400].replace("\n", " | "))


# ---------- agenda ----------
hoy = date.today()
ok, r = c.accion_agenda({"fecha": "2026-10-08"})
chequear("agenda de un día (repetido de los jueves)", ok and "a las 9, Gimnasio" in r, r)
ok, r = c.accion_agenda({"fecha": "2026-10-06"})
chequear("agenda con evento movido", "Gimnasio (movido)" in r, r)
ok, r = c.accion_agenda({"cuando": "el viernes"})
chequear("agenda 'el viernes'", ok and ("no tenés nada" in r or "tenés" in r), r)
chequear("fecha de 'el viernes'", c._fecha_de_texto("que tengo el viernes", date(2026, 9, 29)) == date(2026, 10, 2))
chequear("fecha de 'mañana'", c._fecha_de_texto("que tengo manana", date(2026, 9, 29)) == date(2026, 9, 30))
chequear("'mañana a la mañana' sigue siendo mañana", c._fecha_de_texto("que tengo manana a la manana", date(2026, 9, 29)) == date(2026, 9, 30))
chequear("fecha de 'hoy a la mañana'", c._fecha_de_texto("que tengo hoy a la manana", date(2026, 9, 29)) == date(2026, 9, 29))
AVISOS.clear()
nuevos = c._revisar_agenda(datetime(2026, 9, 29, 9, 35))
nuevos2 = c._revisar_agenda(datetime(2026, 9, 29, 9, 40))
chequear("aviso antes del dentista (una sola vez)", len(nuevos) == 1 and not nuevos2 and "En 25 minutos: Dentista" in AVISOS[0], AVISOS)
cfg_sin = dict(c.CONFIG)
c.CONFIG.pop("calendario_ical")
ok, r = c.accion_agenda({})
chequear("sin calendario: explica y da pendientes", "configurar.bat" in r and "llamar al contador" in r, r)
c.CONFIG.update(cfg_sin)

# ---------- mails ----------
ok, r = c.accion_mails({})
chequear("resumen de mails (IA)", ok and "3 mails sin leer" in r and "Laura" in r and "Galicia" in r, r)
chequear("Gmail en solo lectura", USOS["readonly"] and all(USOS["readonly"]), USOS["readonly"])
t0 = c.time.time()
ok, r = c.accion_mails({"voz": True})
chequear(f"mails por voz: corto y rápido ({c.time.time() - t0:.1f} s)", ok and "Tenés 3 mails sin leer." in r and
         "De Laura Pérez: Turno del dentista." in r and "celular" in r and c.time.time() - t0 < 2.5, r)
correo = c._mod("correo")
total, lista = correo.no_leidos(c.CONFIG, 5)
por_uid = {m["uid"]: m for m in lista}
chequear("remitente con nombre", por_uid[102]["de"] == "Laura Pérez", por_uid[102]["de"])
chequear("sin lo citado del mail anterior", "gracias" not in por_uid[102]["texto"] and "turno del jueves" in por_uid[102]["texto"],
         por_uid[102]["texto"])
chequear("remitente y asunto codificados", por_uid[103]["de"] == "Banco Galicia" and por_uid[103]["asunto"] == "Vencimiento de tu tarjeta",
         (por_uid[103]["de"], por_uid[103]["asunto"]))
chequear("mail solo HTML sin etiquetas ni estilos", "50% off" in por_uid[101]["texto"] and "<" not in por_uid[101]["texto"]
         and "x{}" not in por_uid[101]["texto"], por_uid[101]["texto"])
AVISOS.clear()
primera = c._revisar_mails()
chequear("primera revisión: no avisa lo viejo", primera == [] and not AVISOS, AVISOS)
BUZON[104] = {"no_leido": True, "importante": True, "crudo": mail("Jefe <jefe@trabajo.com>", "Reunión mañana 9 hs", "¿Podés venir antes?")}
BUZON[105] = {"no_leido": True, "importante": False, "crudo": mail("Promo <p@x.com>", "Cupón", "10% off")}
segunda = c._revisar_mails()
tercera = c._revisar_mails()
chequear("mail importante nuevo: avisa una vez", len(segunda) == 1 and not tercera and "Jefe" in AVISOS[0] and "Cupón" not in " ".join(AVISOS), AVISOS)
c.CONFIG["gmail_clave_app"] = "mala"
ok, r = c.accion_mails({})
chequear("clave mala: lo dice claro", not ok and "contraseña de aplicación" in r, r)
c.CONFIG["gmail_clave_app"] = "clave buena"

# ---------- salud de la PC (lectura real) ----------
ok, r = c.accion_salud_pc({})
chequear("salud de la PC", ok and "disco C" in r and "memoria al" in r and "procesador al" in r and "prendida hace" in r, r)
AVISOS.clear()
m1 = c._revisar_pc(datetime(2026, 9, 29, 10, 0), disco=(7.5, 119), ram=50)
m2 = c._revisar_pc(datetime(2026, 9, 29, 10, 15), disco=(7.4, 119), ram=50)
m3 = c._revisar_pc(datetime(2026, 9, 30, 10, 0), disco=(7.4, 119), ram=50)
chequear("disco escaso: un aviso por día", len(m1) == 1 and not m2 and len(m3) == 1 and "7.5 GB" in m1[0], m1 + m3)
g1 = c._revisar_pc(datetime(2026, 9, 30, 11, 0), disco=(2.1, 119), ram=50)
g2 = c._revisar_pc(datetime(2026, 9, 30, 12, 0), disco=(2.0, 119), ram=50)
g3 = c._revisar_pc(datetime(2026, 9, 30, 17, 30), disco=(1.9, 119), ram=50)
chequear("disco casi lleno: urgente cada 6 horas", len(g1) == 1 and "URGENTE" in g1[0] and not g2 and len(g3) == 1, g1 + g3)
r1 = [c._revisar_pc(datetime(2026, 10, 1, 10, i * 15), disco=(50, 119), ram=95) for i in range(4)]
chequear("memoria al límite: avisa a la tercera", [len(x) for x in r1] == [0, 0, 1, 0], r1)
chequear("duraciones legibles", (c._duracion(90061), c._duracion(3700), c._duracion(59)) ==
         ("1 día y 1 hora", "1 hora y 1 minuto", "1 minuto"), (c._duracion(90061), c._duracion(3700), c._duracion(59)))

# ---------- arranque después de un corte ----------
AVISOS.clear()
c.LATIDO.write_text(str(c.time.time() - c._encendida_seg() - 1800))   # último latido: media hora antes de prender
c._aviso_arranque()
chequear("aviso de que la PC se reinició", AVISOS and "se reinició" in AVISOS[0], AVISOS)
AVISOS.clear()
c.LATIDO.write_text(str(c.time.time() - 30))                        # solo se reinició Cerebro
c._aviso_arranque()
chequear("si solo se reinició Cerebro no avisa", not AVISOS, AVISOS)
AVISOS.clear()
c.LATIDO.write_text(str(c.time.time() - c._encendida_seg() - 120))
c.estado_cambiar(lambda e: e.__setitem__("reinicio_pedido_ts", c.time.time() - c._encendida_seg() - 90))
c._aviso_arranque()
chequear("reinicio pedido: avisa que ya volvió", AVISOS and "reinicio que pediste" in AVISOS[0], AVISOS)

# ---------- avisos que no se pierden ----------
c.avisar_celular = AVISAR_REAL
envios = []


def telegram_caido(texto, titulo):
    envios.append(texto)
    raise urllib.error.URLError("sin internet")


c.estado_cambiar(lambda e: e.__setitem__("telegram_chat_id", 12345))
original_enviar = c._telegram_enviar
c._telegram_enviar = telegram_caido
salida = c.avisar_celular("hola")
chequear("sin internet: no olvida el chat de Telegram", salida is False and c.cargar_estado().get("telegram_chat_id") == 12345,
         c.cargar_estado().get("telegram_chat_id"))


def chat_viejo(texto, titulo):
    raise urllib.error.HTTPError("u", 400, "chat not found", {}, None)


c._telegram_enviar = chat_viejo
salida = c.avisar_celular("hola")
chequear("chat inválido: reintenta y si no encuentra otro, conserva el de antes",
         salida is False and c.cargar_estado().get("telegram_chat_id") == 12345, c.cargar_estado().get("telegram_chat_id"))
c._telegram_enviar = original_enviar
c.avisar_celular = lambda texto, titulo="Cerebro": AVISOS.append(texto) or True

# ---------- resumen de la mañana ----------
t0 = c.time.time()
texto = c.armar_resumen(datetime(2026, 9, 29, 8, 0))
chequear(f"resumen completo ({c.time.time() - t0:.1f} s)", all(x in texto for x in (
    "Buen día", "martes 29 de septiembre", "grados", "Dentista", "llamar al contador", "mails sin leer", "Dólar blue",
    "Titulares")) and "hecho" not in texto, texto)
voz = c.armar_resumen(datetime(2026, 9, 29, 8, 0), voz=True)
chequear("resumen para voz sin emojis", not re.search(r"[\U0001F300-\U0001FAFF☀]", voz) and "Dentista" in voz, voz[:200])
cfg = {"activo": True, "hora": "08:00", "dias": "todos"}
chequear("toca a las 8:00", c._toca_resumen(datetime(2026, 9, 29, 8, 0), cfg))
chequear("no toca 7:59", not c._toca_resumen(datetime(2026, 9, 29, 7, 59), cfg))
chequear("PC prendida 9:30: llega igual", c._toca_resumen(datetime(2026, 9, 29, 9, 30), cfg))
chequear("a las 14 ya no", not c._toca_resumen(datetime(2026, 9, 29, 14, 0), cfg))
chequear("ya mandado hoy: no repite", not c._toca_resumen(datetime(2026, 9, 29, 8, 30), {**cfg, "ultimo": "2026-09-29"}))
chequear("solo semana: sábado no", not c._toca_resumen(datetime(2026, 10, 3, 8, 0), {**cfg, "dias": "semana"}))
AVISOS.clear()
c.estado_cambiar(lambda e: e.pop("resumen", None))
envio1 = c._mandar_resumen_si_toca(datetime(2026, 9, 29, 8, 0, 20))
envio2 = c._mandar_resumen_si_toca(datetime(2026, 9, 29, 8, 0, 50))
chequear("el resumen sale una vez", envio1 and not envio2 and len(AVISOS) == 1)
for pedido, esperado in ((({"hora": "7:30"}), "a las 07:30"), ({"hora": "7 y media", "dias": "lunes a viernes"}, "de lunes a viernes a las 07:30"),
                         ({"hora": "8 de la noche"}, "a las 20:00"), ({"activar": False}, "no te mando más"),
                         ({"activar": True}, "a las 20:00"), ({"equipo": "River"}, "cuándo juega River")):
    ok, r = c.accion_resumen_manana(pedido)
    chequear(f"configurar resumen {pedido}", ok and esperado in r, r)

# ---------- música (sin tocar la de verdad) ----------
medios = c._medios()
SUENA = []
TECLAS = []
ABIERTO = []
medios.sesiones = lambda timeout=8: [dict(s) for s in SUENA]
medios.tecla = lambda n: TECLAS.append(n)
c.webbrowser.open = lambda url: ABIERTO.append(url)
SUENA[:] = [{"app": "Spotify.exe", "titulo": "Persiana americana", "artista": "Soda Stereo", "estado": "Playing", "actual": True}]
chequear("qué está sonando", c.accion_musica_control({"accion": "que_suena"})[1] == "Está sonando Persiana americana, de Soda Stereo en Spotify.")
chequear("pausa", c.accion_musica_control({"accion": "pausa"})[1] == "Pausado." and TECLAS == ["pausa"], TECLAS)
SUENA[0]["estado"] = "Paused"
TECLAS.clear()
chequear("pausa sin nada sonando", c.accion_musica_control({"accion": "pausa"})[1] == "No está sonando nada." and not TECLAS)
chequear("seguir", c.accion_musica_control({"accion": "seguir"})[1].startswith("Sigue sonando") and TECLAS == ["seguir"], TECLAS)
SUENA[0]["estado"] = "Playing"
TECLAS.clear()
orig = medios.tecla


def pasar(n):
    TECLAS.append(n)
    SUENA[0]["titulo"] = "De música ligera"


medios.tecla = pasar
t0 = c.time.time()
chequear("siguiente dice el tema nuevo, rápido", c.accion_musica_control({"accion": "siguiente"})[1] ==
         "Ahora suena De música ligera, de Soda Stereo." and c.time.time() - t0 < 1.5)
medios.tecla = orig
TECLAS.clear()
ABIERTO.clear()
ok, r = c.accion_musica({"busqueda": "los redondos"})
chequear("poner música pausa la que sonaba y abre un video que arranca solo",
         TECLAS == ["pausa"] and ABIERTO and "watch?v=" in ABIERTO[0] and "list=RD" in ABIERTO[0] and r == "Pongo los redondos en YouTube.",
         (TECLAS, ABIERTO, r))
SUENA.clear()
ABIERTO.clear()
chequear("seguir sin nada abierto: vuelve a poner lo último",
         c.accion_musica_control({"accion": "seguir"})[1] == "Vuelvo a poner lo último: los redondos." and ABIERTO, ABIERTO)
SPOTIFY_REAL = medios.spotify_reproducir
medios.spotify_reproducir = lambda q: (True, f"Pongo {q} en Spotify.")
ABIERTO.clear()
ok, r = c.accion_musica({"busqueda": "soda stereo", "servicio": "spotify"})
chequear("spotify cuando puede darle play", r == "Pongo soda stereo en Spotify." and not ABIERTO, r)
medios.spotify_reproducir = lambda q: (False, "no apareció la ventana de Spotify")
ok, r = c.accion_musica({"busqueda": "soda stereo", "servicio": "spotify"})
chequear("sin spotify: YouTube y dice por qué", "YouTube" in r and "no apareció la ventana de Spotify" in r and ABIERTO, r)

# Spotify de verdad, simulando pantalla, mouse y la IA que mira: fila de canción con doble clic
m2 = c._medios()
estado_spotify = {"v": ("Tema viejo", "Otro", "Paused")}
CLICS = []
m2.os_startfile = None
m2.ventana_de = lambda exe: (123, (0, 0, 1200, 800))
m2._enfocar = lambda h, ancho_minimo=0: None
m2._spotify_actual = lambda: estado_spotify["v"]
m2.VER = lambda ruta, pregunta: '{"caja": [300, 450, 340, 950]}' if "FILA" in pregunta else '{"caja": null}'
import pyautogui  # noqa: E402
pyautogui.screenshot = lambda region=None: type("I", (), {"save": lambda self, r: None})()
pyautogui.doubleClick = lambda x, y: (CLICS.append((x, y)), estado_spotify.__setitem__("v", ("De música ligera", "Soda Stereo", "Playing")))
import os  # noqa: E402
os.startfile = lambda uri: CLICS.append(uri)
ok, r = SPOTIFY_REAL("soda stereo")
chequear("spotify: doble clic en la primera canción y suena", ok and r == "Pongo soda stereo en Spotify." and
         CLICS[0] == "spotify:search:soda%20stereo" and CLICS[1] == (900, 256), (ok, r, CLICS))
estado_spotify["v"] = ("Tema viejo", "Otro", "Paused")
pyautogui.doubleClick = lambda x, y: CLICS.append((x, y))          # el clic no hace nada
t0 = c.time.time()
ok, r = SPOTIFY_REAL("soda stereo")
chequear("spotify: si no arranca, lo dice", not ok and r == "le di play pero Spotify no arrancó" and c.time.time() - t0 < 9, (ok, r))
m2.VER = lambda ruta, pregunta: '{"caja": null}'
ok, r = SPOTIFY_REAL("soda stereo")
chequear("spotify: sin resultados en pantalla, lo dice", not ok and "no vi resultados" in r, (ok, r))
m2.ventana_de = lambda exe: None
ok, r = SPOTIFY_REAL("soda stereo")
chequear("spotify: sin ventana, lo dice", not ok and r == "no apareció la ventana de Spotify", (ok, r))

# ---------- alertas nuevas ----------
chequear("desactivar alertas de mails", c.accion_alertas({"tipo": "mails", "activar": False})[1] ==
         "Listo, desactivé las alertas de mails importantes.")
chequear("sinónimos: 'correo'", "de mails importantes" in c.accion_alertas({"tipo": "correo", "activar": True})[1])
chequear("sinónimos: 'compu'", "de la PC" in c.accion_alertas({"tipo": "compu", "activar": False})[1])
listado = c.accion_alertas({})[1]
chequear("listado de alertas", all(x in listado for x in ("del dólar", "de lluvia", "de la PC apagada", "mails", "agenda")), listado)
c.accion_alertas({"tipo": "todas", "activar": True})

# ---------- el reloj de cada 30 segundos: corte de internet ----------
class Reloj:
    def __init__(self):
        self.t, self.vueltas = 1_800_000_000.0, 0

    def time(self):
        return self.t

    def sleep(self, s):
        self.vueltas += 1
        if self.vueltas > 14:
            raise StopIteration
        self.t += s


tiempo_real = c.time
c.time = Reloj()
red = iter([True, False, False, False, True] + [True] * 20)
c._hay_internet = lambda timeout=5: next(red)
c.estado_cambiar(lambda e: e.setdefault("resumen", {}).__setitem__("activo", False))
AVISOS.clear()
try:
    c.hilo_minutero()
except StopIteration:
    pass
c.time = tiempo_real
cortes = [a for a in AVISOS if "Se cortó internet" in a]
chequear("corte de internet de 3 minutos: avisa una vez cuando vuelve", len(cortes) == 1 and "3 minutos" in cortes[0], AVISOS)
chequear("el reloj deja el latido", c.LATIDO.exists())

# ---------- Telegram: atajos sin IA ----------
LLAMADAS = []
for nombre in ("agenda", "mails", "salud_pc", "musica_control", "resumen_manana"):
    real_f = getattr(c, "accion_" + nombre)
    setattr(c, "accion_" + nombre, (lambda n, f: (lambda d: (LLAMADAS.append((n, d)), (True, "[" + n + "]"))[1]))(nombre, real_f))
casos = [("qué tengo hoy", "agenda"), ("que tengo mañana?", "agenda"), ("qué tengo el viernes", "agenda"),
         ("agenda de la semana", "agenda"), ("mi agenda", "agenda"), ("tengo algo para mañana?", "agenda"),
         ("tengo mails?", "mails"), ("resumime los mails", "mails"), ("me llegó algún mail?", "mails"),
         ("pausa", "musica_control"), ("siguiente", "musica_control"), ("pasá el tema", "musica_control"),
         ("qué está sonando?", "musica_control"), ("seguí", "musica_control"), ("tema anterior", "musica_control"),
         ("cómo está la pc?", "salud_pc"), ("cuánto espacio libre tiene el disco", "salud_pc"),
         ("resumen", "resumen_manana"), ("mandame el resumen a las 7:30", "resumen_manana"),
         ("desactivá el resumen", "resumen_manana"), ("el resumen de lunes a viernes a las 7", "resumen_manana")]
for frase, esperado in casos:
    LLAMADAS.clear()
    r = c._orden_telegram(frase)
    chequear(f"telegram {frase!r}", LLAMADAS and LLAMADAS[0][0] == esperado, (LLAMADAS, r))
LLAMADAS.clear()
c._orden_telegram("qué tengo que comprar")
chequear("'qué tengo que comprar' sigue siendo la lista", not LLAMADAS, LLAMADAS)

print(f"\n{bien} bien, {mal} mal")
shutil.rmtree(T, ignore_errors=True)
