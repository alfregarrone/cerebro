"""El panel web local (pc/panel.py + pc/panel.html) contra el agente real, sin red, sin Windows y sin IA.

Se levanta un panel por prueba en un puerto libre de 127.0.0.1 (la única salida que permite ``sin_red``) y se le
habla con urllib. Lo que sale de la PC (Telegram, registro) queda anotado en ``pc.PRUEBA``.
"""
import json
import time
import urllib.error
import urllib.request

import pytest

TIPOS_DE_CAMPO = ("texto", "texto_largo", "numero", "opciones", "lista", "booleano", "hora", "dias")


class _SinRedirigir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Cliente:
    """urllib con el token, la cookie y la cabecera anti-CSRF ya puestos (cada cosa se puede sacar)."""

    def __init__(self, puerto, token):
        self.base = "http://127.0.0.1:%d" % puerto
        self.token = token
        self.abridor = urllib.request.build_opener(_SinRedirigir)

    def pedir(self, ruta, metodo="GET", cuerpo=None, auth="bearer", csrf=True, cabeceras=None, crudo=None):
        datos = crudo if crudo is not None else (json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None)
        req = urllib.request.Request(self.base + ruta, data=datos, method=metodo)
        if auth == "bearer":
            req.add_header("Authorization", "Bearer " + self.token)
        elif auth == "cookie":
            req.add_header("Cookie", "cerebro_panel=" + self.token)
        elif auth == "malo":
            req.add_header("Authorization", "Bearer no-es-este")
        if csrf and metodo in ("POST", "DELETE"):
            req.add_header("X-Cerebro-Panel", "1")
        if datos is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (cabeceras or {}).items():
            req.add_header(k, v)
        try:
            with self.abridor.open(req, timeout=10) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def get(self, ruta, **kw):
        estado, cuerpo, _ = self.pedir(ruta, **kw)
        return estado, _json(cuerpo)

    def post(self, ruta, cuerpo=None, **kw):
        estado, resp, _ = self.pedir(ruta, "POST", cuerpo if cuerpo is not None else {}, **kw)
        return estado, _json(resp)

    def delete(self, ruta, **kw):
        estado, resp, _ = self.pedir(ruta, "DELETE", {}, **kw)
        return estado, _json(resp)


def _json(cuerpo):
    try:
        return json.loads(cuerpo.decode("utf-8"))
    except ValueError:
        return cuerpo.decode("utf-8", "replace")


@pytest.fixture
def panel(pc):
    import panel as modulo
    servidor, puerto = modulo.iniciar(pc, puerto=0, en_red=False)
    assert servidor is not None and puerto > 0
    cliente = Cliente(puerto, modulo.token())
    cliente.modulo = modulo
    yield cliente
    modulo.detener()


# ---------- acceso ----------

def test_sin_token_no_entra(panel):
    estado, cuerpo = panel.get("/api/estado", auth=None)
    assert estado == 401 and cuerpo["ok"] is False
    estado, cuerpo, cab = panel.pedir("/", auth=None)
    assert estado == 401 and "text/html" in cab["Content-Type"]
    assert "token" in cuerpo.decode("utf-8") and "<form" in cuerpo.decode("utf-8")


def test_el_token_en_la_url_pone_la_cookie_y_redirige(panel):
    estado, cuerpo, cab = panel.pedir("/?token=" + panel.token, auth=None)
    assert estado == 303 and cab["Location"] == "/"
    galleta = cab["Set-Cookie"]
    assert galleta.startswith("cerebro_panel=") and "HttpOnly" in galleta and "SameSite=Strict" in galleta
    assert "Path=/" in galleta
    valor = galleta.split(";")[0].split("=", 1)[1]
    estado, cuerpo, cab = panel.pedir("/", auth=None, cabeceras={"Cookie": "cerebro_panel=" + valor})
    assert estado == 200 and "<title>" in cuerpo.decode("utf-8") and "no-store" in cab["Cache-Control"]


def test_bearer_y_cookie_valen_y_el_token_malo_no(panel, pc):
    estado, cuerpo = panel.get("/api/estado")
    assert estado == 200 and cuerpo["ok"] and cuerpo["version"] == pc.VERSION
    estado, cuerpo = panel.get("/api/estado", auth="cookie")
    assert estado == 200 and cuerpo["ok"]
    assert panel.get("/api/estado", auth="malo")[0] == 401
    assert panel.pedir("/", auth=None, cabeceras={"Cookie": "cerebro_panel=otro"})[0] == 401
    assert panel.pedir("/?token=otro", auth=None)[0] == 401


