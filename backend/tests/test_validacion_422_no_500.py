"""Un validador de estrategia que falla tiene que dar 422 con su mensaje, no 500.

PRD de Alvaro (18-sep-2026), Fix 3: `POST /api/strategies/` con un `lot_stop`
sin `pct` o con `steps` de un solo paso respondia
    500 {"detail": "Internal Server Error",
         "message": "Object of type ValueError is not JSON serializable"}
La validacion pydantic funcionaba (nada invalido se guardaba); lo que fallaba
era el manejador de RequestValidationError de main.py: devolvia `exc.errors()`
tal cual, y con pydantic v2 cada error lleva el ValueError original dentro de
`ctx`. JSONResponse no lo puede serializar, salta un TypeError y lo recoge el
manejador global como 500. El mensaje del validador se perdia por el camino.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def cliente():
    # raise_server_exceptions=False: queremos ver el codigo que recibiria el
    # navegador, no que el test reviente con la excepcion del servidor.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _estrategia_con_nivel(nivel: dict) -> dict:
    return {
        "name": "sonda 422",
        "bias": "short",
        "entry_logic": {"root_condition": {"type": "group", "operator": "AND", "conditions": []},
                        "entry_time_windows": []},
        "exit_logic": {"root_condition": {"type": "group", "operator": "AND", "conditions": []}},
        "risk_management": {"size_by_sl": False, "use_stop_loss": True, "stop_loss_mode": "Fixed",
                            "fixed_stop_loss_pct": 5.0},
        "pyramiding": {"enabled": True, "mode": "manual", "levels": [nivel]},
    }


def _nivel_base() -> dict:
    return {
        "action": "add", "size_pct": 50, "timeframe": "1m",
        "root_condition": {"type": "group", "operator": "AND", "conditions": []},
    }


@pytest.mark.parametrize("roto, fragmento", [
    ({**_nivel_base(), "lot_stop": {"mode": "pct"}}, "pct"),
    # steps + root_condition juntos: es lo que el PRD sondeaba (su propio validador).
    ({**_nivel_base(), "steps": [{"type": "group", "operator": "AND", "conditions": []}]}, "mutuamente exclusivos"),
    # un solo paso (sin root_condition): «hacen falta al menos 2 pasos».
    ({k: v for k, v in _nivel_base().items() if k != "root_condition"}
     | {"steps": [{"type": "group", "operator": "AND", "conditions": []}]}, "pasos"),
])
def test_validador_roto_responde_422_con_su_mensaje(cliente, roto, fragmento):
    r = cliente.post("/api/strategies/", json=_estrategia_con_nivel(roto))
    assert r.status_code == 422, (r.status_code, r.text[:300])
    cuerpo = r.json()
    assert "detail" in cuerpo
    texto = str(cuerpo["detail"])
    assert fragmento in texto, f"el mensaje del validador no viaja en el 422: {texto[:300]}"
    assert "not JSON serializable" not in texto


def test_un_422_normal_sigue_siendo_422(cliente):
    r = cliente.post("/api/strategies/", json={"name": 123})
    assert r.status_code == 422
