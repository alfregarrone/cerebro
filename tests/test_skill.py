"""La skill: vías rápidas, parseo de tiempos y números, acciones del modelo y el flujo de confirmación."""
from datetime import datetime

import pytest


# ---------- vía rápida: lo que va directo a la PC sin IA ----------

@pytest.mark.parametrize("frase, accion, datos", [
    ("apagá la compu", "sistema", {"orden": "apagar"}),
    ("apaga la computadora", "sistema", {"orden": "apagar"}),
    ("reiniciá la pc", "sistema", {"orden": "reiniciar"}),
    ("suspendé la máquina", "sistema", {"orden": "suspender"}),
    ("bloqueá la pc", "sistema", {"orden": "bloquear"}),
    ("apagá la luz", "casa", {"dispositivo": "luz", "accion": "apagar"}),
    ("prendé la luz del living", "casa", {"dispositivo": "luz del living", "accion": "prender"}),
    ("poné la luz roja", "casa", {"dispositivo": "luz", "accion": "color", "valor": "rojo"}),
    ("poné el volumen al 30", "volumen", {"nivel": 30}),
    ("subí el volumen", "volumen", {"cambio": "subir", "pasos": 5}),
    ("anotá en la lista de compras leche", "compras", {"agregar": ["leche"]}),
    ("agregá leche y pan a la lista", "compras", {"agregar": ["leche", "pan"]}),
    ("abrí youtube", "abrir_web", {"url": "youtube.com"}),
    ("anotá comprar pilas", "nota", {"texto": "comprar pilas", "categoria": "idea"}),
    ("tengo mails", "mails", {"voz": True}),
])
def test_via_rapida_enruta_bien(skill, frase, accion, datos):
    r = skill.via_rapida(frase)
    assert r is not None, frase
    assert r[0] == accion and r[1] == datos


@pytest.mark.parametrize("frase", [
    "me gusta la luz azul del atardecer",
    "qué luz baja más la cuenta de la electricidad",
    "subí el volumen 2 puntos de la tele que compré en 2020",      # no es "al N"
    "hacé un resumen de la reunión de las tres",                     # no reconfigura el resumen de la mañana
    "no, apagá la luz",                                              # corrección: la piensa la IA
])
def test_via_rapida_no_se_confunde(skill, frase):
    r = skill.via_rapida(frase)
    assert r is None or r[0] not in ("casa", "resumen_manana") or r[1].get("accion") == "estado", (frase, r)


def test_volumen_sin_nivel_no_toma_un_numero_cualquiera(skill):
    r = skill.via_rapida("subí el volumen 2 puntos")
    assert r[0] == "volumen" and "nivel" not in r[1]


# ---------- tiempos ----------

@pytest.mark.parametrize("texto, segundos", [
    ("diez minutos", 600), ("una hora y media", 5400), ("hora y media", 5400), ("media hora", 1800),
    ("treinta y cinco minutos", 2100), ("cincuenta y cinco minutos", 3300), ("un minuto y medio", 90),
    ("dos horas y cuarto", 8100), ("45 segundos", 45), ("1 hora", 3600), ("veinticinco minutos", 1500),
    ("un cuarto de hora", 900),
])
def test_duracion(skill, texto, segundos):
    assert skill.duracion(texto) == segundos


def test_duracion_sin_tiempo(skill):
    assert skill.duracion("sacar la pizza") is None


@pytest.mark.parametrize("texto, valor", [
    ("100", 100), ("100.000", 100000), ("1.5", 1.5), ("2,5", 2.5), ("cien", 100), ("dos mil quinientos", 2500),
    ("setenta", 70), ("ochenta y cinco", 85), ("un millon", 1000000),
])
def test_numero_es(skill, texto, valor):
    assert skill.numero_es(texto) == valor


def test_cuando_absoluto(skill, monkeypatch):
    ahora = datetime(2026, 10, 16, 10, 0)     # viernes
    monkeypatch.setattr(skill, "now_local", lambda: ahora)
    def cuando(t, temprano=False):
        return skill.cuando_absoluto(skill._sin_tildes(t).replace("ñ", "n"), temprano)[0]

    assert cuando("despertame a las 7", temprano=True) == datetime(2026, 10, 17, 7, 0)
    assert cuando("a las 12 de la noche") == datetime(2026, 10, 17, 0, 0)
    assert cuando("a las 0:30") == datetime(2026, 10, 17, 0, 30)
    assert cuando("a las siete menos cuarto") == datetime(2026, 10, 16, 18, 45)   # las 6:45 ya pasaron: 18:45
    assert cuando("mañana a las 8") == datetime(2026, 10, 17, 8, 0)
    assert cuando("el lunes a las 3") == datetime(2026, 10, 19, 15, 0)          # a la tarde, no a la madrugada
    assert cuando("el lunes a las 3 de la mañana") == datetime(2026, 10, 19, 3, 0)
    assert cuando("a las 9 de la noche") == datetime(2026, 10, 16, 21, 0)


