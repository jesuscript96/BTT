# -*- coding: utf-8 -*-
"""Tamano por SETUP para el portfolio en crudo (20-sep-2026).

Jaume: «meter mas capital en los mejores setups». Un setup es un grupo de
trades de una estrategia que comparten algo observable ANTES de entrar (hoy,
el tramo de precio de entrada; el molde vale para gap, volumen u hora cuando
los trades guardados lo traigan). Para cada setup se mide en los trades
pasados su EV (retorno medio en la UNIDAD de la estrategia: sobre la posicion
si dimensiona por capital, en R si por stop; neto de comisiones, slippage y
locate esperado) y su dispersion, y el tamano relativo es la Kelly del setup:

    f_setup = EV / sigma^2

normalizada al setup «medio» de la estrategia (media ponderada por trades)
para que el nocional medio no cambie -el nivel de la cuenta lo pone el % del
paso 1-, encogida hacia x1 con la muestra (n / (n + shrink)) y acotada
[clip_lo, clip_hi]. Un setup sin muestra va a x1.

Estimacion WALK-FORWARD anual: los trades del ano Y se dimensionan con la
tabla estimada con TODO lo anterior al 1 de enero de Y (el primer ano va a
x1). Asi lo que se ve a partir del segundo ano es fuera de muestra, que es lo
unico que vale; una ventana movil corta solo mete ruido (medido el 20-sep).
`estimate = "all"` usa toda la historia para todo (in-sample, solo para ver
la tabla). La tabla «vigente» -para operar manana- se estima con todo.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

TRAMOS_PRECIO: list[list[Optional[float]]] = [[0, 0.5], [0.5, 1], [1, 2], [2, 3], [3, 5], [5, 10], [10, 20], [20, None]]

SETUP_DEFAULT: dict[str, Any] = {
    "enabled": False,
    "feature": "price",          # tramo de precio de entrada (unico por ahora)
    "ranges": None,              # [[lo, hi], ...]; None = TRAMOS_PRECIO
    "min_trades": 30,            # muestra minima para que un tramo tenga multiplicador propio
    "shrink": 50,                # encoge hacia x1: m = 1 + (m - 1) * n / (n + shrink)
    "clip_lo": 0.5,
    "clip_hi": 2.0,
    "estimate": "walk_forward",  # walk_forward (anual, con todo lo anterior) | all
    "pooled": False,             # True: una sola tabla con los trades de TODAS las estrategias (mas muestra por tramo)
}


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def setup_cfg(raw: Optional[dict]) -> Optional[dict]:
    """Normaliza el bloque `setup`; None si no viene o esta apagado."""
    if not raw or not raw.get("enabled"):
        return None
    cfg = dict(SETUP_DEFAULT)
    for k, v in raw.items():
        if k in cfg:
            cfg[k] = v
    cfg["enabled"] = True
    cfg["feature"] = "price"
    rangos = []
    for r in (cfg.get("ranges") or TRAMOS_PRECIO):
        try:
            lo = _f(r[0]); hi = None if (len(r) < 2 or r[1] in (None, "")) else _f(r[1])
        except (TypeError, IndexError):
            continue
        if hi is not None and hi <= lo:
            continue
        rangos.append([lo, hi])
    rangos.sort(key=lambda x: x[0])
    cfg["ranges"] = rangos or [[lo, hi] for lo, hi in TRAMOS_PRECIO]
    cfg["min_trades"] = max(5, int(_f(cfg["min_trades"], 30)))
    cfg["shrink"] = max(0.0, _f(cfg["shrink"], 50))
    cfg["clip_lo"] = max(0.0, _f(cfg["clip_lo"], 0.5))
    cfg["clip_hi"] = max(cfg["clip_lo"], _f(cfg["clip_hi"], 2.0))
    cfg["estimate"] = "all" if str(cfg.get("estimate") or "") == "all" else "walk_forward"
    cfg["pooled"] = bool(cfg.get("pooled"))
    return cfg


def tramo_de(valor: float, rangos: list[list[Optional[float]]]) -> int:
    """Indice del tramo que contiene el valor (lo <= v < hi); -1 si ninguno."""
    for k, (lo, hi) in enumerate(rangos):
        if valor >= lo and (hi is None or valor < hi):
            return k
    return -1


def estimar_tabla(muestras: list[tuple[str, float, float]], cfg: dict, hasta: Optional[str]) -> list[dict]:
    """La tabla de una estrategia con los trades anteriores a `hasta` (None =
    todos). `muestras`: (fecha, valor del feature, u). Devuelve un dict por
    tramo: n, ev, sd, f (EV/sigma^2), m_raw (f / f_medio), m (encogido y
    acotado, con la media ponderada por trades igual a 1)."""
    rangos = cfg["ranges"]
    por_tramo: list[list[float]] = [[] for _ in rangos]
    for d, v, u in muestras:
        if hasta is not None and d >= hasta:
            continue
        k = tramo_de(v, rangos)
        if k >= 0:
            por_tramo[k].append(u)
    filas = []
    for k, (lo, hi) in enumerate(rangos):
        xs = np.asarray(por_tramo[k], dtype=float)
        n = int(xs.size)
        if n >= 2:
            ev = float(xs.mean()); sd = float(xs.std())
            f = (ev / sd ** 2) if sd > 1e-12 else (0.0 if ev <= 0 else float("inf"))
        else:
            ev = sd = 0.0; f = 0.0
        filas.append({"lo": lo, "hi": hi, "n": n, "ev": ev, "sd": sd, "f": f, "m_raw": 1.0, "m": 1.0, "con_muestra": n >= cfg["min_trades"]})
    # Referencia: la f media ponderada por trades de los tramos con muestra.
    con = [r for r in filas if r["con_muestra"] and math.isfinite(r["f"])]
    peso = sum(r["n"] for r in con)
    f_ref = (sum(max(0.0, r["f"]) * r["n"] for r in con) / peso) if peso > 0 else 0.0
    if f_ref <= 0:
        return filas            # sin edge medible: todo a x1
    for r in filas:
        if not r["con_muestra"]:
            continue
        raw = (max(0.0, r["f"]) / f_ref) if math.isfinite(r["f"]) else cfg["clip_hi"]
        r["m_raw"] = raw
        n = r["n"]
        m = 1.0 + (raw - 1.0) * (n / (n + cfg["shrink"])) if cfg["shrink"] > 0 else raw
        r["m"] = float(min(cfg["clip_hi"], max(cfg["clip_lo"], m)))
    # Renormaliza para que la media ponderada por trades sea 1 (mismo nocional
    # medio que sin tabla) y vuelve a acotar.
    for _ in range(40):
        peso = sum(r["n"] for r in filas if r["con_muestra"])
        media = (sum(r["m"] * r["n"] for r in filas if r["con_muestra"]) / peso) if peso > 0 else 1.0
        if media <= 0 or abs(media - 1.0) < 1e-9:
            break
        # Si todo lo que queda esta pegado a un tope, no hay nada que mover.
        if all(r["m"] <= cfg["clip_lo"] + 1e-12 or r["m"] >= cfg["clip_hi"] - 1e-12 for r in filas if r["con_muestra"]):
            break
        for r in filas:
            if r["con_muestra"]:
                r["m"] = float(min(cfg["clip_hi"], max(cfg["clip_lo"], r["m"] / media)))
    return filas


class Multiplicadores:
    """Las tablas por estrategia y por fecha de estimacion, y el multiplicador
    de cada trade segun el modo de estimacion."""

    def __init__(self, cfg: dict, muestras: list[list[tuple[str, float, float]]], calendar: list[str]):
        self.cfg = cfg
        self.n = len(muestras)
        self.muestras = muestras
        self.calendar = calendar
        self.rangos = cfg["ranges"]
        # Fechas de estimacion: el 1 de enero de cada ano del calendario (walk-forward).
        anos = sorted({d[:4] for d in calendar})
        self.fechas = [f"{a}-01-01" for a in anos]
        self.tablas: dict[str, list[list[dict]]] = {}
        # Con `pooled`, una tabla comun estimada con los trades de todas.
        fuentes = ([sorted(sum(muestras, []))] * self.n) if cfg.get("pooled") else muestras
        if cfg["estimate"] == "walk_forward":
            for fch in self.fechas:
                self.tablas[fch] = [estimar_tabla(fuentes[i], cfg, fch) for i in range(self.n)]
        # La tabla con TODO: la vigente (para operar manana) y, en modo "all", la que se aplica.
        self.vigente: list[list[dict]] = [estimar_tabla(fuentes[i], cfg, None) for i in range(self.n)]
        self.aplicados: list[list[float]] = [[] for _ in range(self.n)]     # multiplicadores aplicados (para el informe)
        self.pesos: list[list[float]] = [[] for _ in range(self.n)]         # nocional de cada trade (para la media ponderada)

    def tabla_para(self, i: int, fecha: str) -> list[dict]:
        if self.cfg["estimate"] == "all":
            return self.vigente[i]
        t = self.tablas.get(f"{fecha[:4]}-01-01")
        return t[i] if t else self.vigente[i]

    def mult(self, i: int, valor: float, fecha: str) -> float:
        k = tramo_de(valor, self.rangos)
        if k < 0:
            return 1.0
        fila = self.tabla_para(i, fecha)[k]
        return float(fila["m"]) if fila["con_muestra"] else 1.0

    def registrar(self, i: int, m: float, nocional: float) -> None:
        self.aplicados[i].append(m)
        self.pesos[i].append(max(0.0, nocional))

    def informe(self, names: list[str], bases: list[str]) -> dict:
        def tabla_out(tablas: list[list[dict]]) -> list[dict]:
            return [{
                "name": names[i], "basis": bases[i],
                "ranges": [{"lo": r["lo"], "hi": r["hi"], "n": r["n"], "ev_pct": round(r["ev"] * 100.0, 4), "sd_pct": round(r["sd"] * 100.0, 4),
                            "f": (round(r["f"], 4) if math.isfinite(r["f"]) else None), "m": round(r["m"], 4), "con_muestra": bool(r["con_muestra"])}
                           for r in tablas[i]],
            } for i in range(self.n)]
        por_estrategia = []
        for i in range(self.n):
            a = np.asarray(self.aplicados[i], dtype=float); w = np.asarray(self.pesos[i], dtype=float)
            media = float((a * w).sum() / w.sum()) if w.sum() > 0 else (float(a.mean()) if a.size else 1.0)
            por_estrategia.append({"name": names[i], "trades": int(a.size), "distintos_de_1": int(np.count_nonzero(np.abs(a - 1.0) > 1e-9)) if a.size else 0,
                                   "mult_medio": round(media, 4), "mult_min": round(float(a.min()), 4) if a.size else 1.0, "mult_max": round(float(a.max()), 4) if a.size else 1.0})
        return {
            "cfg": self.cfg,
            "vigente": tabla_out(self.vigente),
            "por_ano": [{"desde": fch, "tablas": tabla_out(self.tablas[fch])} for fch in self.fechas if fch in self.tablas],
            "por_estrategia": por_estrategia,
        }


# ── Reparto entre estrategias: Kelly conjunta ─────────────────────────────

def kelly_conjunta(X: np.ndarray, total: float, cap_i: Optional[list[float]] = None) -> np.ndarray:
    """La f (una por estrategia, en % por trade) que maximiza la media de
    log(1 + X f) con f >= 0, sum f <= total y f_i <= cap_i. X: dias x n,
    retorno diario de cada estrategia POR CADA 1 % por trade. Usa scipy si
    esta; si no, una busqueda proyectada simple."""
    X = np.asarray(X, dtype=float)
    n = X.shape[1]
    ub = [float(cap_i[i]) if (cap_i and cap_i[i] and cap_i[i] > 0) else float(total) for i in range(n)]

    def growth(f: np.ndarray) -> float:
        r = X @ f
        if np.any(r <= -1.0):
            return -1e9
        return float(np.mean(np.log1p(r)))

    try:
        from scipy.optimize import minimize
        best = None
        for x0 in (np.full(n, total / n), np.array([min(ub[i], total * (0.6 if i == 0 else 0.4 / max(1, n - 1))) for i in range(n)])):
            x0 = np.minimum(x0, ub)
            if x0.sum() > total:
                x0 = x0 * total / x0.sum()
            res = minimize(lambda f: -growth(f), x0, bounds=[(0.0, ub[i]) for i in range(n)],
                           constraints=[{"type": "ineq", "fun": lambda f: total - f.sum()}], method="SLSQP",
                           options={"maxiter": 300, "ftol": 1e-12})
            if best is None or res.fun < best.fun:
                best = res
        f = np.clip(best.x, 0.0, ub)
        if f.sum() > total + 1e-9:
            f *= total / f.sum()
        return f
    except ImportError:  # pragma: no cover
        f = np.full(n, total / n)
        step = total / 20.0
        for _ in range(200):
            mejor = growth(f); mejorado = False
            for i in range(n):
                for s in (step, -step):
                    g = f.copy(); g[i] = min(ub[i], max(0.0, g[i] + s))
                    if g.sum() > total:
                        g *= total / g.sum()
                    v = growth(g)
                    if v > mejor + 1e-12:
                        f, mejor, mejorado = g, v, True
            if not mejorado:
                step /= 2.0
                if step < total / 2000.0:
                    break
        return f


def crecimiento(X: np.ndarray, f: np.ndarray) -> tuple[float, float]:
    """(multiplo final, drawdown maximo en fraccion) de componer X f dia a dia."""
    r = np.asarray(X, dtype=float) @ np.asarray(f, dtype=float)
    e = 1.0; peak = 1.0; mdd = 0.0
    for x in r:
        e *= max(0.0, 1.0 + x)
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1.0 if peak > 0 else 0.0)
        if e <= 0:
            break
    return float(e), float(mdd)
