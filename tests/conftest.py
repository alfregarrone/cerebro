"""Fixtures compartidas de la suite de Cerebro.

Todo corre en Linux, sin red, sin AWS y sin Windows:

- ``skill``: el módulo ``lambda/lambda_function.py`` importado con un config de prueba.
- ``echo``: un Echo falso para hablarle a la skill entera (ChatHandler y los demás handlers) con la IA,
  la PC, los recordatorios, los temporizadores y la radio simulados. Anota los efectos que hubiera tenido.
- ``pc``: el agente ``pc/cerebro_pc.py`` importado desde una copia aislada, con Telegram, ntfy y el
  registro simulados, y el estado (notas, memoria, programados) limpio en cada prueba.

La red está bloqueada en todas las pruebas, salvo hacia 127.0.0.1 (para el panel local).
"""
import json
import os
import re
import shutil
import socket
import sys
import time
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
LOCALES = ("127.0.0.1", "::1", "localhost", "0.0.0.0")


# ---------- sin red ----------

@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    """Ninguna prueba puede salir a internet: falla rápido en vez de colgarse esperando una API."""
    conectar = socket.socket.connect
    resolver = socket.getaddrinfo

    def conectar_guardado(self, direccion, *a, **k):
        host = direccion[0] if isinstance(direccion, tuple) else str(direccion)
        if host in LOCALES:
            return conectar(self, direccion, *a, **k)
        raise OSError(f"red deshabilitada en las pruebas (intento de conectar a {host!r})")

    def resolver_guardado(host, *a, **k):
        if host in LOCALES or host is None:
            return resolver(host, *a, **k)
        raise OSError(f"red deshabilitada en las pruebas (intento de resolver {host!r})")

    monkeypatch.setattr(socket.socket, "connect", conectar_guardado)
    monkeypatch.setattr(socket, "getaddrinfo", resolver_guardado)


# ---------- la skill ----------

CONFIG_SKILL = {
    "GEMINI_API_KEY": "clave-de-prueba",
    "MODELS": [("modelo-a", None), ("modelo-b", "minimal")],
    "AI_TIMEOUT": 5.0,
    "VOICE": "",
    "CITY": "Buenos Aires",
    "LATITUDE": -34.6037,
    "LONGITUDE": -58.3816,
    "UTC_OFFSET_HOURS": -3,
    "TIMEZONE_ID": "America/Argentina/Buenos_Aires",
    "WEB_SEARCH": False,
    "CEREBRO_LINK": "topico-prueba:clave-secreta-de-prueba",
}


@pytest.fixture(scope="session")
def skill():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("DYNAMODB_PERSISTENCE_REGION", "us-east-1")
    os.environ.setdefault("DYNAMODB_PERSISTENCE_TABLE_NAME", "cerebro-pruebas")
    config = types.ModuleType("config")
    config.__dict__.update(CONFIG_SKILL)
    sys.modules["config"] = config
    sys.path.insert(0, str(RAIZ / "lambda"))
    import lambda_function
    return lambda_function


class Respuesta:
    """Lo que dijo la skill y qué hubiera hecho."""

    def __init__(self, habla, directivas, efectos, tarjeta, fin):
        self.habla = habla
        self.directivas = directivas
        self.efectos = efectos
        self.tarjeta = tarjeta
        self.fin = fin

    def __repr__(self):
        return f"Respuesta({self.habla!r}, efectos={self.efectos}, directivas={self.directivas})"


