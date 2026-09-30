"""Batería de pruebas de Cerebro por VOZ: corre la skill entera (lambda_function.py) con un Echo falso.

La IA es la real; la PC, recordatorios, temporizadores y la radio están simulados (se anota qué haría).
Uso:  python bateria_voz.py      (necesita ask-sdk en PYTHONPATH, igual que Alexa-hosted)
"""
import sys
import time
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "lambda"))
import lambda_function as L  # noqa: E402
from ask_sdk_core.attributes_manager import AttributesManager  # noqa: E402
from ask_sdk_core.handler_input import HandlerInput  # noqa: E402
from ask_sdk_model import (RequestEnvelope, IntentRequest, Intent, Slot, Context, Session, Application,  # noqa: E402
                           User, Device, SupportedInterfaces, Permissions)
from ask_sdk_model.interfaces.system import SystemState  # noqa: E402
from ask_sdk_model.interfaces.audioplayer import AudioPlayerInterface  # noqa: E402

EFECTOS = []


def pc(accion, datos, wait=None):
    EFECTOS.append("pc:" + accion)
    textos = {"pendientes": "No tenés pendientes.", "que_sabes": "Sé que tu hermana se llama Laura.",
              "compras": "La lista de compras está vacía.", "programados": "No tenés avisos.",
              "info_pc": "El disco tiene 20 gigas libres.", "estado": "Tu PC está conectada.",
              "aprendidos": "[]", "tareas_estado": "No estoy haciendo nada.", "whatsapp": "Le voy a mandar a Laura: hola.",
              "agenda": "Hoy tenés una cosa: a las 10, Dentista.", "mails": "Tenés 2 mails sin leer.",
              "salud_pc": "La PC anda bien.", "musica_control": "Pausado."}
    return {"ok": True, "texto": textos.get(accion, f"[{accion}]")}


L.send_to_pc = pc
L.send_to_pc_async = lambda accion, datos: EFECTOS.append("pc_async:" + accion)
L.notify_phone = lambda texto: EFECTOS.append("celular") or True
L.has_permission = lambda h, scope: True
L.create_reminder = lambda h, a: EFECTOS.append("recordatorio" + (":repite" if a.get("repetir") else ""))
L.create_timer = lambda h, a: EFECTOS.append("temporizador")
L.gestionar_recordatorios = lambda h, kind, a: (EFECTOS.append(kind), "Tenés un recordatorio.")[1]
L.gestionar_temporizadores = lambda h, kind: (EFECTOS.append(kind), "No tenés temporizadores.")[1]
L.buscar_radio = lambda nombre: ("Radio de prueba", "https://radio.test/stream.mp3")


class Persistencia:
    def __init__(self):
        self.datos = {}

    def get_attributes(self, request_envelope):
        return dict(self.datos)

    def save_attributes(self, request_envelope, attributes):
        self.datos = dict(attributes)


class Directivas:
    def enqueue(self, pedido):
        EFECTOS.append("un_segundo")


FABRICA = types.SimpleNamespace(get_directive_service=lambda: Directivas(),
                                get_reminder_management_service=lambda: None,
                                get_timer_management_service=lambda: None)
PERSISTENCIA = Persistencia()
SESION = {}


def decir(frase, intent="ChatIntent", manejador=None):
    sistema = SystemState(application=Application("skill"), user=User("usuario", permissions=Permissions("token")),
                          device=Device("echo", supported_interfaces=SupportedInterfaces(audio_player=AudioPlayerInterface())),
                          api_endpoint="https://api.amazonalexa.com")
    pedido = IntentRequest(request_id="r" + str(time.time()), locale="es-US",
                           intent=Intent(name=intent, slots={"query": Slot(name="query", value=frase)} if frase else {}))
    sobre = RequestEnvelope(version="1.0", session=Session(new=False, session_id="s", attributes=dict(SESION)),
                            context=Context(system=sistema), request=pedido)
    am = AttributesManager(request_envelope=sobre, persistence_adapter=PERSISTENCIA)
    hi = HandlerInput(request_envelope=sobre, attributes_manager=am, service_client_factory=FABRICA)
    resp = (manejador or L.ChatHandler()).handle(hi)
    SESION.clear()
    SESION.update(am.session_attributes)
    habla = resp.output_speech.ssml if resp.output_speech else ""
    import re
    return re.sub(r"<[^>]+>", "", habla), [d.object_type for d in (resp.directives or [])]


