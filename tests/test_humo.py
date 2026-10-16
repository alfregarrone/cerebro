"""Pruebas de humo: que la skill y el agente se importen y respondan con todo simulado."""


def test_la_skill_se_importa(skill):
    assert skill.ALEXA_BUDGET < 8
    assert "nota" in skill.PC_ACTIONS


def test_la_hora_no_pasa_por_la_ia(echo):
    r = echo.decir("qué hora es")
    assert r.habla.startswith("Son las")
    assert not echo.prompts_ia


def test_una_charla_pasa_por_la_ia_y_queda_en_memoria(echo):
    echo.ia = lambda system, messages, **kw: "Hola, ¿cómo estás?"
    r = echo.decir("hola")
    assert r.habla == "Hola, ¿cómo estás?"
    assert echo.prompts_ia
    assert echo.memoria["recent"][-1]["content"] == "Hola, ¿cómo estás?"


def test_el_agente_guarda_notas_y_pendientes(pc):
    assert pc.accion_nota({"texto": "comprar pilas", "categoria": "pendiente"}) == (True, "Pendiente agregado.")
    assert pc.accion_pendientes({}) == (True, "Tenés 1 pendiente: comprar pilas.")
    assert (pc.VAULT / "Pendientes.md").exists()


def test_la_red_esta_bloqueada():
    import urllib.request

    import pytest
    with pytest.raises(OSError):
        urllib.request.urlopen("https://dolarapi.com/v1/dolares", timeout=2)