def test_el_token_queda_guardado_en_estado(panel, pc):
    assert pc.cargar_estado()["panel_token"] == panel.token
    assert len(panel.token) >= 24
    assert pc.cargar_estado()["panel_puerto"] == int(panel.base.rsplit(":", 1)[1])


def test_post_sin_cabecera_anti_csrf(panel):
    estado, cuerpo = panel.post("/api/orden", {"texto": "hola"}, csrf=False)
    assert estado == 403 and "X-Cerebro-Panel" in cuerpo["error"]
    assert panel.delete("/api/programados/abc123", csrf=False)[0] == 403


def test_solo_existen_la_pagina_y_la_api(panel):
    for ruta in ("/otro.html", "/../config_pc.json", "/panel.html", "/api/no_existe", "/estado.json", "/api/"):
        estado, _ = panel.get(ruta)
        assert estado == 404, ruta
    assert panel.get("/../config_pc.json", auth=None)[0] in (401, 404)


def test_cuerpo_grande_y_json_invalido(panel):
    estado, cuerpo, _ = panel.pedir("/api/orden", "POST", crudo=b"x" * (64 * 1024 + 1))
    assert estado == 413
    estado, cuerpo, _ = panel.pedir("/api/orden", "POST", crudo=b"{esto no es json")
    assert estado == 400 and "JSON" in _json(cuerpo)["error"]
    estado, cuerpo, _ = panel.pedir("/api/orden", "POST", crudo=b"[1, 2]")
    assert estado == 400


# ---------- catálogo ----------

def test_el_catalogo_cubre_todas_las_acciones(panel, pc):
    from panel import CATALOGO, GRUPOS
    assert set(CATALOGO) == set(pc.ACCIONES), (set(pc.ACCIONES) ^ set(CATALOGO))
    for nombre, entrada in CATALOGO.items():
        assert entrada["grupo"] in GRUPOS, nombre
        assert entrada["etiqueta"] and entrada["descripcion"] and entrada["ejemplos"], nombre
        for campo in entrada["campos"]:
            assert campo["tipo"] in TIPOS_DE_CAMPO, nombre
            assert campo["nombre"] and campo["etiqueta"], nombre
            if campo["tipo"] == "opciones":
                assert campo.get("opciones"), nombre
    for nombre in ("sistema", "whatsapp_confirmar", "pantalla_confirmar", "confirmar_tarea"):
        assert CATALOGO[nombre]["peligrosa"], nombre
    for nombre in ("clima", "dolar", "noticias", "argentina", "futbol", "cotizacion", "convertir"):
        assert CATALOGO[nombre]["grupo"] == "Datos en vivo", nombre
    estado, cuerpo = panel.get("/api/acciones")
    assert estado == 200 and len(cuerpo["acciones"]) == len(pc.ACCIONES)
    assert {a["nombre"] for a in cuerpo["acciones"]} == set(pc.ACCIONES)


# ---------- ejecutar ----------

def test_ejecutar_compras_nota_y_pendientes_de_punta_a_punta(panel, pc):
    estado, r = panel.post("/api/ejecutar", {"accion": "compras", "datos": {"agregar": ["leche", "pan"]}})
    assert estado == 200 and r["ok"] and "leche" in r["texto"]
    assert "- leche\n- pan\n" in (pc.VAULT / "Compras.md").read_text(encoding="utf-8")
    estado, r = panel.post("/api/compras", {"quitar": ["pan"]})
    assert r["ok"] and r["compras"] == ["leche"]

    estado, r = panel.post("/api/ejecutar", {"accion": "nota",
                                             "datos": {"texto": "probar el panel", "categoria": "idea"}})
    assert r["ok"] and r["texto"] == "Nota guardada."
    assert "**idea**: probar el panel" in (pc.VAULT / "Inbox.md").read_text(encoding="utf-8")

    estado, r = panel.post("/api/pendientes", {"agregar": "comprar pilas"})
    assert r["ok"] and r["pendientes"][0]["texto"] == "comprar pilas" and not r["pendientes"][0]["hecho"]
    estado, r = panel.post("/api/pendientes", {"completar": "comprar pilas"})
    assert r["ok"] and r["pendientes"][0]["hecho"]
    assert "- [x] comprar pilas" in (pc.VAULT / "Pendientes.md").read_text(encoding="utf-8")

    estado, r = panel.get("/api/notas")
    assert r["inbox"][0].endswith("probar el panel") and r["compras"] == ["leche"]
    assert panel.post("/api/pendientes", {})[0] == 400


