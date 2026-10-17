"""Mails de Gmail por IMAP con una contraseña de aplicación. Solo lee: nunca marca como leído, borra ni manda nada.

  python correo.py            (usa "gmail_usuario" y "gmail_clave_app" de config_pc.json)
"""
import email
import email.header
import email.utils
import html
import imaplib
import json
import re
from datetime import datetime
from pathlib import Path

SERVIDOR = "imap.gmail.com"
PRINCIPAL = "is:unread category:primary"
IMPORTANTES = "is:unread is:important category:primary newer_than:2d"
MAX_BYTES = 150000          # de cada mail se baja solo el principio (los adjuntos grandes no hacen falta)


class CorreoError(Exception):
    pass


def configurado(config):
    return bool(str(config.get("gmail_usuario") or "").strip() and str(config.get("gmail_clave_app") or "").strip())


def _conectar(config):
    if not configurado(config):
        raise CorreoError("Todavía no conectaste tu Gmail. En la PC, ejecutá configurar.bat y poné tu mail y una "
                          "contraseña de aplicación.")
    try:
        m = imaplib.IMAP4_SSL(SERVIDOR, 993, timeout=15)
    except Exception as e:
        raise CorreoError("No pude conectarme a Gmail: " + str(e)[:100]) from e
    try:
        m.login(str(config["gmail_usuario"]).strip(), str(config["gmail_clave_app"]).replace(" ", "").strip())
    except imaplib.IMAP4.error as e:
        raise CorreoError("Gmail no aceptó la contraseña de aplicación. Creá una nueva y cargala con configurar.bat.") from e
    m.select("INBOX", readonly=True)          # solo lectura: no marca nada como leído
    return m


def _salir(m):
    try:
        m.logout()
    except Exception:
        pass


def _buscar(m, consulta):
    typ, datos = m.uid("SEARCH", "X-GM-RAW", '"' + consulta.replace('"', "") + '"')
    if typ != "OK":
        raise CorreoError("Gmail no aceptó la búsqueda.")
    return [int(x) for x in (datos[0] or b"").split()]


def _decodificar(valor):
    partes = []
    for texto, codif in email.header.decode_header(str(valor or "")):
        if isinstance(texto, bytes):
            try:
                texto = texto.decode(codif or "utf-8", errors="replace")
            except LookupError:
                texto = texto.decode("utf-8", errors="replace")
        partes.append(texto)
    return re.sub(r"\s+", " ", "".join(partes)).strip()


def _remitente(valor):
    nombre, direccion = email.utils.parseaddr(_decodificar(valor))
    return nombre.strip(' "') or direccion


def _texto(msg):
    """El texto del mail: el text/plain si hay; si no, el HTML sin etiquetas."""
    plano = html_ = ""
    for parte in msg.walk():
        if parte.get_content_maintype() != "text" or parte.get_filename():
            continue
        try:
            crudo = parte.get_payload(decode=True) or b""
            texto = crudo.decode(parte.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if parte.get_content_subtype() == "plain" and not plano:
            plano = texto
        elif parte.get_content_subtype() == "html" and not html_:
            html_ = texto
    if not plano and html_:
        html_ = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", html_)
        plano = html.unescape(re.sub(r"<[^>]+>", " ", html_))
    plano = re.sub(r"(?m)^>.*$", "", plano)                       # lo citado de mails anteriores
    plano = re.split(r"\n\s*(El .{5,80} escribió:|On .{5,80} wrote:)", plano)[0]
    return re.sub(r"\s+", " ", plano).strip()


def _traer(m, uids):
    if not uids:
        return []
    typ, datos = m.uid("FETCH", ",".join(str(u) for u in uids), f"(BODY.PEEK[]<0.{MAX_BYTES}>)")
    if typ != "OK":
        raise CorreoError("No pude leer los mails.")
    mails = []
    for item in datos:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        cabecera = item[0].decode(errors="replace")
        uid = re.search(r"UID (\d+)", cabecera)
        msg = email.message_from_bytes(item[1])
        try:
            fecha = email.utils.parsedate_to_datetime(msg.get("Date")).astimezone().replace(tzinfo=None)
        except Exception:
            fecha = None
        mails.append({"uid": int(uid.group(1)) if uid else 0, "de": _remitente(msg.get("From")),
                      "asunto": _decodificar(msg.get("Subject")) or "(sin asunto)", "fecha": fecha,
                      "texto": _texto(msg)[:700]})
    mails.sort(key=lambda x: x["uid"], reverse=True)
    return mails


def no_leidos(config, cantidad=10, consulta=PRINCIPAL):
    """(total sin leer, [los más nuevos con remitente, asunto y el principio del texto])."""
    m = _conectar(config)
    try:
        uids = _buscar(m, consulta)
        return len(uids), _traer(m, sorted(uids)[-cantidad:])
    finally:
        _salir(m)


def encabezados(config, cantidad=3, consulta=PRINCIPAL):
    """Rápido (para la voz): (total sin leer, [remitente y asunto de los más nuevos]) sin bajar el texto."""
    m = _conectar(config)
    try:
        uids = sorted(_buscar(m, consulta))
        elegidos = uids[-cantidad:]
        if not elegidos:
            return len(uids), []
        typ, datos = m.uid("FETCH", ",".join(map(str, elegidos)), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        mails = []
        for item in datos if typ == "OK" else []:
            if isinstance(item, tuple) and len(item) >= 2:
                uid = re.search(r"UID (\d+)", item[0].decode(errors="replace"))
                msg = email.message_from_bytes(item[1])
                mails.append({"uid": int(uid.group(1)) if uid else 0, "de": _remitente(msg.get("From")),
                              "asunto": _decodificar(msg.get("Subject")) or "(sin asunto)", "texto": ""})
        mails.sort(key=lambda x: x["uid"], reverse=True)
        return len(uids), mails
    finally:
        _salir(m)


def nuevos_importantes(config, ya_vistos):
    """Mails importantes sin leer que todavía no avisé. Devuelve (uids actuales, mails nuevos)."""
    m = _conectar(config)
    try:
        uids = _buscar(m, IMPORTANTES)
        nuevos = [u for u in uids if u not in set(ya_vistos)]
        return uids, _traer(m, sorted(nuevos)[-5:])
    finally:
        _salir(m)


def renglon(mail, largo=140):
    texto = mail["texto"][:largo].rstrip() + ("…" if len(mail["texto"]) > largo else "")
    return f"De {mail['de']}: {mail['asunto']}" + (f" — {texto}" if texto else "")


def hora_corta(fecha, hoy=None):
    if not fecha:
        return ""
    hoy = hoy or datetime.now().date()
    return fecha.strftime("%H:%M") if fecha.date() == hoy else fecha.strftime("%d/%m")


if __name__ == "__main__":
    cfg = json.loads((Path(__file__).resolve().parent / "config_pc.json").read_text(encoding="utf-8"))
    try:
        total, mails = no_leidos(cfg, 5)
        print(f"{total} sin leer en Principal")
        for x in mails:
            print("-", renglon(x))
    except CorreoError as e:
        print(e)
