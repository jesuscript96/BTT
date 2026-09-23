# -*- coding: utf-8 -*-
"""Escalado AUTOMATICO del portfolio en crudo (20-sep-2026, tarde).

Dos reglas medidas en las PM de Jaume antes de construirlas (ver MEMORIA):

  ROTACION POR RANKING: cada cierto tiempo (semana, mes o cada N sesiones)
  se ordenan las estrategias por lo que han rendido POR UNIDAD DE TAMANO en
  la ventana anterior (retorno del portfolio que aporto cada una dividido por
  el % por trade que llevaba: comparable aunque una vaya por stop y otra por
  capital) y se les da el % por trade del PATRON segun su puesto: el primero
  del patron a la mejor, el segundo a la siguiente... Con un SUELO por
  estrategia (nunca menos de X %; lo que falte se quita de las de arriba en
  proporcion, para que la suma del patron no cambie). Solo mira el pasado:
  el primer periodo, sin historia, va con los % del paso 1. Funciona porque
  la CALIDAD de una estrategia persiste (2A fue «la peor» el 75 % de los dias)
  aunque el rendimiento del portfolio de un mes no diga nada del siguiente.

  FRENO POR CAIDA: si la cuenta esta mas de X % por debajo de su maximo al
  abrir el dia, todos los tamanos se multiplican por m (0,5 = mitad) hasta que
  la caida se recupere por encima de Y %. No predice nada: limita la
  profundidad de una caida ya empezada a cambio de recuperar mas despacio. No
  evita un precipicio de UN dia (se decide con el cierre anterior).

Los dos devuelven `hoy`: lo que toca aplicar el siguiente periodo.
"""
from __future__ import annotations

import math
from datetime import date as _date
from typing import Any, Optional

import numpy as np

ROTATION_DEFAULT: dict[str, Any] = {
    "enabled": False,
    "lookback_days": 126,    # sesiones de la ventana de ranking
    "rebalance": "M",        # W (semana) | M (mes) | N (cada `every_days` sesiones)
    "every_days": 20,
    "pattern": None,         # % por trade por puesto (mejor primero); None = los % del paso 1 ordenados
    "min_pct": 1.0,          # suelo por estrategia (% por trade); 0 = sin suelo
    "metric": "return",      # return (retorno acumulado por unidad) | ev_trade (EV por trade) | per_hour (por hora en mercado) | sharpe (media/desviacion diaria)
}

BRAKE_DEFAULT: dict[str, Any] = {
    "enabled": False,
    "dd_pct": 10.0,          # se frena cuando la caida desde el maximo pasa de esto
    "mult": 0.5,             # multiplicador de todos los tamanos mientras dura el freno
    "exit_dd_pct": 5.0,      # se suelta cuando la caida vuelve por encima de esto
}


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def rotation_cfg(raw: Optional[dict], n: int) -> Optional[dict]:
    if not raw or not raw.get("enabled"):
        return None
    cfg = dict(ROTATION_DEFAULT)
    for k, v in raw.items():
        if k in cfg:
            cfg[k] = v
    cfg["enabled"] = True
    cfg["lookback_days"] = max(5, int(_f(cfg["lookback_days"], 126)))
    rb = str(cfg.get("rebalance") or "M").upper()[:1]
    cfg["rebalance"] = rb if rb in ("W", "M", "N") else "M"
    cfg["every_days"] = max(1, int(_f(cfg["every_days"], 20)))
    pat = cfg.get("pattern")
    if isinstance(pat, (list, tuple)) and pat:
        cfg["pattern"] = [max(0.0, _f(x)) for x in pat]
    else:
        cfg["pattern"] = None
    cfg["min_pct"] = max(0.0, _f(cfg["min_pct"], 1.0))
    _m = str(cfg.get("metric") or "")
    cfg["metric"] = _m if _m in ("sharpe", "ev_trade", "per_hour") else "return"
    return cfg