def test_la_accion_tiene_que_existir(panel):
    estado, r = panel.post("/api/ejecutar", {"accion": "formatear", "datos": {}})
    assert estado == 400 and "formatear" in r["error"]
    assert panel.post("/api/ejecutar", {})[0] == 400


def test_lo_peligroso_pide_confirmacion(panel, pc, monkeypatch):
    llamadas = []
    monkeypatch.setitem(pc.ACCIONES, "sistema", lambda d: llamadas.append(d) or (True, "stub " + d["orden"]))
    estado, r = panel.post("/api/ejecutar", {"accion": "sistema", "datos": {"orden": "apagar"}})
    assert estado == 400 and r["confirmar"] is True and not llamadas
    estado, r = panel.post("/api/ejecutar", {"accion": "sistema", "datos": {"orden": "apagar"}, "confirmar": True})
    assert estado == 200 and r["ok"] and r["texto"] == "stub apagar" and llamadas == [{"orden": "apagar"}]
    # bloquear no es peligroso: va directo
    estado, r = panel.post("/api/ejecutar", {"accion": "sistema", "datos": {"orden": "bloquear"}})
    assert estado == 200 and r["texto"] == "stub bloquear"
    estado, r = panel.post("/api/ejecutar", {"accion": "confirmar_tarea", "datos": {}})
    assert estado == 400 and r["confirmar"] is True


def test_una_accion_que_falla_no_rompe_el_panel(panel, pc, monkeypatch):
    def rota(d):
        raise RuntimeError("se rompió")
    monkeypatch.setitem(pc.ACCIONES, "estado", rota)
    estado, r = panel.post("/api/ejecutar", {"accion": "estado", "datos": {}})
    assert estado == 500 and "se rompió" in r["error"]
    assert panel.get("/api/estado")[0] == 200


def test_orden_libre_pasa_por_orden_telegram(panel, pc, monkeypatch):
    recibido = []
    monkeypatch.setattr(pc, "_orden_telegram",
                        lambda texto, profundidad=0: recibido.append(texto) or "Respuesta de prueba.")
    estado, r = panel.post("/api/orden", {"texto": "prendé la luz"})
    assert estado == 200 and r["ok"] and r["texto"] == "Respuesta de prueba." and recibido == ["prendé la luz"]
    historial = pc._memoria()["historial"]
    assert historial[-2]["texto"] == "prendé la luz" and historial[-1]["texto"] == "Respuesta de prueba."
    assert ("panel", "prendé la luz") in pc.PRUEBA["registro"]
    assert panel.post("/api/orden", {"texto": "  "})[0] == 400


# ---------- automatizaciones ----------

def test_programados_crear_listar_ejecutar_y_borrar(panel, pc):
    estado, r = panel.post("/api/programados",
                           {"texto": "Tomar agua", "tipo": "aviso", "hora": "10:00", "dias": ["lunes"]})
    assert estado == 200 and r["ok"] and len(r["programados"]) == 1
    p = r["programados"][0]
    assert p["texto"] == "Tomar agua" and p["cuando"] == "los lunes a las 10:00" and p["proximo_texto"]
    estado, r = panel.get("/api/programados")
    assert r["programados"][0]["id"] == p["id"]

    estado, r = panel.post("/api/programados/" + p["id"] + "/ejecutar")
    assert r["ok"] and pc.PRUEBA["avisos"][-1] == ("Cerebro", "⏰ Tomar agua")

    assert panel.delete("/api/programados/zzz")[0] == 404
    estado, r = panel.delete("/api/programados/" + p["id"])
    assert estado == 200 and r["programados"] == [] and pc._programados() == []
    assert panel.post("/api/programados", {})[0] == 400


