"""Prueba REAL de música en esta PC (con permiso del usuario): YouTube y Spotify suenan unos segundos y se pausan.
Usa una copia aislada de Cerebro (no arranca el agente ni se conecta a nada)."""
import json
import re
import shutil
import sys
import time
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
T = Path(__file__).resolve().parent / "_copia_musica"
shutil.rmtree(T, ignore_errors=True)
T.mkdir()
for f in ("cerebro_pc.py", "info.py", "medios.py"):
    shutil.copy(RAIZ / "pc" / f, T / f)
clave = re.search(r'GEMINI_API_KEY\s*=\s*"([^"]+)"', (RAIZ / "lambda" / "config.py").read_text(encoding="utf-8")).group(1)
(T / "config_pc.json").write_text(json.dumps({"cerebro_link": "prueba-falsa:x", "carpeta_notas": str(T / "notas"),
                                              "gemini_api_key": clave}), encoding="utf-8")
sys.path.insert(0, str(T))
sys.modules["casa"] = types.ModuleType("casa")
import cerebro_pc as c  # noqa: E402

c.registrar = lambda *a, **k: None
medios = c._medios()


def estado():
    try:
        return [(medios.nombre_app(s["app"]), s["estado"], s["titulo"][:50]) for s in medios.sesiones()]
    except Exception as e:
        return str(e)


que = (sys.argv[1:] or ["youtube"])[0]
print("antes:", estado())
t0 = time.time()
if que == "youtube":
    print("poner:", c.accion_musica({"busqueda": "los redondos"}), f"({time.time() - t0:.1f} s)")
    time.sleep(9)
else:
    print("poner:", c.accion_musica({"busqueda": "soda stereo", "servicio": "spotify"}), f"({time.time() - t0:.1f} s)")
    time.sleep(3)
print("sonando:", estado())
print("qué suena:", c.accion_musica_control({"accion": "que_suena"}))
print("siguiente:", c.accion_musica_control({"accion": "siguiente"}))
time.sleep(2)
print("pausa:", c.accion_musica_control({"accion": "pausa"}))
time.sleep(1)
print("después:", estado())
shutil.rmtree(T, ignore_errors=True)