# (frase, efectos aceptados). "texto" = solo hablar. Un efecto "x" pasa si alguno de los hechos empieza con x.
CASOS = [
    ("qué hora es", "texto"), ("qué día es hoy", "texto"), ("clima", "texto"), ("¿y mañana?", "texto"),
    ("cómo está el dólar", "texto"), ("cuántos pesos son cien dólares", "texto"), ("a cuánto está el euro", "texto"),
    ("cómo salió Boca", "texto"), ("cuándo es el próximo feriado", "texto"), ("cuánto está el riesgo país", "texto"),
    ("noticias", "texto"), ("repetí", "texto"),
    ("prendé la luz", {"pc:casa"}), ("apagá la luz", {"pc:casa"}), ("poné la luz roja", {"pc:casa"}),
    ("bajá la luz", {"pc:casa"}), ("está prendida la luz", {"pc:casa"}), ("modo fiesta", {"pc:frase", "pc:casa"}), ("apagá la luz y subí el volumen", {"pc:casa"}),
    ("poné un temporizador de diez minutos para los fideos", {"temporizador"}),
    ("cuánto le falta al temporizador", {"temporizadores"}), ("cancelá el temporizador", {"cancelar_temporizador"}),
    ("recordame en veinte minutos sacar la ropa", {"recordatorio"}), ("despertame a las siete", {"recordatorio"}),
    ("recordame tomar agua cada dos horas", {"recordatorio:repite", "pc:programar"}),
    ("todos los lunes a las nueve recordame la reunión", {"recordatorio:repite"}),
    ("qué recordatorios tengo", {"recordatorios"}),
    ("poné la radio Mitre", {"AudioPlayer.Play"}),
    ("poné música de soda stereo", {"pc:musica"}), ("subí el volumen", {"pc:volumen"}), ("abrí chrome", {"pc:abrir_app"}),
    ("anotá comprar pilas", {"pc:nota"}), ("qué pendientes tengo", {"pc:pendientes"}),
    ("agregá leche a la lista de compras", {"pc:compras"}), ("qué hay en la lista de compras", {"pc:compras"}),
    ("qué mensajes tengo", {"pc:whatsapp_resumen"}), ("qué me escribió Laura", {"pc:whatsapp_leer"}),
    ("mandale un whatsapp a Laura diciendo que llego tarde", {"pc:whatsapp"}),
    ("mandame la pantalla", {"pc:captura"}), ("qué estás haciendo", {"pc:tareas_estado"}),
    ("investigá las mejores apps de finanzas y resumilas", {"pc:tarea"}),
    ("desactivá las alertas del dólar", {"pc:alertas"}),
    ("mi hermana se llama Laura", "texto"), ("qué sabés de mí", {"pc:que_sabes", "texto"}),
    ("contame un chiste corto", "texto"), ("cuánto es el quince por ciento de doscientos", "texto"),
    ("qué me recomendás cenar hoy", "texto"), ("cómo se dice gracias en inglés", "texto"),
    ("gracias", "texto"),
    ("qué tengo hoy", {"pc:agenda"}), ("qué tengo mañana", {"pc:agenda"}), ("tengo alguna reunión esta semana", {"pc:agenda"}),
    ("tengo mails", {"pc:mails"}), ("fijate si me llegó algún correo importante", {"pc:mails"}),
    ("pasá el tema", {"pc:musica_control"}), ("qué está sonando", {"pc:musica_control"}),
    ("pausá la música de la compu", {"pc:musica_control"}), ("cómo está la pc", {"pc:salud_pc"}),
    ("cuánto espacio le queda al disco de la compu", {"pc:salud_pc", "pc:info_pc"}),
    ("mandame el resumen de la mañana a las siete y media", {"pc:resumen_manana"}),
    ("activá las alertas de mails importantes", {"pc:alertas"}),
]

bien = mal = 0
fallas = []
inicio = time.time()
for frase, esperado in CASOS:
    EFECTOS.clear()
    t0 = time.time()
    try:
        habla, directivas = decir(frase)
    except Exception as e:
        habla, directivas = f"EXCEPCIÓN: {e!r}", []
    hechos = [e for e in EFECTOS if e not in ("un_segundo", "pc:aprendidos") and not e.startswith("pc_async")] + directivas
    if esperado == "texto":
        ok = bool(habla) and not hechos and "EXCEPCIÓN" not in habla and "tardó demasiado" not in habla \
            and "Se me cortó" not in habla
    else:
        ok = any(h.startswith(tuple(esperado)) for h in hechos) or ("texto" in esperado and not hechos and habla)
    bien += ok
    mal += not ok
    print(f"{'OK ' if ok else 'MAL'} [{time.time() - t0:4.1f}s] {frase!r} -> {hechos} | {habla[:100]!r}", flush=True)
    if not ok:
        fallas.append((frase, esperado, hechos, habla[:150]))
    time.sleep(3.0 if time.time() - t0 > 0.5 else 0.2)

# "Alexa, pausa" / "continuá" / "siguiente" dentro de la skill, sin radio sonando: van a la música de la PC
for intent, manejador in (("AMAZON.PauseIntent", L.PausaHandler()), ("AMAZON.ResumeIntent", L.PausaHandler()),
                          ("AMAZON.NextIntent", L.SiguienteHandler()), ("AMAZON.PreviousIntent", L.SiguienteHandler())):
    EFECTOS.clear()
    habla, directivas = decir("", intent, manejador)
    ok = "pc:musica_control" in EFECTOS and bool(habla)
    bien += ok
    mal += not ok
    print(f"{'OK ' if ok else 'MAL'} {intent} -> {EFECTOS} | {habla!r}")
    if not ok:
        fallas.append((intent, EFECTOS[:], habla))

print(f"\n{bien} bien, {mal} mal, en {time.time() - inicio:.0f} s")
for f in fallas:
    print("  FALLA:", f)