def test_programar_una_accion_con_datos_exactos(panel, pc):
    estado, r = panel.post("/api/programados", {"accion": "compras", "datos": {"agregar": ["pilas"]}, "en_minutos": 1})
    assert estado == 200 and r["ok"], r
    p = r["programados"][0]
    assert p["accion"] == "compras" and p["datos"] == {"agregar": ["pilas"]} and p["tipo"] == "orden"
    assert p["texto"] == "compras: pilas" and p["una_vez"]
    estado, r = panel.post("/api/programados", {"accion": "inexistente", "datos": {}, "en_minutos": 1})
    assert r["ok"] is False and "inexistente" in r["texto"]

    # todavía no venció: no pasa nada
    assert pc.revisar_programados(p["proximo"] - 30) == []
    assert not (pc.VAULT / "Compras.md").exists()
    # venció: se ejecuta la acción con sus datos, queda en el registro y avisa al celular; como era una vez, se borra
    disparados = pc.revisar_programados(p["proximo"] + 1)
    assert [d["id"] for d in disparados] == [p["id"]]
    assert "- pilas" in (pc.VAULT / "Compras.md").read_text(encoding="utf-8")
    assert ("rutina", "compras: pilas -> Agregué pilas a la lista de compras.") in pc.PRUEBA["registro"]
    assert pc.PRUEBA["avisos"][-1][1].startswith("Rutina: compras: pilas")
    assert pc._programados() == []


def test_una_rutina_con_accion_que_se_repite_recalcula_el_proximo(panel, pc):
    estado, r = panel.post("/api/programados", {"accion": "nota", "datos": {"texto": "rutina diaria"}, "hora": "07:00",
                                                "texto": "anotar la rutina"})
    p = r["programados"][0]
    assert p["texto"] == "anotar la rutina" and p["cuando"] == "todos los días a las 7:00"
    vencido = p["proximo"] + 5
    assert pc.revisar_programados(vencido)
    assert "rutina diaria" in (pc.VAULT / "Inbox.md").read_text(encoding="utf-8")
    nuevo = pc._programados()[0]
    assert nuevo["proximo"] > vencido and nuevo["accion"] == "nota"
    # un pedido perdido hace más de una hora (la PC estaba apagada) no se ejecuta, solo se reprograma
    pc.PRUEBA["avisos"].clear()
    assert pc.revisar_programados(nuevo["proximo"] + 2 * 3600) == []
    assert pc._programados()[0]["proximo"] > nuevo["proximo"] + 2 * 3600 and not pc.PRUEBA["avisos"]


def test_una_orden_de_texto_programada_sigue_pasando_por_orden_telegram(pc, monkeypatch):
    monkeypatch.setattr(pc, "_orden_telegram", lambda texto, profundidad=0: "hecho: " + texto)
    ok, _ = pc.accion_programar({"texto": "prendé la luz", "tipo": "orden", "en_minutos": 1})
    assert ok
    p = pc._programados()[0]
    assert "accion" not in p
    pc.revisar_programados(p["proximo"] + 1)
    assert ("rutina", "prendé la luz -> hecho: prendé la luz") in pc.PRUEBA["registro"]


def test_alertas(panel, pc):
    estado, r = panel.get("/api/alertas")
    assert estado == 200 and r["alertas"] == {k: True for k in ("dolar", "lluvia", "pc", "mails", "agenda")}
    assert r["faltan"] == {"mails": True, "agenda": True} and r["nombres"]["dolar"] == "del dólar"
    estado, r = panel.post("/api/alertas", {"tipo": "dolar", "activar": False})
    assert r["ok"] and r["alertas"]["dolar"] is False and r["alertas"]["lluvia"] is True
    assert pc._alertas()["dolar"] is False
    estado, r = panel.post("/api/alertas", {"tipo": "todas", "activar": True})
    assert all(r["alertas"].values())
    assert panel.post("/api/alertas", {"tipo": "dolar"})[0] == 400


