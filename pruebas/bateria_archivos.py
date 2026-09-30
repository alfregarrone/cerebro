"""Prueba del bot de Telegram recibiendo nota de voz, archivo con indicación y foto sola (todo simulado)."""
import io
import json
import re
import shutil
import sys
import threading
import time
import types
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
T = Path(__file__).resolve().parent / "_copia_archivos"
shutil.rmtree(T, ignore_errors=True)
T.mkdir()
for f in ("cerebro_pc.py", "info.py", "agenda.py", "correo.py", "medios.py"):
    shutil.copy(RAIZ / "pc" / f, T / f)
clave = re.search(r'GEMINI_API_KEY\s*=\s*"([^"]+)"', (RAIZ / "lambda" / "config.py").read_text(encoding="utf-8")).group(1)
(T / "config_pc.json").write_text(json.dumps({"cerebro_link": "prueba-falsa:x", "carpeta_notas": str(T / "notas"),
                                              "gemini_api_key": clave, "telegram_token": "falso"}), encoding="utf-8")
sys.path.insert(0, str(T))
sys.modules["casa"] = types.ModuleType("casa")
import cerebro_pc as c  # noqa: E402

RESPUESTAS, CLAUDE = [], []
c.registrar = lambda *a, **k: None
c._telegram_chat_id = lambda: "123"
c._telegram_responder = lambda texto: RESPUESTAS.append(texto)
c.hilo_consulta_remota = lambda x: CLAUDE.append(x)
c.transcribir_audio = lambda ruta: "qué hora es en la compu"      # la transcripción real ya se probó aparte
ahora = time.time()
ACTUALIZACIONES = [
    {"update_id": 1, "message": {"chat": {"id": 123}, "date": ahora, "voice": {"file_id": "v1"}}},
    {"update_id": 2, "message": {"chat": {"id": 123}, "date": ahora, "caption": "guardalo en el escritorio y renombralo a factura",
                                 "document": {"file_id": "d1", "file_name": "factura septiembre.pdf"}}},
    {"update_id": 3, "message": {"chat": {"id": 123}, "date": ahora, "photo": [{"file_id": "p0"}, {"file_id": "p1"}]}},
    {"update_id": 4, "message": {"chat": {"id": 999}, "date": ahora, "text": "apagá la pc"}},        # chat ajeno
]
entregadas = []


def telegram_falso(metodo, datos=None, timeout=10):
    if metodo == "getUpdates":
        if not entregadas:
            entregadas.append(1)
            return {"ok": True, "result": ACTUALIZACIONES}
        time.sleep(60)
        return {"ok": True, "result": []}
    if metodo == "getFile":
        return {"ok": True, "result": {"file_path": "archivos/" + datos["file_id"]}}
    return {"ok": True}


c._telegram = telegram_falso
original = urllib.request.urlopen


def urlopen_falso(url, *a, **k):
    if isinstance(url, str) and url.startswith("https://api.telegram.org/file/"):
        return io.BytesIO(b"contenido de prueba")
    return original(url, *a, **k)


urllib.request.urlopen = urlopen_falso
carpeta = Path.home() / "Downloads" / "Cerebro"
antes = set(carpeta.glob("*")) if carpeta.exists() else set()
threading.Thread(target=c.escuchar_telegram, daemon=True).start()
for _ in range(60):
    if len(RESPUESTAS) >= 4 or (len(RESPUESTAS) >= 3 and CLAUDE):
        break
    time.sleep(0.5)
time.sleep(2)
nuevos = sorted(set(carpeta.glob("*")) - antes) if carpeta.exists() else []
print("Respuestas del bot:")
for r in RESPUESTAS:
    print("  -", r[:160])
print("Pasado a Claude:", CLAUDE)
print("Archivos guardados:", [f.name for f in nuevos])
ok = (any(r.startswith("🎤") for r in RESPUESTAS) and any("factura septiembre.pdf" in x for x in CLAUDE)
      and any("Guardé foto_" in r for r in RESPUESTAS) and not any("apag" in r.lower() for r in RESPUESTAS))
print("RESULTADO:", "OK" if ok else "MAL")
for f in nuevos:                                   # limpiar lo que dejó la prueba
    f.unlink()
shutil.rmtree(T, ignore_errors=True)