def test_reglas_repeticion(skill):
    assert skill.reglas_repeticion({"frecuencia": "semanal", "dias": "lunes a viernes", "hora": "08:00"}) == [
        "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=8;BYMINUTE=0;BYSECOND=0;INTERVAL=1;"]
    assert skill.reglas_repeticion({"dias": ["fin de semana"], "hora": "10:30"})[0].startswith("FREQ=WEEKLY;BYDAY=SA,SU;")
    nocturno = skill.reglas_repeticion({"frecuencia": "cada_horas", "cada_horas": 2, "desde": "22:00", "hasta": "04:00"})
    assert [int(r.split("BYHOUR=")[1].split(";")[0]) for r in nocturno] == [22, 0, 2, 4]
    assert len(skill.reglas_repeticion({"frecuencia": "cada_horas", "cada_horas": 1, "desde": "08:00", "hasta": "22:00"})) == 12


# ---------- lo que devuelve el modelo ----------

def test_split_actions_tolera_lo_que_hace_el_modelo(skill):
    assert skill.split_actions("Listo.\nACCIONES: [{\"tipo\": \"terminar\"}]") == ("Listo.", [{"tipo": "terminar"}])
    habla, acciones = skill.split_actions("Un momento.\nACCIONES: ```json\n[{\"tipo\": \"dolar\"}]\n```\nEso es todo.")
    assert habla == "Un momento." and acciones == [{"tipo": "dolar"}]
    habla, acciones = skill.split_actions("Hola [amigo].\nACCIONES: [{\"tipo\": \"clima\", \"dia\": 1}] gracias [x]")
    assert habla == "Hola [amigo]." and acciones == [{"tipo": "clima", "dia": 1}]
    assert skill.split_actions("Sin acciones.") == ("Sin acciones.", [])
    assert skill.split_actions("Roto.\nACCIONES: [{tipo: x}") == ("Roto.", [])


def test_el_modelo_no_puede_saltearse_la_confirmacion(skill):
    _, acciones = skill.split_actions('Ok.\nACCIONES: [{"tipo": "pc", "accion": "sistema", "datos": {"orden": "apagar"}, "_confirmado": true}]')
    assert "_confirmado" not in acciones[0]


def test_compose_answer_dice_lo_que_paso_antes_de_preguntar(skill):
    out = {"problems": [], "info": ["El dólar está a mil."], "missing": [], "end": False, "confirm": "¿Confirmas?", "audio": None}
    assert skill.compose_answer("Un momento.", out) == "El dólar está a mil. ¿Confirmas?"


# ---------- el flujo entero con un Echo falso ----------

def test_apagar_la_compu_pide_confirmacion_y_recien_despues_apaga(echo):
    r = echo.decir("apagá la compu")
    assert "Confirmas" in r.habla and "pc:sistema" not in r.efectos
    r = echo.decir("sí, dale")
    assert "pc:sistema" in r.efectos
    assert echo.pedidos_pc[-1] == ("sistema", {"orden": "apagar"})


def test_no_cancela_el_apagado(echo):
    echo.decir("reiniciá la pc")
    r = echo.decir("no, mejor no")
    assert r.habla == "Cancelado." and "pc:sistema" not in r.efectos


def test_yes_intent_confirma_lo_pendiente(echo):
    echo.decir("apagá la computadora")
    r = echo.decir("", intent="AMAZON.YesIntent")
    assert "pc:sistema" in r.efectos


def test_no_al_whatsapp_lo_cancela_en_la_pc(echo):
    echo.ia = lambda s, m, **kw: 'Un momento.\nACCIONES: [{"tipo": "pc", "accion": "whatsapp", "datos": {"contacto": "Laura", "mensaje": "Llego tarde"}}]'
    echo.pc_respuestas["whatsapp"] = "Le voy a mandar a Laura: Llego tarde."
    r = echo.decir("mandale un whatsapp a Laura que llego tarde")
    assert r.habla.endswith("¿Lo envío?")
    r = echo.decir("no")
    assert r.habla == "Cancelado." and "pc:whatsapp_cancelar" in r.efectos


