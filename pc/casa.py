"""Control directo de dispositivos TP-Link (Kasa y Tapo) por la red de casa.

  python casa.py descubrir              -> busca dispositivos y guarda la lista
  python casa.py lista                  -> muestra lo guardado
  python casa.py prender "luz living"
  python casa.py apagar "ventilador"
  python casa.py estado "luz living"
  python casa.py brillo "luz living" 40
  python casa.py color "luz living" azul
  python casa.py temperatura "luz living" calida
  python casa.py escena "luz living" fiesta

Funciona con Philips WiZ y con TP-Link (Kasa y Tapo).
Los Tapo necesitan tu usuario y clave de la app TP-Link en config_pc.json
("tplink_usuario" y "tplink_clave"). Las WiZ y los Kasa no necesitan nada.
Todo va por la red local: no pasa por internet y es instantáneo.
"""
import asyncio
import json
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
LISTA = BASE / "casa_dispositivos.json"

try:
    from kasa import Discover
except ImportError:
    Discover = None

try:
    from pywizlight import SCENES, PilotBuilder, wizlight
    from pywizlight.discovery import discover_lights
    import pywizlight.bulb as _bulb
    # Por defecto reintenta hasta 13 segundos si se pierde un paquete: demasiado para un comando de voz.
    _bulb.TIMEOUT = 3
    _bulb.MAX_SEND_DATAGRAMS = 3
    _bulb.FIRST_SEND_INTERVAL = 0.4
except ImportError:
    wizlight = None

if Discover is None and wizlight is None:
    print("Faltan las librerías. Instalalas con: pip install python-kasa pywizlight")
    sys.exit(2)

try:
    CONFIG = json.loads((BASE / "config_pc.json").read_text(encoding="utf-8"))
except OSError:
    CONFIG = {}

USUARIO = str(CONFIG.get("tplink_usuario") or "").strip()
CLAVE = str(CONFIG.get("tplink_clave") or "").strip()


def norm(t):
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


async def _descubrir():
    datos = {}

    if Discover is not None:                       # TP-Link (Kasa y Tapo)
        kwargs = {"username": USUARIO, "password": CLAVE} if USUARIO else {}
        try:
            for host, dev in (await Discover.discover(discovery_timeout=6, **kwargs)).items():
                try:
                    await dev.update()
                    datos[dev.alias or host] = {"host": host, "marca": "tplink",
                                                "modelo": dev.model}
                except Exception as e:
                    datos[host] = {"host": host, "marca": "tplink", "modelo": "?", "error": str(e)[:80]}
        except Exception as e:
            print("aviso: falló la búsqueda TP-Link:", str(e)[:100])

    if wizlight is not None:                       # Philips WiZ
        try:
            for luz in await discover_lights(wait_time=6):
                nombre = luz.ip
                try:
                    cfg = await luz.getBulbConfig()
                    nombre = (cfg or {}).get("result", {}).get("moduleName", luz.ip)
                except Exception:
                    pass
                datos[f"WiZ {nombre}"] = {"host": luz.ip, "marca": "wiz", "modelo": nombre}
        except Exception as e:
            print("aviso: falló la búsqueda WiZ:", str(e)[:100])

    previos = _guardados()                         # se suman: un aparato apagado un rato no se pierde
    previos.update(datos)
    LISTA.write_text(json.dumps(previos, indent=2, ensure_ascii=False), encoding="utf-8")
    return datos


APODOS = BASE / "casa_apodos.json"


