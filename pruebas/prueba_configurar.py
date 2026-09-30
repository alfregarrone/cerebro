"""Prueba configurar.py con respuestas simuladas (calendario de prueba y Gmail falso). No toca nada real."""
import builtins
import getpass
import imaplib
import json
import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
T = Path(__file__).resolve().parent / "_copia_configurar"
shutil.rmtree(T, ignore_errors=True)
T.mkdir()
for f in ("configurar.py", "agenda.py", "correo.py"):
    shutil.copy(RAIZ / "pc" / f, T / f)
ICS = (Path(__file__).resolve().parent / "prueba_agenda.py").read_text(encoding="utf-8").split('ICS = r"""')[1].split('"""')[0]
(T / "cal.ics").write_bytes(ICS.replace("\n", "\r\n").encode("utf-8"))
(T / "config_pc.json").write_text(json.dumps({"cerebro_link": "x:y", "telegram_token": "no-tocar"}), encoding="utf-8")
sys.path.insert(0, str(T))


class GmailFalso:
    def __init__(self, *a, **k):
        pass

    def login(self, u, p):
        if p != "abcdefghijklmnop":
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, *a, **k):
        return "OK", [b"1"]

    def uid(self, cmd, *a):
        return ("OK", [b"7 8"]) if cmd == "SEARCH" else ("OK", [])

    def logout(self):
        pass


imaplib.IMAP4_SSL = GmailFalso
respuestas = iter([
    "esto no es un link", (T / "cal.ics").as_uri(), "n",       # calendario: uno inválido, uno bueno, no agrega otro
    "yo@gmail.com", "s", "yo@gmail.com",                       # gmail: clave mala -> probar de nuevo
    "7.30", "s",                                               # resumen 7:30 de lunes a viernes
    "Boca",                                                    # equipo
])
claves = iter(["mala mala", "abcd efgh ijkl mnop"])
builtins.input = lambda texto="": (print(texto, end=""), print(r := next(respuestas)), r)[2]
getpass.getpass = lambda texto="": (print(texto + "********"), next(claves))[1]
os.environ["COMPUTERNAME"] = "PRUEBA"
import configurar  # noqa: E402

configurar.main()
cfg = json.loads((T / "config_pc.json").read_text(encoding="utf-8"))
estado = json.loads((T / "estado.json").read_text(encoding="utf-8"))
print()
print("config:", {k: ("***" if "clave" in k else v) for k, v in cfg.items()})
print("estado:", estado)
ok = (cfg["telegram_token"] == "no-tocar" and cfg["cerebro_link"] == "x:y" and len(cfg["calendario_ical"]) == 1
      and cfg["gmail_clave_app"] == "abcdefghijklmnop" and cfg["resumen_hora"] == "07:30" and cfg["equipo"] == "Boca"
      and estado["resumen"] == {"activo": True, "hora": "07:30", "dias": "semana", "equipo": "Boca"})
print("RESULTADO:", "OK" if ok else "MAL")
shutil.rmtree(T, ignore_errors=True)
