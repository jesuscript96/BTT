"""Una corrida SIN dataset tiene que arrancar.

EL FALLO (6-sep-2026). Se quitó el dataset de la página y del router, pero
`genetico/corrida.py` seguía haciendo `config["dataset_id"]`. La corrida moría a
los tres segundos con un KeyError — y como el genético es un PROCESO EXTERNO, en
la pantalla no salía ningún error: solo una corrida que «no avanzaba». Jaume:
«sigue en marcha no? parece que no haga nada».

Es el caso peor de esta arquitectura: el traceback acaba en `salida.txt`, dentro
del directorio de la corrida, y nadie lo mira si no sabe que existe. Por eso
este fichero comprueba las dos mitades del contrato.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def test_corrida_no_exige_dataset_id():
    """Lee el fuente: `config["dataset_id"]` mata la corrida entera.

    Se comprueba sobre el texto y no ejecutando `main()` porque `main()` monta
    el entorno, abre el lago y lanza una corrida de verdad. Lo que hay que
    impedir es exactamente el acceso obligatorio.
    """
    src = (RAIZ / "genetico" / "corrida.py").read_text(encoding="utf-8")
    # Solo CODIGO: el comentario que explica el fallo contiene ese mismo
    # literal, y no vale como acusacion.
    codigo = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert 'config["dataset_id"]' not in codigo, (
        "corrida.py vuelve a exigir dataset_id: sin dataset eso es un KeyError "
        "y el proceso externo muere sin que la pagina lo note")
    assert 'config.get("dataset_id")' in codigo


def test_sin_qualifying_y_sin_dataset_el_error_lo_explica():
    """Si de verdad no hay de donde sacar el universo, que se entienda."""
    from genetico import datos
    with pytest.raises(ValueError) as e:
        datos.preparar("", str(RAIZ / "no_existe_este_directorio_de_corrida"))
    msg = str(e.value)
    assert "qualifying" in msg.lower()
    assert "backend" in msg.lower(), "el mensaje tiene que decir quien lo escribe"


def test_el_router_tampoco_lo_exige():
    """La otra mitad: crear la corrida sin dataset no puede reventar."""
    src = (RAIZ / "backend" / "app" / "routers" / "genetico.py").read_text(encoding="utf-8")
    # El unico acceso duro que queda es el de la firma del directorio, y va
    # dentro de un `if cfg.get("dataset_id")`.
    for i, linea in enumerate(src.splitlines()):
        if 'cfg["dataset_id"]' in linea:
            contexto = "\n".join(src.splitlines()[max(0, i - 3):i + 1])
            assert 'if cfg.get("dataset_id")' in contexto or 'cfg.get("dataset_id"):' in contexto, (
                f"acceso duro a cfg['dataset_id'] sin guardia en la linea {i + 1}")
