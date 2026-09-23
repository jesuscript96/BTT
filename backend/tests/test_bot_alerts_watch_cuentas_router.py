"""El endpoint /watch pasa las cuentas al servicio (18-sep-2026). El parche
del router se quedo sin escribir la primera vez y /vigiladas devolvia
cuentas=null aunque la pagina las mandara: este test lo habria pillado."""
import contextlib

from fastapi.testclient import TestClient

from app.main import app
from app.routers import bot_alerts as router_mod


class _Con:
    """Una conexion falsa: la estrategia existe y punto."""
    def execute(self, *a, **k):
        return self
    def fetchone(self):
        return ("s1",)
    def close(self):
        pass


def test_watch_pasa_cuentas_a_set_watch(monkeypatch):
    recibido = {}

    def falso_set_watch(con, sid, activa, riesgo, *args):
        recibido["args"] = args
        return {"strategy_id": sid, "activa": activa, "riesgo_usd": riesgo, "cuentas": args[-1]}

    monkeypatch.setattr(router_mod.bas, "set_watch", falso_set_watch)
    monkeypatch.setattr(router_mod, "get_user_db_connection", lambda *a, **k: _Con())
    monkeypatch.setattr(router_mod, "get_user_db_lock", lambda: contextlib.nullcontext())
    monkeypatch.setattr(router_mod, "scope_clause", lambda uid: ("", []))
    monkeypatch.setattr(router_mod, "_guard", lambda: None)
    from app.services import portfolio_lab_service as pls
    monkeypatch.setattr(pls, "get_assignments", lambda con: {"s1": ["portfolio"]})
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/bot-alerts/watch", json={
            "strategy_id": "s1", "activa": False, "riesgo_usd": 300,
            "cuentas": [{"nombre": "IBKR", "riesgo_usd": 200, "riesgo_piramide_usd": None}],
        })
    assert r.status_code == 200, r.text[:300]
    assert recibido["args"][-1] == [{"nombre": "IBKR", "riesgo_usd": 200.0, "riesgo_piramide_usd": None}]
