"""Estrategias compartidas entre devs: service + API roundtrip.

El service es puro ficheros (sin BD): se prueba contra un tmp_path via
SHARED_STRATEGIES_DIR. El roundtrip de API reusa el payload valido de
test_strategy_api.py y se limpia el rastro (estrategia + fichero) al acabar.
"""
import json

import pytest

from app.services import shared_strategies as svc


@pytest.fixture
def shared_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_STRATEGIES_DIR", str(tmp_path))
    monkeypatch.setenv("SHARED_STRATEGIES_OWNER", "tester")
    return tmp_path


# ── slugify / build_filename ────────────────────────────────────────────────

def test_slugify_quita_tildes_espacios_y_emoji():
    assert svc.slugify("Órdenes & Filtros 🔥 v2") == "ordenes-filtros-v2"
    assert svc.slugify("  Gap   Day  ") == "gap-day"
    assert svc.slugify(" TODO MAYUSCULAS ") == "todo-mayusculas"


def test_slugify_vacio_y_largo():
    assert svc.slugify("") == "estrategia"
    assert svc.slugify("🔥🔥🔥") == "estrategia"
    largo = svc.slugify("a" * 200)
    assert len(largo) == 50 and largo == "a" * 50


def test_build_filename_determinista():
    # Mismo texto con y sin tildes -> mismo slug (re-compartir actualiza).
    a = svc.build_filename("Órdenes y Filtros", "abcdef12-...")
    b = svc.build_filename("ordenes y filtros", "abcdef12-...")
    assert a == b == "ordenes-y-filtros--abcd.json"


# ── write / list / delete sobre tmp_path ────────────────────────────────────

def _definicion(bias="long"):
    return {"bias": bias, "risk_management": {"use_hard_stop": True}}


def test_write_y_list_roundtrip(shared_tmp):
    entry = svc.write_shared(
        name="Prueba Áé",
        description="desc",
        source_strategy_id="11112222-3333",
        definition=_definicion(),
    )
    assert entry["shared_by"] == "tester"
    assert entry["filename"] == "prueba-ae--1111.json"

    ficheros = list(shared_tmp.glob("*/*.json"))
    assert [f.name for f in ficheros] == ["prueba-ae--1111.json"]
    # El JSON del disco debe llevar la definicion intacta.
    data = json.loads((shared_tmp / "tester" / "prueba-ae--1111.json").read_text(encoding="utf-8"))
    assert data["definition"] == _definicion()
    assert data["format_version"] == 1

    listed = svc.list_shared()
    assert len(listed) == 1
    assert listed[0]["name"] == "Prueba Áé"
    assert listed[0]["source_strategy_id"] == "11112222-3333"


def test_recompartir_sobreescribe_el_mismo_fichero(shared_tmp):
    for definicion in (_definicion(), _definicion(bias="short")):
        svc.write_shared(name="Mi Estrategia", description=None,
                         source_strategy_id="aaaabbbb", definition=definicion)
    ficheros = list(shared_tmp.glob("*/*.json"))
    assert len(ficheros) == 1
    assert svc.list_shared()[0]["definition"]["bias"] == "short"


def test_list_lee_a_los_dos_devs(shared_tmp, monkeypatch):
    svc.write_shared(name="Mia", description=None, source_strategy_id="1a", definition=_definicion())
    monkeypatch.setenv("SHARED_STRATEGIES_OWNER", "otro")
    svc.write_shared(name="Suya", description=None, source_strategy_id="2b", definition=_definicion())

    listed = svc.list_shared()
    assert {(e["name"], e["shared_by"]) for e in listed} == {("Mia", "tester"), ("Suya", "otro")}


def test_delete_solo_ficheros_propios(shared_tmp, monkeypatch):
    svc.write_shared(name="Mia", description=None, source_strategy_id="1a", definition=_definicion())
    monkeypatch.setenv("SHARED_STRATEGIES_OWNER", "otro")

    # Con otro owner, el fichero de "tester" no es alcanzable: ni por nombre
    # valido (no esta en MI subcarpeta) ni por traversal.
    with pytest.raises(FileNotFoundError):
        svc.delete_shared("mia--1a.json")
    with pytest.raises(svc.InvalidSharedFilename):
        svc.delete_shared("../tester/mia--1a.json")
    assert len(list(shared_tmp.glob("*/*.json"))) == 1

    monkeypatch.setenv("SHARED_STRATEGIES_OWNER", "tester")
    svc.delete_shared("mia--1a.json")
    assert svc.list_shared() == []


@pytest.mark.parametrize("mal", ["../evil.json", "a b.json", "X.json", "evil..json", "..", ""])
def test_delete_rechaza_nombres_malformados(shared_tmp, mal):
    with pytest.raises(svc.InvalidSharedFilename):
        svc.delete_shared(mal)


# ── API roundtrip (montaje + flujo compartir/quitar) ────────────────────────

def _payload(nombre):
    return {
        "name": nombre,
        "description": "estrategia de prueba del shared roundtrip",
        "bias": "long",
        "universe_filters": {"min_market_cap": 50_000_000, "max_market_cap": 500_000_000},
        "entry_logic": {
            "timeframe": "1m",
            "candle_delay": 1,
            "root_condition": {"operator": "AND", "conditions": []},
        },
        "exit_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": []}},
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 5.0},
            "use_take_profit": True,
            "take_profit": {"type": "Percentage", "value": 20.0},
            "accept_reentries": False,
        },
    }


def test_api_roundtrip_compartir_y_quitar(shared_tmp):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    creada = client.post("/api/strategies/", json=_payload("[test-shared] roundtrip"))
    if creada.status_code in (401, 403):
        pytest.skip("auth activada: el roundtrip de strategies requiere sesion")
    assert creada.status_code == 200, creada.text
    strategy_id = creada.json()["id"]

    try:
        compartida = client.post("/api/shared-strategies/", json={"strategy_id": strategy_id})
        assert compartida.status_code == 200, compartida.text
        entry = compartida.json()
        assert entry["shared_by"] == "tester"
        assert entry["definition"]["risk_management"]["use_hard_stop"] is True

        listing = client.get("/api/shared-strategies/")
        assert listing.status_code == 200
        body = listing.json()
        assert body["owner"] == "tester"
        assert any(e["filename"] == entry["filename"] for e in body["strategies"])

        borrado = client.delete(f"/api/shared-strategies/{entry['filename']}")
        assert borrado.status_code == 200
        assert svc.list_shared() == []
    finally:
        client.delete(f"/api/strategies/{strategy_id}")
