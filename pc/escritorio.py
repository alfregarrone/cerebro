"""Control de pantalla para Cerebro: captura, mouse y teclado.

Uso desde la línea de comandos (lo usa Claude durante las tareas de pantalla):

  python escritorio.py captura                      -> guarda captura y muestra la ruta
  python escritorio.py captura --region 0 0 800 600
  python escritorio.py clic 500 320                 -> clic en esas coordenadas
  python escritorio.py doble-clic 500 320
  python escritorio.py escribir "hola que tal"
  python escritorio.py tecla enter                  -> enter, tab, esc, up, down...
  python escritorio.py atajo ctrl v                 -> combinación de teclas
  python escritorio.py mover 400 400
  python escritorio.py scroll -5                    -> negativo baja, positivo sube
  python escritorio.py abrir "spotify"              -> abre una app por el menú inicio
  python escritorio.py esperar 2
  python escritorio.py ventanas                     -> lista las ventanas abiertas
  python escritorio.py foco "Chrome"                -> trae una ventana al frente

Las capturas se guardan en la carpeta capturas, al lado de este archivo.
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
CAPTURAS = BASE / "capturas"

try:
    import pyautogui
    pyautogui.FAILSAFE = False   # mover el mouse a una esquina no corta la tarea
    pyautogui.PAUSE = 0.15
except ImportError:
    print("Falta pyautogui. Instalalo con: pip install pyautogui pillow")
    sys.exit(2)


def captura(region=None, nombre=None):
    CAPTURAS.mkdir(exist_ok=True)
    for viejo in sorted(CAPTURAS.glob("*.png"))[:-15]:   # solo guardamos las últimas 15
        viejo.unlink(missing_ok=True)
    destino = CAPTURAS / (nombre or f"{datetime.now():%H%M%S}.png")
    img = pyautogui.screenshot(region=tuple(region)) if region else pyautogui.screenshot()
    img.save(destino)
    ancho, alto = pyautogui.size()
    print(f"{destino}  (pantalla {ancho}x{alto}, imagen {img.width}x{img.height})")
    return destino


def ventanas():
    ps = ("Get-Process | Where-Object { $_.MainWindowTitle } | "
          "Select-Object -ExpandProperty MainWindowTitle")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8")
    print(r.stdout.strip() or "(no hay ventanas con título)")


def foco(texto):
    ps = (f"$w = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{texto}*' }} | Select-Object -First 1; "
          "if ($w) { (New-Object -ComObject WScript.Shell).AppActivate($w.Id) | Out-Null; "
          "Write-Output ('foco en: ' + $w.MainWindowTitle) } else { Write-Output 'no encontre esa ventana' }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8")
    print(r.stdout.strip())


def abrir(nombre):
    """Abre una app usando el menú inicio, como haría una persona."""
    pyautogui.press("win")
    time.sleep(0.8)
    pyautogui.write(nombre, interval=0.03)
    time.sleep(1.2)
    pyautogui.press("enter")
    time.sleep(2)
    print(f"abrí (o intenté abrir): {nombre}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1].lower(), sys.argv[2:]
    if cmd == "captura":
        region = None
        if "--region" in args:
            i = args.index("--region")
            region = [int(x) for x in args[i + 1:i + 5]]
        captura(region)
    elif cmd in ("clic", "click"):
        pyautogui.click(int(args[0]), int(args[1]))
        print(f"clic en {args[0]},{args[1]}")
    elif cmd in ("doble-clic", "doble_clic"):
        pyautogui.doubleClick(int(args[0]), int(args[1]))
        print(f"doble clic en {args[0]},{args[1]}")
    elif cmd == "derecho":
        pyautogui.rightClick(int(args[0]), int(args[1]))
        print(f"clic derecho en {args[0]},{args[1]}")
    elif cmd == "mover":
        pyautogui.moveTo(int(args[0]), int(args[1]), duration=0.3)
        print("mouse movido")
    elif cmd == "escribir":
        pyautogui.write(" ".join(args), interval=0.02)
        print("texto escrito")
    elif cmd == "tecla":
        pyautogui.press(args[0])
        print(f"tecla {args[0]}")
    elif cmd == "atajo":
        pyautogui.hotkey(*args)
        print("atajo " + "+".join(args))
    elif cmd == "scroll":
        pyautogui.scroll(int(args[0]) * 120)
        print("scroll")
    elif cmd == "abrir":
        abrir(" ".join(args))
    elif cmd == "esperar":
        time.sleep(float(args[0]))
        print("esperado")
    elif cmd == "ventanas":
        ventanas()
    elif cmd == "foco":
        foco(" ".join(args))
    else:
        print(f"no conozco el comando {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
