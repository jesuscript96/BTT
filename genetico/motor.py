"""El algoritmo genetico: poblacion, seleccion, cruce, mutacion, elite.

Todo el estado vive en el directorio de la corrida y se vuelca tras CADA
evaluacion, asi que la pagina puede leerlo en vivo y una corrida cortada se
reanuda donde iba:

    estado.json     progreso, mejor actual, tiempos (lo que pinta la pagina)
    mejores.json    top N de TODO lo evaluado, con receta y definicion del motor
    poblacion.json  poblacion viva + cache de evaluados (para reanudar)
    parar.txt       si existe, la corrida termina limpia tras la evaluacion en curso
"""
from __future__ import annotations

import copy
import json
import os
import random
import time

from genetico import catalogo as C
from genetico import cromosoma, evaluador

TOP_N = 20


# ── Operadores ──────────────────────────────────────────────────────────────

def _vecino(valor, rejilla, rng: random.Random):
    """Un paso en la rejilla (70%) o cualquier valor de ella (30%)."""
    rejilla = list(rejilla)
    if valor in rejilla and len(rejilla) > 1 and rng.random() < 0.7:
        i = rejilla.index(valor)
        j = max(0, min(len(rejilla) - 1, i + rng.choice((-1, 1))))
        return rejilla[j]
    return rng.choice(rejilla)


def _mutar_condicion(c: dict, config: dict, rng: random.Random) -> dict:
    c = copy.deepcopy(c)
    ind = C.CATALOGO[c["ind"]]
    que = rng.choice(["objetivo", "comparador", "param", "param"] if ind.params else ["objetivo", "comparador"])
    if que == "comparador":
        c["comp"] = rng.choice(ind.comparadores)
    elif que == "param":
        k = rng.choice(list(ind.params))
        c["params"][k] = _vecino(c["params"].get(k), ind.params[k], rng)
    else:
        obj = c["objetivo"]
        if isinstance(obj, dict):
            c["objetivo"] = {"ind": rng.choice(ind.objetivos), "params": {}}
        else:
            c["objetivo"] = _vecino(obj, ind.valores, rng)
    return c


def _mutar_stop(s: dict, config: dict, rng: random.Random) -> dict:
    sesgo = config.get("sesgo", "short")
    modos = list(config.get("stops", ["pct"]))
    if len(modos) > 1 and rng.random() < 0.2:
        return cromosoma._stop_aleatorio(rng, [m for m in modos if m != s["modo"]], sesgo)
    s = copy.deepcopy(s)
    if s["modo"] == "pct":
        s["valor"] = _vecino(s["valor"], C.STOP_PCT, rng)
    elif rng.random() < 0.5:
        s["offset_pct"] = _vecino(s["offset_pct"], C.STOP_OFFSET_PCT, rng)
    else:
        s["nivel"], s["operador"] = rng.choice(C.STOP_NIVELES[sesgo])
    return s


def _mutar_tp(t: dict, config: dict, rng: random.Random) -> dict:
    modos = list(config.get("tps", ["pct"]))
    if len(modos) > 1 and rng.random() < 0.2:
        return cromosoma._tp_aleatorio(rng, [m for m in modos if m != t["modo"]])
    t = copy.deepcopy(t)
    rejilla = {"pct": C.TP_PCT, "hora": C.TP_HORA, "tiempo": C.TP_TIEMPO_MIN}[t["modo"]]
    t["valor"] = _vecino(t["valor"], rejilla, rng)
    return t


def mutar(ind: dict, config: dict, rng: random.Random) -> dict:
    """Cada gen muta con probabilidad p_mut; al menos uno muta siempre."""
    p = float(config.get("p_mutacion", 0.25))
    nuevo = copy.deepcopy(ind)
    tocado = False
    for i, c in enumerate(nuevo["condiciones"]):
        if rng.random() < p:
            if rng.random() < 0.25:  # cambiar el indicador entero
                otros = [n for n in config["catalogo"] if n not in {x["ind"] for x in nuevo["condiciones"]}]
                if otros:
                    nuevo["condiciones"][i] = cromosoma._condicion_aleatoria(rng, otros)
                    tocado = True
                    continue
            nuevo["condiciones"][i] = _mutar_condicion(c, config, rng)
            tocado = True
    if rng.random() < p:
        nuevo["stop"] = _mutar_stop(nuevo["stop"], config, rng)
        tocado = True
    if rng.random() < p:
        nuevo["tp"] = _mutar_tp(nuevo["tp"], config, rng)
        tocado = True
    if not tocado:
        k = rng.randrange(len(nuevo["condiciones"]) + 2)
        if k < len(nuevo["condiciones"]):
            nuevo["condiciones"][k] = _mutar_condicion(nuevo["condiciones"][k], config, rng)
        elif k == len(nuevo["condiciones"]):
            nuevo["stop"] = _mutar_stop(nuevo["stop"], config, rng)
        else:
            nuevo["tp"] = _mutar_tp(nuevo["tp"], config, rng)
    return nuevo


