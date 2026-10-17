"""El orbe en pantalla: mensajes firmados, máquina de estados y texto, sin ventana."""
import hashlib
import hmac
import json
import time


def _firmado(secret, accion, datos, ts=None, id_="abc123"):
    ts = int(ts or time.time())
    cuerpo = json.dumps(datos, sort_keys=True, ensure_ascii=False)
    firma = hmac.new(secret.encode(), f"{id_}|{ts}|{accion}|{cuerpo}".encode(), hashlib.sha256).hexdigest()
    return {"event": "message", "time": ts, "message": json.dumps(
        {"id": id_, "ts": ts, "accion": accion, "datos": datos, "firma": firma}, ensure_ascii=False)}


def test_solo_acepta_mensajes_firmados_y_recientes(pc):
    import orbe
    ev = _firmado("clave", "hud", {"estado": "pensando", "texto": "hola"})
    orden = orbe.interpretar(ev, "clave")
    assert orden and orden["accion"] == "hud" and orden["datos"]["texto"] == "hola"
    assert orbe.interpretar(ev, "otra-clave") is None
    viejo = _firmado("clave", "hud", {"estado": "pensando"}, ts=time.time() - 3600)
    assert orbe.interpretar(viejo, "clave") is None
    assert orbe.interpretar({"event": "open"}, "clave") is None
    assert orbe.interpretar({"event": "message", "message": "no es json"}, "clave") is None


def test_el_enlace_sale_del_config_del_agente(pc):
    import orbe
    assert orbe.enlace() == ("topico-prueba", "clave-secreta-de-prueba")


def test_la_skill_manda_los_avisos_del_orbe(echo):
    echo.ia = lambda s, m, **kw: "Hola, ¿qué tal?"
    r = echo.decir("hola")
    assert r.efectos.count("pc_async:hud") == 2          # "pensando" con lo que dijiste y "hablando" con la respuesta
    r = echo.decir("", intent="LaunchRequest")
    assert "pc_async:hud" in r.efectos


def test_el_agente_no_contesta_los_avisos_del_orbe(pc):
    ev = _firmado("clave-secreta-de-prueba", "hud", {"estado": "pensando", "texto": "hola"})
    pc.procesar(ev, {})
    assert pc.PRUEBA["publicados"] == []
    ev = _firmado("clave-secreta-de-prueba", "estado", {}, id_="otro")
    pc.procesar(ev, {})
    assert len(pc.PRUEBA["publicados"]) == 1


def test_estado_escucha_piensa_habla_y_se_esconde(pc):
    import orbe
    e = orbe.Estado()
    assert e.modo == "oculto"
    assert e.aplicar({"accion": "hud", "datos": {"estado": "escuchando"}}, ahora=100)
    assert e.modo == "escuchando" and e.texto == "Te escucho."
    assert e.aplicar({"accion": "hud", "datos": {"estado": "pensando", "texto": "qué hora es"}}, ahora=102)
    assert e.modo == "pensando" and e.titulo == "Vos" and e.texto == "qué hora es"
    assert e.aplicar({"accion": "hud", "datos": {"estado": "hablando", "texto": "Son las diez."}}, ahora=104)
    assert e.modo == "hablando" and e.titulo == "Cerebro" and not e.vencido(ahora=106)
    assert e.vencido(ahora=104 + 30)
    assert e.aplicar({"accion": "hud", "datos": {"estado": "oculto"}}, ahora=110) is False
    assert e.modo == "oculto"


def test_una_orden_de_la_pc_tambien_se_muestra(pc):
    import orbe
    e = orbe.Estado()
    assert e.aplicar({"accion": "nota", "datos": {"texto": "comprar pilas", "categoria": "idea"}}, ahora=10)
    assert e.modo == "haciendo" and e.titulo == "Anotando" and e.texto == "comprar pilas"
    assert e.aplicar({"accion": "aprendidos", "datos": {}}, ahora=11) is False    # ruido interno: no se muestra
    assert e.aplicar({"accion": "casa", "datos": {"dispositivo": "luz living", "accion": "prender"}}, ahora=12)
    assert e.texto == "luz living"


def test_envolver_corta_prolijo(pc):
    import orbe
    texto = "una " * 60
    salida = orbe.envolver(texto, ancho=20, lineas=3)
    assert salida.count("\n") == 2 and salida.endswith("…") and all(len(l) <= 21 for l in salida.splitlines())
    assert orbe.envolver("corto") == "corto"