class EchoFalso:
    """Le habla a la skill como lo haría Alexa, con todo lo externo simulado.

    - ``echo.ia = lambda system, messages, **kw: "texto"``: qué contesta Gemini (por defecto, una frase fija).
    - ``echo.pc_respuestas["pendientes"] = "No tenés pendientes."``: qué contesta la PC a cada acción.
    - ``echo.pc_conectada = False``: la PC no responde.
    - ``echo.permisos = False``: Alexa no dio permiso de recordatorios ni temporizadores.
    - ``echo.efectos``: lista de lo que pasó ("pc:nota", "recordatorio", "temporizador", "celular", ...).
    - ``echo.memoria``: lo que quedó guardado en la "DynamoDB".  ``echo.sesion``: atributos de sesión.
    """

    def __init__(self, L, monkeypatch):
        self.L = L
        self.ia = lambda system, messages, **kw: "Te escucho."
        self.pc_respuestas = {}
        self.pc_conectada = True
        self.permisos = True
        self.efectos = []
        self.pedidos_pc = []
        self.prompts_ia = []
        self.memoria = {}
        self.sesion = {}
        self.audio = True
        self.radio = ("Radio de prueba", "https://radio.test/stream.mp3")

        def pc(accion, datos, wait=None):
            self.efectos.append("pc:" + accion)
            self.pedidos_pc.append((accion, datos))
            if not self.pc_conectada:
                return None
            texto = self.pc_respuestas.get(accion)
            if texto is None:
                texto = {"aprendidos": "[]", "estado": "Tu PC está conectada."}.get(accion, f"[{accion}]")
            return {"ok": True, "texto": texto}

        def ia(system, messages, **kw):
            self.prompts_ia.append((system, list(messages)))
            return self.ia(system, messages, **kw)

        monkeypatch.setattr(L, "send_to_pc", pc)
        monkeypatch.setattr(L, "send_to_pc_async", lambda accion, datos: self.efectos.append("pc_async:" + accion))
        monkeypatch.setattr(L, "notify_phone", lambda texto: self.efectos.append("celular") or True)
        monkeypatch.setattr(L, "has_permission", lambda h, scope: self.permisos)
        monkeypatch.setattr(L, "create_reminder", lambda h, a: self.efectos.append(
            "recordatorio" + (":repite" if a.get("repetir") else ":fecha" if a.get("fecha_hora") else "")))
        monkeypatch.setattr(L, "create_timer", lambda h, a: self.efectos.append("temporizador"))
        monkeypatch.setattr(L, "gestionar_recordatorios",
                            lambda h, kind, a: (self.efectos.append(kind), "Tienes un recordatorio.")[1])
        monkeypatch.setattr(L, "gestionar_temporizadores",
                            lambda h, kind: (self.efectos.append(kind), "No tienes temporizadores activos.")[1])
        monkeypatch.setattr(L, "buscar_radio", lambda nombre: self.radio)
        monkeypatch.setattr(L, "ask_ai", ia)
        monkeypatch.setattr(L, "aviso_progresivo", lambda h, texto="Un segundo.": self.efectos.append("un_segundo"))

    def _envelope(self, frase, intent):
        from ask_sdk_model import (Application, Context, Device, Intent, IntentRequest, LaunchRequest, Permissions,
                                   RequestEnvelope, Session, Slot, SupportedInterfaces, User)
        from ask_sdk_model.interfaces.audioplayer import AudioPlayerInterface
        from ask_sdk_model.interfaces.system import SystemState

        interfaces = SupportedInterfaces(audio_player=AudioPlayerInterface() if self.audio else None)
        sistema = SystemState(application=Application("skill"),
                              user=User("usuario", permissions=Permissions("token")),
                              device=Device("echo", supported_interfaces=interfaces),
                              api_endpoint="https://api.amazonalexa.com")
        if intent == "LaunchRequest":
            pedido = LaunchRequest(request_id="r" + str(time.time()), locale="es-US")
        else:
            slots = {"query": Slot(name="query", value=frase)} if frase else {}
            pedido = IntentRequest(request_id="r" + str(time.time()), locale="es-US",
                                   intent=Intent(name=intent, slots=slots))
        return RequestEnvelope(version="1.0", session=Session(new=False, session_id="s", attributes=dict(self.sesion)),
                               context=Context(system=sistema), request=pedido)

    def decir(self, frase, intent="ChatIntent", manejador=None):
        from ask_sdk_core.attributes_manager import AttributesManager
        from ask_sdk_core.handler_input import HandlerInput

        echo = self

        class Persistencia:
            def get_attributes(self, request_envelope):
                return json.loads(json.dumps(echo.memoria))

            def save_attributes(self, request_envelope, attributes):
                echo.memoria = json.loads(json.dumps(attributes))

        class Directivas:
            def enqueue(self, pedido):
                echo.efectos.append("un_segundo")

        fabrica = types.SimpleNamespace(get_directive_service=lambda: Directivas(),
                                        get_reminder_management_service=lambda: None,
                                        get_timer_management_service=lambda: None)
        sobre = self._envelope(frase, intent)
        am = AttributesManager(request_envelope=sobre, persistence_adapter=Persistencia())
        hi = HandlerInput(request_envelope=sobre, attributes_manager=am, service_client_factory=fabrica)
        L = self.L
        if manejador is None:
            manejadores = {"ChatIntent": L.ChatHandler, "LaunchRequest": L.LaunchHandler,
                           "BriefingIntent": L.BriefingHandler, "AMAZON.HelpIntent": L.HelpHandler,
                           "AMAZON.StopIntent": L.StopHandler, "AMAZON.CancelIntent": L.StopHandler,
                           "AMAZON.FallbackIntent": L.FallbackHandler, "AMAZON.PauseIntent": L.PausaHandler,
                           "AMAZON.ResumeIntent": L.PausaHandler, "AMAZON.NextIntent": L.SiguienteHandler,
                           "AMAZON.PreviousIntent": L.SiguienteHandler}
            manejador = manejadores[intent]()
        assert manejador.can_handle(hi), f"{type(manejador).__name__} no maneja {intent}"
        resp = manejador.handle(hi)
        self.sesion = dict(am.session_attributes)
        ssml = resp.output_speech.ssml if resp.output_speech else ""
        habla = re.sub(r"<[^>]+>", "", ssml).strip()
        directivas = [str(d.object_type) for d in (resp.directives or [])]
        tarjeta = getattr(resp.card, "permissions", None) if resp.card else None
        return Respuesta(habla, directivas, list(self.efectos), tarjeta, bool(resp.should_end_session))