def cruzar(a: dict, b: dict, config: dict, rng: random.Random) -> dict:
    """Hijo: condiciones cogidas de la union de los dos padres (sin repetir
    indicador), stop de uno y take profit del otro (a cara o cruz)."""
    n = len(a["condiciones"])
    pool = [copy.deepcopy(c) for c in a["condiciones"] + b["condiciones"]]
    rng.shuffle(pool)
    conds, vistos = [], set()
    for c in pool:
        if c["ind"] in vistos:
            continue
        vistos.add(c["ind"])
        conds.append(c)
        if len(conds) == n:
            break
    return {
        "condiciones": conds,
        "stop": copy.deepcopy(a["stop"] if rng.random() < 0.5 else b["stop"]),
        "tp": copy.deepcopy(a["tp"] if rng.random() < 0.5 else b["tp"]),
    }


def torneo(poblacion: list[dict], rng: random.Random, k: int = 3) -> dict:
    return max(rng.sample(poblacion, min(k, len(poblacion))), key=lambda x: x["fitness"])


# ── La corrida ──────────────────────────────────────────────────────────────

class Corrida:
    def __init__(self, config: dict, dir_corrida: str, evaluar_lote, log=print):
        self.config = config
        self.dir = dir_corrida
        self.evaluar_lote = evaluar_lote   # list[individuo] -> list[metricas]
        self.log = log
        self.semilla = int(config.get("semilla", 42))
        self.poblacion_n = int(config.get("poblacion", 80))
        self.generaciones = int(config.get("generaciones", 40))
        self.elite_n = max(1, int(round(self.poblacion_n * float(config.get("elite", 0.05)))))
        self.p_cruce = float(config.get("p_cruce", 0.8))
        self.paciencia = int(config.get("paciencia", 12))
        self.cache: dict[str, dict] = {}          # huella -> metricas
        self.individuos: dict[str, dict] = {}     # huella -> individuo
        self.poblacion: list[dict] = []           # [{huella, individuo, fitness, metricas}]
        self.generacion = 0
        self.historial: list[dict] = []
        self.evaluadas = 0
        self.segundos_eval: list[float] = []
        self.inicio = time.time()
        self.estado = "preparando"
        self.mensaje = ""
        os.makedirs(dir_corrida, exist_ok=True)

    # ── persistencia ────────────────────────────────────────────────────────
    def _ruta(self, nombre: str) -> str:
        return os.path.join(self.dir, nombre)

    def _escribir(self, nombre: str, obj) -> None:
        tmp = self._ruta(nombre + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
        # En Windows `os.replace` lanza PermissionError (WinError 5) si en ESE
        # instante alguien tiene el destino abierto: la pagina sondeandolo cada
        # 4 s, o el antivirus escaneandolo. Es transitorio -> reintentar.
        # (2026-09-03: sin esto, una corrida de 12 generaciones murio a las
        # 02:14 escribiendo mejores.json.)
        ultimo = None
        for espera in (0.05, 0.2, 0.5, 1.0, 2.0, 4.0):
            try:
                os.replace(tmp, self._ruta(nombre))
                return
            except PermissionError as e:
                ultimo = e
                time.sleep(espera)
        raise ultimo

    def _mejores(self) -> list[dict]:
        filas = []
        for h, m in self.cache.items():
            if "error" in m:
                continue
            ind = self.individuos[h]
            filas.append({"huella": h, "fitness": m.get("fitness", 0.0), "receta": cromosoma.receta(ind),
                          "metricas": m, "individuo": ind,
                          "definicion": cromosoma.a_definicion(ind, self.config)})
        filas.sort(key=lambda x: x["fitness"], reverse=True)
        return filas[:TOP_N]

    def guardar(self) -> None:
        media = sum(self.segundos_eval[-20:]) / max(1, len(self.segundos_eval[-20:]))
        pendientes = max(0, (self.generaciones - self.generacion) * (self.poblacion_n - self.elite_n))
        mejor = self.poblacion[0] if self.poblacion else None
        # Orden deliberado: `poblacion.json` (lo que permite REANUDAR) va
        # primero; si luego falla un fichero de presentacion, el trabajo ya
        # esta a salvo. Y ningun fallo de escritura tumba la corrida: se avisa
        # y se reintenta en el ciclo siguiente (hay uno por evaluacion).
        _ficheros = []
        _ficheros.append(("poblacion.json", {
            "generacion": self.generacion, "evaluadas": self.evaluadas,
            "segundos_eval": self.segundos_eval[-50:], "historial": self.historial,
            "poblacion": [p["huella"] for p in self.poblacion],
            "individuos": self.individuos, "cache": self.cache,
        }))
        _ficheros.append(("estado.json", {
            "estado": self.estado, "mensaje": self.mensaje,
            "generacion": self.generacion, "generaciones": self.generaciones,
            "poblacion": self.poblacion_n, "evaluadas": self.evaluadas,
            "unicas": len(self.cache), "segundos_por_eval": round(media, 1),
            "eta_segundos": int(pendientes * media * 0.65),   # ~35% salen repetidos y no se evaluan
            "inicio": self.inicio, "actualizado": time.time(),
            "semilla": self.semilla,
            "mejor": None if mejor is None else {"huella": mejor["huella"], "fitness": mejor["fitness"],
                                                 "receta": cromosoma.receta(mejor["individuo"]),
                                                 "metricas": mejor["metricas"]},
            "historial": self.historial,
        }))
        _ficheros.append(("mejores.json", {"config": self.config, "mejores": self._mejores()}))
        for _nombre, _obj in _ficheros:
            try:
                self._escribir(_nombre, _obj)
            except OSError as e:
                self.log(f"aviso: no se pudo escribir {_nombre} ({type(e).__name__}); "
                         f"se reintenta en el siguiente ciclo")

    def reanudar(self) -> bool:
        ruta = self._ruta("poblacion.json")
        if not os.path.exists(ruta):
            return False
        d = json.load(open(ruta, encoding="utf-8"))
        self.generacion = int(d["generacion"])
        self.evaluadas = int(d["evaluadas"])
        self.segundos_eval = list(d.get("segundos_eval", []))
        self.historial = list(d.get("historial", []))
        self.individuos = dict(d["individuos"])
        self.cache = dict(d["cache"])
        self.poblacion = [self._fila(h) for h in d["poblacion"] if h in self.cache]
        self.poblacion.sort(key=lambda x: x["fitness"], reverse=True)
        self.log(f"reanudada en la generacion {self.generacion} con {len(self.cache)} evaluados")
        return True

    # ── evaluacion ──────────────────────────────────────────────────────────
    def _fila(self, h: str) -> dict:
        m = self.cache[h]
        return {"huella": h, "individuo": self.individuos[h], "fitness": float(m.get("fitness", 0.0)), "metricas": m}

    def _parar_pedido(self) -> bool:
        if os.path.exists(self._ruta("parar.txt")):
            return True
        # Hora limite ("HH:MM"): la corrida se para sola antes de que arranque
        # el bot de alertas (regla: nada de esto con el bot encendido).
        limite = self.config.get("parar_a_las")
        if limite:
            try:
                h, m = (int(x) for x in str(limite).split(":"))
                ahora = time.localtime()
                inicio = time.localtime(self.inicio)
                # solo cuenta si la hora limite queda POR DELANTE del arranque
                # (una corrida lanzada a las 20:00 con limite 09:00 para manana)
                pasado_medianoche = ahora.tm_yday != inicio.tm_yday
                if (pasado_medianoche or (h, m) > (inicio.tm_hour, inicio.tm_min)) and                         (ahora.tm_hour, ahora.tm_min) >= (h, m):
                    if self.mensaje != f"hora limite {limite}":
                        self.mensaje = f"hora limite {limite}"
                        self.log(f"hora limite {limite} alcanzada: parada limpia")
                    return True
            except ValueError:
                pass
        return False

    def _evaluar(self, individuos: list[dict]) -> list[dict]:
        """Evalua los que no esten en cache; devuelve filas de poblacion."""
        nuevos, huellas = [], []
        for ind in individuos:
            h = cromosoma.huella(ind)
            self.individuos.setdefault(h, ind)
            huellas.append(h)
            if h not in self.cache and h not in {cromosoma.huella(x) for x in nuevos}:
                nuevos.append(ind)
        # por lotes para volcar progreso y poder parar entre lotes
        lote = max(1, int(self.config.get("workers", 1)))
        for i in range(0, len(nuevos), lote):
            if self._parar_pedido():
                break
            trozo = nuevos[i:i + lote]
            t = time.time()
            for ind, m in zip(trozo, self.evaluar_lote(trozo)):
                self.cache[cromosoma.huella(ind)] = m
                self.evaluadas += 1
            self.segundos_eval.append((time.time() - t) / len(trozo))
            mejor_lote = max((self.cache[cromosoma.huella(x)].get("fitness", 0.0) for x in trozo), default=0.0)
            self.log(f"  gen {self.generacion} · {self.evaluadas} evaluadas · lote {len(trozo)} en "
                     f"{time.time()-t:.0f}s · mejor del lote {mejor_lote:.2f}")
            self.guardar()
        return [self._fila(h) for h in huellas if h in self.cache]

    # ── bucle principal ─────────────────────────────────────────────────────
    def correr(self) -> None:
        rng = random.Random(self.semilla + self.generacion * 1000)
        try:
            if not self.poblacion:
                self.estado = "corriendo"
                self.mensaje = "poblacion inicial"
                self.guardar()
                iniciales, vistos = [], set()
                intentos = 0
                while len(iniciales) < self.poblacion_n and intentos < self.poblacion_n * 20:
                    intentos += 1
                    ind = cromosoma.aleatorio(self.config, rng)
                    h = cromosoma.huella(ind)
                    if h in vistos:
                        continue
                    vistos.add(h)
                    iniciales.append(ind)
                self.poblacion = self._evaluar(iniciales)
                self.poblacion.sort(key=lambda x: x["fitness"], reverse=True)
                self._cerrar_generacion()

            sin_mejora = 0
            while self.generacion < self.generaciones and not self._parar_pedido():
                self.generacion += 1
                rng = random.Random(self.semilla + self.generacion * 1000)
                self.estado = "corriendo"
                self.mensaje = f"generacion {self.generacion}"
                mejor_antes = self.poblacion[0]["fitness"] if self.poblacion else 0.0

                elite = self.poblacion[:self.elite_n]
                huellas_vivas = {p["huella"] for p in elite}
                hijos = []
                intentos = 0
                while len(hijos) < self.poblacion_n - len(elite) and intentos < self.poblacion_n * 30:
                    intentos += 1
                    p1, p2 = torneo(self.poblacion, rng), torneo(self.poblacion, rng)
                    hijo = cruzar(p1["individuo"], p2["individuo"], self.config, rng) \
                        if rng.random() < self.p_cruce else copy.deepcopy(p1["individuo"])
                    hijo = mutar(hijo, self.config, rng)
                    h = cromosoma.huella(hijo)
                    if h in huellas_vivas:
                        continue
                    huellas_vivas.add(h)
                    hijos.append(hijo)
                filas = self._evaluar(hijos)
                self.poblacion = sorted(elite + filas, key=lambda x: x["fitness"], reverse=True)[:self.poblacion_n]
                self._cerrar_generacion()

                if self.poblacion[0]["fitness"] > mejor_antes + 1e-9:
                    sin_mejora = 0
                else:
                    sin_mejora += 1
                    if sin_mejora >= self.paciencia:
                        self.mensaje = f"sin mejora en {self.paciencia} generaciones: parada temprana"
                        self.log(self.mensaje)
                        break

            self.estado = "parada" if self._parar_pedido() else "terminada"
            if self.estado == "terminada" and not self.mensaje.startswith("sin mejora"):
                self.mensaje = "terminada"
        except Exception as e:  # que quede escrito, no perdido en una consola
            self.estado = "error"
            self.mensaje = f"{type(e).__name__}: {e}"
            self.log("ERROR " + self.mensaje)
            raise
        finally:
            self.guardar()

    def _cerrar_generacion(self) -> None:
        mejor = self.poblacion[0]
        fits = [p["fitness"] for p in self.poblacion]
        self.historial.append({"generacion": self.generacion, "mejor": mejor["fitness"],
                               "media": sum(fits) / len(fits), "unicas": len(self.cache),
                               "distintas_top": len({p["huella"] for p in self.poblacion[:TOP_N]})})
        self.log(f"gen {self.generacion}: mejor {mejor['fitness']:.2f} · media {sum(fits)/len(fits):.2f} · "
                 f"{cromosoma.receta(mejor['individuo'])}")
        self.guardar()
