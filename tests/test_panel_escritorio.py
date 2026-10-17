"""El panel de escritorio (la ventana en la PC principal) contra el panel del agente, los dos acá, en 127.0.0.1."""
import json

import pytest


@pytest.fixture
def servidor(pc):
    import panel
    servidor, puerto = panel.iniciar(pc, puerto=0, en_red=False)
    yield panel, puerto
    panel.detener()


@pytest.fixture
def escritorio(pc, tmp_path, monkeypatch):
    import panel_escritorio as pe
    monkeypatch.setattr(pe, "BASE", tmp_path)
    monkeypatch.setattr(pe, "CONFIG", tmp_path / "panel_escritorio.json")
    return pe


def test_el_icono_del_panel_es_un_ico_valido():
    from pathlib import Path
    ico = Path(__file__).resolve().parent.parent / "pc" / "panel.ico"
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"          # cabecera de un .ico de Windows
    html = (ico.parent / "panel.html").read_text(encoding="utf-8")
    assert 'rel="icon" type="image/png" href="data:image/png;base64,' in html


def test_config_va_y_vuelve(escritorio):
    assert escritorio.cargar() == {"host": "", "puerto": 8765, "token": ""}
    escritorio.guardar({"host": "192.168.0.20", "puerto": 8766, "token": "abc def"})
    assert escritorio.cargar() == {"host": "192.168.0.20", "puerto": 8766, "token": "abc def"}
    assert escritorio.url(escritorio.cargar()) == "http://192.168.0.20:8766/?token=abc%20def"
    assert escritorio.url(escritorio.cargar(), con_token=False) == "http://192.168.0.20:8766/"


def test_ping_encuentra_al_agente_sin_token(servidor, escritorio):
    panel, puerto = servidor
    datos = escritorio.sondear("127.0.0.1", puerto)
    assert datos and datos["cerebro"] is True and datos["version"] and datos["en_red"] is False
    assert escritorio.sondear("127.0.0.1", puerto + 1) is None


def test_verificar_distingue_token_malo_de_pc_apagada(servidor, escritorio):
    panel, puerto = servidor
    ok, texto = escritorio.verificar({"host": "127.0.0.1", "puerto": puerto, "token": panel.token()})
    assert ok and texto.startswith("Conectado con")
    ok, texto = escritorio.verificar({"host": "127.0.0.1", "puerto": puerto, "token": "otro"})
    assert not ok and "token" in texto
    ok, texto = escritorio.verificar({"host": "127.0.0.1", "puerto": puerto + 1, "token": "x"})
    assert not ok and "panel_en_red" in texto
    assert escritorio.verificar({"host": "", "puerto": 1, "token": ""})[0] is False


def test_buscar_recorre_la_red(servidor, escritorio, monkeypatch):
    panel, puerto = servidor
    monkeypatch.setattr(escritorio, "sondear",
                        lambda host, p=8765, timeout=0.5: {"cerebro": True, "equipo": "PC2"} if host == "10.0.0.7" else None)
    assert escritorio.buscar(puerto, redes=["10.0.0"]) == [("10.0.0.7", {"cerebro": True, "equipo": "PC2"})]
    assert escritorio.buscar(puerto, redes=[]) == []


def test_abrir_sin_webview_ni_edge_usa_el_navegador(escritorio, monkeypatch):
    import sys
    abiertos = []
    monkeypatch.setitem(sys.modules, "webview", None)          # como si pywebview no estuviera
    monkeypatch.setattr(escritorio.shutil, "which", lambda nombre: None)
    monkeypatch.setattr(escritorio, "NAVEGADORES", (("msedge", ("/no/existe/msedge.exe",)),))
    monkeypatch.setattr(escritorio.webbrowser, "open", lambda u: abiertos.append(u) or True)
    assert escritorio.abrir({"host": "1.2.3.4", "puerto": 8765, "token": "t"}) == "navegador"
    assert abiertos == ["http://1.2.3.4:8765/?token=t"]


def test_abrir_con_edge_en_modo_aplicacion(escritorio, monkeypatch, tmp_path):
    import sys
    lanzados = []
    monkeypatch.setitem(sys.modules, "webview", None)
    monkeypatch.setattr(escritorio.shutil, "which", lambda nombre: "/usr/bin/msedge" if nombre == "msedge" else None)
    monkeypatch.setattr(escritorio.subprocess, "Popen", lambda cmd, **k: lanzados.append(cmd))
    assert escritorio.abrir({"host": "1.2.3.4", "puerto": 8765, "token": "t"}) == "msedge"
    assert lanzados[0][:2] == ["/usr/bin/msedge", "--app=http://1.2.3.4:8765/?token=t"]


def test_main_buscar_y_config_incompleta(escritorio, monkeypatch, capsys):
    monkeypatch.setattr(escritorio, "buscar", lambda *a, **k: [])
    assert escritorio.main(["--buscar"]) == 1
    monkeypatch.setattr(escritorio, "configurar", lambda: None)
    assert escritorio.main([]) == 1                           # sin host ni token y el usuario canceló
    escritorio.guardar({"host": "127.0.0.1", "puerto": 1, "token": "t"})
    monkeypatch.setattr(escritorio, "verificar", lambda cfg: (True, "Conectado con PC2."))
    monkeypatch.setattr(escritorio, "abrir", lambda cfg: "webview")
    assert escritorio.main([]) == 0
    assert json.loads(escritorio.CONFIG.read_text(encoding="utf-8"))["host"] == "127.0.0.1"
