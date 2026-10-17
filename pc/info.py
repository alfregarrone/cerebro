"""Datos en vivo gratis, sin claves: clima (Open-Meteo), dólar (dolarapi.com) y noticias (Google Noticias).

  python info.py clima [ciudad]
  python info.py dolar
  python info.py noticias [tema]
"""
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

CIUDAD = "Buenos Aires"
LAT, LON = -34.6037, -58.3816

ESTADOS = ((0, "despejado"), (1, "mayormente despejado"), (2, "parcialmente nublado"), (3, "nublado"),
           (48, "con niebla"), (57, "con llovizna"), (67, "con lluvia"), (77, "con nieve"),
           (82, "con chaparrones"), (86, "con nevadas"), (99, "con tormentas"))
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _leer(url, timeout=4):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Cerebro)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _estado(codigo):
    for tope, texto in ESTADOS:
        if codigo <= tope:
            return texto
    return "variable"


def clima(ciudad="", dia=0):
    """dia: 0 hoy, 1 mañana... hasta 6."""
    lat, lon, nombre = LAT, LON, CIUDAD
    ciudad = str(ciudad or "").strip()
    if ciudad and ciudad.lower() not in CIUDAD.lower():
        g = json.loads(_leer("https://geocoding-api.open-meteo.com/v1/search?count=1&language=es&name="
                             + urllib.parse.quote(ciudad)))
        r = (g.get("results") or [None])[0]
        if not r:
            return f"No encontré la ciudad {ciudad}."
        lat, lon, nombre = r["latitude"], r["longitude"], r["name"]
    try:
        dia = max(0, min(6, int(dia or 0)))
    except (TypeError, ValueError):
        dia = 0
    d = json.loads(_leer(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&timezone=auto&forecast_days={dia + 1}"
        "&current=temperature_2m,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"))
    dd = d["daily"]
    cuando = "hoy" if dia == 0 else "mañana" if dia == 1 else "el " + DIAS[(date.today() + timedelta(days=dia)).weekday()]
    texto = (f"En {nombre}, {cuando} va a estar {_estado(dd['weather_code'][dia])}, "
             f"mínima de {round(dd['temperature_2m_min'][dia])} y máxima de {round(dd['temperature_2m_max'][dia])} grados, "
             f"con {dd['precipitation_probability_max'][dia] or 0} por ciento de probabilidad de lluvia.")
    if dia == 0:
        texto = f"Ahora hace {round(d['current']['temperature_2m'])} grados. " + texto
    return texto


def dolar():
    nombres = (("oficial", "oficial"), ("blue", "blue"), ("bolsa", "MEP"), ("tarjeta", "tarjeta"))
    datos = {x.get("casa"): x for x in json.loads(_leer("https://dolarapi.com/v1/dolares"))}
    partes = [f"{dicho}: {round(datos[casa]['compra'])} compra y {round(datos[casa]['venta'])} venta"
              for casa, dicho in nombres if datos.get(casa, {}).get("venta") and datos[casa].get("compra")]
    return ("Dólar " + "; ".join(partes) + ".") if partes else "No pude leer la cotización del dólar."


def titulares(tema="", cantidad=5):
    base = "https://news.google.com/rss"
    url = (base + "/search?q=" + urllib.parse.quote(tema) + "&" if tema else base + "?") + "hl=es-419&gl=AR&ceid=AR:es-419"
    items = list(ET.fromstring(_leer(url)).iter("item"))[:cantidad]
    return [(str(i.findtext("title") or "").rsplit(" - ", 1)[0].strip(), str(i.findtext("link") or "")) for i in items]


def noticias(tema="", con_links=False):
    lista = titulares(tema)
    if not lista:
        return "No encontré noticias" + (f" sobre {tema}." if tema else ".")
    if con_links:
        return (f"Noticias sobre {tema}:" if tema else "Titulares:") + "\n\n" + "\n\n".join(
            f"• {t}" for t, _ in lista)
    return (f"Noticias sobre {tema}: " if tema else "Titulares: ") + ". ".join(t for t, _ in lista) + "."


def lluvia_por_hora(lat=LAT, lon=LON):
    """[(hora, probabilidad %, milímetros)] de hoy y mañana (hora local)."""
    from datetime import datetime
    d = json.loads(_leer("https://api.open-meteo.com/v1/forecast"
                         f"?latitude={lat}&longitude={lon}&timezone=auto&forecast_days=2"
                         "&hourly=precipitation_probability,precipitation"))
    h = d["hourly"]
    return [(datetime.fromisoformat(t), int(p or 0), float(mm or 0))
            for t, p, mm in zip(h["time"], h["precipitation_probability"], h["precipitation"])]


MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")


def _json(url):
    return json.loads(_leer(url))


def proximo_feriado():
    hoy = date.today()
    feriados = []
    for anio in (hoy.year, hoy.year + 1):
        try:
            feriados += [f for f in _json(f"https://api.argentinadatos.com/v1/feriados/{anio}")
                         if date.fromisoformat(f["fecha"]) >= hoy]
        except Exception:
            pass
        if feriados:
            break
    if not feriados:
        return "No encontré el próximo feriado."
    f = min(feriados, key=lambda x: x["fecha"])
    d = date.fromisoformat(f["fecha"])
    faltan = (d - hoy).days
    cuando = ("hoy" if faltan == 0 else "mañana" if faltan == 1
              else f"el {DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}, en {faltan} días")
    return f"El próximo feriado es {cuando}: {f['nombre']}."


def riesgo_pais():
    d = _json("https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais/ultimo")
    return f"El riesgo país está en {round(d['valor'])} puntos."


def inflacion():
    lista = _json("https://api.argentinadatos.com/v1/finanzas/indices/inflacion")
    u, a = lista[-1], lista[-2]

    def v(x):
        return str(x).replace(".", ",")

    return (f"La inflación de {MESES[int(u['fecha'][5:7]) - 1]} fue de {v(u['valor'])} %. "
            f"En {MESES[int(a['fecha'][5:7]) - 1]} había sido {v(a['valor'])} %.")


