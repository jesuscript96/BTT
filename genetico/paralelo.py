"""Workers persistentes con `spawn` (lo unico que hay en Windows).

Cada worker carga el dataset UNA vez al arrancar (feather, segundos) y
evalua individuos hasta que la corrida acaba. Medido en la fase 0: escala
lineal (2 workers = 2x). El tope lo pone la RAM, no la CPU.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from concurrent.futures import ProcessPoolExecutor

_Q = None
_G = None
_CONFIG = None
_DIR = None


def _apuntar(dir_corrida, individuo: dict) -> None:
    """Deja escrito QUE se va a evaluar, ANTES de evaluarlo.

    PARA QUE. La corrida muere sola cada pocas horas y no deja rastro: el visor
    de sucesos de Windows la apunta como APPCRASH con codigo 0xC0000005
    (violacion de acceso) y modulo «unknown», o sea que el fallo pasa dentro de
    codigo maquina que no pertenece a ningun DLL — el que compila numba al
    vuelo. Eso NO es una excepcion de Python: no hay traceback, no lo captura
    ningun `except`, y el `try` de aqui abajo no sirve de nada.

    La unica forma de saber QUIEN lo tumba es dejarlo escrito antes. Cuando el
    proceso desaparezca, el ultimo `evaluando_<pid>.txt` es el sospechoso.

    UN FICHERO POR PROCESO. Con varios workers no vale uno solo: se pisarian y
    el superviviente borraria la pista del que murio.

    NO SIRVE `poblacion.json` (ya probado): se guarda DESPUES de cada
    evaluacion, asi que el individuo que revienta nunca llega a quedar escrito.

    PARA CAZARLO DEL TODO, ademas de esto, arrancar la corrida con
    `NUMBA_BOUNDSCHECK=1` en el entorno: numba deja de compilar sin comprobar
    los limites de los arrays y un indice fuera de rango pasa a ser un
    `IndexError` normal, con traceback y con el `except` funcionando otra vez.
    Cuesta velocidad, asi que va apagado salvo cuando se este cazando.

    JAMAS puede tumbar una evaluacion: si falla el apunte, se sigue.
    """
    if not dir_corrida:
        return
    # EL ORDEN IMPORTA. La receta es un lujo legible; el JSON del individuo es
    # LA PRUEBA, y es con lo que se reproduce el fallo. Si `receta()` peta con
    # un individuo raro — y el que buscamos es raro por definicion — escribirla
    # antes se lleva por delante el volcado entero y el fichero se queda en la
    # fecha. Asi que primero la prueba, y la receta despues y en su propio try.
    try:
        texto = json.dumps(individuo, ensure_ascii=False, indent=1, default=str)
    except Exception:                                            # noqa: BLE001
        texto = repr(individuo)[:20000]
    try:
        from genetico import especie
        receta = especie.receta(_CONFIG or {}, individuo)
    except Exception as e:                                       # noqa: BLE001
        receta = f"(sin receta: {type(e).__name__})"
    try:
        with open(os.path.join(dir_corrida, f"evaluando_{os.getpid()}.txt"),
                  "w", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{receta}\n\n{texto}")
    except Exception:                                            # noqa: BLE001
        pass


def _init(dir_corrida: str, config: dict) -> None:
    global _Q, _G, _CONFIG, _DIR
    from genetico import entorno
    entorno.preparar()
    from genetico import datos
    _Q, _G = datos.cargar(dir_corrida)
    _CONFIG = config
    _DIR = dir_corrida


def _evaluar(individuo: dict) -> dict:
    from genetico import evaluador
    _apuntar(_DIR, individuo)
    try:
        return evaluador.evaluar(individuo, _CONFIG, _Q, _G)
    except Exception as e:  # un individuo roto no tumba el worker
        return {"error": f"{type(e).__name__}: {str(e)[:200]}", "fitness": 0.0, "trades": 0, "segundos": 0.0}


class Lote:
    """`evaluar_lote(individuos)` para Corrida: en serie o con N workers."""

    def __init__(self, dir_corrida: str, config: dict, workers: int, log=print):
        self.workers = max(1, int(workers))
        self.dir = dir_corrida
        self.config = config
        self.log = log
        self._pool = None
        self._q = self._g = None

    def __enter__(self):
        if self.workers > 1:
            self.log(f"arrancando {self.workers} workers (spawn)...")
            self._pool = ProcessPoolExecutor(
                max_workers=self.workers, mp_context=mp.get_context("spawn"),
                initializer=_init, initargs=(self.dir, self.config),
            )
        else:
            from genetico import datos
            self._q, self._g = datos.cargar(self.dir)
        return self

    def __exit__(self, *exc):
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)

    def __call__(self, individuos: list[dict]) -> list[dict]:
        if self._pool is not None:
            return list(self._pool.map(_evaluar, individuos))
        from genetico import evaluador
        salida = []
        for ind in individuos:
            _apuntar(self.dir, ind)     # el camino de 1 worker tambien se cae
            try:
                salida.append(evaluador.evaluar(ind, self.config, self._q, self._g))
            except Exception as e:
                salida.append({"error": f"{type(e).__name__}: {str(e)[:200]}", "fitness": 0.0,
                               "trades": 0, "segundos": 0.0})
        return salida


def workers_recomendados(ram_por_worker_gb: float = 1.3, margen_gb: float = 1.5, tope: int = 4) -> int:
    """Cuantos workers caben ahora mismo sin dejar la maquina sin aire."""
    from genetico import entorno
    libre = entorno.ram_libre_gb() - margen_gb
    return max(1, min(tope, int(libre // ram_por_worker_gb), os.cpu_count() or 1))
