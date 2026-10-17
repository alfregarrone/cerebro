"""El agente de PC: estado, Telegram, confirmaciones, rutinas, casa, WhatsApp e info, todo simulado."""
import json
import time

import pytest


# ---------- estado y memoria ----------

def test_el_estado_se_escribe_atomico(pc):
    pc.guardar_estado({"a": 1})
    assert json.loads(pc.STATE_FILE.read_text(encoding="utf-8")) == {"a": 1}
    assert not pc.STATE_FILE.with_suffix(".json.tmp").exists()
    assert pc.estado_cambiar(lambda e: e.__setitem__("b", 2)) is None
    assert pc.cargar_estado() == {"a": 1, "b": 2}


def test_la_memoria_recuerda_y_olvida(pc):
    assert pc.recordar_dato("La hermana del usuario se llama Laura")
    assert pc.accion_que_sabes({}) == (True, "Esto es lo que sé: tu hermana se llama Laura.")
    assert pc.olvidar_dato("laura") == 1
    assert pc.accion_que_sabes({})[1] == "Todavía no guardé nada sobre vos."


# ---------- Telegram ----------

def test_el_chat_se_ata_solo_con_start(pc, monkeypatch):
    actualizaciones = {"result": [
        {"update_id": 1, "message": {"chat": {"id": 111}, "text": "hola, soy un desconocido"}},
        {"update_id": 2, "message": {"chat": {"id": 222}, "text": "/start"}},
    ]}
    monkeypatch.setattr(pc, "_telegram", lambda metodo, datos=None, timeout=10: actualizaciones)
    monkeypatch.setitem(pc.CONFIG, "telegram_token", "123:AAtoken")
    assert pc._telegram_chat_id() == 222
    assert pc.cargar_estado()["telegram_chat_id"] == 222


def test_sin_start_nadie_se_ata(pc, monkeypatch):
    actualizaciones = {"result": [{"update_id": 1, "message": {"chat": {"id": 111}, "text": "apagá la pc"}}]}
    monkeypatch.setattr(pc, "_telegram", lambda metodo, datos=None, timeout=10: actualizaciones)
    monkeypatch.setitem(pc.CONFIG, "telegram_token", "123:AAtoken")
    assert pc._telegram_chat_id() is None


def test_el_si_va_para_la_ultima_pregunta(pc, monkeypatch):
    ahora = int(time.time())
    pc.guardar_estado({"sistema_pendiente": {"orden": "apagar", "ts": ahora - 100},
                       "whatsapp_pendiente": {"tipo": "mensaje", "contacto": "Laura", "mensaje": "hola", "ts": ahora - 5}})
    hechos = []
    monkeypatch.setattr(pc, "accion_sistema", lambda d: hechos.append(("sistema", d)) or (True, "Apagando."))
    monkeypatch.setattr(pc, "_hilo_whatsapp", lambda pend: hechos.append(("whatsapp", pend)))
    r = pc._confirmaciones_telegram("si")
    time.sleep(0.05)
    assert r == "Enviando." and hechos and hechos[0][0] == "whatsapp"
    assert "whatsapp_pendiente" not in pc.cargar_estado() and "sistema_pendiente" in pc.cargar_estado()


def test_lo_vencido_no_se_confirma(pc):
    pc.guardar_estado({"whatsapp_pendiente": {"tipo": "mensaje", "contacto": "Laura", "mensaje": "hola",
                                              "ts": int(time.time()) - 3600}})
    assert pc._confirmaciones_telegram("si") is None
    assert "whatsapp_pendiente" not in pc.cargar_estado()


def test_no_descarta_todo(pc):
    pc.guardar_estado({"sistema_pendiente": {"orden": "apagar", "ts": int(time.time())}})
    assert pc._confirmaciones_telegram("no") == "Listo, lo descarté."
    assert pc.cargar_estado() == {}


def test_whatsapp_cancelar(pc):
    pc._preparar_whatsapp({"contacto": "Laura", "mensaje": "hola"}, "mensaje")
    assert pc.accion_whatsapp_cancelar({}) == (True, "Descarté el mensaje.")
    assert pc.accion_whatsapp_cancelar({}) == (True, "No había ningún mensaje esperando.")
    assert pc.accion_whatsapp_confirmar({})[0] is False


def test_las_alertas_se_apagan_de_a_una(pc, monkeypatch):
    monkeypatch.setattr(pc, "_mod", lambda nombre: type("M", (), {"configurado": staticmethod(lambda c: False),
                                                                     "links": staticmethod(lambda c: [])}))
    assert "mails" in pc._orden_telegram("desactivá las alertas de mails")
    alertas = pc._alertas()
    assert alertas["mails"] is False and alertas["dolar"] is True and alertas["pc"] is True
    pc._orden_telegram("desactivá las alertas de la pc")
    assert pc._alertas()["pc"] is False and pc._alertas()["lluvia"] is True


# ---------- rutinas ----------

def test_programa_desde_texto_entiende_la_noche(pc):
    d = pc._programa_desde_texto("todos los días a las 8 de la noche prendé la luz")
    assert d["hora"] == "20:00" and d["texto"] == "prendé la luz" and d["tipo"] == "orden"
    d = pc._programa_desde_texto("avisame mañana a las 3 de la tarde que llame al contador")
    assert d["hora"] == "15:00" and d["texto"] == "llame al contador" and d["frecuencia"] == "una_vez"