def brake_cfg(raw: Optional[dict]) -> Optional[dict]:
    if not raw or not raw.get("enabled"):
        return None
    cfg = dict(BRAKE_DEFAULT)
    for k, v in raw.items():
        if k in cfg:
            cfg[k] = v
    cfg["enabled"] = True
    cfg["dd_pct"] = max(0.1, _f(cfg["dd_pct"], 10.0))
    cfg["mult"] = min(1.0, max(0.0, _f(cfg["mult"], 0.5)))
    cfg["exit_dd_pct"] = min(cfg["dd_pct"], max(0.0, _f(cfg["exit_dd_pct"], 5.0)))
    return cfg


def aplicar_suelo(sizes: list[float], min_pct: float) -> list[float]:
    """Nadie por debajo del suelo; lo que falte se quita de las que estan por
    encima, en proporcion, para conservar la suma. Si no se puede (todas al
    suelo no caben en la suma), se devuelve el suelo para todas."""
    s = [max(0.0, float(x)) for x in sizes]
    if min_pct <= 0 or not s:
        return s
    total = sum(s)
    n = len(s)
    if min_pct * n >= total:
        return [min_pct] * n
    for _ in range(n + 1):
        bajos = [i for i, x in enumerate(s) if x < min_pct - 1e-12]
        if not bajos:
            break
        falta = sum(min_pct - s[i] for i in bajos)
        for i in bajos:
            s[i] = min_pct
        altos = [i for i, x in enumerate(s) if x > min_pct + 1e-12]
        exceso = sum(s[i] - min_pct for i in altos)
        if exceso <= 0:
            break
        for i in altos:
            s[i] -= falta * (s[i] - min_pct) / exceso
    return s