def _apodos():
    """Nombres que el usuario le puso a sus aparatos: {"luz del living": "WiZ ESP25..."}."""
    try:
        archivo = json.loads(APODOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        archivo = {}
    return {**(CONFIG.get("casa_apodos") or {}), **archivo}


def nombrar(aparato, apodo):
    """Le pone un nombre a un aparato. Devuelve el alias real, o None si no lo encontró."""
    hallado = _buscar(aparato) or _buscar("luz")
    apodo = str(apodo or "").strip(' ".')
    if not hallado or not apodo:
        return None
    try:
        archivo = json.loads(APODOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        archivo = {}
    archivo = {k: v for k, v in archivo.items() if v != hallado[0]}   # un nombre por aparato
    archivo[apodo] = hallado[0]
    APODOS.write_text(json.dumps(archivo, indent=2, ensure_ascii=False), encoding="utf-8")
    return hallado[0]


def _guardados():
    try:
        return json.loads(LISTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


GENERICOS = ("luz", "luces", "lampara", "lamparita", "foco", "velador", "led",
             "enchufe", "tomacorriente", "dispositivo")


def _buscar(nombre):
    """Encuentra el dispositivo por nombre aproximado, o por apodo del config."""
    datos = _guardados()
    if not datos:
        return None
    objetivo = norm(nombre)

    # 1) apodos que el usuario puso en config_pc.json: {"casa_apodos": {"living": "WiZ ESP25..."}}
    for apodo, real in _apodos().items():
        if norm(apodo) and norm(apodo) in objetivo:
            for alias, info in datos.items():
                if norm(real) in norm(alias):
                    return (alias, info)

    palabras = [p for p in objetivo.split() if len(p) > 2]
    mejor, puntaje = None, 0
    for alias, info in datos.items():
        a = norm(alias)
        p = 3 if a == objetivo else (2 if objetivo in a or a in objetivo else 0)
        p += sum(1 for w in palabras if w in a)
        if p > puntaje:
            mejor, puntaje = (alias, info), p
    if mejor:
        return mejor

    # 2) si hay un solo dispositivo, o pidió algo genérico ("la luz"), no hay ambigüedad
    # 2) "la luz" con un solo dispositivo en la red: es ese. Un nombre desconocido ("la tele") NO.
    if len(datos) == 1 and (not objetivo or any(g in objetivo for g in GENERICOS)):
        alias = list(datos)[0]
        return (alias, datos[alias])
    return None


async def _conectar(host):
    """discover_single detecta solo el protocolo del dispositivo (Kasa viejo o Tapo nuevo)."""
    kwargs = {"username": USUARIO, "password": CLAVE} if USUARIO else {}
    dev = await Discover.discover_single(host, discovery_timeout=5, **kwargs)
    if dev is None:
        raise RuntimeError(f"no pude conectarme a {host}")
    return dev


COLORES = {
    "rojo": (255, 0, 0), "verde": (0, 255, 0), "azul": (0, 0, 255), "amarillo": (255, 220, 0),
    "naranja": (255, 110, 0), "violeta": (140, 0, 255), "morado": (140, 0, 255), "lila": (180, 130, 255),
    "rosa": (255, 60, 160), "rosado": (255, 60, 160), "celeste": (0, 180, 255), "turquesa": (0, 230, 200),
    "verde agua": (0, 230, 200), "blanco": (255, 255, 255), "dorado": (255, 190, 60), "coral": (255, 90, 70),
    "fucsia": (255, 0, 140), "menta": (150, 255, 200), "bordo": (120, 0, 30),
}

ESCENAS_ES = {
    "fiesta": "Party", "romance": "Romance", "romantico": "Romance", "relax": "Relax", "relajado": "Relax",
    "oceano": "Ocean", "mar": "Ocean", "atardecer": "Sunset", "bosque": "Forest", "selva": "Jungle",
    "chimenea": "Fireplace", "fuego": "Fireplace", "velas": "Candlelight", "vela": "Candlelight",
    "acogedor": "Cozy", "calido": "Warm white", "frio": "Cool white", "luz de dia": "Daylight",
    "concentracion": "Focus", "estudiar": "Focus", "trabajar": "Focus", "dormir": "Bedtime",
    "noche": "Night light", "despertar": "Wake-up", "amanecer": "Wake-up", "tele": "TV time",
    "television": "TV time", "pelicula": "TV time", "navidad": "Christmas", "halloween": "Halloween",
    "boliche": "Club", "club": "Club", "primavera": "Spring", "verano": "Summer", "otono": "Fall",
    "pastel": "Pastel colors", "colores": "True colors", "arcoiris": "True colors", "pulso": "Pulse",
    "mojito": "Mojito", "dorado": "Golden white", "blanco": "White", "alarma": "Alarm", "ritmo": "Rhythm",
}


def _id_escena(nombre):
    """Busca la escena por nombre en español o en inglés."""
    objetivo = norm(nombre)
    ingles = ESCENAS_ES.get(objetivo)
    for numero, titulo in SCENES.items():
        if ingles and norm(titulo) == norm(ingles):
            return numero, titulo
    for numero, titulo in SCENES.items():
        if objetivo and (objetivo in norm(titulo) or norm(titulo) in objetivo):
            return numero, titulo
    return None, None


def _color(nombre):
    objetivo = norm(nombre)
    if objetivo in COLORES:
        return COLORES[objetivo]
    if objetivo.endswith("a") and objetivo[:-1] + "o" in COLORES:      # roja, amarilla, blanca...
        return COLORES[objetivo[:-1] + "o"]
    for nombre_color, rgb in COLORES.items():
        if nombre_color in objetivo:
            return rgb
    return None


def _amigable(alias):
    """El nombre que le puso el usuario, o 'la luz' en vez del nombre técnico ('WiZ ESP25_SHRGB_01')."""
    import re
    for apodo, real in _apodos().items():
        if real == alias:
            return apodo
    return "la luz" if re.fullmatch(r"WiZ [A-Z0-9_]+", str(alias)) else alias


async def _accion_wiz(alias, info, que, valor):
    alias = _amigable(alias)
    luz = wizlight(info["host"])
    if que == "prender":
        await luz.turn_on(PilotBuilder())
        return f"Prendí {alias}."
    if que == "apagar":
        await luz.turn_off()
        return f"Apagué {alias}."
    if que == "brillo":
        pct = max(1, min(100, int(float(valor))))
        await luz.turn_on(PilotBuilder(brightness=int(pct * 255 / 100)))
        return f"Puse {alias} al {pct} por ciento."
    if que == "color":
        rgb = _color(valor)
        if not rgb:
            return f"No conozco el color {valor}. Probá con rojo, azul, verde, violeta, rosa, celeste..."
        await luz.turn_on(PilotBuilder(rgb=rgb))
        return f"Puse {alias} en {valor}."
    if que == "temperatura":
        texto = norm(valor)
        if texto.isdigit():
            kelvin = max(2200, min(6500, int(texto)))
        elif "calid" in texto or "calor" in texto or "amarill" in texto:
            kelvin = 2700
        elif "neutr" in texto:
            kelvin = 4000
        else:
            kelvin = 6000
        await luz.turn_on(PilotBuilder(colortemp=kelvin))
        return f"Puse {alias} en luz {'cálida' if kelvin <= 3000 else 'neutra' if kelvin <= 4500 else 'fría'}."
    if que == "escena":
        numero, titulo = _id_escena(valor)
        if numero is None:
            return f"No encontré la escena {valor}."
        await luz.turn_on(PilotBuilder(scene=numero))
        return f"Puse {alias} en modo {valor}."
    estado = await luz.updateState()
    prendida = None
    if estado is not None:
        try:
            prendida = estado.get_state()
        except AttributeError:          # según la versión, devuelve otra cosa
            prendida = bool(getattr(luz, "status", None))
    if prendida is None:
        return f"No pude leer el estado de {alias}."
    return f"{alias} está {'prendida' if prendida else 'apagada'}."


LUCES = ("luz", "luces", "lampara", "lamparas", "lamparita", "foco", "focos", "velador", "led")
VERBOS_TODAS = {"prender": "Prendí las luces.", "apagar": "Apagué las luces."}


def _varias(objetivo, datos):
    """¿Pidió todas las luces? ('las luces', 'todas', o 'la luz' sin decir cuál cuando hay más de una)."""
    if len(datos) < 2:
        return False
    if any(norm(a) and norm(a) in objetivo for a in _apodos()):
        return False
    palabras = objetivo.split()
    return any(p in ("luces", "todas", "todo", "todos") for p in palabras) or any(p in LUCES for p in palabras)


async def _accion(nombre, que, valor=None):
    datos = _guardados()
    objetivo = norm(nombre)
    if _varias(objetivo, datos):
        import asyncio
        resultados = await asyncio.gather(*[_accion_uno(a, i, que, valor) for a, i in datos.items()],
                                          return_exceptions=True)
        bien = [r for r in resultados if isinstance(r, str)]
        if not bien:
            return "No pude manejar las luces."
        if que in VERBOS_TODAS:
            return VERBOS_TODAS[que]
        if que == "brillo":
            return f"Puse las luces al {max(1, min(100, int(float(valor))))} por ciento."
        if que in ("color", "escena"):
            return f"Puse las luces en {valor}."
        return " ".join(bien)
    hallado = _buscar(nombre)
    if not hallado:
        return f"No encontré ningún dispositivo parecido a '{nombre}'. Probá: python casa.py descubrir"
    return await _accion_uno(*hallado, que, valor)


async def _accion_uno(alias, info, que, valor=None):
    if info.get("marca") == "wiz":
        return await _accion_wiz(alias, info, que, valor)
    dev = await _conectar(info["host"])
    await dev.update()
    alias = _amigable(alias)
    if que == "prender":
        await dev.turn_on()
        texto = f"Prendí {alias}."
    elif que == "apagar":
        await dev.turn_off()
        texto = f"Apagué {alias}."
    elif que == "brillo":
        if not getattr(dev, "is_dimmable", False):
            texto = f"{alias} no permite regular el brillo."
        else:
            await dev.set_brightness(max(1, min(100, int(valor))))
            texto = f"Puse {alias} al {int(valor)} por ciento."
    else:
        await dev.update()
        texto = f"{alias} está {'prendido' if dev.is_on else 'apagado'}."
    await dev.disconnect()
    return texto


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1].lower()
    if cmd == "descubrir":
        datos = asyncio.run(_descubrir())
        if not datos:
            print("No encontré dispositivos WiZ ni TP-Link en la red.")
        for alias, info in datos.items():
            print(f"- {alias}  ({info.get('modelo')}, {info.get('host')})")
    elif cmd == "lista":
        datos = _guardados()
        print("\n".join(f"- {a} ({i.get('host')})" for a, i in datos.items()) or "(nada guardado)")
    elif cmd in ("prender", "apagar", "estado"):
        print(asyncio.run(_accion(sys.argv[2], cmd)))
    elif cmd in ("brillo", "color", "temperatura", "escena"):
        print(asyncio.run(_accion(sys.argv[2], cmd, sys.argv[3])))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
