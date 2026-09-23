# -*- coding: utf-8 -*-
"""Kelly sobre la cuenta REAL (19-sep-2026): R diaria desde el PnL real y el
riesgo por trade usado, Kelly exacta de la ventana, y el reparto entre
estrategias por sus Kellys del backtest con los dos topes."""
import numpy as np
import pytest

from app.services.portfolio_lab_raw import kelly_cuenta_real


def _rows(n=60, seed=1):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        d = f"2026-{1 + k // 28:02d}-{1 + k % 28:02d}"
        # dia tipico: +1,5 R de media con dispersion 3 R, riesgo 100 $ por trade
        out.append({"date": d, "pnl": float(rng.normal(150.0, 300.0))})
    return out


def test_r_diaria_en_usd_y_en_pct():
    rows = [{"date": "2026-01-02", "pnl": 200.0}, {"date": "2026-01-02", "pnl": -50.0}, {"date": "2026-01-05", "pnl": -100.0}]
    # $ fijos: 150/100 = 1,5 R y -1 R
    o = kelly_cuenta_real(rows, "usd", 100.0, 10000.0, 0.5, 5.0, 2.0, 0, [], 10000.0)
    assert [x["r"] for x in o["serie"]] == [1.5, -1.0]
    assert o["dias"] == 2 and o["nota"] and "sin muestra" in o["nota"] and o["total_pct"] is None
    # % del equity del dia: 1 % de 10.000 = 100 $ el primer dia; el segundo, 1 % de 10.150
    o = kelly_cuenta_real(rows, "pct", 1.0, 10000.0, 0.5, 5.0, 2.0, 0, [], 10000.0)
    assert o["serie"][0]["riesgo"] == pytest.approx(100.0) and o["serie"][1]["riesgo"] == pytest.approx(101.5)
    assert o["serie"][1]["r"] == pytest.approx(-100.0 / 101.5, rel=1e-6)


def test_reparto_por_kellys_del_backtest_con_topes():
    rows = _rows()
    est = [{"name": "A", "kelly_pct": 60.0}, {"name": "B", "kelly_pct": 30.0}, {"name": "C", "kelly_pct": 0.0}]
    o = kelly_cuenta_real(rows, "usd", 100.0, 10000.0, 0.5, 5.0, 2.0, 0, est, 20000.0)
    assert o["kelly_raw_pct"] is not None and o["kelly_raw_pct"] > 0
    shares = [p["share"] for p in o["per_strategy"]]
    assert shares == pytest.approx([2 / 3, 1 / 3, 0.0])
    # Ninguna pasa del tope por estrategia (2 %) y la suma no pasa del tope (5 %).
    apl = [p["risk_pct"] for p in o["per_strategy"]]
    assert all(a <= 2.0 + 1e-9 for a in apl) and sum(apl) <= 5.0 + 1e-9
    assert o["total_pct"] == pytest.approx(sum(apl))
    assert o["per_strategy"][0]["risk_usd"] == pytest.approx(20000.0 * apl[0] / 100.0)
    # Con Kelly pedida grande, el tope por estrategia actua antes que el de la suma.
    assert o["capped_strategy"] is True or o["capped"] is True


def test_ventana_solo_mira_los_ultimos_dias():
    rows = _rows(120)
    todo = kelly_cuenta_real(rows, "usd", 100.0, 10000.0, 0.5, 0.0, 0.0, 0, [], 10000.0)
    ult = kelly_cuenta_real(rows, "usd", 100.0, 10000.0, 0.5, 0.0, 0.0, 30, [], 10000.0)
    assert todo["dias_ventana"] == 120 and ult["dias_ventana"] <= 31
    assert ult["desde"] >= "2026-03-31"


def test_fichero_xlsx_de_das_da_el_mismo_csv(tmp_path):
    """20-sep: el paso 5 admite el FICHERO (csv o Excel). Un .xlsx con el export
    de DAS, con las fechas como fechas de Excel, tiene que dar las mismas
    operaciones que el CSV de texto."""
    import csv as _csv
    import datetime as _dt
    import openpyxl
    from app.services.cuenta_real import parse_csv, texto_de_fichero

    cab = ["Account #", "Trade Date", "Side", "Symbol", "Qty", "Price", "Total Fees", "Locate Fee", "Net Amt"]
    filas = [
        ["1", "2026-09-17", "B", "SDST", "800", "0.3206", "0.8", "0", "257.28"],
        ["1", "2026-09-17", "SS", "SDST", "-800", "0.3225", "0.92", "0", "-257.08"],
        ["1", "2026-09-18", "SS", "RETO", "-121", "3.30", "0.48", "1.5", "-399.78"],
        ["1", "2026-09-18", "B", "RETO", "121", "2.63", "0.48", "0", "318.71"],
    ]
    texto = "\n".join(",".join(r) for r in [cab] + filas) + "\n"
    ref = parse_csv(texto)
    assert ref["formato"] == "das" and ref["n_fills"] == 4 and len(ref["filas"]) == 2

    # El mismo contenido en Excel: fechas de verdad, numeros de verdad.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(cab)
    for r in filas:
        ws.append([r[0], _dt.datetime.fromisoformat(r[1]), r[2], r[3], float(r[4]), float(r[5]), float(r[6]), float(r[7]), float(r[8])])
    f = tmp_path / "Transactions.xlsx"
    wb.save(f)
    texto_x = texto_de_fichero(f.read_bytes(), "Transactions.xlsx")
    out = parse_csv(texto_x)
    assert out["formato"] == "das" and out["n_fills"] == 4
    assert [(x["date"], x["symbol"], round(x["pnl"], 2), round(x["notional"], 2)) for x in out["filas"]] == \
        [(x["date"], x["symbol"], round(x["pnl"], 2), round(x["notional"], 2)) for x in ref["filas"]]

    # CSV con BOM (Excel «guardar como CSV UTF-8») y .xls viejo.
    assert parse_csv(texto_de_fichero(("﻿" + texto).encode("utf-8"), "t.csv"))["n_fills"] == 4
    with pytest.raises(ValueError):
        texto_de_fichero(b"xx", "viejo.xls")


def test_sin_estrategias_el_total_sale_igual():
    """20-sep: sin el paso 4 (lista de estrategias vacia) el total del
    siguiente periodo salia 0 %: el total es Kelly x fraccion topado, y no
    depende de tener a quien repartirselo."""
    from app.services import portfolio_lab_raw as plr
    rows = []
    for k in range(40):
        rows.append({"date": f"2026-0{1 + k // 20}-{1 + k % 20:02d}", "pnl": (60.0 if k % 3 else -40.0), "notional": 1000.0})
    con = plr.kelly_cuenta_real(rows, "notional", 1.0, 10000.0, 0.5, 10.0, 0.0, 0, [{"name": "A", "kelly_pct": 30.0}], 10000.0, "clasica")
    sin = plr.kelly_cuenta_real(rows, "notional", 1.0, 10000.0, 0.5, 10.0, 0.0, 0, [], 10000.0, "clasica")
    assert con["kelly_clasica_pct"] == sin["kelly_clasica_pct"] > 0
    assert sin["total_pct"] == con["total_pct"] == pytest.approx(min(10.0, con["total_pedido_pct"]))
    assert sin["total_usd"] == pytest.approx(10000.0 * sin["total_pct"] / 100.0)
    assert sin["per_strategy"] == []
