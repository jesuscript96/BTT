"""Lanzar una corrida desde la linea de comandos (lo mismo que hara la pagina).

    python -m genetico.corrida --config corrida.json --dir D:/tmp/btt_genetico/corridas/mi_corrida
    python -m genetico.corrida --dir ...  --reanudar          (usa el config.json del directorio)

El config es el mismo dict que construye la pagina (ver prueba_fase1.CONFIG).
Escribe `log.txt`, `estado.json`, `mejores.json` y `poblacion.json` en --dir.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from genetico import entorno

entorno.preparar()

from genetico import datos, motor, paralelo  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="ruta al JSON de la corrida")
    ap.add_argument("--dir", required=True, help="directorio de la corrida (estado, resultados)")
    ap.add_argument("--reanudar", action="store_true")
    ap.add_argument("--workers", type=int, default=None, help="por defecto: los que quepan en RAM (max 4)")
    args = ap.parse_args()

    os.makedirs(args.dir, exist_ok=True)
    ruta_cfg = os.path.join(args.dir, "config.json")
    if args.config:
        config = json.load(open(args.config, encoding="utf-8"))
        json.dump(config, open(ruta_cfg, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    else:
        config = json.load(open(ruta_cfg, encoding="utf-8"))

    log_f = open(os.path.join(args.dir, "log.txt"), "a", encoding="utf-8")

    def log(*a):
        linea = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
        print(linea, flush=True)
        log_f.write(linea + "\n")
        log_f.flush()

    workers = args.workers or int(config.get("workers", 0)) or paralelo.workers_recomendados()
    config["workers"] = workers
    log(f"corrida en {args.dir} · semilla {config.get('semilla')} · poblacion {config.get('poblacion')} "
        f"· generaciones {config.get('generaciones')} · workers {workers} · RAM libre {entorno.ram_libre_gb():.1f} GB")

    # Datos del dataset (una vez; los workers los recargan del feather)
    dir_datos = config.get("dir_datos") or os.path.join(
        entorno.DIR_TRABAJO, "datos", f"{config['dataset_id']}_{config.get('fecha_ini')}_{config.get('fecha_fin')}")
    config["dir_datos"] = dir_datos
    meta = datos.preparar(config["dataset_id"], dir_datos, config.get("fecha_ini"), config.get("fecha_fin"), log=log)
    log(f"dataset: {meta}")

    corrida = motor.Corrida(config, args.dir, evaluar_lote=None, log=log)
    if args.reanudar:
        corrida.reanudar()
    with paralelo.Lote(dir_datos, config, workers, log=log) as lote:
        corrida.evaluar_lote = lote
        corrida.correr()
    log(f"fin: {corrida.estado} · {corrida.mensaje} · {corrida.evaluadas} evaluaciones · "
        f"{(time.time()-corrida.inicio)/60:.0f} min")


if __name__ == "__main__":
    main()
