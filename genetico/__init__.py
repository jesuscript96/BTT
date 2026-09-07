"""Algoritmo genetico de estrategias (2026-09).

Paquete APARTE del backtester: importa el motor (`run_backtest`) y lo llama;
no modifica nada de `backend/app`. Vive fuera de `backend/` a proposito: el
backend corre con `--reload` y cada fichero guardado ahi lo reinicia.

Decision de diseno (Jaume, 2026-09-02): cada individuo se evalua con
`run_backtest` tal cual (opcion A). Es lento (~30 s por evaluacion en esta
maquina) pero la paridad con el panel es por definicion. Corridas de noche.
"""
