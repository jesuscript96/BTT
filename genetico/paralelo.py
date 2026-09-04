"""Workers persistentes con `spawn` (lo unico que hay en Windows).

Cada worker carga el dataset UNA vez al arrancar (feather, segundos) y
evalua individuos hasta que la corrida acaba. Medido en la fase 0: escala
lineal (2 workers = 2x). El tope lo pone la RAM, no la CPU.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor

_Q = None
_G = None
_CONFIG = None


def _init(dir_corrida: str, config: dict) -> None:
    global _Q, _G, _CONFIG
    from genetico import entorno
    entorno.preparar()
    from genetico import datos
    _Q, _G = datos.cargar(dir_corrida)
    _CONFIG = config


def _evaluar(individuo: dict) -> dict:
    from genetico import evaluador
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