def _plano(texto):
    """Minúsculas y sin tildes: 'Dólar' -> 'dolar'."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def cotizacion(moneda=""):
    m = _plano(moneda)
    if any(x in m for x in ("bitcoin", "btc", "ethereum", "ether", "cripto")):
        cual = "ethereum" if "ether" in m else "bitcoin"
        d = _json("https://api.coingecko.com/api/v3/simple/price?ids=" + cual + "&vs_currencies=usd")
        return f"El {cual} está a {round(d[cual]['usd'])} dólares."
    if "dolar" in m or "usd" in m:
        return dolar()
    codigos = (("euro", "EUR", "El euro"), ("real", "BRL", "El real"), ("chileno", "CLP", "El peso chileno"),
               ("uruguayo", "UYU", "El peso uruguayo"))
    cod, dicho = next(((c, d) for k, c, d in codigos if k in m), ("EUR", "El euro"))
    x = {c.get("moneda"): c for c in _json("https://dolarapi.com/v1/cotizaciones")}.get(cod) or {}
    if not x.get("venta"):
        return "No encontré esa moneda."
    v = float(x["venta"])
    return f"{dicho} oficial está a {round(v) if v >= 100 else str(round(v, 2)).replace('.', ',')} pesos."


def convertir(monto, de="dolar", a="peso"):
    """Convierte entre pesos, dólares (blue y oficial), euros y reales."""
    monto = float(str(monto).replace(",", "."))
    de, a = _plano(de), _plano(a)
    dol = {x.get("casa"): float(x["venta"]) for x in _json("https://dolarapi.com/v1/dolares") if x.get("venta")}
    otras = {x.get("moneda"): float(x["venta"]) for x in _json("https://dolarapi.com/v1/cotizaciones") if x.get("venta")}
    tasas = {"dolar": dol["oficial"], "euro": otras.get("EUR"), "real": otras.get("BRL"), "peso": 1.0}
    alias = {"usd": "dolar", "eur": "euro", "brl": "real", "ars": "peso"}

    def clave(s):
        s = alias.get(s.strip(), s)
        return next((k for k in tasas if k in s), "peso")

    de, a = clave(de), clave(a)

    def fmt(x):
        return str(round(x)) if x >= 100 or float(x).is_integer() else f"{x:.2f}".replace(".", ",")

    plural = {"dolar": "dólares", "euro": "euros", "real": "reales", "peso": "pesos"}
    texto = f"{fmt(monto)} {plural[de]} son {fmt(monto * tasas[de] / tasas[a])} {plural[a]} al oficial"
    if {de, a} == {"dolar", "peso"}:              # con el dólar, también al blue
        texto += f" y {fmt(monto * dol['blue'] if de == 'dolar' else monto / dol['blue'])} al blue"
    return texto + "."


EQUIPOS_AR = {"boca": "Boca Juniors", "river": "River Plate", "racing": "Racing Club", "independiente": "Independiente",
              "san lorenzo": "San Lorenzo", "estudiantes": "Estudiantes", "velez": "Velez Sarsfield",
              "newells": "Newell's Old Boys", "rosario central": "Rosario Central", "talleres": "Talleres",
              "belgrano": "Belgrano", "lanus": "Lanus", "huracan": "Huracan", "argentinos": "Argentinos Juniors",
              "banfield": "Banfield", "gimnasia": "Gimnasia La Plata", "tigre": "Tigre", "platense": "Platense",
              "seleccion": "Argentina", "argentina": "Argentina"}


DEPORTES = "https://www.thesportsdb.com/api/v1/json/3/"


def _buscar_equipo(equipo):
    import re
    import unicodedata
    clave = "".join(c for c in unicodedata.normalize("NFKD", str(equipo).lower()) if not unicodedata.combining(c))
    nombre = next((v for k, v in sorted(EQUIPOS_AR.items(), key=lambda x: -len(x[0]))
                   if re.search(r"\b" + k + r"\b", clave)), equipo)
    equipos = [x for x in (_json(DEPORTES + "searchteams.php?t=" + urllib.parse.quote(nombre)).get("teams") or [])
               if x.get("strSport") == "Soccer"]
    return next((x for x in equipos if x.get("strCountry") == "Argentina"), equipos[0] if equipos else None)


def _hora_partido(evento):
    from datetime import datetime, timezone, timedelta
    return datetime.fromisoformat(str(evento.get("strTimestamp"))[:19]).replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=-3))).replace(tzinfo=None)


def partido_de_hoy(equipo, hoy=None):
    """'Hoy juega Boca Juniors contra Unión a las 21:00 (Liga Profesional).' o None si hoy no juega."""
    hoy = hoy or date.today()
    eq = _buscar_equipo(equipo)
    if not eq:
        return None
    for ev in (_json(DEPORTES + "eventsnext.php?id=" + str(eq["idTeam"])).get("events") or [])[:2]:
        try:
            c = _hora_partido(ev)
        except (TypeError, ValueError):
            continue
        if c.date() == hoy:
            rival = ev["strAwayTeam"] if str(ev.get("idHomeTeam")) == str(eq["idTeam"]) else ev["strHomeTeam"]
            return f"Hoy juega {eq['strTeam']} contra {rival} a las {c.hour}:{c.minute:02d} ({ev.get('strLeague')})."
    return None


def feriado_de(fecha=None):
    """Nombre del feriado de esa fecha, o None."""
    fecha = fecha or date.today()
    try:
        for f in _json(f"https://api.argentinadatos.com/v1/feriados/{fecha.year}"):
            if f.get("fecha") == fecha.isoformat():
                return f.get("nombre")
    except Exception:
        pass
    return None


def futbol(equipo):
    """Último y próximo partido de un equipo (TheSportsDB, gratis)."""
    base = DEPORTES
    eq = _buscar_equipo(equipo)
    if not eq:
        return f"No encontré al equipo {equipo}."
    id_eq = str(eq["idTeam"])

    def seguro(url):
        try:
            return _json(url)
        except Exception:
            return {}

    # la versión gratis de "últimos" solo trae partidos de local: sumamos el último de cada torneo del equipo
    ligas = [str(eq[k]) for k in ["idLeague"] + [f"idLeague{i}" for i in range(2, 8)] if eq.get(k)]
    pasados = (seguro(base + "eventslast.php?id=" + id_eq).get("results") or []) + [
        e for x in ligas for e in (seguro(base + "eventspastleague.php?id=" + x).get("events") or [])
        if id_eq in (str(e.get("idHomeTeam")), str(e.get("idAwayTeam")))]
    pasados = [e for e in pasados if e.get("intHomeScore") not in (None, "")]
    ult = max(pasados, key=lambda e: str(e.get("strTimestamp") or e.get("dateEvent") or ""), default=None)
    prox = (seguro(base + "eventsnext.php?id=" + id_eq).get("events") or [None])[0]
    partes = []
    if ult:
        partes.append(f"Último: {ult['strHomeTeam']} {ult.get('intHomeScore')}, {ult['strAwayTeam']} "
                      f"{ult.get('intAwayScore')} ({ult.get('strLeague')})")
    if prox:
        c = _hora_partido(prox)
        partes.append(f"Próximo: {prox['strHomeTeam']} contra {prox['strAwayTeam']}, el {DIAS[c.weekday()]} "
                      f"{c.day} a las {c.hour}:{c.minute:02d} ({prox.get('strLeague')})")
    return ". ".join(partes) + "." if partes else f"No encontré partidos de {equipo}."


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    resto = " ".join(sys.argv[2:])
    if cmd == "clima":
        print(clima(resto))
    elif cmd == "dolar":
        print(dolar())
    elif cmd == "noticias":
        print(noticias(resto, con_links=True))
    else:
        print(__doc__)
