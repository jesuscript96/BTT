"""Criterios de MARGEN y BUYING POWER del broker (Jaume, 19-sep-2026).

Hasta hoy el backtest suponia que cualquier tamano cabe en la cuenta. Un broker
de acceso directo no: cada posicion abierta consume margen segun su precio y su
lado, y la orden que no cabe no se ejecuta. En cortos de small caps la regla
que manda no es el «4:1» sino la exigencia POR ACCION de las acciones baratas
(2,50 $ por accion por debajo de 2,50 $: el 500 % del nocional a 0,50 $).

Reglas publicadas por SageTrader (FAQ, consultada el 19-sep-2026):
  - largos: inicial 25 % del valor (4:1 intradia), mantenimiento 30 %;
  - cortos: inicial 30 % del valor; mantenimiento por precio:
      >= 5 $         -> el mayor de 30 % del valor o 5 $ por accion
      2,50 $ - 5 $   -> 100 % del valor
      < 2,50 $       -> 2,50 $ por accion
  - overnight 2:1 (aqui no aplica: todo es intradia);
  - regla de casa: liquidacion al perder el 75 % del equity del dia (eso es el
    cortacircuitos diario que ya existe, con ese %).
Al abrir se exige el MAYOR de la inicial y el mantenimiento por precio: es lo
que hace DAS al calcular el buying power de la orden.

COMO SE APLICA (semantica cerrada con Jaume): en cada dia, todas las entradas
de todos los tickers se recorren en ORDEN CRONOLOGICO; el margen usado sube
con cada entrada/anadido y baja con cada salida/reduccion; la entrada (o el
anadido) que en ese instante no cabe en el equity del dia NO se ejecuta, y ese
ticker no toma riesgo nuevo el resto del dia (misma palanca que el
cortacircuitos: `no_new_risk_after`). Las posiciones ya abiertas siguen hasta
su salida. Corta lo que entra tarde, que es lo que pidio.

Apagado (lo normal), nada de esto se mira.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

BROKERS: dict[str, dict[str, Any]] = {
    "sagetrader": {
        "nombre": "SageTrader",
        "largo_pct": 25.0,          # inicial largos, % del valor
        "corto_pct": 30.0,          # inicial cortos, % del valor
        "corto_alto_min_usd": 5.0,  # cortos >= umbral_alto: max(corto_pct, 5 $/accion)
        "umbral_alto": 5.0,
        "umbral_bajo": 2.5,         # entre bajo y alto: 100 % del valor
        "corto_bajo_usd": 2.5,      # por debajo de umbral_bajo: 2,50 $/accion
        "resumen": ("Largos 25 % del valor (4:1). Cortos: ≥ 5 $ → el mayor de 30 % o 5 $/acción; "
                    "2,50–5 $ → 100 % del valor; < 2,50 $ → 2,50 $/acción. Todo intradía."),
    },
    # 20-sep, Jaume: «en real pocas veces me deja tener tantas posiciones
    # abiertas con tanto capital expuesto». Los gappers que se venden en
    # corto suelen ir en lista especial (hard to borrow): el broker exige el
    # 100 % del valor aunque coticen a mas de 5 $. Esta variante lo aplica a
    # TODOS los cortos (y 2,50 $/accion por debajo de 2,50 $); largos igual.
    "sagetrader_estricto": {
        "nombre": "SageTrader estricto (cortos 100 %)",
        "largo_pct": 25.0,
        "corto_pct": 100.0,
        "corto_alto_min_usd": 0.0,
        "umbral_alto": 5.0,
        "umbral_bajo": 2.5,
        "corto_bajo_usd": 2.5,
        "resumen": ("Largos 25 % del valor (4:1). Cortos: ≥ 2,50 $ → el 100 % del valor (lista especial / HTB); "
                    "< 2,50 $ → 2,50 $/acción. Todo intradía."),
    },
}


def broker_valido(nombre: str) -> str:
    n = str(nombre or "sagetrader").strip().lower()
    return n if n in BROKERS else "sagetrader"


def requisito_por_accion(precio: float, es_corto: bool, broker: str = "sagetrader") -> float:
    """Dolares de margen que exige UNA accion a ese precio, para abrirla."""
    b = BROKERS[broker_valido(broker)]
    p = float(precio or 0.0)
    if p <= 0:
        return 0.0
    if not es_corto:
        return p * b["largo_pct"] / 100.0
    if p < b["umbral_bajo"]:
        return max(p * b["corto_pct"] / 100.0, b["corto_bajo_usd"])
    if p < b["umbral_alto"]:
        return p                       # 100 % del valor
    return max(p * b["corto_pct"] / 100.0, b["corto_alto_min_usd"])


def requisito(precio: float, acciones: float, es_corto: bool, broker: str = "sagetrader") -> float:
    return requisito_por_accion(precio, es_corto, broker) * max(0.0, float(acciones or 0.0))


@dataclass
class ConfigMargen:
    broker: str = "sagetrader"
    # % del equity del dia que cuenta como margen disponible (100 = todo el
    # equity; menos, si se quiere dejar colchon).
    capacidad_pct: float = 100.0

    def __post_init__(self):
        self.broker = broker_valido(self.broker)
        self.capacidad_pct = float(self.capacidad_pct)
        if not (0 < self.capacidad_pct <= 1000):
            raise ValueError("capacidad_pct tiene que estar entre 0 y 1000")

    def resumen(self) -> dict:
        b = BROKERS[self.broker]
        return {"broker": self.broker, "broker_nombre": b["nombre"], "capacidad_pct": self.capacidad_pct, "reglas": b["resumen"]}


# ── Eventos de margen de un ticker-dia ya simulado ────────────────────────

def _posiciones(trades: list[dict]) -> list[list[dict]]:
    """Agrupa los legs consecutivos con el mismo entry_idx (una posicion)."""
    grupos: list[list[dict]] = []
    actual: list[dict] = []
    idx_actual = None
    for t in trades:
        if actual and t.get("entry_idx") == idx_actual:
            actual.append(t)
        else:
            if actual:
                grupos.append(actual)
            actual = [t]
            idx_actual = t.get("entry_idx")
    if actual:
        grupos.append(actual)
    return grupos


def eventos_ticker_dia(trades: list[dict], timestamps, broker: str, look_ahead: bool = True) -> list[tuple]:
    """(t_s, orden, delta_margen, es_entrada, precio, acciones, t_decision) de
    cada ejecucion de un ticker-dia: entradas y anadidos suman margen;
    parciales, reducciones, SL de lote y cierres lo liberan. `orden` = 0 para
    liberar y 1 para tomar: a la misma hora, primero se libera.

    `t_decision` es la hora de la VELA QUE DECIDE la entrada/anadido (la senal
    va en `i` y el fill en `i+1` con look_ahead_prevention): es el instante que
    hay que pasarle al motor como `no_new_risk_after` para que esa orden no
    llegue a existir, porque el motor compara la vela de la decision, no la del
    fill. Para lo que libera es la misma hora del evento."""
    out: list[tuple] = []
    if timestamps is None or not trades:
        return out
    n_ts = len(timestamps)

    def _t(k: int) -> int:
        return int(timestamps[max(0, min(int(k), n_ts - 1))] // 1_000_000_000)

    def _t_dec(k_fill: int) -> int:
        return _t(k_fill - 1) if (look_ahead and k_fill > 0) else _t(k_fill)

    for legs in _posiciones(trades):
        first = legs[0]
        es_corto = str(first.get("direction") or "").lower().startswith("s")
        entry_idx = int(first.get("entry_idx") or 0)
        t_entry = _t(entry_idx)
        precio_entrada = float(first.get("trade_entry_price") or first.get("entry_price") or 0.0)
        size_legs = sum(float(l.get("size") or 0.0) for l in legs)
        # Anadidos: los de la piramide se deciden en `i` y ejecutan en `i+1`
        # (como la entrada); los de la escalera se deciden y ejecutan en la
        # misma vela. Se guarda con cada uno la hora de su decision.
        adds = [(pe, True) for l in legs for pe in (l.get("pyr_executions") or []) if pe.get("kind") == "add"]
        adds += [(pe, False) for l in legs for pe in (l.get("escalera_executions") or []) if pe.get("kind") == "add"]
        libera = [pe for l in legs for pe in ((l.get("pyr_executions") or []) + (l.get("escalera_executions") or []))
                  if pe.get("kind") in ("reduce", "lot_stop")]
        size_adds = sum(float(pe.get("size") or 0.0) for pe, _ in adds)
        size_entry = size_legs - size_adds
        if size_entry <= 0:
            size_entry = float(first.get("size") or 0.0)
        req_ps = requisito_por_accion(precio_entrada, es_corto, broker)
        out.append((t_entry, 1, req_ps * size_entry, True, precio_entrada, size_entry, _t_dec(entry_idx)))
        for pe, es_piramide in adds:
            t = int(pe.get("time_epoch") or t_entry)
            px = float(pe.get("price") or precio_entrada)
            sz = float(pe.get("size") or 0.0)
            if pe.get("idx") is not None:
                t_dec = _t_dec(int(pe["idx"])) if es_piramide else _t(int(pe["idx"]))
            else:
                t_dec = t
            out.append((t, 1, requisito_por_accion(px, es_corto, broker) * sz, True, px, sz, t_dec))
        # Lo que se libera: al precio medio de exigencia de la posicion (los
        # lotes no se rastrean uno a uno; la posicion es una).
        for pe in libera:
            t = int(pe.get("time_epoch") or t_entry)
            sz = float(pe.get("size") or 0.0)
            out.append((t, 0, -req_ps * sz, False, precio_entrada, sz, t))
        for l in legs:
            exit_idx = int(l.get("exit_idx") or entry_idx)
            t_exit = _t(exit_idx)
            sz = float(l.get("size") or 0.0)
            out.append((t_exit, 0, -req_ps * sz, False, precio_entrada, sz, t_exit))
    return out


def primera_violacion(pend: list[dict], capacidad: float, broker: str) -> Optional[dict]:
    """Recorre el dia entero en orden cronologico y devuelve la primera
    entrada/anadido que no cabe: {"i": indice en pend, "t": segundos, ...}.
    None si cabe todo."""
    eventos: list[tuple] = []
    for i, e in enumerate(pend):
        ts = e["sim_kwargs"].get("timestamps")
        la = bool(e["sim_kwargs"].get("look_ahead_prevention", True))
        for ev in eventos_ticker_dia(e["sim_result"].get("trades") or [], ts, broker, look_ahead=la):
            eventos.append((ev[0], ev[1], i) + ev[2:])
    eventos.sort(key=lambda x: (x[0], x[1]))
    usado = 0.0
    pico = 0.0
    for t, orden, i, delta, es_entrada, precio, acciones, t_dec in eventos:
        if es_entrada:
            if usado + delta > capacidad + 1e-6:
                return {"i": i, "t": t, "t_decision": t_dec, "requisito": delta, "usado": usado,
                        "capacidad": capacidad, "precio": precio, "acciones": acciones, "pico": pico}
            usado += delta
            pico = max(pico, usado)
        else:
            usado = max(0.0, usado + delta)
    return {"i": None, "pico": pico}


def aplicar_margen_dia(pend: list[dict], cash_dia: float, cfg: ConfigMargen,
                       simulate_fn: Callable[..., dict], fecha: str) -> dict:
    """Aplica el margen al dia bufferizado (lista de ticker-dias con
    sim_kwargs/sim_result): cada vez que una entrada no cabe, ese ticker se
    re-simula sin riesgo nuevo desde ese instante y se vuelve a recorrer el
    dia. Devuelve el registro del dia."""
    capacidad = float(cash_dia) * cfg.capacidad_pct / 100.0
    bloqueos: list[dict] = []
    pico = 0.0
    for _ in range(4 * max(1, len(pend)) + 4):
        v = primera_violacion(pend, capacidad, cfg.broker)
        if v is None or v.get("i") is None:
            pico = float((v or {}).get("pico") or 0.0)
            break
        e = pend[v["i"]]
        # El corte va en la vela que DECIDE la orden (la senal), no en la del
        # fill: el motor compara `timestamps[i] >= no_new_risk_after` en la
        # vela de la decision. Con la hora del fill la orden seguiria entrando.
        t_ns = int(v.get("t_decision", v["t"])) * 1_000_000_000
        kw = e["sim_kwargs"]
        previo = int(kw.get("no_new_risk_after") or 0)
        # Si ya estaba bloqueado desde antes y aun asi viola (un anadido de una
        # posicion abierta antes del bloqueo no puede pasar: el motor lo corta),
        # se sale para no dar vueltas.
        if previo and previo <= t_ns:
            bloqueos.append({"ticker": e["ticker"], "t": int(v["t"]), "requisito": round(v["requisito"], 2),
                             "usado": round(v["usado"], 2), "capacidad": round(capacidad, 2),
                             "precio": round(v["precio"], 4), "acciones": round(v["acciones"], 2), "nota": "ya bloqueado"})
            break
        kw["no_new_risk_after"] = t_ns
        kw.setdefault("force_close_at", 0)
        try:
            e["sim_result"] = simulate_fn(**kw)
        except Exception as exc:  # noqa: BLE001
            bloqueos.append({"ticker": e["ticker"], "t": int(v["t"]), "nota": f"re-sim fallo: {exc}"})
            break
        bloqueos.append({"ticker": e["ticker"], "t": int(v["t"]), "requisito": round(v["requisito"], 2),
                         "usado": round(v["usado"], 2), "capacidad": round(capacidad, 2),
                         "precio": round(v["precio"], 4), "acciones": round(v["acciones"], 2)})
    return {"date": fecha, "capacidad": round(capacidad, 2), "pico": round(pico, 2),
            "pico_pct": round(100.0 * pico / capacidad, 2) if capacidad > 0 else 0.0,
            "bloqueos": bloqueos}


@dataclass
class RegistroMargen:
    """Acumula los dias para el resumen de la corrida."""
    cfg: ConfigMargen
    dias: list[dict] = field(default_factory=list)

    def resumen(self) -> dict:
        n_bloq = sum(len(d["bloqueos"]) for d in self.dias)
        dias_bloq = sum(1 for d in self.dias if d["bloqueos"])
        picos = [d["pico_pct"] for d in self.dias if d.get("capacidad")]
        return {
            "enabled": True,
            **self.cfg.resumen(),
            "dias": len(self.dias),
            "dias_con_bloqueo": dias_bloq,
            "bloqueos": n_bloq,
            "pico_medio_pct": round(sum(picos) / len(picos), 2) if picos else 0.0,
            "pico_max_pct": round(max(picos), 2) if picos else 0.0,
            # Los dias con bloqueo, para la tabla (los sin bloqueo no aportan).
            "log": [d for d in self.dias if d["bloqueos"]][-400:],
        }