def test_resumen_de_la_manana(panel, pc, monkeypatch):
    monkeypatch.setattr(pc, "armar_resumen", lambda *a, **k: "Buen día. Resumen de prueba.")
    estado, r = panel.get("/api/resumen")
    assert r["resumen"]["hora"] == "08:00" and r["resumen"]["activo"] is True
    estado, r = panel.post("/api/resumen", {"hora": "7:30", "dias": "semana", "equipo": "River"})
    assert r["ok"] and r["resumen"]["hora"] == "07:30" and r["resumen"]["dias"] == "semana"
    assert r["resumen"]["equipo"] == "River"
    assert "7:30" in r["texto"] and "River" in r["texto"]
    estado, r = panel.post("/api/resumen", {"activar": False})
    assert r["ok"] and r["resumen"]["activo"] is False
    assert panel.post("/api/resumen", {})[0] == 400
    estado, r = panel.post("/api/resumen/vista")
    assert r["ok"] and r["texto"] == "Buen día. Resumen de prueba."
    estado, r = panel.post("/api/resumen/mandar")
    assert r["ok"] and pc.PRUEBA["avisos"][-1] == ("Cerebro: resumen del día", "Buen día. Resumen de prueba.")


# ---------- tareas ----------

def test_tareas_archivo_solo_dentro_de_la_carpeta(panel, pc):
    carpeta = pc.VAULT / "Tareas"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "2026-01-01_informe.md").write_text("# Consulta: algo\n\ncontenido del informe\n", encoding="utf-8")
    (pc.VAULT / "afuera.md").write_text("secreto", encoding="utf-8")
    estado, r = panel.get("/api/tareas/archivo?nombre=2026-01-01_informe.md")
    assert estado == 200 and r["contenido"].startswith("# Consulta: algo") and r["nombre"] == "2026-01-01_informe.md"
    for malo in ("../afuera.md", "..%2Fafuera.md", "../../config_pc.json", "/etc/passwd", "..\\afuera.md", ".md",
                 "afuera.md", "", "2026-01-01_informe.txt", "../Tareas/2026-01-01_informe.md"):
        estado, r = panel.get("/api/tareas/archivo?nombre=" + malo)
        assert estado == 404, malo
    estado, r = panel.get("/api/tareas")
    assert r["informes"][0]["nombre"] == "2026-01-01_informe.md" and r["informes"][0]["titulo"] == "Consulta: algo"
    assert r["activas"] == [] and r["plan"] is None


def test_los_informes_se_releen_si_cambian_y_desaparecen_si_se_borran(panel, pc):
    carpeta = pc.VAULT / "Tareas"
    carpeta.mkdir(parents=True, exist_ok=True)
    informe = carpeta / "2026-02-02_informe.md"
    informe.write_text("", encoding="utf-8")                  # Claude crea el archivo y después lo escribe
    assert panel.get("/api/tareas")[1]["informes"][0]["titulo"] == "2026-02-02_informe"
    informe.write_text("# Consulta: el título de verdad\n\nlisto\n", encoding="utf-8")
    assert panel.get("/api/tareas")[1]["informes"][0]["titulo"] == "Consulta: el título de verdad"
    informe.unlink()
    assert all(i["nombre"] != informe.name for i in panel.get("/api/tareas")[1]["informes"])


def test_plan_pendiente_aprobar_y_descartar(panel, pc, monkeypatch):
    monkeypatch.setattr(pc, "_buscar_claude", lambda: "")
    estado, r = panel.post("/api/tareas", {"instruccion": "ordená descargas", "modo": "cambios"})
    assert r["ok"] is False and "Claude Code" in r["texto"]
    plan = {"instruccion": "ordenar", "plan": "1. mover", "ts": int(time.time())}
    pc.estado_cambiar(lambda e: e.__setitem__("plan_pendiente", plan))
    estado, r = panel.get("/api/tareas")
    assert r["plan"]["instruccion"] == "ordenar" and r["plan"]["plan"] == "1. mover"
    assert panel.post("/api/tareas/confirmar", {})[0] == 400
    estado, r = panel.post("/api/tareas/descartar")
    assert r["ok"] and r["texto"] == "Plan descartado." and "plan_pendiente" not in pc.cargar_estado()
    estado, r = panel.post("/api/tareas/confirmar", {"confirmar": True})
    assert r["ok"] is False and "plan" in r["texto"]
    estado, r = panel.post("/api/tareas/cancelar")
    assert r["ok"] and "ninguna tarea" in r["texto"]


# ---------- memoria, casa, registro, estado ----------

