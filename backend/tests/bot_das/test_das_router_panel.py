"""Router de la pestaña «Ejecución» (`app/routers/bot_das.py`): estado, cambios del cuadro y exportación.

El cuadro de ejemplo se copia a BOT_DAS_DIR (= tmp_path, fixture `entorno_limpio`); nadie toca D:\\bot_senales.
"""
from __future__ import annotations

import copy
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user_id
from app.bot_das import config as cfgmod
from app.bot_das.reloj import ET
from app.routers import bot_das as panel

FIXTURE = Path(__file__).parent / "fixtures" / "config_ejemplo.json"


@pytest.fixture
def cuadro(dir_bot: Path) -> Path:
    ruta = dir_bot / "config" / cfgmod.NOMBRE_FICHERO_CONFIG
    shutil.copyfile(FIXTURE, ruta)
    return ruta


@pytest.fixture
def cliente(cuadro: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BOT_ALERTS_ENABLED", "1")
    app = FastAPI()
    app.include_router(panel.router, prefix="/api/bot-das")
    app.dependency_overrides[get_current_user_id] = lambda: "jaume"
    with TestClient(app) as c:
        yield c


def _latir(dir_bot: Path, proceso: str = "ejecutor") -> None:
    (dir_bot / "estado" / f"latido_{proceso}").write_text(repr(time.time()), encoding="ascii")


def _crudo(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def test_estado_con_el_bot_apagado(cliente, dir_bot):
    hoy = datetime.now(ET).date().isoformat()
    lineas = [
        {"v": 1, "seq": 1, "t": f"{hoy}T09:31:00.000-04:00", "proceso": "ejecutor", "tipo": "orden", "datos": {}},
        {"v": 1, "seq": 2, "t": f"{hoy}T09:32:00.000-04:00", "proceso": "ejecutor", "tipo": "aviso",
         "datos": {"nivel": 2, "texto": "prueba de aviso"}},
    ]
    (dir_bot / "diario" / f"diario_ejecutor_{hoy}.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lineas) + "\n", encoding="utf-8")
    r = cliente.get("/api/bot-das/estado")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["encendido"] is False and d["bloquea_no_calientes"] is False
    assert d["foto"] is None and d["ultimo_latido"] is None
    assert d["cuadro_error"] is None
    assert d["cuadro"]["fase"] == "sombra"
    assert d["cuadro"]["estrategias"][0]["strategy_id"] == "prueba-1"
    assert d["cuadro"]["halts"]["silencio"] is True          # hoja opcional ausente → su defecto
    assert [a["texto"] for a in d["avisos"]] == ["prueba de aviso"]


def test_estado_con_latido_y_foto(cliente, dir_bot):
    _latir(dir_bot)
    foto = {"fase": "sombra", "vigilando": True, "posiciones": {"XYZ": {"neta_das": -100, "lotes": []}},
            "ordenes": [{"token": "t1", "ticker": "XYZ", "estado": "Accepted"}], "gasto_locates_dia": "12.5",
            "cuenta": {"equity": "30000"}}
    (dir_bot / "estado" / "foto.json").write_text(json.dumps(foto), encoding="utf-8")
    d = cliente.get("/api/bot-das/estado").json()
    assert d["encendido"] is True and d["bloquea_no_calientes"] is True
    assert d["foto"]["posiciones"][0]["ticker"] == "XYZ"
    assert d["foto"]["gasto_locates_dia"] == 12.5 and d["foto"]["equity"] == 30000.0


def test_put_refirma_y_carga(cliente, cuadro, dir_bot):
    antes = _crudo(cuadro)
    r = cliente.put("/api/bot-das/cuadro", json={
        "config_version": antes["config_version"], "vigilando": False,
        "estrategias": [{"strategy_id": "prueba-1", "riesgo_usd": 250, "ev_pct": None}],
        "locates": {"tope_gasto_dia_usd": 300},
    })
    assert r.status_code == 200, r.text
    assert r.json()["escrito"] is True
    cfg = cfgmod.cargar(cuadro, "CUENTA")                     # carga: firma y hashes bien
    despues = _crudo(cuadro)
    assert despues["config_version"] == antes["config_version"] + 1
    assert despues["sha256"] == cfgmod.hash_canonico({k: v for k, v in despues.items() if k != "sha256"})
    assert cfg.vigilando is False and cfg.locates["tope_gasto_dia_usd"] == 300
    e = cfg.estrategias["prueba-1"]
    assert e.riesgo_usd == 250 and e.sin_ev is True           # ev_pct null: carga pero no ejecuta (decisión 23)
    assert despues["estrategias"][0]["ev_pct"] is None
    log = (dir_bot / "logs" / panel.NOMBRE_LOG_CAMBIOS).read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(log[-1])["quien"] == "jaume"


def test_put_que_no_carga_es_422_y_no_escribe(cliente, cuadro):
    antes = cuadro.read_bytes()
    r = cliente.put("/api/bot-das/cuadro", json={"estrategias": [{"strategy_id": "prueba-1", "riesgo_usd": 0}]})
    assert r.status_code == 422, r.text                      # ejecutar=true exige riesgo > 0
    assert "riesgo_usd" in json.dumps(r.json())
    assert cuadro.read_bytes() == antes


def test_put_estrategia_desconocida_es_422(cliente):
    r = cliente.put("/api/bot-das/cuadro", json={"estrategias": [{"strategy_id": "no-existe", "ejecutar": False}]})
    assert r.status_code == 422


def test_put_version_vieja_es_409(cliente, cuadro):
    r = cliente.put("/api/bot-das/cuadro", json={"config_version": 999, "vigilando": False})
    assert r.status_code == 409 and "recarga" in r.json()["detail"]


def test_put_silencio_con_latido_vivo_es_409(cliente, cuadro, dir_bot):
    _latir(dir_bot)
    antes = cuadro.read_bytes()
    r = cliente.put("/api/bot-das/cuadro", json={"halts": {"silencio": False}})
    assert r.status_code == 409, r.text
    assert "apaga el bot" in r.json()["detail"] and "halts.silencio" in r.json()["detail"]
    assert cuadro.read_bytes() == antes
    # una hoja [C] sí se deja con el bot encendido
    r = cliente.put("/api/bot-das/cuadro", json={"locates": {"tope_gasto_dia_usd": 350}})
    assert r.status_code == 200, r.text


def test_put_silencio_con_el_bot_apagado(cliente, cuadro):
    r = cliente.put("/api/bot-das/cuadro", json={"halts": {"silencio": False}})
    assert r.status_code == 200, r.text
    assert cfgmod.cargar(cuadro, "CUENTA").halts["silencio"] is False


def _filas(crudo: dict) -> list[dict]:
    base = crudo["estrategias"][0]
    vieja = {"strategy_id": "prueba-1", "name": base["name"], "definition": copy.deepcopy(base["definition"]),
             "riesgo_usd": 999, "ev_pct": 9.9}
    nueva = {"strategy_id": "nueva-1", "name": "Nueva", "definition": copy.deepcopy(base["definition"]),
             "riesgo_usd": 100, "ev_pct": 3.0}
    return [vieja, nueva]


def test_exportar_conserva_lo_del_panel(cliente, cuadro, monkeypatch):
    previo = _crudo(cuadro)
    r = cliente.put("/api/bot-das/cuadro", json={"vigilando": False, "locates": {"tope_gasto_dia_usd": 222}})
    assert r.status_code == 200
    monkeypatch.setattr(cfgmod, "_pedir_vigiladas", lambda url, t: _filas(previo))
    r = cliente.post("/api/bot-das/exportar")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["nuevas"] == ["nueva-1"] and d["estrategias"] == 2
    cfg = cfgmod.cargar(cuadro, "CUENTA")
    assert cfg.config_version == previo["config_version"] + 2
    vieja, nueva = cfg.estrategias["prueba-1"], cfg.estrategias["nueva-1"]
    assert (vieja.ejecutar, vieja.riesgo_usd, vieja.ev_pct) == (True, 300, 4.0)   # del cuadro, no del backend
    assert (nueva.ejecutar, nueva.riesgo_usd, nueva.ev_pct) == (False, 100, 3.0)  # nueva: apagada (decisión 22)
    assert cfg.vigilando is False and cfg.locates["tope_gasto_dia_usd"] == 222
    assert cfg.stops["techo_pct"] == 50                       # cuadro de producción aplicado (decisión 72)


def test_exportar_con_estrategia_nueva_y_bot_encendido_es_409(cliente, cuadro, dir_bot, monkeypatch):
    _latir(dir_bot, "vigilante")
    antes = cuadro.read_bytes()
    monkeypatch.setattr(cfgmod, "_pedir_vigiladas", lambda url, t: _filas(_crudo(cuadro)))
    r = cliente.post("/api/bot-das/exportar")
    assert r.status_code == 409, r.text
    assert cuadro.read_bytes() == antes


def test_exportar_sin_backend_es_502(cliente, cuadro, monkeypatch):
    antes = cuadro.read_bytes()
    monkeypatch.setattr(cfgmod, "_pedir_vigiladas", lambda url, t: None)
    assert cliente.post("/api/bot-das/exportar").status_code == 502
    assert cuadro.read_bytes() == antes


def test_sin_interruptor_es_503(cuadro, monkeypatch):
    monkeypatch.delenv("BOT_ALERTS_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(panel.router, prefix="/api/bot-das")
    app.dependency_overrides[get_current_user_id] = lambda: None
    with TestClient(app) as c:
        assert c.get("/api/bot-das/estado").status_code == 503
