"""Alarmas del Screener — motor de avisos en vivo, independiente del backtester.

Deliberadamente NO importa nada de `app.backtester`, `app.services.strategy_engine`
ni `app.services.indicators`: son dos productos distintos y el acoplamiento entre
ellos fue descartado en diseño. Este módulo tiene su propia aritmética (primitivas
en `fields.py` + `bars.py`), su propio modelo de regla y su propio almacenamiento.
"""