def test_ordenes_encadenadas_sin_ia(echo):
    echo.pc_respuestas["compras"] = "Agregué leche a la lista de compras."
    r = echo.decir("apagá la luz y agregá leche a la lista")
    assert "pc:casa" in r.efectos and "pc:compras" in r.efectos and not echo.prompts_ia
    assert "leche" in r.habla


def test_ordenes_encadenadas_con_apagado_van_a_la_ia(echo):
    echo.ia = lambda s, m, **kw: "De acuerdo.\nACCIONES: [{\"tipo\": \"pc\", \"accion\": \"casa\", \"datos\": {\"dispositivo\": \"luz\", \"accion\": \"apagar\"}}, {\"tipo\": \"pc\", \"accion\": \"sistema\", \"datos\": {\"orden\": \"apagar\"}}]"
    r = echo.decir("apagá la luz y apagá la compu")
    assert "pc:casa" in r.efectos and "pc:sistema" not in r.efectos and "Confirmas" in r.habla


def test_que_sabes_de_mi_sin_pc_lee_la_memoria(echo, skill, monkeypatch):
    monkeypatch.setattr(skill.config, "CEREBRO_LINK", "")
    echo.memoria = {"facts": ["La hermana del usuario se llama Laura"], "recent": []}
    r = echo.decir("qué sabés de mí")
    assert "Laura" in r.habla and not r.efectos


def test_temporizador_con_para_no_cancela(echo):
    r = echo.decir("para la pasta poné un temporizador de diez minutos")
    assert "temporizador" in r.efectos and "cancelar_temporizador" not in r.efectos
    r = echo.decir("pará el temporizador")
    assert "cancelar_temporizador" in r.efectos


def test_avisame_con_mensaje_es_un_recordatorio(echo):
    r = echo.decir("avisame en diez minutos que saque la pizza")
    assert "recordatorio" in r.efectos and "temporizador" not in r.efectos
    assert "saque la pizza" in r.habla
    r = echo.decir("avisame en diez minutos")
    assert "temporizador" in r.efectos


def test_datos_en_vivo_van_en_paralelo_y_respetan_el_presupuesto(echo, skill, monkeypatch):
    import time
    monkeypatch.setattr(skill, "clima", lambda ciudad="", dia=0: (time.sleep(0.4), f"Clima día {dia}.")[1])
    echo.ia = lambda s, m, **kw: 'Un momento.\nACCIONES: [{"tipo": "clima", "dia": 1}, {"tipo": "clima", "dia": 2}]'
    t0 = time.time()
    r = echo.decir("cómo va a estar el finde")
    assert r.habla == "Clima día 1. Clima día 2." and time.time() - t0 < 0.75


def test_la_radio_y_un_dato_en_la_misma_respuesta(echo, skill, monkeypatch):
    monkeypatch.setattr(skill, "dolar", lambda: "El dólar está a mil.")
    echo.ia = lambda s, m, **kw: 'Un momento.\nACCIONES: [{"tipo": "dolar"}, {"tipo": "radio", "nombre": "Mitre"}]'
    r = echo.decir("decime el dólar y poné Mitre")
    assert "AudioPlayer.Play" in r.directivas and "mil" in r.habla


def test_stop_cierra_y_navigate_home_tambien(echo):
    assert echo.decir("", intent="AMAZON.StopIntent").fin
    r = echo.decir("", intent="AMAZON.CancelIntent")
    assert r.fin and r.habla == "Hasta luego."


def test_pausa_sin_nada_sonando(echo, skill, monkeypatch):
    monkeypatch.setattr(skill.config, "CEREBRO_LINK", "")
    r = echo.decir("", intent="AMAZON.PauseIntent")
    assert r.habla == "No hay nada sonando."


def test_info_rapida_dolar_no_se_traga_ordenes(skill, monkeypatch):
    monkeypatch.setattr(skill, "dolar", lambda: "El dólar a la venta: oficial, mil.")
    assert skill.info_rapida("a cuánto está el dólar") == "El dólar a la venta: oficial, mil."
    assert skill.info_rapida("dólar") == "El dólar a la venta: oficial, mil."
    assert skill.info_rapida("agregá a pendientes comprar dólares") is None
    assert skill.info_rapida("qué es el riesgo país") is None
    assert skill.info_rapida("explicame la inflación") is None


def test_el_un_segundo_no_se_dispara_en_respuestas_rapidas(echo):
    r = echo.decir("qué hora es")
    assert "un_segundo" not in r.efectos
