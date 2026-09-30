"""Configura en esta PC lo que Cerebro no puede averiguar solo: tu Google Calendar, tu Gmail, la hora del resumen de
la mañana y tu equipo. Prueba cada cosa en el momento y la guarda en config_pc.json (sin tocar lo demás).

Se abre con configurar.bat.
"""
import getpass
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUTA = BASE / "config_pc.json"
ESTADO = BASE / "estado.json"
sys.path.insert(0, str(BASE))


def pregunta(texto, defecto=""):
    try:
        r = input(texto + (f" [{defecto}]" if defecto else "") + ": ").strip()
    except EOFError:
        return defecto
    return r or defecto


def si(texto):
    return pregunta(texto + " (s/n)", "n").lower().startswith("s")


def titulo(texto):
    print()
    print("=" * 60)
    print("  " + texto)
    print("=" * 60)


def guardar(cfg):
    RUTA.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def calendario(cfg):
    import agenda
    titulo("1 de 4 - Google Calendar")
    actuales = agenda.links(cfg)
    if actuales:
        print(f"Ya tenés {len(actuales)} calendario(s) conectado(s).")
        if not si("¿Querés cambiarlos o agregar otro?"):
            return
        if si("¿Borro los que están y empiezo de cero?"):
            actuales = []
    print("Cómo sacar el link (una sola vez):")
    print("  1. En la compu, entrá a calendar.google.com")
    print("  2. Arriba a la derecha: la ruedita > Configuración")
    print("  3. A la izquierda, en 'Configuración de mis calendarios', tocá tu calendario")
    print("  4. Bajá hasta 'Integrar el calendario' y copiá la 'Dirección secreta en formato iCal'")
    print("     (termina en .ics). No la compartas con nadie: el que la tiene ve tu agenda.")
    while True:
        link = pregunta("Pegá el link acá (Enter para saltear)")
        if not link:
            break
        if not link.startswith(("https://", "http://", "webcal://", "file:")):
            print("  Eso no parece un link. Tiene que empezar con https://")
            continue
        prueba = {"calendario_ical": actuales + [link]}
        try:
            desde = datetime.now()
            eventos = agenda.eventos(prueba, desde, desde + timedelta(days=7))
            print(f"  ¡Conectado! Veo {len(eventos)} evento(s) en los próximos 7 días.")
            for e in eventos[:3]:
                print("   -", e["inicio"].strftime("%d/%m %H:%M"), e["titulo"])
            actuales.append(link)
        except agenda.AgendaError as e:
            print("  No funcionó:", e)
            continue
        if not si("¿Agregás otro calendario (por ejemplo, uno compartido)?"):
            break
    cfg["calendario_ical"] = actuales
    guardar(cfg)


def gmail(cfg):
    import correo
    titulo("2 de 4 - Gmail")
    if correo.configurado(cfg):
        print(f"Ya está conectado el Gmail {cfg.get('gmail_usuario')}.")
        if not si("¿Querés cambiarlo?"):
            return
    print("Cerebro solo LEE tus mails (no marca como leído, no borra ni manda nada).")
    print("Necesita una 'contraseña de aplicación' (NO es tu contraseña de Google):")
    print("  1. Entrá a https://myaccount.google.com/apppasswords")
    print("     (si no aparece, primero activá la 'Verificación en 2 pasos' en tu cuenta)")
    print("  2. Poné un nombre, por ejemplo Cerebro, y tocá Crear")
    print("  3. Copiá las 16 letras que aparecen")
    while True:
        usuario = pregunta("Tu Gmail (Enter para saltear)", str(cfg.get("gmail_usuario") or ""))
        if not usuario:
            return
        clave = getpass.getpass("Pegá la contraseña de aplicación (no se ve mientras la pegás, es normal): ")
        clave = clave.replace(" ", "").strip()
        if not clave:
            print("  No llegó nada. Probá pegar con clic derecho, o escribila (son 16 letras).")
            continue
        prueba = {"gmail_usuario": usuario, "gmail_clave_app": clave}
        try:
            total, _ = correo.no_leidos(prueba, 1)
            print(f"  ¡Conectado! Tenés {total} mail(s) sin leer en Principal.")
        except correo.CorreoError as e:
            print("  No funcionó:", e)
            if si("¿Probás de nuevo?"):
                continue
            return
        cfg.update(prueba)
        guardar(cfg)
        return


def resumen(cfg):
    titulo("3 de 4 - Resumen de la mañana")
    print("Todas las mañanas te llega por Telegram: clima, agenda, pendientes, mails, dólar y titulares.")
    hora = pregunta("¿A qué hora? (por ejemplo 7:30; 'no' para no recibirlo)", str(cfg.get("resumen_hora") or "08:00"))
    estado = {}
    try:
        estado = json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    r = estado.setdefault("resumen", {})
    if hora.lower().startswith("n"):
        r["activo"] = False
    else:
        partes = hora.replace(".", ":").split(":")
        try:
            h, m = int(partes[0]), int(partes[1]) if len(partes) > 1 else 0
            assert 0 <= h < 24 and 0 <= m < 60
        except (ValueError, AssertionError):
            print("  No entendí la hora; dejo las 8:00.")
            h, m = 8, 0
        cfg["resumen_hora"] = f"{h:02d}:{m:02d}"
        r.update({"activo": True, "hora": cfg["resumen_hora"]})
        if si("¿Solo de lunes a viernes?"):
            r["dias"] = "semana"
        else:
            r["dias"] = "todos"
        print(f"  Listo: {'de lunes a viernes' if r['dias'] == 'semana' else 'todos los días'} a las {cfg['resumen_hora']}.")
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    guardar(cfg)


def equipo(cfg):
    titulo("4 de 4 - Tu equipo (opcional)")
    print("Si juega ese día, te lo digo en el resumen.")
    nombre = pregunta("¿De qué equipo sos? (Enter para saltear)", str(cfg.get("equipo") or ""))
    if nombre:
        cfg["equipo"] = nombre
        try:
            estado = json.loads(ESTADO.read_text(encoding="utf-8"))
            estado.setdefault("resumen", {})["equipo"] = nombre
            ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass
        guardar(cfg)


def main():
    if not RUTA.exists():
        print("No encuentro config_pc.json en esta carpeta. Ejecutá esto en la carpeta de Cerebro.")
        return
    cfg = json.loads(RUTA.read_text(encoding="utf-8"))
    print("Configuración de Cerebro: agenda, mails y resumen de la mañana.")
    print("Podés saltear cualquier paso con Enter y volver a ejecutar esto cuando quieras.")
    for paso in (calendario, gmail, resumen, equipo):
        try:
            paso(cfg)
        except KeyboardInterrupt:
            print()
            return
        except Exception as e:
            print("  Algo falló en este paso:", str(e)[:200])
    titulo("Listo")
    print("Guardé todo. Ahora reinicio Cerebro para que lo use.")


if __name__ == "__main__":
    main()