def test_dias_con_plurales(pc):
    assert pc._dias(["los sábados", "domingos"]) == [5, 6]
    assert pc._dias("lunes, miércoles") == [0, 2]


def test_una_rutina_atrasada_no_se_ejecuta_tarde(pc, monkeypatch):
    ejecutadas = []
    monkeypatch.setitem(pc.ACCIONES, "sistema", lambda d: ejecutadas.append(d) or (True, "Apagando."))
    ok, _ = pc.accion_programar({"accion": "sistema", "datos": {"orden": "apagar"}, "en_minutos": 1})
    assert ok
    disparados = pc.revisar_programados(time.time() + 60 + 2 * 3600)      # la PC estuvo apagada dos horas
    assert disparados == [] and ejecutadas == []
    assert any("estaba apagada" in texto for _, texto in pc.PRUEBA["avisos"])
    assert pc._programados() == []


def test_una_rutina_programada_se_ejecuta_a_tiempo(pc, monkeypatch):
    ejecutadas = []
    monkeypatch.setitem(pc.ACCIONES, "compras", lambda d: ejecutadas.append(d) or (True, "Agregué pan."))
    pc.accion_programar({"accion": "compras", "datos": {"agregar": ["pan"]}, "hora": "07:00"})
    p = pc._programados()[0]
    disparados = pc.revisar_programados(p["proximo"] + 30)
    assert len(disparados) == 1 and ejecutadas == [{"agregar": ["pan"]}]
    assert pc._programados()[0]["proximo"] > p["proximo"]            # quedó recalculada para mañana


def test_el_resumen_solo_se_marca_si_salio(pc, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(pc, "armar_resumen", lambda ahora_dt=None, voz=False: "Resumen.")
    cuando = datetime(2026, 10, 17, 8, 5)
    monkeypatch.setattr(pc, "avisar_celular", lambda texto, titulo="Cerebro": False)
    assert pc._mandar_resumen_si_toca(cuando) is False
    assert "ultimo" not in (pc.cargar_estado().get("resumen") or {})
    monkeypatch.setattr(pc, "avisar_celular", lambda texto, titulo="Cerebro": True)
    assert pc._mandar_resumen_si_toca(cuando) is True
    assert pc.cargar_estado()["resumen"]["ultimo"] == "2026-10-17"
    assert pc._mandar_resumen_si_toca(cuando) is False                 # no se manda dos veces


# ---------- la IA por Telegram ----------

def test_interpretar_con_ia_tolera_acciones_como_objeto(pc, monkeypatch):
    monkeypatch.setattr(pc, "preguntar_ia", lambda *a, **k: json.dumps(
        {"respuesta": "Anoto.", "acciones": {"accion": "nota", "datos": {"texto": "comprar café", "categoria": "idea"}}}))
    r = pc.interpretar_con_ia("anotá comprar café")
    assert r and "comprar café" in (pc.VAULT / "Inbox.md").read_text(encoding="utf-8")


# ---------- módulos ----------

def test_casa_se_importa_sin_librerias_y_avisa(pc):
    import asyncio
    casa = pc._casa_modulo()
    if casa.DISPONIBLE:
        pytest.skip("hay librerías de domótica instaladas")
    assert "Faltan" in asyncio.run(casa._accion("luz", "prender"))


def test_casa_no_apaga_todo_cuando_nombran_una_luz(pc, monkeypatch):
    casa = pc._casa_modulo()
    monkeypatch.setattr(casa, "_apodos", lambda: {})
    datos = {"WiZ 1": {"host": "a", "marca": "wiz"}, "Enchufe estufa": {"host": "b", "marca": "tplink"}}
    assert casa._varias("las luces", datos) is True
    assert casa._varias("luz", datos) is True
    assert casa._varias("luz del dormitorio", datos) is False
    assert casa._varias("estufa", datos) is False
    assert casa._entero("40%") == 40 and casa._entero("40.0") == 40


def test_whatsapp_elige_palabras_enteras(pc, monkeypatch):
    import sys
    import types
    for falso in ("pyautogui", "pyperclip", "pygetwindow"):      # son de Windows: acá solo hace falta importar
        monkeypatch.setitem(sys.modules, falso, types.ModuleType(falso))
    import whatsapp_app as wa
    resultados = [{"nombre": "Juana López"}, {"nombre": "Juan Pérez"}]
    assert wa._elegir("Juan", resultados)[0] == {"nombre": "Juan Pérez"}
    elegido, motivo = wa._elegir("Juan", [{"nombre": "Juana López"}])
    assert elegido is None and "Juana López" in motivo
    assert wa._elegir("Juan Pérez", resultados)[0] == {"nombre": "Juan Pérez"}


def test_info_cotizacion_del_dolar_no_devuelve_el_euro(pc, monkeypatch):
    info = pc._info()
    monkeypatch.setattr(info, "dolar", lambda: "El dólar a la venta: oficial, mil.")
    assert info.cotizacion("dólar") == "El dólar a la venta: oficial, mil."
    monkeypatch.setattr(info, "_json", lambda url: (
        [{"casa": "oficial", "venta": 1000}, {"casa": "blue", "venta": 1400}] if "dolares" in url
        else [{"moneda": "EUR", "venta": 1100}, {"moneda": "BRL", "venta": 200}]))
    assert info.convertir(100, "dólares", "pesos") == "100 dólares son 100000 pesos al oficial y 140000 al blue."
    assert info.convertir("2,5", "euros", "pesos") == "2,50 euros son 2750 pesos al oficial."