class Rotacion:
    """Reparto rotatorio por ranking. `registrar` cada dia con lo que aporto
    cada estrategia por unidad; `sizes_para(d)` al abrir el dia."""

    def __init__(self, cfg: dict, base_sizes: list[float], names: list[str]):
        self.cfg = cfg
        self.n = len(base_sizes)
        self.base = [float(x) for x in base_sizes]
        self.names = names
        pat = cfg["pattern"] or sorted(self.base, reverse=True)
        pat = list(pat)[: self.n] + [pat[-1] if pat else 0.0] * max(0, self.n - len(pat))
        self.pattern = [max(0.0, float(x)) for x in pat]
        self.total = float(sum(self.pattern))
        self.r_unit: list[list[float]] = [[] for _ in range(self.n)]   # retorno por 1 % por dia, por estrategia
        self.n_tr: list[list[int]] = [[] for _ in range(self.n)]         # trades por dia, por estrategia
        self.horas: list[list[float]] = [[] for _ in range(self.n)]      # horas en mercado por dia, por estrategia
        self.dias: list[str] = []
        self.sizes = list(self.base)
        self.ranks: Optional[list[int]] = None
        self.periods: list[dict] = []
        self.ultimo_rebalanceo: Optional[str] = None
        self.sesiones_desde = 0
        self.dias_con_rotacion = 0

    # -- cuando toca --------------------------------------------------------
    def _toca(self, d: str) -> bool:
        if self.ultimo_rebalanceo is None:
            return True
        rb = self.cfg["rebalance"]
        if rb == "M":
            return d[:7] != self.ultimo_rebalanceo[:7]
        if rb == "W":
            a, b = _date.fromisoformat(d), _date.fromisoformat(self.ultimo_rebalanceo)
            return a.isocalendar()[:2] != b.isocalendar()[:2]
        return self.sesiones_desde >= self.cfg["every_days"]

    def _puntuacion(self, i: int) -> Optional[float]:
        lb = self.cfg["lookback_days"]
        serie = np.asarray(self.r_unit[i][-lb:], dtype=float)
        if serie.size < lb:
            return None
        if self.cfg["metric"] == "sharpe":
            sd = float(serie.std())
            return float(serie.mean() / sd) if sd > 1e-12 else 0.0
        if self.cfg["metric"] == "ev_trade":
            n_tr = int(sum(self.n_tr[i][-lb:]))
            return float(serie.sum() / n_tr) if n_tr > 0 else 0.0
        if self.cfg["metric"] == "per_hour":
            # Lo ganado por unidad y por HORA con posicion abierta: premia a la
            # que entra y sale rapido frente a la que ocupa la sesion entera.
            h = float(sum(self.horas[i][-lb:]))
            return float(serie.sum() / h) if h > 1e-9 else 0.0
        return float(serie.sum())

    def _asignar(self) -> tuple[list[float], Optional[list[int]], str]:
        punt = [self._puntuacion(i) for i in range(self.n)]
        if any(p is None for p in punt):
            return list(self.base), None, "sin historia suficiente: los % del paso 1"
        orden = sorted(range(self.n), key=lambda i: -punt[i])       # mejor primero
        sizes = [0.0] * self.n
        for puesto, i in enumerate(orden):
            sizes[i] = self.pattern[puesto]
        sizes = aplicar_suelo(sizes, self.cfg["min_pct"])
        ranks = [0] * self.n
        for puesto, i in enumerate(orden):
            ranks[i] = puesto + 1
        return sizes, ranks, ""

    def sizes_para(self, d: str) -> list[float]:
        if self._toca(d):
            sizes, ranks, nota = self._asignar()
            self.sizes, self.ranks = sizes, ranks
            self.periods.append({"from": d, "sizes": [round(x, 4) for x in sizes], "ranks": ranks, "nota": nota,
                                 "scores": [(round(self._puntuacion(i), 6) if self._puntuacion(i) is not None else None) for i in range(self.n)]})
            self.ultimo_rebalanceo = d
            self.sesiones_desde = 0
        self.sesiones_desde += 1
        if self.ranks is not None:
            self.dias_con_rotacion += 1
        return self.sizes

    def registrar(self, d: str, r_unit: list[float], n_trades: Optional[list[int]] = None, horas: Optional[list[float]] = None) -> None:
        """`r_unit[i]`: lo que habria aportado la estrategia i ese dia por cada
        1 % por trade (la sombra: suma de la R neta por accion de sus trades en
        su unidad x 0,01). No depende del tamano que llevara ni de si iba a 0:
        una estrategia apagada puede volver a subir en el ranking."""
        self.dias.append(d)
        for i in range(self.n):
            self.r_unit[i].append(float(r_unit[i]))
            self.n_tr[i].append(int(n_trades[i]) if n_trades is not None else 0)
            self.horas[i].append(float(horas[i]) if horas is not None else 0.0)

    def hoy(self) -> dict:
        """Lo que toca el siguiente periodo, con TODO lo registrado."""
        sizes, ranks, nota = self._asignar()
        return {
            "sizes": [round(x, 4) for x in sizes], "ranks": ranks, "nota": nota,
            "scores": [(round(self._puntuacion(i), 6) if self._puntuacion(i) is not None else None) for i in range(self.n)],
            "weights": [round(x / sum(sizes), 4) if sum(sizes) > 0 else 0.0 for x in sizes],
            "total_pct": round(float(sum(sizes)), 4),
            "desde": (self.dias[-1] if self.dias else None),
        }

    def puntuaciones_diarias(self) -> list[list[Optional[float]]]:
        """La puntuacion de cada estrategia a CADA dia registrado con la misma
        ventana y metrica del ranking (None hasta tener ventana completa): el
        «oscilador» de la UI, para ver quien va mejor en cada momento."""
        lb = self.cfg["lookback_days"]
        out: list[list[Optional[float]]] = []
        for i in range(self.n):
            r = np.asarray(self.r_unit[i], dtype=float)
            ntr = np.asarray(self.n_tr[i], dtype=float)
            hrs = np.asarray(self.horas[i], dtype=float)
            serie: list[Optional[float]] = []
            cr = np.concatenate([[0.0], np.cumsum(r)])
            cn = np.concatenate([[0.0], np.cumsum(ntr)])
            ch = np.concatenate([[0.0], np.cumsum(hrs)])
            for t in range(len(r)):
                if t + 1 < lb:
                    serie.append(None)
                    continue
                a, b = t + 1 - lb, t + 1
                suma = float(cr[b] - cr[a])
                if self.cfg["metric"] == "sharpe":
                    w = r[a:b]
                    sd = float(w.std())
                    serie.append(round(float(w.mean() / sd), 6) if sd > 1e-12 else 0.0)
                elif self.cfg["metric"] == "ev_trade":
                    k = float(cn[b] - cn[a])
                    serie.append(round(suma / k, 6) if k > 0 else 0.0)
                elif self.cfg["metric"] == "per_hour":
                    h = float(ch[b] - ch[a])
                    serie.append(round(suma / h, 6) if h > 1e-9 else 0.0)
                else:
                    serie.append(round(suma, 6))
            out.append(serie)
        return out

    def informe(self) -> dict:
        medias = [float(np.mean([p["sizes"][i] for p in self.periods])) if self.periods else self.base[i] for i in range(self.n)]
        cambios = sum(1 for k in range(1, len(self.periods))
                      if self.periods[k]["ranks"] is not None and self.periods[k - 1]["ranks"] is not None
                      and self.periods[k]["ranks"] != self.periods[k - 1]["ranks"])
        return {
            "cfg": dict(self.cfg, pattern=self.pattern), "periods": self.periods, "hoy": self.hoy(),
            "size_medio": [round(x, 4) for x in medias], "rebalanceos": len(self.periods), "cambios_de_ranking": int(cambios),
            "dias_con_rotacion": int(self.dias_con_rotacion),
            "scores_daily": {"dates": list(self.dias), "por_estrategia": self.puntuaciones_diarias()},
        }


