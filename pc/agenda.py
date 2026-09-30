"""Agenda de Google Calendar (o cualquier calendario) leída con su link secreto iCal: sin contraseñas ni permisos.

  python agenda.py hoy | manana | semana        (usa "calendario_ical" de config_pc.json)
"""
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")
_CACHE = {}                 # url -> (hora de descarga, contenido)
REFRESCO = 10 * 60


class AgendaError(Exception):
    pass


def links(config):
    valor = config.get("calendario_ical") or []
    return [u.strip() for u in ([valor] if isinstance(valor, str) else valor) if str(u).strip()]


def _descargar(url, forzar=False):
    guardado = _CACHE.get(url)
    if guardado and not forzar and time.time() - guardado[0] < REFRESCO:
        return guardado[1]
    req = urllib.request.Request(url.replace("webcal://", "https://"), headers={"User-Agent": "Mozilla/5.0 (Cerebro)"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            datos = r.read()
    except Exception as e:
        if guardado:                      # sin internet: uso lo último que bajé
            return guardado[1]
        raise AgendaError("No pude bajar tu calendario: " + str(e)[:120])
    if b"BEGIN:VCALENDAR" not in datos[:2000]:
        raise AgendaError("El link del calendario no devuelve un calendario. Revisá que sea la "
                          "'Dirección secreta en formato iCal'.")
    _CACHE[url] = (time.time(), datos)
    return datos


def _local(valor):
    """date o datetime (con o sin zona) -> datetime local sin zona."""
    if isinstance(valor, datetime):
        return valor.astimezone().replace(tzinfo=None) if valor.tzinfo else valor
    return datetime(valor.year, valor.month, valor.day)


def eventos(config, desde, hasta):
    """Eventos entre dos datetimes locales, ordenados. Incluye los que se repiten y los de todo el día."""
    try:
        import icalendar
        import recurring_ical_events
    except ImportError:
        raise AgendaError("Falta instalar el lector de calendarios: ejecutá instalar-extras.bat en la PC.")
    urls = links(config)
    if not urls:
        raise AgendaError("Todavía no conectaste tu calendario. En la PC, ejecutá configurar.bat y pegá el link "
                          "secreto de Google Calendar.")
    lista = []
    for url in urls:
        try:
            cal = icalendar.Calendar.from_ical(_descargar(url))
        except AgendaError:
            raise
        except Exception as e:
            raise AgendaError("No pude leer tu calendario: " + str(e)[:120])
        # margen de un día para no perder eventos por la zona horaria; después se filtra exacto
        for ev in recurring_ical_events.of(cal).between(desde - timedelta(days=1), hasta + timedelta(days=1)):
            if str(ev.get("STATUS") or "").upper() == "CANCELLED":
                continue
            ini_crudo = ev.get("DTSTART").dt
            todo_el_dia = not isinstance(ini_crudo, datetime)
            inicio = _local(ini_crudo)
            fin_crudo = ev.get("DTEND").dt if ev.get("DTEND") else None
            fin = _local(fin_crudo) if fin_crudo else inicio + (timedelta(days=1) if todo_el_dia else timedelta(hours=1))
            if fin <= desde or inicio >= hasta:
                continue
            lista.append({"inicio": inicio, "fin": fin, "todo_el_dia": todo_el_dia,
                          "titulo": str(ev.get("SUMMARY") or "(sin título)").strip(),
                          "lugar": str(ev.get("LOCATION") or "").strip(),
                          "uid": str(ev.get("UID") or "") + "|" + inicio.isoformat()})
    lista.sort(key=lambda e: (not e["todo_el_dia"], e["inicio"]))
    vistos, unicos = set(), []
    for e in lista:                                   # el mismo evento en dos calendarios: una sola vez
        clave = (e["titulo"].lower(), e["inicio"])
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(e)
    return unicos


def hora_dicha(dt):
    return f"{dt.hour}" if dt.minute == 0 else f"{dt.hour}:{dt.minute:02d}"


def _renglon(e, con_lugar=True):
    lugar = f" (en {e['lugar'].split(',')[0]})" if con_lugar and e["lugar"] else ""
    if e["todo_el_dia"]:
        return f"todo el día: {e['titulo']}{lugar}"
    return f"a las {hora_dicha(e['inicio'])}, {e['titulo']}{lugar}"


def nombre_dia(fecha, hoy=None):
    hoy = hoy or date.today()
    if fecha == hoy:
        return "hoy"
    if fecha == hoy + timedelta(days=1):
        return "mañana"
    if fecha == hoy + timedelta(days=2):
        return "pasado mañana"
    texto = f"el {DIAS[fecha.weekday()]} {fecha.day}"
    return texto if 0 < (fecha - hoy).days < 7 else texto + f" de {MESES[fecha.month - 1]}"


def del_dia(config, fecha=None, ahora=None):
    """'Hoy tenés 2 cosas: a las 10, dentista; a las 15:30, reunión con Juan.'"""
    ahora = ahora or datetime.now()
    fecha = fecha or ahora.date()
    desde = datetime(fecha.year, fecha.month, fecha.day)
    lista = eventos(config, desde, desde + timedelta(days=1))
    cuando = nombre_dia(fecha, ahora.date())
    if fecha == ahora.date():                          # hoy: lo que ya terminó no se lee
        lista = [e for e in lista if e["todo_el_dia"] or e["fin"] > ahora]
    if not lista:
        return f"{cuando.capitalize()} no tenés nada en la agenda." if fecha != ahora.date() or not ahora.hour >= 12 \
            else "No te queda nada más en la agenda por hoy."
    cantidad = "una cosa" if len(lista) == 1 else f"{len(lista)} cosas"
    return f"{cuando.capitalize()} tenés {cantidad}: " + "; ".join(_renglon(e) for e in lista) + "."


def semana(config, ahora=None):
    ahora = ahora or datetime.now()
    desde = datetime(ahora.year, ahora.month, ahora.day)
    lista = [e for e in eventos(config, desde, desde + timedelta(days=7)) if e["todo_el_dia"] or e["fin"] > ahora]
    if not lista:
        return "No tenés nada en la agenda en los próximos 7 días."
    por_dia = {}
    for e in lista:
        por_dia.setdefault(e["inicio"].date() if not e["todo_el_dia"] else max(e["inicio"].date(), ahora.date()),
                           []).append(e)
    partes = [nombre_dia(d, ahora.date()).capitalize() + ": " + "; ".join(_renglon(e, False) for e in evs)
              for d, evs in sorted(por_dia.items())]
    return "En los próximos 7 días: " + ". ".join(partes) + "."


def proximos(config, minutos, ahora=None):
    """Eventos con hora que empiezan dentro de los próximos `minutos` (para avisar antes)."""
    ahora = ahora or datetime.now()
    return [e for e in eventos(config, ahora, ahora + timedelta(minutes=minutos))
            if not e["todo_el_dia"] and ahora < e["inicio"] <= ahora + timedelta(minutes=minutos)]


if __name__ == "__main__":
    cfg = json.loads((Path(__file__).resolve().parent / "config_pc.json").read_text(encoding="utf-8"))
    que = (sys.argv[1:] or ["hoy"])[0]
    try:
        if que == "semana":
            print(semana(cfg))
        else:
            print(del_dia(cfg, date.today() + timedelta(days={"hoy": 0, "manana": 1}.get(que, 0))))
    except AgendaError as e:
        print(e)