def test_memoria_recordar_y_olvidar(panel, pc):
    estado, r = panel.post("/api/memoria/recordar", {"dato": "mi hermana se llama Laura"})
    assert r["ok"] and r["datos"] == ["mi hermana se llama Laura"]
    pc._guardar_leccion("modo cine", ["poné la luz al 10"])
    estado, r = panel.get("/api/memoria")
    assert r["datos"] == ["mi hermana se llama Laura"] and len(r["lecciones"]) == 1 and "modo cine" in r["lecciones"][0]
    estado, r = panel.post("/api/memoria/olvidar_frase", {"frase": "modo cine"})
    assert r["ok"] and r["lecciones"] == []
    estado, r = panel.post("/api/memoria/olvidar", {"dato": "laura"})
    assert r["ok"] and r["datos"] == []
    assert panel.post("/api/memoria/olvidar", {})[0] == 400


def test_casa_sin_librerias_no_rompe(panel):
    estado, r = panel.get("/api/casa")
    assert estado == 200 and r["ok"] and r["dispositivos"] == []
    assert r["disponible"] is False and "instalar-extras" in r["aviso"]


def test_registro_y_estado(panel, pc):
    estado, r = panel.get("/api/registro?n=5")
    assert estado == 200 and isinstance(r["registro"], list) and isinstance(r["log"], list)
    assert panel.get("/api/registro?n=abc")[0] == 200
    estado, r = panel.get("/api/estado")
    assert r["pendientes"] == 0 and r["compras"] == 0 and r["programados"] == 0 and r["tareas"] == []
    assert r["telegram"] == {"token": False, "chat": False}
    assert r["panel"]["puerto"] == int(panel.base.rsplit(":", 1)[1])
    assert r["alertas"]["dolar"] is True and r["resumen"]["hora"] == "08:00"
    assert r["panel"]["url"] == panel.base + "/" and r["panel"]["en_red"] is False


def test_desde_telegram_panel_devuelve_el_link(panel, pc):
    respuesta = pc._atajos_telegram(pc.norm("abrí el panel"))
    assert panel.base + "/?token=" + panel.token in respuesta and "Solo abre en esa PC" in respuesta
    assert pc._orden_telegram("panel").startswith("Panel de Cerebro: http://127.0.0.1:")
    assert pc._orden_telegram("url del panel").startswith("Panel de Cerebro: http://127.0.0.1:")


def test_sin_panel_corriendo_telegram_lo_dice(pc):
    import panel as modulo
    modulo.detener()
    modulo.A = pc
    assert "no está corriendo" in modulo.url_para_telegram() and modulo.url() == ""
    assert "no está corriendo" in pc.panel_url()


def test_la_pagina_se_lee_del_disco_en_cada_pedido(panel):
    pagina = panel.modulo.PAGINA
    original = pagina.read_text(encoding="utf-8")
    try:
        pagina.write_text(original.replace("<title>", "<title>RETOCADO ", 1), encoding="utf-8")
        assert "RETOCADO" in panel.pedir("/", auth="cookie")[1].decode("utf-8")
    finally:
        pagina.write_text(original, encoding="utf-8")
    assert "RETOCADO" not in panel.pedir("/", auth="cookie")[1].decode("utf-8")


def _script_de_la_pagina():
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "pc" / "panel.html").read_text(encoding="utf-8")
    return html[html.index("<script>") + len("<script>"):html.rindex("</script>")]


def test_el_javascript_de_la_pagina_no_tiene_errores_de_sintaxis(tmp_path):
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("sin Node no se puede revisar la sintaxis")
    archivo = tmp_path / "panel.js"
    archivo.write_text(_script_de_la_pagina(), encoding="utf-8")
    r = subprocess.run([node, "--check", str(archivo)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_todo_lo_que_pide_la_pagina_existe_en_la_api(panel):
    import re
    rutas = [patron for _, patron, _ in panel.modulo.RUTAS]
    pedidos = set(re.findall(r'api\("([a-z_/]+)', _script_de_la_pagina()))
    assert {"estado", "acciones", "ejecutar", "orden", "notas", "tareas", "casa", "memoria"} <= pedidos
    for pedido in sorted(pedidos):          # "programados/" + id (+ "/ejecutar") se completa con un id de ejemplo
        candidatos = [pedido + "abc123", pedido + "abc123/ejecutar"] if pedido.endswith("/") else [pedido]
        assert any(p.fullmatch(c) for p in rutas for c in candidatos), pedido


def test_panel_desactivado_en_config(pc, monkeypatch):
    import panel as modulo
    monkeypatch.setitem(pc.CONFIG, "panel_activo", False)
    assert modulo.iniciar(pc) is None
