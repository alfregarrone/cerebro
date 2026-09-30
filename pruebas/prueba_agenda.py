"""Prueba de agenda.py con un calendario falso con el formato de Google (zonas, repetidos, excepciones)."""
import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pc"))
import agenda  # noqa: E402

ICS = r"""BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
CALSCALE:GREGORIAN
X-WR-CALNAME:alfre
X-WR-TIMEZONE:America/Argentina/Buenos_Aires
BEGIN:VTIMEZONE
TZID:America/Argentina/Buenos_Aires
X-LIC-LOCATION:America/Argentina/Buenos_Aires
BEGIN:STANDARD
TZOFFSETFROM:-0300
TZOFFSETTO:-0300
TZNAME:-03
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
DTSTART;TZID=America/Argentina/Buenos_Aires:20260929T100000
DTEND;TZID=America/Argentina/Buenos_Aires:20260929T110000
UID:dentista@google.com
SUMMARY:Dentista
LOCATION:Av. Santa Fe 1234, CABA, Argentina
END:VEVENT
BEGIN:VEVENT
DTSTART:20260929T183000Z
DTEND:20260929T193000Z
UID:reunion@google.com
SUMMARY:Reunión con Juan
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260930
DTEND;VALUE=DATE:20261001
UID:cumple@google.com
SUMMARY:Cumpleaños de Laura
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Argentina/Buenos_Aires:20260901T090000
DTEND;TZID=America/Argentina/Buenos_Aires:20260901T100000
RRULE:FREQ=WEEKLY;BYDAY=TU,TH
EXDATE;TZID=America/Argentina/Buenos_Aires:20261001T090000
UID:gimnasio@google.com
SUMMARY:Gimnasio
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Argentina/Buenos_Aires:20261006T120000
DTEND;TZID=America/Argentina/Buenos_Aires:20261006T130000
RECURRENCE-ID;TZID=America/Argentina/Buenos_Aires:20261006T090000
UID:gimnasio@google.com
SUMMARY:Gimnasio (movido)
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Argentina/Buenos_Aires:20260929T200000
DTEND;TZID=America/Argentina/Buenos_Aires:20260929T210000
UID:cancelado@google.com
STATUS:CANCELLED
SUMMARY:Cena cancelada
END:VEVENT
END:VCALENDAR
"""
ruta = Path(__file__).resolve().parent / "_calendario_prueba.ics"
ruta.write_bytes(ICS.replace("\n", "\r\n").encode("utf-8"))
cfg = {"calendario_ical": ruta.as_uri()}
ahora = datetime(2026, 9, 29, 8, 0)
casos = [
    ("hoy", agenda.del_dia(cfg, date(2026, 9, 29), ahora),
     ["2 cosas" not in "x", "a las 9, Gimnasio", "a las 10, Dentista (en Av. Santa Fe 1234)", "a las 15:30, Reunión con Juan"]),
    ("mañana", agenda.del_dia(cfg, date(2026, 9, 30), ahora), ["Mañana tenés una cosa", "todo el día: Cumpleaños de Laura"]),
    ("jueves con EXDATE", agenda.del_dia(cfg, date(2026, 10, 1), ahora), ["no tenés nada"]),
    ("martes movido", agenda.del_dia(cfg, date(2026, 10, 6), ahora), ["a las 12, Gimnasio (movido)"]),
    ("semana", agenda.semana(cfg, ahora), ["Hoy:", "Mañana: todo el día: Cumpleaños de Laura", "Gimnasio"]),
    ("próximos 90 min a las 8:45", str([e["titulo"] for e in agenda.proximos(cfg, 90, datetime(2026, 9, 29, 8, 45))]),
     ["Gimnasio", "Dentista"]),
    ("hoy a la tarde", agenda.del_dia(cfg, date(2026, 9, 29), datetime(2026, 9, 29, 17, 0)), ["No te queda nada"]),
]
mal = 0
for nombre, texto, esperado in casos:
    ok = all(x is True or x in texto for x in esperado) and "Cena cancelada" not in texto
    mal += not ok
    print("OK " if ok else "MAL", nombre, "->", texto)
try:
    agenda.del_dia({}, date(2026, 9, 29))
except agenda.AgendaError as e:
    print("OK  sin configurar ->", e)
ruta.unlink()
print("RESULTADO:", "OK" if not mal else f"{mal} MAL")