class Freno:
    """Freno por caida de la cuenta. `mult_para(equity_open)` al abrir el dia,
    `registrar(equity)` al cerrar."""

    def __init__(self, cfg: dict, capital: float):
        self.cfg = cfg
        self.peak = float(capital)
        self.frenado = False
        self.dias_frenado = 0
        self.episodios = 0
        self.eventos: list[dict] = []

    def mult_para(self, d: str, equity_open: float) -> float:
        dd = (equity_open / self.peak - 1.0) if self.peak > 0 else 0.0
        if not self.frenado and dd < -self.cfg["dd_pct"] / 100.0:
            self.frenado = True
            self.episodios += 1
            self.eventos.append({"date": d, "que": "freno", "dd_pct": round(dd * 100, 2)})
        elif self.frenado and dd > -self.cfg["exit_dd_pct"] / 100.0:
            self.frenado = False
            self.eventos.append({"date": d, "que": "suelta", "dd_pct": round(dd * 100, 2)})
        if self.frenado:
            self.dias_frenado += 1
            return float(self.cfg["mult"])
        return 1.0

    def registrar(self, equity: float) -> None:
        self.peak = max(self.peak, float(equity))

    def hoy(self, equity: float) -> dict:
        dd = (equity / self.peak - 1.0) * 100 if self.peak > 0 else 0.0
        return {"frenado": bool(self.frenado), "dd_pct": round(dd, 2), "mult": (float(self.cfg["mult"]) if self.frenado else 1.0), "peak": round(self.peak, 2)}

    def informe(self, equity: float) -> dict:
        return {"cfg": self.cfg, "dias_frenado": self.dias_frenado, "episodios": self.episodios, "eventos": self.eventos[-40:], "hoy": self.hoy(equity)}


def freno_sobre_curva(cfg: dict, equity: list[float], capital: float) -> dict:
    """El estado del freno al final de una curva cualquiera (la cuenta REAL del
    CSV): se recorre entera con la misma regla."""
    fr = Freno(cfg, capital)
    prev = float(capital)
    for e in equity:
        fr.mult_para("", prev)
        fr.registrar(e)
        prev = float(e)
    fr.mult_para("", prev)   # el estado con el que se abre manana
    return fr.informe(prev)