@pytest.fixture
def echo(skill, monkeypatch):
    return EchoFalso(skill, monkeypatch)


# ---------- el agente de PC ----------

ARCHIVOS_ESTADO = ("estado.json", "memoria.json", "programados.json", "aprendido.json", "frases.json",
                   "casa_dispositivos.json", "casa_apodos.json", "latido.txt")


@pytest.fixture(scope="session")
def agente_modulo(tmp_path_factory):
    """Importa pc/cerebro_pc.py una sola vez desde una copia aislada (lee config_pc.json al importar)."""
    base = tmp_path_factory.mktemp("agente")
    for archivo in (RAIZ / "pc").glob("*.py"):
        shutil.copy(archivo, base / archivo.name)
    for archivo in (RAIZ / "pc").glob("*.html"):
        shutil.copy(archivo, base / archivo.name)
    notas = base / "notas"
    notas.mkdir()
    (base / "config_pc.json").write_text(json.dumps({
        "cerebro_link": "topico-prueba:clave-secreta-de-prueba",
        "carpeta_notas": str(notas),
        "telegram_token": "",
        "gemini_api_key": "",
    }), encoding="utf-8")
    sys.path.insert(0, str(base))
    import cerebro_pc
    cerebro_pc.PRUEBA = {"avisos": [], "registro": [], "publicados": [], "fotos": [], "documentos": []}
    return cerebro_pc


@pytest.fixture
def pc(agente_modulo, monkeypatch):
    """El agente con el estado limpio y todo lo que sale de la PC (Telegram, ntfy, registro) anotado en pc.PRUEBA."""
    C = agente_modulo
    for nombre in ARCHIVOS_ESTADO:
        (C.BASE / nombre).unlink(missing_ok=True)
    for archivo in C.VAULT.glob("**/*"):
        if archivo.is_file():
            archivo.unlink()
    C.PRUEBA = {"avisos": [], "registro": [], "publicados": [], "fotos": [], "documentos": []}
    monkeypatch.setattr(C, "registrar", lambda etiqueta, linea: C.PRUEBA["registro"].append((etiqueta, linea)))
    monkeypatch.setattr(C, "avisar_celular", lambda texto, titulo="Cerebro": C.PRUEBA["avisos"].append((titulo, texto)) or True)
    monkeypatch.setattr(C, "_telegram_foto", lambda ruta, texto="": C.PRUEBA["fotos"].append((str(ruta), texto)) or True)
    monkeypatch.setattr(C, "_telegram_documento", lambda ruta, texto="": C.PRUEBA["documentos"].append((str(ruta), texto)) or True)
    monkeypatch.setattr(C, "publicar", lambda topic, texto, titulo=None: C.PRUEBA["publicados"].append((topic, texto)))
    monkeypatch.setattr(C, "_telegram", lambda metodo, datos=None, timeout=10: (_ for _ in ()).throw(
        RuntimeError("Telegram simulado: " + metodo)))
    with C.TAREAS_LOCK:
        C.TAREAS_ACTIVAS.clear()
    return C
