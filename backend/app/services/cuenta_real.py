"""Cuenta REAL (Jaume, 19/20-sep-2026): leer el CSV de la operativa real y
sacar de el una fila por operacion (fecha, PnL neto, valor de la posicion).

Dos formatos:

  1. El export de DAS («Transactions»): una fila por FILL con Trade Date,
     Side (B, S, SS), Symbol, Qty, Price, comisiones/ECN/tasas, Gross Amt y
     Net Amt. Net Amt es la caja: positivo en las compras (lo que cuesta),
     negativo en las ventas (lo que entra). Cada operacion es un simbolo-dia:
     PnL = ventas − compras (con las tasas ya dentro de Net Amt), y el valor
     de la posicion es lo mayor de lo comprado y lo vendido (para un corto,
     lo vendido primero). Si un simbolo-dia no queda plano (overnight), se
     cuenta igual y se avisa.
  2. Un CSV sencillo con fecha y pnl (y, si se quiere, la posicion) por dia
     o por operacion; cabeceras en espanol o ingles.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any


def _num(s: Any) -> float:
    if s is None:
        return 0.0
    t = str(s).strip().replace("$", "").replace("€", "").replace(" ", "")
    if not t:
        return 0.0
    if "." in t and "," in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


def _fecha(s: Any) -> str | None:
    t = str(s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        # DD/MM (espanol) salvo que el primero no pueda ser un dia.
        if b > 12 and a <= 12:
            a, b = b, a
        return f"{y}-{b:02d}-{a:02d}"
    return None


def _separador(primera_linea: str) -> str:
    c = primera_linea.count(",")
    p = primera_linea.count(";")
    t = primera_linea.count("\t")
    if t > max(c, p):
        return "\t"
    return ";" if p >= c else ","


def es_das(texto: str) -> bool:
    cab = (texto.strip().split("\n", 1)[0] if texto else "").lower()
    return "symbol" in cab and ("net amt" in cab or "net_amt" in cab) and "side" in cab


def parse_das(texto: str) -> dict:
    """Operaciones (simbolo-dia) del export de DAS."""
    lineas = texto.strip().split("\n")
    sep = _separador(lineas[0])
    rd = csv.DictReader(io.StringIO(texto.strip()), delimiter=sep)
    campos = {k.strip().lower(): k for k in (rd.fieldnames or [])}
    def col(*nombres: str) -> str | None:
        for nm in nombres:
            if nm in campos:
                return campos[nm]
        return None
    c_fecha = col("trade date", "date", "fecha")
    c_side = col("side")
    c_sym = col("symbol")
    c_qty = col("qty", "quantity")
    c_net = col("net amt", "net_amt", "net amount")
    c_gross = col("gross amt", "gross_amt")
    c_fees = col("total fees", "fees")
    c_loc = col("locate fee")
    if not (c_fecha and c_side and c_sym and c_net):
        raise ValueError("El CSV de DAS necesita las columnas Trade Date, Side, Symbol y Net Amt")
    ops: dict[tuple[str, str], dict] = {}
    n_fills = 0
    for row in rd:
        d = _fecha(row.get(c_fecha))
        if not d:
            continue
        sym = str(row.get(c_sym) or "").strip().upper()
        side = str(row.get(c_side) or "").strip().upper()
        if not sym or not side:
            continue
        net = _num(row.get(c_net))
        qty = abs(_num(row.get(c_qty))) if c_qty else 0.0
        o = ops.setdefault((d, sym), {"date": d, "symbol": sym, "compras": 0.0, "ventas": 0.0, "qty_neta": 0.0,
                                      "fees": 0.0, "locates": 0.0, "n_fills": 0, "lado": None})
        if side.startswith("B"):
            o["compras"] += net
            o["qty_neta"] += qty
        else:
            o["ventas"] += -net
            o["qty_neta"] -= qty
        if o["lado"] is None:
            o["lado"] = "Long" if side.startswith("B") else "Short"
        o["fees"] += _num(row.get(c_fees)) if c_fees else 0.0
        o["locates"] += _num(row.get(c_loc)) if c_loc else 0.0
        o["n_fills"] += 1
        n_fills += 1
    filas = []
    abiertas = 0
    for (d, sym), o in sorted(ops.items()):
        pnl = o["ventas"] - o["compras"]
        notional = max(o["compras"], o["ventas"])
        plano = abs(o["qty_neta"]) < 1e-9
        if not plano:
            abiertas += 1
        filas.append({"date": d, "symbol": sym, "pnl": round(pnl, 4), "notional": round(notional, 4),
                      "lado": o["lado"], "fees": round(o["fees"], 4), "locates": round(o["locates"], 4),
                      "n_fills": o["n_fills"], "plano": plano})
    aviso = None
    if abiertas:
        aviso = f"{abiertas} operaciones no quedan planas en el dia (posicion abierta al cierre): su PnL es el de la caja del dia"
    return {"formato": "das", "filas": filas, "n_fills": n_fills, "aviso": aviso}


def parse_simple(texto: str) -> dict:
    """CSV sencillo: fecha, pnl [, posicion]. Con o sin cabecera."""
    lineas = [l.strip() for l in texto.strip().split("\n") if l.strip()]
    if not lineas:
        return {"formato": "simple", "filas": [], "n_fills": 0, "aviso": None}
    sep = _separador(lineas[0])
    cab = [c.strip().strip('"').lower() for c in lineas[0].split(sep)]
    def idx(pat: str) -> int:
        for i, c in enumerate(cab):
            if re.search(pat, c):
                return i
        return -1
    i_f = idx(r"fecha|date|d[ií]a")
    i_p = idx(r"p&l|pnl|neto|\bnet\b|profit|beneficio|resultado|realized|ganancia")
    i_n = idx(r"posici[oó]n|notional|nocional|valor|size|importe")
    con_cab = i_f >= 0 or i_p >= 0
    cf, cp = (i_f if i_f >= 0 else 0), (i_p if i_p >= 0 else 1)
    filas = []
    malas = 0
    for l in lineas[1:] if con_cab else lineas:
        c = [x.strip().strip('"') for x in l.split(sep)]
        d = _fecha(c[cf] if cf < len(c) else "")
        v = _num(c[cp]) if cp < len(c) else None
        if not d or v is None or (cp < len(c) and not c[cp]):
            malas += 1
            continue
        fila = {"date": d, "symbol": "", "pnl": v, "notional": 0.0, "lado": None, "fees": 0.0, "locates": 0.0, "n_fills": 1, "plano": True}
        if i_n >= 0 and i_n < len(c):
            fila["notional"] = _num(c[i_n])
        filas.append(fila)
    return {"formato": "simple", "filas": filas, "n_fills": len(filas),
            "aviso": (f"{malas} filas sin fecha o sin PnL legibles se han saltado" if malas else None)}


def parse_csv(texto: str) -> dict:
    return parse_das(texto) if es_das(texto) else parse_simple(texto)


# ── Fichero subido (20-sep): CSV/TXT o Excel .xlsx → el texto CSV de siempre ──

def _celda_a_texto(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        # datetime/date de Excel -> ISO, que _fecha entiende.
        try:
            return v.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v, "hour") else v.strftime("%Y-%m-%d")
        except Exception:
            return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def texto_de_fichero(contenido: bytes, nombre: str) -> str:
    """Devuelve el CSV (texto) de un fichero subido: .csv/.txt tal cual (UTF-8
    con o sin BOM, o latin-1), .xlsx/.xlsm por openpyxl (la primera hoja con
    datos, celdas separadas por coma, entrecomilladas si hace falta). El .xls
    viejo no: hay que guardarlo como .xlsx o .csv."""
    ext = (nombre or "").rsplit(".", 1)[-1].lower() if "." in (nombre or "") else ""
    if ext in ("xlsx", "xlsm"):
        try:
            import openpyxl  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ValueError("Para leer Excel hace falta openpyxl en el backend (pip install openpyxl)") from e
        try:
            wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        except Exception as e:
            raise ValueError(f"No se pudo abrir el Excel: {e}") from e
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        n_filas = 0
        for ws in wb.worksheets:
            for fila in ws.iter_rows(values_only=True):
                celdas = [_celda_a_texto(v) for v in fila]
                if not any(c.strip() for c in celdas):
                    continue
                w.writerow(celdas)
                n_filas += 1
            if n_filas:
                break
        wb.close()
        if not n_filas:
            raise ValueError("El Excel no tiene ninguna hoja con datos")
        return buf.getvalue()
    if ext == "xls":
        raise ValueError("El .xls antiguo no se puede leer: guárdalo como .xlsx o como .csv")
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return contenido.decode(enc)
        except UnicodeDecodeError:
            continue
    return contenido.decode("utf-8", errors="replace")
